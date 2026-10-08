"""メインウィンドウ（全体の組み立てと制御）."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QWidget
from PySide6.QtGui import QColor
from qfluentwidgets import FluentWindow, InfoBar, InfoBarPosition, isDarkTheme

from . import i18n
from . import theme as theme_utils

# 設定（QSettings）のキー
SETTINGS_KEY_KINDS = "filters/kinds"
SETTINGS_KEY_CAMERA = "filters/camera"
SETTINGS_KEY_PERIOD = "filters/period"
SETTINGS_KEY_DATE_FROM = "filters/date_from"
SETTINGS_KEY_DATE_TO = "filters/date_to"
SETTINGS_KEY_GPS = "filters/gps"
SETTINGS_KEY_FOLDER = "filters/folder"
DEFAULT_KINDS = {"jpeg", "heic", "raw", "video", "other"}
from .compat import PILLOW_HEIF_AVAILABLE, RAWPY_AVAILABLE, app_icon, has_ffmpeg
from .exifdata import ExifInfo, fmt_size
from .gallery import ZOOM_DEFAULT, GalleryPanel
from .imaging import THUMB_EDGE
from .model import PhotoFilterProxy, PhotoModel, SourceStats, compute_stats
from .sidebar import Sidebar, sd_card_icon
from .sources import (
    FolderNode,
    Source,
    dcim_hint,
    discover_sources,
    list_photo_folders,
    source_from_folder,
)
from .viewer import PhotoViewerDialog
from .workers import (
    LargeImageWorker,
    MetaCache,
    MetadataWorker,
    ScanWorker,
    ThumbnailService,
)


class SDPhotoViewerWindow(FluentWindow):
    """SD カードの写真をタイル表示するメインウィンドウ。"""

    # ウィンドウ背景（Windows 11 のダーク/ライトに合わせた色）
    WINDOW_BG_LIGHT = "#F3F3F3"
    WINDOW_BG_DARK = "#202020"

    def __init__(self, initial_path: str | None = None, parent=None):
        super().__init__(parent)
        self._initial_path = initial_path
        self.setWindowTitle(i18n.tr("app.title"))
        self.resize(1440, 920)
        self.setMinimumSize(1080, 680)
        icon = app_icon()
        self.setWindowIcon(icon if not icon.isNull() else QIcon(sd_card_icon(64).pixmap(64, 64)))
        self._apply_window_effects()

        # ---- 状態 ----
        self._settings = QSettings("SDPhotoViewer", "SDPhotoViewer")
        self._epoch = 0
        self._source: Source | None = None
        self._folder_root: FolderNode | None = None
        self._stats: SourceStats | None = None
        self._meta_total = 0
        self._meta_done = 0
        self._date_bounds_set = False
        self._notified_missing_codec = False
        self._viewer: PhotoViewerDialog | None = None
        self._bg_pos = 0
        self._thumbs_requested: set[int] = set()

        # ---- モデル ----
        self.model = PhotoModel(self)
        self.proxy = PhotoFilterProxy(self)
        self.proxy.setSourceModel(self.model)

        # ---- スレッド ----
        threads = max(1, min(4, (os.cpu_count() or 2) - 1))
        self._scanner = ScanWorker(self)
        self._scanner.batch.connect(self._on_scan_batch)
        self._scanner.progress.connect(self._on_scan_progress)
        self._scanner.finished_scan.connect(self._on_scan_finished)
        self._scanner.failed.connect(lambda e, msg: self._toast(f"スキャンに失敗しました: {msg}", error=True))

        self._metadata = MetadataWorker(self)
        self._metadata.meta.connect(self._on_meta)
        self._metadata.start()

        self._thumb_edge = THUMB_EDGE if (self.devicePixelRatioF() <= 1.25) else int(THUMB_EDGE * 1.4)
        self._thumbs = ThumbnailService(threads=threads, parent=self)
        self._thumbs.thumbnail.connect(self._on_thumbnail)

        self._large_worker = LargeImageWorker(self)
        self._large_worker.start()

        self._cache = MetaCache()

        # ---- UI ----
        self._build_ui()
        self._wire_signals()
        self._restore_settings()

        # ---- タイマー ----
        self._stats_timer = QTimer(self)
        self._stats_timer.setSingleShot(True)
        self._stats_timer.setInterval(500)
        self._stats_timer.timeout.connect(self._refresh_stats)

        self._bg_timer = QTimer(self)
        self._bg_timer.setInterval(220)
        self._bg_timer.timeout.connect(self._request_background_thumbs)

        self._codec_timer = QTimer(self)
        self._codec_timer.setSingleShot(True)
        self._codec_timer.setInterval(1500)
        self._codec_timer.timeout.connect(self._warn_missing_codec)

        self._refresh_sources()
        QTimer.singleShot(200, self._open_initial_source)

    # ------------------------------------------------------------------
    # 見た目
    # ------------------------------------------------------------------
    def _apply_window_effects(self) -> None:
        try:
            if sys.platform.startswith("win"):
                self.setMicaEffectEnabled(True)
        except Exception:  # noqa: BLE001
            pass
        self._apply_theme_colors()

    def _apply_theme_colors(self) -> None:
        """ウィンドウ背景色を今のテーマに合わせて即座に反映する。

        qfluentwidgets は背景色を 120ms かけてアニメーションさせるため、
        テーマ切り替え直後に明るいままの領域が残ることがある。
        自前で描画している部分（左パネル・タイル）は即時に切り替わるので、
        背景も合わせて即時に切り替えて見た目を揃える。
        """
        self.setCustomBackgroundColor(self.WINDOW_BG_LIGHT, self.WINDOW_BG_DARK)
        self.backgroundColorAni.stop()
        self.setBackgroundColor(QColor(self.WINDOW_BG_DARK if isDarkTheme() else self.WINDOW_BG_LIGHT))
        self.update()

    def _build_ui(self) -> None:
        self.navigationInterface.hide()
        self.stackedWidget.hide()

        self.content = QWidget(self)
        layout = QHBoxLayout(self.content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = Sidebar(self.content)
        self.gallery = GalleryPanel(self.content)
        layout.addWidget(self.sidebar)
        layout.addWidget(self.gallery, 1)
        self.widgetLayout.addWidget(self.content)

    def _wire_signals(self) -> None:
        self.sidebar.sourceSelected.connect(self.open_source)
        self.sidebar.folderSelected.connect(self._on_folder_selected)
        self.sidebar.filtersChanged.connect(self._save_filter_settings)
        self.sidebar.folderSelected.connect(lambda _rel: self._save_filter_settings())
        self.sidebar.filtersChanged.connect(self._apply_filters)
        self.sidebar.sortChanged.connect(self._apply_sort)
        self.sidebar.refreshRequested.connect(self.refresh)
        self.sidebar.chooseFolderRequested.connect(self.choose_folder)
        self.sidebar.fixedDisksToggled.connect(self._on_fixed_disks_toggled)
        self.gallery.languageToggleRequested.connect(self._toggle_language)
        self.gallery.aboutRequested.connect(self.show_about)

        self.gallery.openRequested.connect(self.open_viewer)
        self.gallery.searchChanged.connect(lambda _t: self._apply_filters())
        self.gallery.zoomChanged.connect(self._on_zoom_changed)
        self.gallery.detailedToggled.connect(self._on_detailed_toggled)
        self.gallery.refreshRequested.connect(self.refresh)
        self.gallery.themeToggleRequested.connect(self.toggle_theme)
        self.gallery.visibleRangeChanged.connect(self._on_visible_range)
        self.gallery.chooseFolderRequested.connect(self.choose_folder)

        self.gallery.set_model(self.model, self.proxy)
        self.gallery.view.selectionModel().currentChanged.connect(self._on_current_changed)

        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.choose_folder)
        QShortcut(QKeySequence("F5"), self, activated=self.refresh)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: self.gallery.search.setFocus())
        self.setAcceptDrops(True)

    # ------------------------------------------------------------------
    # 設定の保存 / 復元
    # ------------------------------------------------------------------
    def _restore_settings(self) -> None:
        geometry = self._settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        width = int(self._settings.value("tile_width", ZOOM_DEFAULT))
        self.gallery.set_zoom(width)
        detailed = self._settings.value("detailed", "false") in ("true", "True", True)
        self.gallery.set_detailed(detailed)
        self.sidebar._sort_combo.setCurrentIndex(
            max(0, int(self._settings.value("sort_index", 0)))
        )
        descending = self._settings.value("sort_desc", "true") in ("true", "True", True)
        # 前回の絞り込み / 選択フォルダ（スキャンが終わってから反映する）
        self._pending_filters = self._load_filter_state()
        self._pending_folder = str(self._settings.value(SETTINGS_KEY_FOLDER, "") or "")
        if self._pending_filters:
            self.sidebar.apply_filters_state(self._pending_filters)
        if descending != self.sidebar._descending:
            self.sidebar._toggle_order()
        self._apply_sort()

    def _load_filter_state(self) -> dict | None:
        """保存された絞り込みを読み出す（何も設定されていなければ None）。"""
        kinds_text = str(self._settings.value(SETTINGS_KEY_KINDS, "") or "")
        if not kinds_text:
            return None
        state = {
            "kinds": [k for k in kinds_text.split(",") if k],
            "camera": str(self._settings.value(SETTINGS_KEY_CAMERA, "") or ""),
            "period": self._settings.value(SETTINGS_KEY_PERIOD, "false") in ("true", "True", True),
            "date_from": str(self._settings.value(SETTINGS_KEY_DATE_FROM, "") or ""),
            "date_to": str(self._settings.value(SETTINGS_KEY_DATE_TO, "") or ""),
            "gps": self._settings.value(SETTINGS_KEY_GPS, "false") in ("true", "True", True),
        }
        # 全部既定のままなら「絞り込みなし」として扱う（初回起動と同じ動きにする）
        if (
            set(state["kinds"]) == DEFAULT_KINDS
            and not state["camera"]
            and not state["period"]
            and not state["gps"]
        ):
            return None
        return state

    def _save_filter_settings(self) -> None:
        """絞り込みと選択フォルダだけを保存する（変更のたびに呼ばれる）。"""
        state = self.sidebar.saved_filters()
        self._settings.setValue(SETTINGS_KEY_KINDS, ",".join(state["kinds"]))
        self._settings.setValue(SETTINGS_KEY_CAMERA, state["camera"])
        self._settings.setValue(SETTINGS_KEY_PERIOD, "true" if state["period"] else "false")
        self._settings.setValue(SETTINGS_KEY_DATE_FROM, state["date_from"])
        self._settings.setValue(SETTINGS_KEY_DATE_TO, state["date_to"])
        self._settings.setValue(SETTINGS_KEY_GPS, "true" if state["gps"] else "false")
        self._settings.setValue(SETTINGS_KEY_FOLDER, self.sidebar.current_folder_rel() or "")

    def _save_settings(self) -> None:
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.setValue("tile_width", self.gallery.zoom_slider.value())
        self._settings.setValue("detailed", "true" if self.gallery.delegate.detailed else "false")
        self._settings.setValue("sort_index", self.sidebar._sort_combo.currentIndex())
        self._settings.setValue("sort_desc", "true" if self.sidebar._descending else "false")
        self._settings.setValue("language", i18n.current_language())
        self._settings.setValue(theme_utils.THEME_KEY, theme_utils.load_saved_theme() or ("dark" if isDarkTheme() else "light"))
        self._save_filter_settings()
        if self._source is not None:
            kind = "removable" if self._source.removable else ("folder" if self._source.kind == "folder" else "fixed")
            self._settings.setValue("last_path", self._source.path)
            self._settings.setValue("last_path_kind", kind)

    # ------------------------------------------------------------------
    # 取り込み元
    # ------------------------------------------------------------------
    def _refresh_sources(self) -> None:
        include_fixed = self._settings.value("include_fixed", "false") in ("true", "True", True)
        self._include_fixed = include_fixed
        self.sidebar.set_include_fixed(include_fixed)
        self._sources = discover_sources(include_fixed=include_fixed)
        # いま開いている取り込み元が一覧から外れた場合でも、表示中のものが分かるように残す
        if self._source is not None and not any(
            os.path.normcase(s.path) == os.path.normcase(self._source.path) for s in self._sources
        ):
            self._sources.append(self._source)
        self.sidebar.set_sources(self._sources, self._source.path if self._source else None)

    def _on_fixed_disks_toggled(self, checked: bool) -> None:
        self._settings.setValue("include_fixed", "true" if checked else "false")
        self._refresh_sources()
        if checked:
            InfoBar.info(
                i18n.tr("info.local_on_title"),
                i18n.tr("info.local_on_body"),
                duration=4000,
                position=InfoBarPosition.BOTTOM_RIGHT,
                parent=self,
            )
        elif not self._sources:
            self.gallery.show_empty(i18n.tr("empty.no_card_title"), i18n.tr("empty.no_card_body"))

    def _open_initial_source(self) -> None:
        if self._initial_path and os.path.isdir(self._initial_path):
            self.open_path(self._initial_path)
            return
        last = self._settings.value("last_path", "")
        last_kind = str(self._settings.value("last_path_kind", "removable"))
        if last and os.path.isdir(str(last)) and self._can_restore(last_kind):
            self.open_path(str(last))
            return
        if self._sources:
            self.open_source(self._sources[0])
        else:
            self.gallery.show_empty(i18n.tr("empty.no_card_title"), i18n.tr("empty.no_card_body"))

    def _can_restore(self, kind: str) -> bool:
        """前回開いていたフォルダを自動で開き直してよいか。

        内蔵ディスク（きっかけが曖昧で重くなりやすい）は、ローカルディスク表示を
        オンにしているときだけ復元する。
        """
        if kind in ("removable", "folder"):
            return True
        return bool(getattr(self, "_include_fixed", False))

    def open_source(self, source: Source) -> None:
        if source is None:
            return
        self._source = source
        self.sidebar.set_current_source(source.path)
        self.open_path(source.path)

    def open_path(self, path: str) -> None:
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            self._toast("フォルダが見つかりません", error=True)
            return
        sources = getattr(self, "_sources", [])
        match = next((s for s in sources if os.path.normcase(s.path) == os.path.normcase(path)), None)
        if match is None:
            match = source_from_folder(path)
            sources.append(match)
            self.sidebar.set_sources(sources, path)
            self._sources = sources
        self._sources = sources
        self._source = match
        self.sidebar.set_current_source(path)
        self._start_scan(path)

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, i18n.tr("dialog.choose_folder"))
        if folder:
            self.open_path(folder)
            self._refresh_sources()

    def refresh(self) -> None:
        if self._source is not None:
            self._start_scan(self._source.path)
        else:
            self._refresh_sources()
            self._open_initial_source()

    # ------------------------------------------------------------------
    # スキャン
    # ------------------------------------------------------------------
    def _start_scan(self, path: str) -> None:
        self._epoch += 1
        self._meta_total = 0
        self._meta_done = 0
        self._date_bounds_set = False
        self._kinds_initialized = False
        self._bg_pos = 0
        self._thumbs_requested.clear()
        self._cache = MetaCache()
        self.model.reset_entries(path, [])
        self.proxy.set_root(path)
        self.proxy.set_filters(kinds={"jpeg", "heic", "raw", "video", "other"}, camera=None, date_from=None, date_to=None, gps_only=False, text="", folder_rel=None)
        if not self._pending_filters:
            self.sidebar.reset_filters()
        self._kinds_initialized = False
        self.sidebar.set_current_folder(None)
        self.sidebar.set_folders(None)
        self._thumbs.set_epoch(self._epoch)
        self._metadata.set_epoch(self._epoch)
        self.gallery.show_list()
        self.gallery.set_scanning(True, 0)
        self.gallery.set_meta_progress(0, 0)
        self.gallery.set_breadcrumb(os.path.basename(path.rstrip("\\/")) or path)
        self.gallery.update_counts()
        hint = dcim_hint(path)
        self.gallery.set_status(path + (f"　（{hint}）" if hint else ""), "")
        self._bg_timer.stop()
        self._scanner.start_scan(path, self._epoch)
        if self._viewer is not None:
            self._viewer.close()

    def _on_scan_batch(self, epoch: int, files: list) -> None:
        if epoch != self._epoch:
            return
        start_row = self.model.rowCount()
        added = self.model.append_files(files)
        if added:
            self._meta_total = self.model.rowCount()
            rows = []
            for offset, f in enumerate(files):
                row = start_row + offset
                cached = self._cache.get(f.path, f.size, f.mtime)
                if cached is not None:
                    self.model.set_exif(row, cached)
                else:
                    rows.append((row, f.path, f.size))
            if rows:
                self._metadata.submit(rows)
        self.gallery.update_counts()

    def _on_scan_progress(self, found: int, dirs: int) -> None:
        self.gallery.set_scanning(True, found)

    def _on_scan_finished(self, epoch: int, total: int) -> None:
        if epoch != self._epoch:
            return
        self.gallery.set_scanning(False)
        self.gallery.set_meta_progress(self._meta_done, max(1, self._meta_total))
        if total == 0:
            self.gallery.show_empty(
                i18n.tr("empty.no_media_title"),
                i18n.tr("empty.no_media_body", path=self._source.path if self._source else ""),
            )
        else:
            self.gallery.show_list()
            self._build_folder_tree()
            self._bg_timer.start()
        self._stats_timer.start()
        self.gallery.update_counts()

    # ------------------------------------------------------------------
    # フォルダツリー
    # ------------------------------------------------------------------
    def _build_folder_tree(self) -> None:
        if self._source is None:
            return
        folders = list_photo_folders(self._source.path)
        self._folder_root = folders
        self.sidebar.set_folders(folders)
        rel = getattr(self, "_pending_folder", "")
        self._pending_folder = ""
        if rel and self.sidebar.folder_exists(rel):
            self.sidebar.set_current_folder(rel)
            self._on_folder_selected(rel)

    # ------------------------------------------------------------------
    # Exif 読み込み
    # ------------------------------------------------------------------
    def _on_meta(self, epoch: int, row: int, info: ExifInfo) -> None:
        if epoch != self._epoch:
            return
        entry = self.model.entry(row)
        if entry is None:
            return
        self._cache.put(entry.path, entry.size, entry.mtime, info)
        self.model.set_exif(row, info)
        self._meta_done += 1
        if self._meta_done % 25 == 0 or self._meta_done == self._meta_total:
            self.gallery.set_meta_progress(self._meta_done, self._meta_total)
        if self._meta_done % 40 == 0:
            self._coalesce_sort()
        if not self._stats_timer.isActive():
            self._stats_timer.start()
        self._codec_timer.start()

    def _coalesce_sort(self) -> None:
        """Exif が増えると並び順が変わるため、まとめて再ソートする。"""
        order = Qt.SortOrder.DescendingOrder if self.sidebar.sort_descending() else Qt.SortOrder.AscendingOrder
        self.proxy.resort(self.sidebar.sort_key(), order)
        self._request_visible_thumbs()

    # ------------------------------------------------------------------
    # 集計と表示更新
    # ------------------------------------------------------------------
    def _refresh_stats(self) -> None:
        entries = self.model.entries()
        self._stats = compute_stats(entries)
        self.sidebar.update_camera_card(self._stats, self._source)

        cameras = [name for name, _count in self._stats.cameras.most_common() if name]
        self.sidebar.set_camera_choices(cameras)
        # 初回は全形式をチェックするが、復元する絞り込みがあるときはその内容を優先する
        auto_check = (not self._kinds_initialized) and not self._pending_filters
        self.sidebar.set_kind_counts(self.model.counts(), auto_check=auto_check)
        if self._pending_filters:
            self.sidebar.apply_filters_state(self._pending_filters)
            self._pending_filters = None
        self._kinds_initialized = True
        if not self._date_bounds_set and self._stats.date_min and self._stats.date_max:
            self.sidebar.set_date_bounds(self._stats.date_min.date(), self._stats.date_max.date())
            self._date_bounds_set = True

        if self._source is not None and self.model.rowCount():
            self.sidebar.update_source_row(
                self._source.path,
                i18n.tr("source.summary", n=i18n.n_files(self.model.rowCount()), size=fmt_size(self._stats.total_bytes)),
            )
        self._apply_filters()
        self.gallery.update_counts()

    def _warn_missing_codec(self) -> None:
        if self._notified_missing_codec or self._stats is None:
            return
        hints = []
        if self._stats.kinds.get("heic") and not PILLOW_HEIF_AVAILABLE:
            hints.append(i18n.tr("warn.heic"))
        if self._stats.kinds.get("raw") and not RAWPY_AVAILABLE:
            hints.append(i18n.tr("warn.raw"))
        if self._stats.kinds.get("video") and not has_ffmpeg():
            hints.append(i18n.tr("warn.video"))
        if hints:
            self._notified_missing_codec = True
            InfoBar.warning(
                i18n.tr("warn.codec_title"),
                " / ".join(hints),
                duration=6000,
                position=InfoBarPosition.BOTTOM_RIGHT,
                parent=self,
            )

    # ------------------------------------------------------------------
    # 絞り込み / 並べ替え
    # ------------------------------------------------------------------
    def _apply_filters(self) -> None:
        filters = self.sidebar.current_filters()
        filters["text"] = self.gallery.search.text()
        self.proxy.set_filters(**filters)
        self._thumbs_requested.clear()
        self.gallery.update_counts()
        self._request_visible_thumbs()
        if self.proxy.rowCount() == 0 and self.model.rowCount() > 0:
            self.gallery.show_empty(i18n.tr("empty.filtered_title"), i18n.tr("empty.filtered_body"))
        elif self.model.rowCount() > 0:
            self.gallery.show_list()

    def _apply_sort(self) -> None:
        order = Qt.SortOrder.DescendingOrder if self.sidebar.sort_descending() else Qt.SortOrder.AscendingOrder
        self.proxy.resort(self.sidebar.sort_key(), order)
        self._request_visible_thumbs()

    def _on_folder_selected(self, rel) -> None:
        self.proxy.set_filters(folder_rel=rel)
        self.gallery.update_counts()
        self._request_visible_thumbs()
        parts = [self._source.name if self._source else ""] + ([rel] if rel else [])
        self.gallery.set_breadcrumb("  ›  ".join(p for p in parts if p))
        if self.proxy.rowCount() == 0 and self.model.rowCount() > 0:
            self.gallery.show_empty(i18n.tr("empty.folder_title"), i18n.tr("empty.folder_body"))
        else:
            self.gallery.show_list()

    def _on_current_changed(self, current, previous) -> None:
        self.gallery.update_counts()

    # ------------------------------------------------------------------
    # サムネイル
    # ------------------------------------------------------------------
    def _on_visible_range(self, first: int, last: int) -> None:
        if self._epoch == 0:
            return
        for row in range(max(0, first), min(self.proxy.rowCount() - 1, last) + 1):
            proxy_index = self.proxy.index(row, 0)
            entry = proxy_index.data(Qt.ItemDataRole.UserRole + 1)
            if entry is None or entry.thumb_state in (1, 2):
                continue
            source_row = self.proxy.mapToSource(proxy_index).row()
            self._request_thumb(source_row, entry.path, priority=0)

    def _request_visible_thumbs(self) -> None:
        # ビューの可視範囲を取り直す
        self.gallery.view.schedule_range_update()

    def _request_thumb(self, row: int, path: str, priority: int = 5) -> None:
        key = (self._epoch, row)
        if key in self._thumbs_requested:
            return
        self._thumbs_requested.add(key)
        self.model.mark_thumb_loading(row)
        self._thumbs.request(row, path, edge=self._thumb_edge, priority=priority)

    def _request_background_thumbs(self) -> None:
        """画面外のサムネイルを少しずつ先読みする。"""
        if self._epoch == 0:
            return
        count = self.model.rowCount()
        budget = 240
        while self._bg_pos < count and budget > 0:
            row = self._bg_pos
            self._bg_pos += 1
            entry = self.model.entry(row)
            if entry is None or entry.thumb_state in (1, 2):
                continue
            self._request_thumb(row, entry.path, priority=20)
            budget -= 1
        if self._bg_pos >= count:
            self._bg_timer.stop()

    def _on_thumbnail(self, epoch: int, row: int, image) -> None:
        if epoch != self._epoch:
            return
        self.model.set_thumb(row, image)

    # ------------------------------------------------------------------
    # 表示オプション
    # ------------------------------------------------------------------
    def _on_zoom_changed(self, value: int) -> None:
        self._request_visible_thumbs()

    def _on_detailed_toggled(self, checked: bool) -> None:
        self._request_visible_thumbs()

    def toggle_theme(self) -> None:
        target = "light" if isDarkTheme() else "dark"
        theme_utils.apply_theme(target)
        theme_utils.save_theme(target)  # 次回起動時も同じテーマで開く
        QTimer.singleShot(50, self._refresh_theme)

    def _refresh_theme(self) -> None:
        self._apply_theme_colors()
        self.gallery.refresh_theme()
        self.sidebar.refresh_theme()
        for row in self.sidebar.findChildren(QWidget):
            row.update()
        if self._viewer is not None:
            self._viewer.refresh_theme()

    # ------------------------------------------------------------------
    # ビューア
    # ------------------------------------------------------------------
    def open_viewer(self, entries: list) -> None:
        if not entries:
            return
        if self._viewer is not None:
            self._viewer.close()
            self._viewer = None
        self._viewer = PhotoViewerDialog(entries, 0, worker=None, parent=self)
        self._viewer.connect_worker(self._large_worker)
        self._viewer.reload_current()
        self._viewer.closed.connect(self._on_viewer_closed)
        self._viewer.show()
        self._viewer.raise_()
        self._viewer.activateWindow()

    def _on_viewer_closed(self) -> None:
        if self._viewer is not None:
            self._viewer.disconnect_worker()
            self._viewer.deleteLater()
            self._viewer = None

    # ------------------------------------------------------------------
    # その他
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # 言語の切り替え（設定を保存して画面を作り直す）
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # アプリについて（著作権・ライセンスの表示）
    # ------------------------------------------------------------------
    def about_text(self) -> str:
        """「アプリについて」に出す文章（GPLv3 の著作権表示・無保証の告知を含む）。"""
        from . import CONTACT, LICENSE_NAME, SOURCE_URL, __version__, copyright_line

        lines = [
            i18n.tr(
                "about.content",
                version=__version__,
                copyright=copyright_line(),
                license=LICENSE_NAME,
            ),
            "",
            i18n.tr("about.contact", contact=CONTACT),
            i18n.tr("about.source_line", url=SOURCE_URL) if SOURCE_URL else i18n.tr("about.no_source"),
            "",
            i18n.tr("about.third_party"),
        ]
        return "\n".join(lines)

    def show_about(self) -> None:
        """アプリについて（バージョン・著作権・ライセンス・ソースの場所）を表示する。"""
        from . import SOURCE_URL
        from qfluentwidgets import MessageBox
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        box = MessageBox(i18n.tr("about.title"), self.about_text(), self)
        if SOURCE_URL:
            box.yesButton.setText(i18n.tr("about.source_button"))
        else:
            box.yesButton.hide()
        box.cancelButton.setText(i18n.tr("common.close"))
        if box.exec() and SOURCE_URL:
            QDesktopServices.openUrl(QUrl(SOURCE_URL))

    def _toggle_language(self) -> None:
        target = "en" if i18n.is_japanese() else "ja"
        self.switch_language(target)

    def switch_language(self, code: str) -> None:
        """言語を切り替えて、同じフォルダを開いた画面を作り直す。"""
        if code == i18n.current_language() or code not in i18n.available_languages():
            return
        i18n.save_language(code)
        i18n.set_language(code)
        # ウィンドウが一旦 0 枚になってもアプリが終了しないようにする
        app = QApplication.instance()
        if app is not None:
            app.setQuitOnLastWindowClosed(False)
            # 言語に合わせてフォント（日本語: Yu Gothic UI / 英語: Segoe UI 系）を選び直す
            theme_utils.install_fonts()
            app.setFont(theme_utils.ui_font())
        self._pending_restart_path = self._source.path if self._source else ""
        self.close()

    def _spawn_restarted_window(self) -> None:
        app = QApplication.instance()
        path = getattr(self, "_pending_restart_path", "") or None
        try:
            window = SDPhotoViewerWindow(initial_path=path)
        except Exception:  # noqa: BLE001 - 作り直しに失敗しても元の言語設定は残っている
            import traceback

            message = traceback.format_exc()
            print(message, file=sys.stderr)
            if app is not None:
                app.setQuitOnLastWindowClosed(True)
            return
        window.show()
        if app is not None:
            app.setQuitOnLastWindowClosed(True)
        InfoBar.success(
            "",
            i18n.tr("info.lang_switched"),
            duration=2200,
            position=InfoBarPosition.BOTTOM_RIGHT,
            parent=window,
        )
        self.deleteLater()

    def _toast(self, text: str, error: bool = False) -> None:
        if error:
            InfoBar.error("", text, duration=3000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
        else:
            InfoBar.success("", text, duration=2000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

    def dragEnterEvent(self, event) -> None:  # noqa: D102, N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: D102, N802
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and os.path.isdir(path):
                self.open_path(path)
                self._refresh_sources()
                break
            if path and os.path.isfile(path):
                self.open_path(os.path.dirname(path))
                self._refresh_sources()
                break

    def closeEvent(self, event) -> None:  # noqa: D102, N802
        self._save_settings()
        if getattr(self, "_pending_restart_path", None) is not None:
            QTimer.singleShot(0, self._spawn_restarted_window)
            self._pending_restart_path = None
        try:
            self._scanner.requestInterruption()
            # 走査中に閉じても落ちないよう、スレッドの終了を待つ
            self._scanner.wait(3000)
            self._metadata.stop()
            self._thumbs.stop()
            self._large_worker.stop()
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(event)
