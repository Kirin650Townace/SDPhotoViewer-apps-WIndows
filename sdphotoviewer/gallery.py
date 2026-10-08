"""右側のメイン領域（タイル状の写真一覧）."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPoint, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    IndeterminateProgressBar,
    InfoBar,
    InfoBarPosition,
    PillPushButton,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    SearchLineEdit,
    Slider,
    StrongBodyLabel,
    SubtitleLabel,
    TransparentToolButton,
    RoundMenu,
)

from . import i18n, theme
from .delegate import TileDelegate, entry_tooltip
from .exifdata import exif_text_for_clipboard, fmt_size
from .model import EntryRole, PhotoEntry
from .sources import explorer_reveal

ZOOM_MIN = 158
ZOOM_MAX = 396
ZOOM_DEFAULT = 236


class TileListView(QListView):
    """Ctrl + ホイールでタイルサイズを変えられるアイコンビュー。"""

    zoomStep = Signal(int)
    visibleRangeChanged = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionRectVisible(True)
        self.setWordWrap(False)
        self.setSpacing(0)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLayoutMode(QListView.LayoutMode.Batched)
        self.setBatchSize(120)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setStyleSheet("QListView{background:transparent;border:none;}")
        self._range_timer = QTimer(self)
        self._range_timer.setSingleShot(True)
        self._range_timer.setInterval(80)
        self._range_timer.timeout.connect(self._emit_range)

    def wheelEvent(self, event) -> None:  # noqa: D102, N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoomStep.emit(event.angleDelta().y())
            event.accept()
            return
        super().wheelEvent(event)
        self._range_timer.start()

    def scrollContentsBy(self, dx, dy) -> None:  # noqa: D102, N802
        super().scrollContentsBy(dx, dy)
        self._range_timer.start()

    def resizeEvent(self, event) -> None:  # noqa: D102
        super().resizeEvent(event)
        self._range_timer.start()

    def schedule_range_update(self) -> None:
        self._range_timer.start()

    def _emit_range(self) -> None:
        model = self.model()
        if model is None or model.rowCount() == 0:
            self.visibleRangeChanged.emit(0, -1)
            return
        top = self.indexAt(QPoint(0, 0))
        bottom = self.indexAt(QPoint(0, self.viewport().height() - 2))
        first = top.row() if top.isValid() else 0
        last = bottom.row() if bottom.isValid() else min(model.rowCount() - 1, first + 60)
        self.visibleRangeChanged.emit(first, last)


class EmptyState(QWidget):
    """写真が無いときの案内。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(10)
        layout.addStretch(1)

        self.icon_label = QLabel(self)
        self.icon_label.setPixmap(FluentIcon.PHOTO.icon(color=theme.pick("#B4B4B4", "#4A4A4A")).pixmap(72, 72))
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_label)

        self.title = SubtitleLabel(i18n.tr("empty.title"), self)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)

        self.subtitle = BodyLabel(i18n.tr("empty.body"), self)
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.subtitle)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.choose_button = PrimaryPushButton(FluentIcon.FOLDER_ADD, i18n.tr("common.choose_folder"), self)
        self.refresh_button = PushButton(FluentIcon.SYNC, i18n.tr("common.reload"), self)
        buttons.addWidget(self.choose_button)
        buttons.addWidget(self.refresh_button)
        buttons.addStretch(1)
        layout.addSpacing(6)
        layout.addLayout(buttons)
        layout.addStretch(2)

    def set_state(self, title: str, subtitle: str) -> None:
        self.title.setText(title)
        self.subtitle.setText(subtitle)


class GalleryPanel(QWidget):
    """ツールバー + タイル一覧 + ステータスバー。"""

    openRequested = Signal(list)        # [PhotoEntry]
    searchChanged = Signal(str)
    zoomChanged = Signal(int)
    detailedToggled = Signal(bool)
    refreshRequested = Signal()
    themeToggleRequested = Signal()
    languageToggleRequested = Signal()
    aboutRequested = Signal()
    visibleRangeChanged = Signal(int, int)
    chooseFolderRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.delegate = TileDelegate(self)
        self._model = None
        self._proxy = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- ツールバー ----
        toolbar = QWidget(self)
        toolbar.setObjectName("galleryToolbar")
        tb = QVBoxLayout(toolbar)
        tb.setContentsMargins(14, 8, 14, 8)
        tb.setSpacing(6)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self.breadcrumb = StrongBodyLabel("", self)
        self.breadcrumb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row1.addWidget(self.breadcrumb, 1)
        self.search = SearchLineEdit(self)
        self.search.setPlaceholderText(i18n.tr("gallery.search"))
        self.search.setFixedWidth(230)
        self.search.searchSignal.connect(self._on_search)
        self.search.textChanged.connect(self._on_search_text)
        row1.addWidget(self.search)
        tb.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.count_label = BodyLabel(i18n.tr("common.loading"), self)
        row2.addWidget(self.count_label)
        self.selection_label = CaptionLabel("", self)
        row2.addWidget(self.selection_label)
        row2.addStretch(1)

        self.detail_button = PillPushButton(i18n.tr("gallery.detail_toggle"), self)
        self.detail_button.setCheckable(True)
        self.detail_button.setToolTip(i18n.tr("gallery.detail_tip"))
        self.detail_button.toggled.connect(self._on_detailed_toggled)
        row2.addWidget(self.detail_button)

        self.zoom_out_button = TransparentToolButton(FluentIcon.ZOOM_OUT, self)
        self.zoom_out_button.setToolTip(i18n.tr("gallery.zoom_out_tip"))
        self.zoom_out_button.setFixedSize(28, 28)
        self.zoom_out_button.clicked.connect(lambda: self._nudge_zoom(-24))
        row2.addWidget(self.zoom_out_button)

        self.zoom_slider = Slider(Qt.Orientation.Horizontal, self)
        self.zoom_slider.setRange(ZOOM_MIN, ZOOM_MAX)
        self.zoom_slider.setValue(ZOOM_DEFAULT)
        self.zoom_slider.setFixedWidth(120)
        self.zoom_slider.valueChanged.connect(self._on_zoom_changed)
        row2.addWidget(self.zoom_slider)

        self.zoom_in_button = TransparentToolButton(FluentIcon.ZOOM_IN, self)
        self.zoom_in_button.setToolTip(i18n.tr("gallery.zoom_in_tip"))
        self.zoom_in_button.setFixedSize(28, 28)
        self.zoom_in_button.clicked.connect(lambda: self._nudge_zoom(24))
        row2.addWidget(self.zoom_in_button)

        self.refresh_button = TransparentToolButton(FluentIcon.SYNC, self)
        self.refresh_button.setToolTip(i18n.tr("common.reload_tip"))
        self.refresh_button.setFixedSize(28, 28)
        self.refresh_button.clicked.connect(self.refreshRequested)
        row2.addWidget(self.refresh_button)

        self.theme_button = TransparentToolButton(FluentIcon.BRIGHTNESS, self)
        self.theme_button.setToolTip(i18n.tr("gallery.theme_tip"))
        self.theme_button.setFixedSize(28, 28)
        self.theme_button.clicked.connect(self.themeToggleRequested)
        row2.addWidget(self.theme_button)

        self.language_button = TransparentToolButton(FluentIcon.LANGUAGE, self)
        self.language_button.setToolTip(i18n.tr("gallery.language_tip"))
        self.language_button.setFixedSize(28, 28)
        self.language_button.clicked.connect(self.languageToggleRequested)
        row2.addWidget(self.language_button)

        # 著作権・ライセンスの表示（GPLv3 の条件を満たすために常設）
        self.about_button = TransparentToolButton(FluentIcon.INFO, self)
        self.about_button.setToolTip(i18n.tr("about.tip"))
        self.about_button.setFixedSize(28, 28)
        self.about_button.clicked.connect(self.aboutRequested)
        row2.addWidget(self.about_button)
        tb.addLayout(row2)

        # ---- 進捗 ----
        self.progress_container = QWidget(self)
        pc = QVBoxLayout(self.progress_container)
        pc.setContentsMargins(0, 0, 0, 0)
        pc.setSpacing(0)
        self.scan_bar = IndeterminateProgressBar(self, start=False)
        self.meta_bar = ProgressBar(self)
        pc.addWidget(self.scan_bar)
        pc.addWidget(self.meta_bar)
        self.meta_bar.hide()
        layout.addWidget(toolbar)
        layout.addWidget(self.progress_container)

        sep = QFrame(self)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{theme.border().name()};")
        self._separator = sep
        layout.addWidget(sep)

        # ---- 一覧 / 空状態 ----
        self.stack = QStackedWidget(self)
        self.view = TileListView(self)
        self.view.setItemDelegate(self.delegate)
        self.view.doubleClicked.connect(self._on_activated)
        self.view.activated.connect(self._on_activated)
        self.view.customContextMenuRequested.connect(self._on_context_menu)
        self.view.zoomStep.connect(lambda d: self._nudge_zoom(28 if d > 0 else -28))
        self.view.visibleRangeChanged.connect(self.visibleRangeChanged)

        self.empty = EmptyState(self)
        self.empty.choose_button.clicked.connect(self.chooseFolderRequested)
        self.empty.refresh_button.clicked.connect(self.refreshRequested)
        self.stack.addWidget(self.view)
        self.stack.addWidget(self.empty)
        layout.addWidget(self.stack, 1)

        # ---- ステータスバー ----
        status = QWidget(self)
        sb = QHBoxLayout(status)
        sb.setContentsMargins(14, 4, 14, 6)
        sb.setSpacing(8)
        self.status_left = CaptionLabel("", self)
        self.status_right = CaptionLabel("", self)
        sb.addWidget(self.status_left, 1)
        sb.addWidget(self.status_right, 0)
        layout.addWidget(status)

        self.set_zoom(ZOOM_DEFAULT)
        self.show_empty(i18n.tr("empty.title"), i18n.tr("empty.body"))

    # ------------------------------------------------------------------
    # モデル
    # ------------------------------------------------------------------
    def set_model(self, model, proxy) -> None:
        self._model = model
        self._proxy = proxy
        self.view.setModel(proxy)
        self.view.selectionModel().selectionChanged.connect(lambda *_a: self.update_counts())

    # ------------------------------------------------------------------
    # 表示状態
    # ------------------------------------------------------------------
    def show_empty(self, title: str, subtitle: str) -> None:
        self.empty.set_state(title, subtitle)
        self.stack.setCurrentWidget(self.empty)

    def show_list(self) -> None:
        self.stack.setCurrentWidget(self.view)

    def set_breadcrumb(self, text: str) -> None:
        self.breadcrumb.setText(text)

    def set_zoom(self, value: int) -> None:
        value = max(ZOOM_MIN, min(ZOOM_MAX, int(value)))
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(value)
        self.zoom_slider.blockSignals(False)
        self.delegate.set_tile_width(value)
        self._apply_grid()
        self.zoomChanged.emit(value)

    def _nudge_zoom(self, delta: int) -> None:
        self.set_zoom(self.zoom_slider.value() + delta)

    def _on_zoom_changed(self, value: int) -> None:
        self.delegate.set_tile_width(value)
        self._apply_grid()
        self.zoomChanged.emit(value)

    def _apply_grid(self) -> None:
        size: QSize = self.delegate.metrics().size()
        self.view.setGridSize(size)
        self.view.scheduleDelayedItemsLayout()
        self.view.viewport().update()

    def _on_detailed_toggled(self, checked: bool) -> None:
        self.delegate.set_detailed(checked)
        self._apply_grid()
        self.detailedToggled.emit(checked)

    def set_detailed(self, checked: bool) -> None:
        self.detail_button.blockSignals(True)
        self.detail_button.setChecked(checked)
        self.detail_button.blockSignals(False)
        self.delegate.set_detailed(checked)
        self._apply_grid()

    # ------------------------------------------------------------------
    # 進捗表示
    # ------------------------------------------------------------------
    def set_scanning(self, active: bool, found: int = 0) -> None:
        if active:
            self.progress_container.show()
            self.scan_bar.show()
            self.scan_bar.start()
            self.meta_bar.hide()
            self.status_right.setText(i18n.tr("gallery.scanning", count=f"{found:,}"))
        else:
            self.scan_bar.stop()
            self.scan_bar.hide()
            self.status_right.setText("")

    def set_meta_progress(self, done: int, total: int) -> None:
        if total <= 0 or done >= total:
            self.meta_bar.hide()
            if done >= total:
                self.status_right.setText("")
            return
        self.progress_container.show()
        self.meta_bar.show()
        self.meta_bar.setValue(int(done / total * 100))
        self.status_right.setText(i18n.tr("gallery.meta_progress", done=f"{done:,}", total=f"{total:,}"))

    def set_status(self, left: str, right: str = "") -> None:
        self.status_left.setText(left)
        if right:
            self.status_right.setText(right)

    # ------------------------------------------------------------------
    # 件数表示
    # ------------------------------------------------------------------
    def update_counts(self) -> None:
        if self._model is None:
            return
        total = self._proxy.rowCount()
        total_bytes = sum(self._model.entry(r).size for r in range(self._model.rowCount()) if self._model.entry(r))
        self.count_label.setText(
            i18n.tr("gallery.count", count=i18n.n_files(total), size=fmt_size(total_bytes))
        )
        entries = self.selected_entries()
        if entries:
            size = sum(e.size for e in entries)
            self.selection_label.setText(
                i18n.tr("gallery.selected", count=i18n.n_files(len(entries)), size=fmt_size(size))
            )
        else:
            self.selection_label.setText("")

    # ------------------------------------------------------------------
    # 選択・操作
    # ------------------------------------------------------------------
    def selected_entries(self) -> list[PhotoEntry]:
        if self._proxy is None:
            return []
        entries = []
        for index in self.view.selectionModel().selectedIndexes():
            entry = index.data(EntryRole)
            if entry is not None:
                entries.append(entry)
        # 表示順（プロキシの並び）に整える
        ordered = []
        for row in range(self._proxy.rowCount()):
            idx = self._proxy.index(row, 0)
            entry = idx.data(EntryRole)
            if entry in entries:
                ordered.append(entry)
        return ordered

    def current_entry(self) -> PhotoEntry | None:
        index = self.view.currentIndex()
        if not index.isValid():
            return None
        return index.data(EntryRole)

    def _on_activated(self, index: QModelIndex) -> None:
        entries = self.selected_entries()
        if not entries:
            entry = index.data(EntryRole)
            entries = [entry] if entry is not None else []
        if entries:
            self.openRequested.emit(entries)

    def _on_search_text(self, text: str) -> None:
        if text == "":
            self._on_search(text)

    def _on_search(self, text: str) -> None:
        self.searchChanged.emit(text)

    # ------------------------------------------------------------------
    # コンテキストメニュー
    # ------------------------------------------------------------------
    def _on_context_menu(self, pos: QPoint) -> None:
        index = self.view.indexAt(pos)
        if index.isValid() and index not in self.view.selectionModel().selectedIndexes():
            self.view.setCurrentIndex(index)
        entries = self.selected_entries()
        if not entries:
            return
        menu = RoundMenu(parent=self)
        is_video = entries[0].is_video
        open_action = QAction(FluentIcon.ZOOM.icon(), i18n.tr("menu.open_large"), menu)
        open_action.triggered.connect(lambda: self.openRequested.emit(entries))
        app_action = QAction(
            FluentIcon.PLAY.icon() if is_video else FluentIcon.APPLICATION.icon(),
            i18n.tr("menu.play_video") if is_video else i18n.tr("menu.open_default"),
            menu,
        )
        app_action.triggered.connect(lambda: [QDesktopServices.openUrl(QUrl.fromLocalFile(e.path)) for e in entries[:10]])
        folder_action = QAction(FluentIcon.FOLDER.icon(), i18n.tr("menu.reveal"), menu)
        folder_action.triggered.connect(lambda: explorer_reveal(entries[0].path))
        path_action = QAction(FluentIcon.COPY.icon(), i18n.tr("menu.copy_path"), menu)
        path_action.triggered.connect(lambda: self._copy_text("\n".join(e.path for e in entries)))
        exif_action = QAction(FluentIcon.DOCUMENT.icon(), i18n.tr("menu.copy_exif"), menu)
        exif_action.triggered.connect(lambda: self._copy_exif(entries))
        image_action = QAction(FluentIcon.PHOTO.icon(), i18n.tr("menu.copy_image"), menu)
        image_action.triggered.connect(lambda: self._copy_image(entries[0]))
        clear_action = QAction(FluentIcon.CLEAR_SELECTION.icon(), i18n.tr("menu.clear_selection"), menu)
        clear_action.triggered.connect(self.view.clearSelection)
        for action in (open_action, app_action, folder_action):
            menu.addAction(action)
        menu.addSeparator()
        for action in (path_action, exif_action, image_action):
            menu.addAction(action)
        menu.addSeparator()
        menu.addAction(clear_action)
        menu.exec(self.view.viewport().mapToGlobal(pos))

    def _copy_text(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)
        self._toast(i18n.tr("toast.copied"))

    def _copy_exif(self, entries: list[PhotoEntry]) -> None:
        if len(entries) == 1:
            entry = entries[0]
            info = entry.exif
            text = exif_text_for_clipboard(info, entry.name) if info else f"{i18n.tr('exif.filename')}: {entry.name}"
        else:
            lines = []
            for entry in entries:
                info = entry.exif
                base = entry.name
                if info and info.exposure_text:
                    base += f" — {info.datetime_text} / {info.exposure_text}"
                lines.append(base)
            text = "\n".join(lines)
        self._copy_text(text)

    def _copy_image(self, entry: PhotoEntry) -> None:
        if entry.thumb is not None and not entry.thumb.isNull():
            QGuiApplication.clipboard().setImage(entry.thumb)
            self._toast(i18n.tr("toast.copied_image"))
        else:
            self._toast(i18n.tr("toast.wait_loading"), error=True)

    def _toast(self, text: str, error: bool = False) -> None:
        if error:
            InfoBar.warning("", text, duration=1800, position=InfoBarPosition.BOTTOM_RIGHT, parent=self.window())
        else:
            InfoBar.success("", text, duration=1500, position=InfoBarPosition.BOTTOM_RIGHT, parent=self.window())

    # ------------------------------------------------------------------
    # テーマ
    # ------------------------------------------------------------------
    def refresh_theme(self) -> None:
        self.delegate.clear_icon_cache()
        self._separator.setStyleSheet(f"background:{theme.border().name()};")
        self.empty.icon_label.setPixmap(FluentIcon.PHOTO.icon(color=theme.pick("#B4B4B4", "#4A4A4A")).pixmap(72, 72))
        self.view.viewport().update()


def tooltip_for(entry: PhotoEntry) -> str:
    return entry_tooltip(entry)
