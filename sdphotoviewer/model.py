"""写真一覧のデータモデル / 並べ替え・絞り込み."""

from __future__ import annotations

import datetime as _dt
import os
from collections import Counter, OrderedDict
from dataclasses import dataclass, field

from PySide6.QtCore import QAbstractListModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QImage

from . import i18n
from .exifdata import ExifInfo
from .imaging import kind_label
from .workers import ScannedFile

EntryRole = Qt.ItemDataRole.UserRole + 1

# サムネイルを保持する最大数（メモリ対策。超えたら古いものから捨てる）
THUMB_CACHE_LIMIT = 420


@dataclass
class PhotoEntry:
    """1枚の写真。"""

    path: str
    name: str
    folder: str
    size: int
    mtime: float
    kind: str
    exif: ExifInfo | None = None
    thumb: QImage | None = None
    thumb_state: int = 0  # 0=未読込 / 1=読込中 / 2=完了 / 3=失敗

    @property
    def ext(self) -> str:
        return os.path.splitext(self.name)[1].lower()

    @property
    def is_video(self) -> bool:
        return self.kind == "video"

    @property
    def kind_text(self) -> str:
        return kind_label(self.kind)

    def sort_datetime(self) -> float:
        if self.exif and self.exif.datetime_original:
            return self.exif.datetime_original.timestamp()
        return self.mtime

    def has_gps(self) -> bool:
        return bool(self.exif and self.exif.has_gps)


class PhotoModel(QAbstractListModel):
    """写真のリストを保持するモデル。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: list[PhotoEntry] = []
        self._thumb_order: OrderedDict[int, QImage] = OrderedDict()
        self.root: str = ""

    # ---- 基本 ----
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: D102, B008
        return 0 if parent.isValid() else len(self._entries)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: D102
        if not index.isValid():
            return None
        if role == EntryRole:
            return self._entries[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return self._entries[index.row()].name
        return None

    def roleNames(self):  # noqa: D102
        return {EntryRole: b"entry"}

    # ---- 内容の更新 ----
    def reset_entries(self, root: str, files: list[ScannedFile]) -> None:
        self.beginResetModel()
        self.root = root
        self._entries = [
            PhotoEntry(path=f.path, name=f.name, folder=f.folder, size=f.size, mtime=f.mtime, kind=f.kind)
            for f in files
        ]
        self._thumb_order.clear()
        self.endResetModel()

    def append_files(self, files: list[ScannedFile]) -> int:
        if not files:
            return 0
        start = len(self._entries)
        self.beginInsertRows(QModelIndex(), start, start + len(files) - 1)
        self._entries.extend(
            PhotoEntry(path=f.path, name=f.name, folder=f.folder, size=f.size, mtime=f.mtime, kind=f.kind) for f in files
        )
        self.endInsertRows()
        return len(files)

    def clear(self) -> None:
        self.reset_entries("", [])

    def entry(self, row: int) -> PhotoEntry | None:
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def entries(self) -> list[PhotoEntry]:
        return self._entries

    def set_exif(self, row: int, info: ExifInfo) -> None:
        if 0 <= row < len(self._entries):
            self._entries[row].exif = info
            idx = self.index(row, 0)
            self.dataChanged.emit(idx, idx)

    def set_thumb(self, row: int, image: QImage | None) -> None:
        if not (0 <= row < len(self._entries)):
            return
        entry = self._entries[row]
        entry.thumb = image
        entry.thumb_state = 2 if image is not None and not image.isNull() else 3
        self._remember_thumb(row, image)
        idx = self.index(row, 0)
        self.dataChanged.emit(idx, idx)

    def mark_thumb_loading(self, row: int) -> None:
        if 0 <= row < len(self._entries) and self._entries[row].thumb_state == 0:
            self._entries[row].thumb_state = 1

    def _remember_thumb(self, row: int, image: QImage | None) -> None:
        if image is None:
            return
        self._thumb_order.pop(row, None)
        self._thumb_order[row] = image
        while len(self._thumb_order) > THUMB_CACHE_LIMIT:
            old_row, _ = self._thumb_order.popitem(last=False)
            if old_row == row:
                continue
            entry = self._entries[old_row] if 0 <= old_row < len(self._entries) else None
            if entry is not None and entry.thumb is not None:
                entry.thumb = None
                if entry.thumb_state == 2:
                    entry.thumb_state = 0
                idx = self.index(old_row, 0)
                self.dataChanged.emit(idx, idx)

    # ---- 集計 ----
    def counts(self) -> dict:
        kinds = Counter(e.kind for e in self._entries)
        return {
            "total": len(self._entries),
            "bytes": sum(e.size for e in self._entries),
            "jpeg": kinds.get("jpeg", 0),
            "heic": kinds.get("heic", 0),
            "raw": kinds.get("raw", 0),
            "video": kinds.get("video", 0),
            "other": kinds.get("other", 0),
        }


# --------------------------------------------------------------------------
# 絞り込み + 並べ替え
# --------------------------------------------------------------------------

SORT_KEY_ORDER = ("datetime", "name", "size", "mtime", "kind")


def sort_options() -> list[tuple[str, str]]:
    """並べ替えの選択肢（表示言語に追従）。"""
    return [(key, i18n.tr(f"sort.{key}")) for key in SORT_KEY_ORDER]


# 後方互換（起動時の並べ替えキー参照用）
SORT_KEYS = [(key, key) for key in SORT_KEY_ORDER]


class PhotoFilterProxy(QSortFilterProxyModel):
    """形式 / カメラ / 期間 / GPS / 文字列 / フォルダで絞り込み、並べ替える。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDynamicSortFilter(True)
        self.setSourceModel(None)  # 後で設定
        self._kinds: set[str] = {"jpeg", "heic", "raw", "video", "other"}
        self._camera: str | None = None
        self._date_from: _dt.datetime | None = None
        self._date_to: _dt.datetime | None = None
        self._gps_only = False
        self._text = ""
        self._folder_rel: str | None = None
        self._root = ""
        self._sort_key = "datetime"

    # ---- 設定 ----
    def set_filters(
        self,
        *,
        kinds: set[str] | None = None,
        camera: str | None = None,
        date_from: _dt.datetime | None = None,
        date_to: _dt.datetime | None = None,
        gps_only: bool | None = None,
        text: str | None = None,
        folder_rel: str | None = None,
    ) -> None:
        changed = False
        if kinds is not None and kinds != self._kinds:
            self._kinds = set(kinds)
            changed = True
        if camera != self._camera:
            self._camera = camera
            changed = True
        if date_from != self._date_from:
            self._date_from = date_from
            changed = True
        if date_to != self._date_to:
            self._date_to = date_to
            changed = True
        if gps_only is not None and gps_only != self._gps_only:
            self._gps_only = gps_only
            changed = True
        if text is not None and text != self._text:
            self._text = text.strip().lower()
            changed = True
        if folder_rel != self._folder_rel:
            self._folder_rel = folder_rel
            changed = True
        if changed:
            self.invalidateFilter()

    def set_root(self, root: str) -> None:
        self._root = root

    def set_sort_key(self, key: str) -> None:
        self._sort_key = key

    def resort(self, key: str, order: Qt.SortOrder) -> None:
        """比較キーを変えて並べ替え直す。

        Qt の sort() は「同じ列・同じ順序」だと何もせずに戻ってしまうため、
        invalidate() でソート状態をリセットしてから並べ替える。
        """
        self._sort_key = key
        self.invalidate()
        self.sort(0, order)

    def filters(self) -> dict:
        return {
            "kinds": set(self._kinds),
            "camera": self._camera,
            "date_from": self._date_from,
            "date_to": self._date_to,
            "gps_only": self._gps_only,
            "text": self._text,
            "folder_rel": self._folder_rel,
        }

    # ---- 判定 ----
    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: D102
        model = self.sourceModel()
        if model is None:
            return False
        entry: PhotoEntry | None = model.entry(source_row)
        if entry is None:
            return False

        if entry.kind not in self._kinds:
            return False

        if self._folder_rel:
            rel = os.path.relpath(entry.folder, self._root) if self._root else ""
            if not (rel == self._folder_rel or rel.startswith(self._folder_rel + os.sep)):
                return False

        if self._camera:
            name = entry.exif.camera_name if entry.exif else ""
            if name != self._camera:
                return False

        if self._gps_only and not entry.has_gps():
            return False

        if self._date_from or self._date_to:
            dt = _entry_datetime(entry)
            if dt is None:
                return False
            if self._date_from and dt < self._date_from:
                return False
            if self._date_to and dt > self._date_to:
                return False

        if self._text and self._text not in entry.name.lower():
            return False

        return True

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: D102
        model = self.sourceModel()
        a: PhotoEntry = model.entry(left.row())
        b: PhotoEntry = model.entry(right.row())
        key = self._sort_key
        if key == "name":
            return _natural_key(a.name) < _natural_key(b.name)
        if key == "size":
            return a.size < b.size
        if key == "kind":
            return (a.kind, _natural_key(a.name)) < (b.kind, _natural_key(b.name))
        if key == "mtime":
            return a.mtime < b.mtime
        return (a.sort_datetime(), _natural_key(a.name)) < (b.sort_datetime(), _natural_key(b.name))


def _entry_datetime(entry: PhotoEntry) -> _dt.datetime | None:
    if entry.exif and entry.exif.datetime_original:
        return entry.exif.datetime_original
    try:
        return _dt.datetime.fromtimestamp(entry.mtime)
    except (OverflowError, OSError, ValueError):
        return None


def _natural_key(text: str):
    """IMG_2 < IMG_10 になる自然順キー。"""
    import re

    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


# --------------------------------------------------------------------------
# カメラ情報カード用の集計
# --------------------------------------------------------------------------


@dataclass
class SourceStats:
    total: int = 0
    total_bytes: int = 0
    kinds: Counter = field(default_factory=Counter)
    cameras: Counter = field(default_factory=Counter)
    lenses: Counter = field(default_factory=Counter)
    makes: Counter = field(default_factory=Counter)
    sizes: Counter = field(default_factory=Counter)
    gps_count: int = 0
    parsed: int = 0
    date_min: _dt.datetime | None = None
    date_max: _dt.datetime | None = None

    @property
    def camera(self) -> str:
        return self.cameras.most_common(1)[0][0] if self.cameras else ""

    @property
    def make(self) -> str:
        return self.makes.most_common(1)[0][0] if self.makes else ""

    @property
    def lens(self) -> str:
        return self.lenses.most_common(1)[0][0] if self.lenses else ""

    @property
    def main_size(self) -> str:
        if not self.sizes:
            return ""
        (w, h), _count = self.sizes.most_common(1)[0]
        return f"{w}×{h}"

    @property
    def period_text(self) -> str:
        if not self.date_min or not self.date_max:
            return ""
        if self.date_min.date() == self.date_max.date():
            return self.date_min.strftime("%Y/%m/%d")
        return i18n.tr(
            "stats.period_range",
            a=self.date_min.strftime("%Y/%m/%d"),
            b=self.date_max.strftime("%Y/%m/%d"),
        )


def compute_stats(entries: list[PhotoEntry]) -> SourceStats:
    stats = SourceStats()
    for entry in entries:
        stats.total += 1
        stats.total_bytes += entry.size
        stats.kinds[entry.kind] += 1
        info = entry.exif
        if not info:
            continue
        stats.parsed += 1
        if info.model or info.make:
            stats.cameras[info.camera_name] += 1
        if info.make:
            stats.makes[info.make] += 1
        if info.lens:
            stats.lenses[info.lens] += 1
        if info.width and info.height:
            stats.sizes[(info.width, info.height)] += 1
        if info.has_gps:
            stats.gps_count += 1
        dt = info.datetime_original
        if dt:
            stats.date_min = dt if stats.date_min is None else min(stats.date_min, dt)
            stats.date_max = dt if stats.date_max is None else max(stats.date_max, dt)
    return stats
