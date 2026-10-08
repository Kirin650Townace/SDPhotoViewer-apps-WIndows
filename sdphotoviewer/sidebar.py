"""左側パネル（エクスプローラー風）.

取り込み元（SD カード / ドライブ / フォルダ）、カメラ情報、フォルダ一覧、
絞り込みと並べ替えをまとめたサイドバー。
"""

from __future__ import annotations

import datetime as _dt
import os

from PySide6.QtCore import QDate, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    DatePicker,
    FluentIcon,
    HorizontalSeparator,
    ProgressBar,
    PushButton,
    SmoothScrollArea,
    StrongBodyLabel,
    TransparentToolButton,
)

from . import i18n, theme
from .exifdata import fmt_size
from .imaging import support_summary
from .model import SourceStats, sort_options
from .sources import FolderNode, Source

SIDEBAR_WIDTH = 322


# --------------------------------------------------------------------------
# アイコン（SD カードを自作）
# --------------------------------------------------------------------------


def sd_card_icon(size: int = 20, accent: bool = False) -> QIcon:
    """SD カードのアイコンを描く。"""
    dpr = 2
    pixmap = QPixmap(size * dpr, size * dpr)
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    body = QRectF(1.5, 0.5, size - 3, size - 1)
    color = theme.accent() if accent else theme.pick("#4A4A4A", "#D0D0D0")
    pen = QPen(color)
    pen.setWidthF(1.4)
    painter.setPen(pen)
    # 下側の角を丸めたカード形状
    path = QPainterPath()
    path.moveTo(body.left(), body.top() + 3)
    path.lineTo(body.left() + 3, body.top())
    path.lineTo(body.right() - 3, body.top())
    path.lineTo(body.right(), body.top() + 3)
    path.lineTo(body.right(), body.bottom() - 2)
    path.quadTo(body.right(), body.bottom(), body.right() - 2, body.bottom())
    path.lineTo(body.left() + 2, body.bottom())
    path.quadTo(body.left(), body.bottom(), body.left(), body.bottom() - 2)
    path.closeSubpath()
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)
    # 接点（ピン）
    painter.setPen(QPen(color, 1.2))
    pin_h = (size - 1) * 0.32
    for i in range(4):
        x = body.left() + 4 + i * ((body.width() - 8) / 3.4)
        painter.drawLine(QPointF(x, body.top() + 2), QPointF(x, body.top() + 2 + pin_h))
    painter.end()
    return QIcon(pixmap)


# --------------------------------------------------------------------------
# 汎用の行ウィジェット
# --------------------------------------------------------------------------


class NavRow(QWidget):
    """クリックできる行（取り込み元 / フォルダ）。"""

    clicked = Signal(object)

    def __init__(self, title: str, subtitle: str = "", icon: QIcon | None = None, payload=None, indent: int = 0, parent=None):
        super().__init__(parent)
        self._title = title
        self._subtitle = subtitle
        self._icon = icon
        self._badge = ""
        self.payload = payload
        self.indent = indent
        self._selected = False
        self._hovered = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setFixedHeight(50 if subtitle else 34)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setToolTip(title if not subtitle else f"{title}\n{subtitle}")

    # ---- 状態 ----
    def set_selected(self, value: bool) -> None:
        if self._selected != value:
            self._selected = bool(value)
            self.update()

    def set_title(self, text: str) -> None:
        self._title = text
        self.update()

    def set_subtitle(self, text: str) -> None:
        self._subtitle = text
        self.setToolTip(f"{self._title}\n{text}" if text else self._title)
        self.update()

    def set_badge(self, text: str) -> None:
        self._badge = text
        self.update()

    def set_icon(self, icon: QIcon | None) -> None:
        self._icon = icon
        self.update()

    def title(self) -> str:
        return self._title

    # ---- イベント ----
    def enterEvent(self, event) -> None:  # noqa: D102, N802
        self._hovered = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: D102, N802
        self._hovered = False
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: D102, N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.payload)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: D102, N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(6, 2, -6, -2)
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 6, 6)
        if self._selected:
            painter.fillPath(path, theme.selected_surface())
            painter.setPen(QPen(theme.accent(), 1.2))
            painter.drawPath(path)
        elif self._hovered:
            painter.fillPath(path, theme.pick("#EDEDED", "#343434"))
        elif self.isEnabled():
            painter.fillPath(path, theme.sidebar_bg())

        x = rect.x() + 8 + self.indent
        if self._icon is not None:
            pix = self._icon.pixmap(QSize(20, 20))
            painter.drawPixmap(x, rect.center().y() - pix.height() // 2, pix)
            x += 26

        right = rect.right() - 8
        badge_text = self._badge
        badge_font = theme.ui_font(theme.FONT_SMALL)
        fm_badge = QFontMetrics(badge_font)
        badge_w = fm_badge.horizontalAdvance(badge_text) + 6 if badge_text else 0
        text_right = right - badge_w

        title_font = theme.ui_font(theme.FONT_NAME, QFont.Weight.DemiBold if self._subtitle else QFont.Weight.Normal)
        fm_title = QFontMetrics(title_font)
        if self._subtitle:
            painter.setFont(title_font)
            painter.setPen(theme.text_primary())
            title_rect = QRect(x, rect.y() + 5, text_right - x, fm_title.height())
            painter.drawText(
                title_rect,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                fm_title.elidedText(self._title, Qt.TextElideMode.ElideMiddle, title_rect.width()),
            )
            painter.setFont(theme.ui_font(theme.FONT_SMALL))
            painter.setPen(theme.text_secondary())
            sub_rect = QRect(x, rect.y() + 5 + fm_title.height(), text_right - x, rect.height() - fm_title.height() - 8)
            painter.drawText(
                sub_rect,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
                fm_title.elidedText(self._subtitle, Qt.TextElideMode.ElideRight, sub_rect.width()),
            )
        else:
            painter.setFont(title_font)
            painter.setPen(theme.text_primary())
            title_rect = QRect(x, rect.y(), text_right - x, rect.height())
            painter.drawText(
                title_rect,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                fm_title.elidedText(self._title, Qt.TextElideMode.ElideMiddle, title_rect.width()),
            )

        if badge_text:
            painter.setFont(badge_font)
            painter.setPen(theme.text_tertiary())
            painter.drawText(
                QRect(text_right, rect.y(), badge_w, rect.height()),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                badge_text,
            )
        painter.end()


# --------------------------------------------------------------------------
# カメラ情報カード
# --------------------------------------------------------------------------


class CameraInfoCard(CardWidget):
    """読み込んだ写真から判定したカメラ情報。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBorderRadius(8)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)
        self._camera_icon_label = QLabel(self)
        self._camera_icon_label.setPixmap(FluentIcon.CAMERA.icon(color=theme.accent()).pixmap(18, 18))
        self._title_label = StrongBodyLabel(i18n.tr("sidebar.camera_info"), self)
        title = self._title_label
        header.addWidget(self._camera_icon_label)
        header.addWidget(title)
        header.addStretch(1)
        layout.addLayout(header)

        self._rows: dict[str, QLabel] = {}
        self._row_labels: dict[str, CaptionLabel] = {}
        for key, _label in (
            ("camera", "sidebar.model"),
            ("lens", "sidebar.lens"),
            ("period", "sidebar.period"),
            ("count", "sidebar.count"),
            ("size", "sidebar.image_size"),
            ("gps", "sidebar.gps"),
        ):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            name = CaptionLabel(i18n.tr(_label), self)
            self._row_labels[key] = name
            value = BodyLabel("—", self)
            value.setWordWrap(True)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            value.setMinimumWidth(150)
            row.addWidget(name, 0, Qt.AlignmentFlag.AlignTop)
            row.addStretch(1)
            row.addWidget(value)
            layout.addLayout(row)
            self._rows[key] = value

        self._capacity = ProgressBar(self)
        self._capacity.setValue(0)
        layout.addSpacing(2)
        self._capacity_caption = CaptionLabel(i18n.tr("sidebar.capacity"), self)
        layout.addWidget(self._capacity_caption)
        layout.addWidget(self._capacity)
        self._capacity.hide()
        self._capacity_caption.hide()

    def refresh_theme(self) -> None:
        """テーマ変更時の再描画（アイコン・容量バー・背景色）。"""
        self._camera_icon_label.setPixmap(FluentIcon.CAMERA.icon(color=theme.accent()).pixmap(18, 18))
        # 既定では背景色が 120ms かけて変わるため、切り替え直後に明るいままの
        # 状態が見えてしまう。ここでは即時に最終色へ合わせる。
        self.backgroundColorAni.stop()
        self.setBackgroundColor(self._normalBackgroundColor())
        for child in self.findChildren(QWidget):
            child.update()
        self.update()

    def update_from(self, stats: SourceStats | None, source: Source | None = None) -> None:
        if stats is None or stats.total == 0:
            for value in self._rows.values():
                value.setText("—")
            if source and source.total_bytes:
                used = (source.total_bytes - (source.free_bytes or 0)) / max(1, source.total_bytes)
                self._capacity.show()
                self._capacity_caption.show()
                self._capacity.setValue(int(used * 100))
                self._capacity_caption.setText(
                    i18n.tr(
                        "sidebar.capacity_used",
                        used=fmt_size(source.total_bytes - (source.free_bytes or 0)),
                        total=fmt_size(source.total_bytes),
                    )
                )
            else:
                self._capacity.hide()
                self._capacity_caption.hide()
            return

        self._rows["camera"].setText(stats.camera or i18n.tr("common.unknown"))
        self._rows["lens"].setText(stats.lens or "—")
        self._rows["period"].setText(stats.period_text or "—")
        kinds = stats.kinds
        kind_bits = []
        for key in ("jpeg", "heic", "raw", "video"):
            if kinds.get(key):
                kind_bits.append(f"{i18n.tr('kind.' + key)} {kinds[key]:,}")
        self._rows["count"].setText(
            i18n.n_files(stats.total) + (f"（{' / '.join(kind_bits)}）" if kind_bits else "")
        )
        self._rows["size"].setText(
            i18n.tr("stats.resolution_size", size=stats.main_size, bytes=fmt_size(stats.total_bytes))
            if stats.main_size else fmt_size(stats.total_bytes)
        )
        self._rows["gps"].setText(i18n.tr("stats.gps_count", n=f"{stats.gps_count:,}") if stats.gps_count else i18n.tr("common.none"))

        if source and source.total_bytes:
            used_bytes = source.total_bytes - (source.free_bytes or 0)
            self._capacity.show()
            self._capacity_caption.show()
            self._capacity.setValue(int(used_bytes / max(1, source.total_bytes) * 100))
            self._capacity_caption.setText(
                i18n.tr(
                    "sidebar.capacity_detail",
                    used=fmt_size(used_bytes),
                    total=fmt_size(source.total_bytes),
                    free=fmt_size(source.free_bytes or 0),
                )
            )


# --------------------------------------------------------------------------
# サイドバー本体
# --------------------------------------------------------------------------


class Sidebar(QWidget):
    """左側のナビゲーションパネル。"""

    sourceSelected = Signal(object)       # Source
    fixedDisksToggled = Signal(bool)      # ローカルディスク表示の切り替え
    folderSelected = Signal(object)       # rel path (str) または None
    filtersChanged = Signal()
    sortChanged = Signal()
    refreshRequested = Signal()
    chooseFolderRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(SIDEBAR_WIDTH)
        self._source_rows: list[NavRow] = []
        self._folder_rows: list[NavRow] = []
        self._current_folder_rel: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = SmoothScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        self._scroll = scroll

        content = QWidget()
        scroll.setWidget(content)
        content.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False)
        self._scroll_content = content
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 10, 16)
        layout.setSpacing(4)

        # ---- 取り込み元 ----
        layout.addLayout(self._section_header(i18n.tr("sidebar.sources"), refresh=True))
        self._sources_box = QVBoxLayout()
        self._sources_box.setSpacing(2)
        layout.addLayout(self._sources_box)

        self._no_source_label = CaptionLabel(i18n.tr("sidebar.no_source"), self)
        self._no_source_label.setWordWrap(True)
        layout.addWidget(self._no_source_label)

        self._choose_button = PushButton(FluentIcon.FOLDER_ADD, i18n.tr("common.choose_folder"), self)
        self._choose_button.clicked.connect(self.chooseFolderRequested)
        layout.addSpacing(4)
        layout.addWidget(self._choose_button)

        self._fixed_check = CheckBox(i18n.tr("sidebar.include_fixed"), self)
        self._fixed_check.setToolTip(i18n.tr("sidebar.include_fixed_tip"))
        self._fixed_check.stateChanged.connect(self._on_fixed_toggled)
        layout.addSpacing(2)
        layout.addWidget(self._fixed_check)

        layout.addSpacing(10)
        self._camera_card = CameraInfoCard(self)
        layout.addWidget(self._camera_card)

        # ---- フォルダ ----
        layout.addSpacing(12)
        layout.addLayout(self._section_header(i18n.tr("sidebar.folders")))
        self._folders_box = QVBoxLayout()
        self._folders_box.setSpacing(2)
        layout.addLayout(self._folders_box)
        self._folders_hint = CaptionLabel(i18n.tr("sidebar.folders_hint"), self)
        layout.addWidget(self._folders_hint)

        # ---- 絞り込み ----
        layout.addSpacing(12)
        header = self._section_header(i18n.tr("sidebar.filters"))
        self._reset_button = TransparentToolButton(FluentIcon.SYNC, self)
        self._reset_button.setToolTip(i18n.tr("sidebar.reset_filters"))
        self._reset_button.setFixedSize(28, 28)
        self._reset_button.clicked.connect(self.reset_filters)
        header.addWidget(self._reset_button)
        layout.addLayout(header)  # ← 見出し行をレイアウトに追加（これが無いと左上に重なって表示される）

        self._kind_checks: dict[str, CheckBox] = {}
        for key in ("jpeg", "heic", "raw", "video"):
            check = CheckBox(i18n.tr("kind." + key), self)
            check.setChecked(True)
            check.stateChanged.connect(lambda *_a: self.filtersChanged.emit())
            self._kind_checks[key] = check
            layout.addWidget(check)

        layout.addSpacing(6)
        layout.addWidget(self._caption(i18n.tr("sidebar.camera")))
        self._camera_combo = ComboBox(self)
        self._camera_combo.addItem(i18n.tr("sidebar.all_cameras"))
        self._camera_combo.currentIndexChanged.connect(lambda *_a: self.filtersChanged.emit())
        layout.addWidget(self._camera_combo)

        layout.addSpacing(6)
        self._period_check = CheckBox(i18n.tr("sidebar.period_filter"), self)
        self._period_check.stateChanged.connect(self._on_period_toggled)
        layout.addWidget(self._period_check)

        self._period_box = QWidget(self)
        period_layout = QVBoxLayout(self._period_box)
        period_layout.setContentsMargins(24, 0, 0, 0)
        period_layout.setSpacing(4)
        row_from = QHBoxLayout()
        row_from.addWidget(self._caption(i18n.tr("sidebar.from")), 0)
        self._date_from = DatePicker(self)
        row_from.addWidget(self._date_from, 1)
        period_layout.addLayout(row_from)
        row_to = QHBoxLayout()
        row_to.addWidget(self._caption(i18n.tr("sidebar.to")), 0)
        self._date_to = DatePicker(self)
        row_to.addWidget(self._date_to, 1)
        period_layout.addLayout(row_to)
        self._period_box.setEnabled(False)
        layout.addWidget(self._period_box)
        self._toggle_period_widgets(False)
        self._date_from.dateChanged.connect(lambda *_a: self.filtersChanged.emit())
        self._date_to.dateChanged.connect(lambda *_a: self.filtersChanged.emit())

        self._gps_check = CheckBox(i18n.tr("sidebar.gps_only"), self)
        self._gps_check.stateChanged.connect(lambda *_a: self.filtersChanged.emit())
        layout.addSpacing(4)
        layout.addWidget(self._gps_check)

        # ---- 並べ替え ----
        layout.addSpacing(12)
        layout.addLayout(self._section_header(i18n.tr("sidebar.sort")))
        sort_row = QHBoxLayout()
        sort_row.setSpacing(6)
        self._sort_combo = ComboBox(self)
        for key, label in sort_options():
            self._sort_combo.addItem(label, userData=key)
        self._sort_combo.setCurrentIndex(0)
        self._sort_combo.currentIndexChanged.connect(lambda *_a: self.sortChanged.emit())
        self._order_button = TransparentToolButton(FluentIcon.DOWN, self)
        self._order_button.setToolTip(i18n.tr("sidebar.desc"))
        self._order_button.setFixedSize(30, 30)
        self._order_button.clicked.connect(self._toggle_order)
        self._descending = True
        sort_row.addWidget(self._sort_combo, 1)
        sort_row.addWidget(self._order_button)
        layout.addLayout(sort_row)

        layout.addSpacing(12)
        layout.addWidget(HorizontalSeparator(self))
        self._support_label = CaptionLabel(i18n.tr("sidebar.support", value=support_summary()), self)
        self._support_label.setWordWrap(True)
        layout.addWidget(self._support_label)
        layout.addStretch(1)
        self.refresh_theme()

    # ---- 小物 ----
    def _section_header(self, text: str, refresh: bool = False) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(8, 6, 6, 2)
        label = CaptionLabel(text, self)
        label.setFont(theme.ui_font(theme.FONT_SMALL, QFont.Weight.DemiBold))
        row.addWidget(label)
        row.addStretch(1)
        if refresh:
            button = TransparentToolButton(FluentIcon.SYNC, self)
            button.setToolTip(i18n.tr("common.reload"))
            button.setFixedSize(28, 28)
            button.clicked.connect(self.refreshRequested.emit)
            row.addWidget(button)
        return row

    def _caption(self, text: str, width: int | None = None) -> CaptionLabel:
        label = CaptionLabel(text, self)
        if width:
            label.setFixedWidth(width)
        return label

    # ---- 取り込み元 ----
    def set_sources(self, sources: list[Source], current_path: str | None) -> None:
        while self._sources_box.count():
            item = self._sources_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._source_rows.clear()

        for source in sources:
            icon = sd_card_icon(20, accent=source.removable) if source.removable else FluentIcon.HOME.icon()
            row = NavRow(source.name, source.detail, icon, payload=source, parent=self)
            row.clicked.connect(self._on_source_clicked)
            self._sources_box.addWidget(row)
            self._source_rows.append(row)

        self._no_source_label.setVisible(not sources)
        self.set_current_source(current_path)

    def set_current_source(self, path: str | None) -> None:
        for row in self._source_rows:
            source: Source = row.payload
            row.set_selected(bool(path) and os.path.normcase(source.path) == os.path.normcase(path))

    def update_source_row(self, path: str, detail: str) -> None:
        for row in self._source_rows:
            source: Source = row.payload
            if os.path.normcase(source.path) == os.path.normcase(path):
                row.set_subtitle(detail)
                source.detail = detail
                return

    def _on_source_clicked(self, payload) -> None:
        self.sourceSelected.emit(payload)

    # ---- ローカルディスク表示 ----
    def set_include_fixed(self, value: bool) -> None:
        self._fixed_check.blockSignals(True)
        self._fixed_check.setChecked(bool(value))
        self._fixed_check.blockSignals(False)

    def include_fixed(self) -> bool:
        return self._fixed_check.isChecked()

    def _on_fixed_toggled(self, *_args) -> None:
        self.fixedDisksToggled.emit(self._fixed_check.isChecked())

    # ---- カメラ情報 ----
    def update_camera_card(self, stats: SourceStats | None, source: Source | None) -> None:
        self._camera_card.update_from(stats, source)

    # ---- フォルダ ----
    def set_folders(self, root: FolderNode | None) -> None:
        while self._folders_box.count():
            item = self._folders_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._folder_rows.clear()

        if root is None or root.total == 0:
            self._folders_hint.setVisible(True)
            return
        self._folders_hint.setVisible(False)

        all_row = NavRow(i18n.tr("sidebar.all_files"), "", FluentIcon.PHOTO.icon(), payload=None, parent=self)
        all_row.set_badge(f"{root.total:,}")
        all_row.clicked.connect(self._on_folder_clicked)
        self._folders_box.addWidget(all_row)
        self._folder_rows.append(all_row)
        self._current_folder_rel = None

        def add_nodes(node: FolderNode) -> None:
            for child in node.children:
                icon = FluentIcon.FOLDER.icon()
                row = NavRow(child.name, "", icon, payload=child.rel, indent=min(child.depth, 3) * 14, parent=self)
                row.set_badge(f"{child.total:,}")
                row.clicked.connect(self._on_folder_clicked)
                self._folders_box.addWidget(row)
                self._folder_rows.append(row)
                add_nodes(child)

        add_nodes(root)
        self.set_current_folder(None)

    def set_current_folder(self, rel: str | None) -> None:
        self._current_folder_rel = rel
        for row in self._folder_rows:
            row.set_selected(row.payload == rel)

    def _on_folder_clicked(self, payload) -> None:
        self.set_current_folder(payload)
        self.folderSelected.emit(payload)

    # ---- 絞り込み ----
    def set_camera_choices(self, cameras: list[str]) -> None:
        current = self._camera_combo.currentText()
        self._camera_combo.blockSignals(True)
        self._camera_combo.clear()
        self._camera_combo.addItem(i18n.tr("sidebar.all_cameras"))
        for name in cameras:
            self._camera_combo.addItem(name)
        index = self._camera_combo.findText(current)
        self._camera_combo.setCurrentIndex(max(0, index))
        self._camera_combo.blockSignals(False)

    def set_kind_counts(self, counts: dict, auto_check: bool = False) -> None:
        """形式ごとの枚数を表示する。auto_check=True なら初回のみ自動でチェックする。"""
        for key, check in self._kind_checks.items():
            count = counts.get(key, 0)
            label = i18n.tr("kind." + key)
            check.setText(
                f"{label}（{count:,}）" if i18n.is_japanese() else f"{label} ({count:,})"
            )
            check.setEnabled(count > 0)
            if count == 0:
                check.blockSignals(True)
                check.setChecked(False)
                check.blockSignals(False)
            elif auto_check and not check.isChecked():
                check.blockSignals(True)
                check.setChecked(True)
                check.blockSignals(False)

    def set_date_bounds(self, date_from: _dt.date | None, date_to: _dt.date | None) -> None:
        if not date_from or not date_to:
            return
        self._date_from.blockSignals(True)
        self._date_to.blockSignals(True)
        self._date_from.setDate(QDate(date_from.year, date_from.month, date_from.day))
        self._date_to.setDate(QDate(date_to.year, date_to.month, date_to.day))
        self._date_from.blockSignals(False)
        self._date_to.blockSignals(False)

    def _toggle_period_widgets(self, enabled: bool) -> None:
        self._period_box.setVisible(enabled)

    def _on_period_toggled(self, *_args) -> None:
        enabled = self._period_check.isChecked()
        self._period_box.setEnabled(enabled)
        self._toggle_period_widgets(enabled)
        self.filtersChanged.emit()

    def current_filters(self) -> dict:
        kinds = {key for key, check in self._kind_checks.items() if check.isChecked()}
        if not kinds:
            kinds = {"jpeg", "heic", "raw", "video", "other"}
        date_from = date_to = None
        if self._period_check.isChecked():
            d1 = self._date_from.getDate()
            d2 = self._date_to.getDate()
            date_from = _dt.datetime(d1.year(), d1.month(), d1.day())
            date_to = _dt.datetime(d2.year(), d2.month(), d2.day(), 23, 59, 59)
        camera_text = self._camera_combo.currentText()
        camera = None if camera_text in ("", self._camera_combo.itemText(0)) else camera_text
        return {
            "kinds": kinds,
            "camera": camera,
            "date_from": date_from,
            "date_to": date_to,
            "gps_only": self._gps_check.isChecked(),
        }

    def current_folder_rel(self) -> str | None:
        """いま選んでいるフォルダ（全体表示なら None）。"""
        return self._current_folder_rel

    def folder_exists(self, rel: str) -> bool:
        """ツリーにそのフォルダがあるかどうか。"""
        return any(getattr(row, "payload", None) == rel for row in self._folder_rows)

    def saved_filters(self) -> dict:
        """設定に書き出すための絞り込み状態。"""
        kinds = sorted(key for key, check in self._kind_checks.items() if check.isChecked())
        return {
            "kinds": kinds,
            "camera": self.current_filters()["camera"] or "",
            "period": self._period_check.isChecked(),
            "date_from": self._date_from.getDate().toString("yyyy-MM-dd"),
            "date_to": self._date_to.getDate().toString("yyyy-MM-dd"),
            "gps": self._gps_check.isChecked(),
        }

    def apply_filters_state(self, state: dict | None) -> None:
        """保存しておいた絞り込みを画面に戻す（シグナルは出さない）。

        枚数が 0 の形式（チェックできない項目）は、そのままにしておく。
        """
        if not state:
            return
        kinds = set(state.get("kinds") or ())
        for key, check in self._kind_checks.items():
            check.blockSignals(True)
            check.setChecked(bool(key in kinds and check.isEnabled()))
            check.blockSignals(False)

        camera = str(state.get("camera") or "")
        self._camera_combo.blockSignals(True)
        index = self._camera_combo.findText(camera) if camera else 0
        self._camera_combo.setCurrentIndex(max(0, index))
        self._camera_combo.blockSignals(False)

        for key, widget in (("date_from", self._date_from), ("date_to", self._date_to)):
            text = str(state.get(key) or "")
            if not text:
                continue
            date = QDate.fromString(text, "yyyy-MM-dd")
            if date.isValid():
                widget.blockSignals(True)
                widget.setDate(date)
                widget.blockSignals(False)

        period = bool(state.get("period"))
        self._period_check.blockSignals(True)
        self._period_check.setChecked(period)
        self._period_check.blockSignals(False)
        self._period_box.setEnabled(period)
        self._toggle_period_widgets(period)

        self._gps_check.blockSignals(True)
        self._gps_check.setChecked(bool(state.get("gps")))
        self._gps_check.blockSignals(False)

    def reset_filters(self) -> None:
        for check in self._kind_checks.values():
            check.blockSignals(True)
            check.setChecked(check.isEnabled())
            check.blockSignals(False)
        self._camera_combo.blockSignals(True)
        self._camera_combo.setCurrentIndex(0)
        self._camera_combo.blockSignals(False)
        self._period_check.blockSignals(True)
        self._period_check.setChecked(False)
        self._period_check.blockSignals(False)
        self._period_box.setEnabled(False)
        self._period_box.hide()
        self._gps_check.blockSignals(True)
        self._gps_check.setChecked(False)
        self._gps_check.blockSignals(False)
        self.filtersChanged.emit()

    def filter_badge_text(self) -> str:
        return ""

    # ---- 並べ替え ----
    def sort_key(self) -> str:
        data = self._sort_combo.currentData()
        return data or "datetime"

    def sort_descending(self) -> bool:
        return self._descending

    def _toggle_order(self) -> None:
        self._descending = not self._descending
        self._order_button.setIcon(FluentIcon.DOWN.icon() if self._descending else FluentIcon.UP.icon())
        self._order_button.setToolTip(
            i18n.tr("sidebar.desc") if self._descending else i18n.tr("sidebar.asc")
        )
        self.sortChanged.emit()

    # ---- テーマ ----
    def refresh_theme(self) -> None:
        """テーマに合わせて背景色・アイコン・カードを作り直す。"""
        # 自作アイコン（SD カード）は色を固定で持っているので作り直す
        for row in self._source_rows:
            source: Source = row.payload
            row.set_icon(sd_card_icon(20, accent=source.removable) if source.removable else FluentIcon.HOME.icon())
        self._camera_card.refresh_theme()

        bg = theme.sidebar_bg().name()
        self._scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:{bg};}}"
            f"QScrollArea > QWidget > QWidget{{background:{bg};}}"
        )
        self._scroll.viewport().setAutoFillBackground(False)
        self._scroll_content.setAutoFillBackground(False)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: D102, N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), theme.sidebar_bg())
        painter.setPen(QPen(theme.border(), 1))
        painter.drawLine(self.rect().topRight(), self.rect().bottomRight())
        painter.end()
