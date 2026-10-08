"""拡大表示（ビューア）ダイアログ.

写真を大きく表示し、右側に Exif の詳細をまとめて表示する。
← → で前後の写真へ移動できる。
"""

from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import QPoint, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    PrimaryPushButton,
    CaptionLabel,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    PushButton,
    SmoothScrollArea,
    StrongBodyLabel,
    SubtitleLabel,
    TransparentToolButton,
)

from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView

from . import i18n, theme
from .exifdata import (
    ExposureProgramLabel,
    color_space_label,
    ev_label,
    exposure_mode_label,
    exif_text_for_clipboard,
    flash_label,
    fmt_shutter,
    fmt_size,
    focal_label,
    metering_label,
    white_balance_label,
)
from .imaging import video_kind_label
from .model import PhotoEntry
from .sources import explorer_reveal
from .workers import LargeImageWorker


class ImageCanvas(QGraphicsView):
    """ホイールでズーム、ドラッグで移動できるキャンバス。"""

    zoomChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._item = QGraphicsPixmapItem()
        self._item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._scene.addItem(self._item)
        self.setScene(self._scene)
        self.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background:transparent;border:none;")
        self._fit_mode = True
        self._message = ""

    # ---- 画像 ----
    def set_image(self, image: QImage | None, fit: bool = True, message: str = "") -> None:
        self._message = message
        if image is None or image.isNull():
            self._item.setPixmap(QPixmap())
        else:
            self._item.setPixmap(QPixmap.fromImage(image))
        self._scene.setSceneRect(self._item.boundingRect())
        if fit and not self._item.pixmap().isNull():
            self.fit_to_window()
        else:
            self.viewport().update()

    def set_message(self, message: str) -> None:
        self._message = message
        self.viewport().update()

    def fit_to_window(self) -> None:
        if self._item.pixmap().isNull():
            return
        self._fit_mode = True
        self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)
        self._update_drag_mode()

    def actual_size(self) -> None:
        if self._item.pixmap().isNull():
            return
        self._fit_mode = False
        self.resetTransform()
        self._update_drag_mode()

    def zoom_by(self, factor: float) -> None:
        if self._item.pixmap().isNull():
            return
        self._fit_mode = False
        self.scale(factor, factor)
        self._update_drag_mode()

    def zoom_ratio(self) -> float:
        return self.transform().m11()

    def _update_drag_mode(self) -> None:
        zoomed = self.zoom_ratio() > self._fit_ratio() * 1.02
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag if zoomed else QGraphicsView.DragMode.NoDrag)
        self.zoomChanged.emit(self.zoom_ratio())

    def _fit_ratio(self) -> float:
        rect = self._item.boundingRect()
        if rect.isEmpty():
            return 1.0
        viewport = self.viewport().size()
        return min(viewport.width() / rect.width(), viewport.height() / rect.height())

    # ---- イベント ----
    def wheelEvent(self, event) -> None:  # noqa: D102, N802
        delta = event.angleDelta().y()
        if delta:
            self.zoom_by(1.0018 ** delta)
            event.accept()
            return
        super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: D102, N802
        if self._fit_mode:
            self.actual_size()
        else:
            self.fit_to_window()
        event.accept()

    def resizeEvent(self, event) -> None:  # noqa: D102
        super().resizeEvent(event)
        if self._fit_mode:
            self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)
        self.zoomChanged.emit(self.zoom_ratio())

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: D102
        if self._message and self._item.pixmap().isNull():
            painter.save()
            painter.setPen(theme.text_secondary())
            painter.setFont(theme.ui_font(theme.FONT_BODY))
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), self._message)
            painter.restore()


class InfoPanel(QWidget):
    """右側の Exif 詳細パネル。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(344)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(14, 10, 8, 6)
        title = SubtitleLabel(i18n.tr("viewer.metadata_title"), self)
        header.addWidget(title, 1)
        self.copy_button = TransparentToolButton(FluentIcon.COPY, self)
        self.copy_button.setToolTip(i18n.tr("viewer.copy_tip"))
        self.copy_button.setFixedSize(30, 30)
        header.addWidget(self.copy_button)
        layout.addLayout(header)

        self.scroll = SmoothScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.scroll, 1)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(14, 4, 14, 14)
        self._content_layout.setSpacing(6)
        self.scroll.setWidget(self._content)
        self._content.setAutoFillBackground(False)
        self.scroll.viewport().setAutoFillBackground(False)
        self.refresh_theme()
        self._current_entry: PhotoEntry | None = None

    def set_entry(self, entry: PhotoEntry) -> None:
        self._current_entry = entry
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for section, rows in build_info_rows(entry):
            self._content_layout.addWidget(self._section_title(section))
            for label, value in rows:
                self._content_layout.addWidget(self._row(label, value))
        if entry.exif and entry.exif.has_gps:
            button = PushButton(FluentIcon.GLOBE, i18n.tr("exif.resolve"), self._content)
            button.clicked.connect(lambda: self._open_map(entry))
            self._content_layout.addSpacing(4)
            self._content_layout.addWidget(button)
        self._content_layout.addStretch(1)

    def _section_title(self, text: str) -> QLabel:
        label = StrongBodyLabel(text, self._content)
        label.setContentsMargins(0, 10, 0, 2)
        return label

    def _row(self, label: str, value: str) -> QWidget:
        row = QWidget(self._content)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        name = CaptionLabel(label, row)
        name.setFixedWidth(104)
        name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        val = BodyLabel(value or "—", row)
        val.setWordWrap(True)
        val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        val.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(name)
        layout.addWidget(val, 1)
        return row

    def _open_map(self, entry: PhotoEntry) -> None:
        info = entry.exif
        if not info or not info.has_gps:
            return
        url = f"https://www.google.com/maps?q={info.gps_lat:.6f},{info.gps_lon:.6f}"
        QDesktopServices.openUrl(QUrl(url))

    def refresh_theme(self) -> None:
        """パネルの背景色をスタイルシートに反映する。"""
        bg = theme.window_bg().name()
        self.scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:{bg};}}"
            f"QScrollArea > QWidget > QWidget{{background:{bg};}}"
        )
        self._content.setAutoFillBackground(False)
        self.update()


def build_info_rows(entry: PhotoEntry) -> list[tuple[str, list[tuple[str, str]]]]:
    t = i18n.tr
    info = entry.exif
    sections: list[tuple[str, list[tuple[str, str]]]] = []
    modified = _dt.datetime.fromtimestamp(entry.mtime).strftime("%Y/%m/%d %H:%M:%S")
    file_rows = [
        (t("exif.filename"), entry.name),
        (t("exif.format"), video_kind_label(entry.name) if entry.is_video else entry.kind_text),
        (t("exif.filesize"), fmt_size(entry.size)),
        (t("exif.folder"), entry.folder),
        (t("exif.modified"), modified),
    ]
    if entry.is_video:
        video_rows = []
        if info:
            if info.duration is not None:
                video_rows.append((t("exif.duration"), info.duration_text))
            if info.width and info.height:
                video_rows.append((t("exif.dimensions"), f"{info.width}×{info.height}"))
        video_rows.append((t("exif.taken"), modified))
        sections.append((t("exif.section.video"), video_rows))
        sections.append((t("exif.section.file"), file_rows))
        return sections

    if not info:
        sections.append((t("exif.section.shooting"), [(t("exif.status"), t("exif.no_exif"))]))
        sections.append((t("exif.section.file"), file_rows))
        return sections

    shoot = [
        (t("exif.taken"), info.datetime_text),
        (t("exif.shutter"), fmt_shutter(info.exposure_time)),
        (t("exif.aperture"), f"F{info.f_number:g}" if info.f_number else ""),
        (t("exif.iso"), f"ISO {info.iso}" if info.iso else ""),
        (t("exif.focal"), focal_label(info)),
        (t("exif.exposure_bias"), ev_label(info.exposure_bias)),
        (t("exif.exposure_program"), ExposureProgramLabel(info.exposure_program)),
        (t("exif.exposure_mode"), exposure_mode_label(info.exposure_mode)),
        (t("exif.metering"), metering_label(info.metering_mode)),
        (t("exif.white_balance"), white_balance_label(info.white_balance)),
        (t("exif.flash"), flash_label(info.flash)),
    ]
    camera = [
        (t("exif.make"), info.make),
        (t("exif.model"), info.model),
        (t("exif.lens"), info.lens),
        (t("exif.lens_make"), info.lens_make),
        (t("exif.body_serial"), info.body_serial),
        (t("exif.software"), info.software),
        (t("exif.artist"), info.artist),
        (t("exif.copyright"), info.copyright),
    ]
    image = [
        (t("exif.dimensions"), f"{info.width}×{info.height}" if info.width and info.height else ""),
        (t("exif.aspect"), info.aspect_ratio_text),
        (t("exif.megapixels"), f"{info.width * info.height / 1_000_000:.1f}MP" if info.width and info.height else ""),
        (t("exif.color_space"), color_space_label(info.color_space)),
    ]
    gps = []
    if info.has_gps:
        gps = [
            (t("exif.latitude"), f"{info.gps_lat:.6f}"),
            (t("exif.longitude"), f"{info.gps_lon:.6f}"),
            (t("exif.altitude"), f"{info.gps_alt:.1f} m" if info.gps_alt is not None else ""),
        ]
    sections.append((t("exif.section.shooting"), shoot))
    sections.append((t("exif.section.camera"), camera))
    sections.append((t("exif.section.image"), image))
    if gps:
        sections.append((t("exif.section.location"), gps))
    sections.append((t("exif.section.file"), file_rows))
    return sections


class PhotoViewerDialog(QDialog):
    """写真の拡大表示ウィンドウ。"""

    closed = Signal()

    def __init__(self, entries: list[PhotoEntry], index: int = 0, worker: LargeImageWorker | None = None, parent=None):
        super().__init__(parent)
        self._entries = entries
        self._index = max(0, min(index, len(entries) - 1))
        self._worker = worker
        self._epoch = 0
        self._loading = False
        self._info_visible = True

        self.setWindowTitle(i18n.tr("app.viewer_title"))
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(1280, 830)
        self.setMinimumSize(880, 560)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._root = QWidget(self)
        self._root.setObjectName("viewerRoot")
        outer.addWidget(self._root)
        root_layout = QVBoxLayout(self._root)
        root_layout.setContentsMargins(1, 1, 1, 1)
        root_layout.setSpacing(0)

        # ---- 上部バー ----
        top = QWidget(self._root)
        top.setFixedHeight(46)
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(12, 4, 6, 4)
        top_layout.setSpacing(8)
        self._title_icon = QLabel(top)
        self._title_icon.setPixmap(FluentIcon.PHOTO.icon(color=theme.accent()).pixmap(18, 18))
        top_layout.addWidget(self._title_icon)
        self.title_label = StrongBodyLabel("", top)
        top_layout.addWidget(self.title_label, 1)
        self.counter_label = CaptionLabel("", top)
        top_layout.addWidget(self.counter_label)

        self.info_button = TransparentToolButton(FluentIcon.INFO, top)
        self.info_button.setCheckable(True)
        self.info_button.setChecked(True)
        self.info_button.setToolTip(i18n.tr("viewer.info_tip"))
        self.info_button.setFixedSize(30, 30)
        self.info_button.clicked.connect(self._toggle_info)
        top_layout.addWidget(self.info_button)

        self.open_button = TransparentToolButton(FluentIcon.APPLICATION, top)
        self.open_button.setToolTip(i18n.tr("viewer.open_tip"))
        self.open_button.setFixedSize(30, 30)
        self.open_button.clicked.connect(self._open_external)
        top_layout.addWidget(self.open_button)

        self.folder_button = TransparentToolButton(FluentIcon.FOLDER, top)
        self.folder_button.setToolTip(i18n.tr("viewer.reveal_tip"))
        self.folder_button.setFixedSize(30, 30)
        self.folder_button.clicked.connect(self._reveal)
        top_layout.addWidget(self.folder_button)

        self.close_button = TransparentToolButton(FluentIcon.CLOSE, top)
        self.close_button.setToolTip(i18n.tr("viewer.close_tip"))
        self.close_button.setFixedSize(30, 30)
        self.close_button.clicked.connect(self.close)
        top_layout.addWidget(self.close_button)
        root_layout.addWidget(top)

        # ---- 中央 ----
        center = QHBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(0)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(0)
        self.canvas = ImageCanvas(self._root)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas.zoomChanged.connect(self._on_zoom_changed)
        left.addWidget(self.canvas, 1)

        bottom = QWidget(self._root)
        bottom.setFixedHeight(46)
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(12, 4, 12, 6)
        bottom_layout.setSpacing(6)
        self.prev_button = TransparentToolButton(FluentIcon.LEFT_ARROW, bottom)
        self.prev_button.setToolTip(i18n.tr("viewer.prev_tip"))
        self.prev_button.clicked.connect(lambda: self.show_offset(-1))
        self.next_button = TransparentToolButton(FluentIcon.RIGHT_ARROW, bottom)
        self.next_button.setToolTip(i18n.tr("viewer.next_tip"))
        self.next_button.clicked.connect(lambda: self.show_offset(1))
        bottom_layout.addWidget(self.prev_button)
        bottom_layout.addWidget(self.next_button)
        bottom_layout.addSpacing(10)
        self.zoom_label = CaptionLabel("", bottom)
        bottom_layout.addWidget(self.zoom_label)
        bottom_layout.addStretch(1)
        self._play_button = PrimaryPushButton(FluentIcon.PLAY, i18n.tr("viewer.play_video"), bottom)
        self._play_button.clicked.connect(self._open_external)
        self._play_button.hide()
        bottom_layout.addWidget(self._play_button)
        self.fit_button = PushButton(i18n.tr("viewer.fit"), bottom)
        self.fit_button.clicked.connect(self.canvas.fit_to_window)
        self.actual_button = PushButton(i18n.tr("viewer.actual"), bottom)
        self.actual_button.clicked.connect(self.canvas.actual_size)
        bottom_layout.addWidget(self.fit_button)
        bottom_layout.addWidget(self.actual_button)
        left.addWidget(bottom)
        center.addLayout(left, 1)

        self.info_panel = InfoPanel(self._root)
        self.info_panel.copy_button.clicked.connect(self._copy_exif)
        center.addWidget(self.info_panel)
        root_layout.addLayout(center, 1)

        self._drag_offset: QPoint | None = None
        self._load_current(preview_first=True)

    # ------------------------------------------------------------------
    # 読み込み / 表示
    # ------------------------------------------------------------------
    def _load_current(self, preview_first: bool = False) -> None:
        if not self._entries:
            return
        entry = self._entries[self._index]
        self.setWindowTitle(f"{entry.name} — {i18n.tr('app.viewer_title')}")
        self.title_label.setText(entry.name)
        self.counter_label.setText(
            i18n.tr("viewer.counter", index=self._index + 1, total=len(self._entries))
        )
        self.info_panel.set_entry(entry)
        self.prev_button.setEnabled(self._index > 0)
        self.next_button.setEnabled(self._index < len(self._entries) - 1)

        self._epoch += 1
        self._loading = True
        self._play_button.setVisible(entry.is_video)
        if preview_first and entry.thumb is not None and not entry.thumb.isNull():
            self.canvas.set_image(entry.thumb, fit=True, message="")
        else:
            self.canvas.set_image(None, message=i18n.tr("common.loading"))
        self.canvas.set_message(i18n.tr("common.loading"))
        if self._worker is not None:
            self._worker.request(self._epoch, entry.path)
        else:
            from .imaging import load_full_image

            self._on_loaded(self._epoch, entry.path, load_full_image(entry.path))

    def _on_loaded(self, epoch: int, path: str, image) -> None:
        if epoch != self._epoch:
            return
        self._loading = False
        if image is None or image.isNull():
            entry = self._entries[self._index]
            hint = ""
            ext = entry.ext
            if ext in (".heic", ".heif", ".hif"):
                hint = i18n.tr("viewer.hint_heic")
            elif entry.kind == "raw":
                hint = i18n.tr("viewer.hint_raw")
            elif entry.is_video:
                hint = i18n.tr("viewer.hint_video")
            self.canvas.set_image(entry.thumb, fit=True, message=i18n.tr("viewer.cannot_show", hint=hint))
            return
        self.canvas.set_image(image, fit=True, message="")

    def _on_failed(self, epoch: int, message: str) -> None:
        if epoch == self._epoch:
            self._loading = False
            self.canvas.set_message(i18n.tr("viewer.load_error", error=message))

    def show_offset(self, delta: int) -> None:
        new_index = self._index + delta
        if 0 <= new_index < len(self._entries):
            self._index = new_index
            self._load_current(preview_first=True)

    def _on_zoom_changed(self, ratio: float) -> None:
        self.zoom_label.setText(f"{ratio * 100:.0f}%")

    # ------------------------------------------------------------------
    # 操作
    # ------------------------------------------------------------------
    def _toggle_info(self) -> None:
        self._info_visible = self.info_button.isChecked()
        self.info_panel.setVisible(self._info_visible)

    def _open_external(self) -> None:
        if self._entries:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._entries[self._index].path))

    def _play_current(self) -> None:
        self._open_external()

    def _reveal(self) -> None:
        if self._entries:
            explorer_reveal(self._entries[self._index].path)

    def reload_current(self) -> None:
        self._load_current(preview_first=True)

    def refresh_theme(self) -> None:
        """テーマ変更時の再描画。"""
        self._title_icon.setPixmap(FluentIcon.PHOTO.icon(color=theme.accent()).pixmap(18, 18))
        self.info_panel.refresh_theme()
        self.update()

    def _copy_exif(self) -> None:
        entry = self._entries[self._index]
        text = exif_text_for_clipboard(entry.exif, entry.name) if entry.exif else entry.name
        QGuiApplication.clipboard().setText(text)
        InfoBar.success("", i18n.tr("toast.copied_exif"), duration=1400, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

    # ------------------------------------------------------------------
    # キー / ドラッグ / 描画
    # ------------------------------------------------------------------
    def keyPressEvent(self, event) -> None:  # noqa: D102, N802
        key = event.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_PageUp):
            self.show_offset(-1)
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_PageDown, Qt.Key.Key_Space):
            self.show_offset(1)
        elif key == Qt.Key.Key_Escape:
            self.close()
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.canvas.zoom_by(1.2)
        elif key == Qt.Key.Key_Minus:
            self.canvas.zoom_by(1 / 1.2)
        elif key == Qt.Key.Key_0:
            self.canvas.fit_to_window()
        elif key == Qt.Key.Key_1:
            self.canvas.actual_size()
        elif key == Qt.Key.Key_I:
            self.info_button.setChecked(not self.info_button.isChecked())
            self._toggle_info()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: D102, N802
        # 上部バーをつかんでウィンドウを移動
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() <= 46:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: D102, N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: D102, N802
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: D102, N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        painter.fillPath(path, theme.window_bg())
        painter.setPen(theme.border())
        painter.drawPath(path)
        painter.end()

    def closeEvent(self, event) -> None:  # noqa: D102, N802
        self._epoch += 1  # 読み込み中の結果を無効化
        self.closed.emit()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    def connect_worker(self, worker: LargeImageWorker) -> None:
        self._worker = worker
        worker.loaded.connect(self._on_loaded)
        worker.failed.connect(self._on_failed)

    def disconnect_worker(self) -> None:
        if self._worker is None:
            return
        try:
            self._worker.loaded.disconnect(self._on_loaded)
            self._worker.failed.disconnect(self._on_failed)
        except (RuntimeError, TypeError):
            pass
