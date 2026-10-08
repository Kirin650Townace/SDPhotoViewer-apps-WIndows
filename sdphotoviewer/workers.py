"""バックグラウンド処理（走査 / Exif 解析 / サムネイル生成）.

UI を固まらせないために、重い処理はすべて別スレッドで行う。
「エポック」という世代番号で、古い処理結果を捨てる仕組みにしている。
"""

from __future__ import annotations

import heapq
import itertools
import os
import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, QThread, Signal

from .exifdata import ExifInfo, parse_exif
from .imaging import THUMB_EDGE, is_media, is_video, kind_of, load_thumbnail, video_info


# --------------------------------------------------------------------------
# 走査（フォルダ内の写真を列挙）
# --------------------------------------------------------------------------


@dataclass
class ScannedFile:
    path: str
    name: str
    size: int
    mtime: float
    folder: str
    kind: str


class ScanWorker(QThread):
    """フォルダを走査して写真ファイルを列挙する。"""

    batch = Signal(int, list)          # epoch, [ScannedFile]
    progress = Signal(int, int)        # 見つかった数, 見たフォルダ数
    finished_scan = Signal(int, int)   # epoch, 合計
    failed = Signal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._epoch = 0
        self._root = ""
        self._recursive = True

    def start_scan(self, root: str, epoch: int, recursive: bool = True) -> None:
        self._root = root
        self._epoch = epoch
        self._recursive = recursive
        self.requestInterruption()
        self.start()

    def run(self) -> None:  # noqa: D102
        epoch = self._epoch
        root = self._root
        found = 0
        dirs = 0
        buf: list[ScannedFile] = []
        last_emit = time.monotonic()
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                if self.isInterruptionRequested():
                    return
                dirnames[:] = [
                    d
                    for d in dirnames
                    if not d.startswith(".")
                    and d.lower() not in ("$recycle.bin", "system volume information", "lost.dir", "found.000")
                ]
                dirs += 1
                for name in filenames:
                    if not is_media(name):
                        continue
                    full = os.path.join(dirpath, name)
                    try:
                        st = os.stat(full)
                    except OSError:
                        continue
                    buf.append(
                        ScannedFile(
                            path=full,
                            name=name,
                            size=st.st_size,
                            mtime=st.st_mtime,
                            folder=dirpath,
                            kind=kind_of(name),
                        )
                    )
                    found += 1
                if len(buf) >= 400 or (buf and time.monotonic() - last_emit > 0.15):
                    self.batch.emit(epoch, buf)
                    buf = []
                    last_emit = time.monotonic()
                    self.progress.emit(found, dirs)
            if buf:
                self.batch.emit(epoch, buf)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(epoch, str(exc))
            return
        self.progress.emit(found, dirs)
        self.finished_scan.emit(epoch, found)


# --------------------------------------------------------------------------
# Exif 解析
# --------------------------------------------------------------------------


class MetadataWorker(QThread):
    """行番号とパスを受け取り、順に Exif を解析して返す。"""

    meta = Signal(int, int, object)     # epoch, row, ExifInfo
    idle = Signal(int)                  # epoch, すべて処理し終えた

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._queue: list[tuple[int, int, str, int]] = []
        self._epoch = 0
        self._running = True

    def set_epoch(self, epoch: int) -> None:
        with self._cond:
            self._epoch = epoch
            self._queue.clear()
            self._cond.notify_all()

    def submit(self, rows: list[tuple[int, str, int]]) -> None:
        """rows: [(row, path, size), ...]"""
        with self._cond:
            epoch = self._epoch
            self._queue.extend((epoch, r, p, s) for r, p, s in rows)
            self._cond.notify_all()

    def stop(self) -> None:
        with self._cond:
            self._running = False
            self._cond.notify_all()
        self.wait(2000)

    def run(self) -> None:  # noqa: D102
        while True:
            with self._cond:
                while self._running and not self._queue:
                    self._cond.wait(0.2)
                if not self._running:
                    return
                epoch, row, path, size = self._queue.pop(0)
            item_epoch = epoch
            if is_video(path):
                # 動画は Exif ではなく再生時間・解像度を ffmpeg から取得する
                info = ExifInfo(file_size=size)
                info.format_name = os.path.splitext(path)[1].lstrip(".").upper()
                meta = video_info(path)
                info.duration = meta.get("duration")
                info.width = meta.get("width")
                info.height = meta.get("height")
                info.parsed = True
            else:
                info = parse_exif(path, size)
            with self._cond:
                stale = item_epoch != self._epoch
                empty = not self._queue
            if not stale:
                self.meta.emit(item_epoch, row, info)
                if empty:
                    self.idle.emit(item_epoch)


# --------------------------------------------------------------------------
# サムネイル生成
# --------------------------------------------------------------------------


@dataclass(order=True)
class _ThumbJob:
    sort_key: tuple
    row: int = 0
    path: str = ""
    epoch: int = 0
    edge: int = THUMB_EDGE


class ThumbnailService(QObject):
    """優先度付きキュー + 複数スレッドでサムネイルを作る。"""

    thumbnail = Signal(int, int, object)  # epoch, row, QImage

    def __init__(self, threads: int = 3, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._heap: list[_ThumbJob] = []
        self._counter = itertools.count()
        self._epoch = 0
        self._pending: set[tuple[int, int]] = set()
        self._running = True
        self._threads = [_ThumbThread(self) for _ in range(max(1, threads))]
        for t in self._threads:
            t.start()

    # ---- 外から呼ぶ API ----
    def set_epoch(self, epoch: int) -> None:
        with self._cond:
            self._epoch = epoch
            self._heap.clear()
            self._pending.clear()
            self._cond.notify_all()

    def request(self, row: int, path: str, edge: int = THUMB_EDGE, priority: int = 10) -> None:
        """priority が小さいほど先に処理される。"""
        key = (self._epoch, row)
        with self._cond:
            if key in self._pending:
                return
            self._pending.add(key)
            heapq.heappush(
                self._heap,
                _ThumbJob(sort_key=(priority, row), row=row, path=path, epoch=self._epoch, edge=edge),
            )
            self._cond.notify()

    def cancel_pending(self) -> None:
        with self._cond:
            self._heap.clear()
            self._pending.clear()

    def stop(self) -> None:
        with self._cond:
            self._running = False
            self._cond.notify_all()
        for t in self._threads:
            t.wait(2000)

    # ---- スレッドから使う内部 API ----
    def _next_job(self) -> _ThumbJob | None:
        with self._cond:
            while self._running and not self._heap:
                self._cond.wait(0.2)
            if not self._running:
                return None
            job = heapq.heappop(self._heap)
            return job

    def _job_done(self, job: _ThumbJob) -> bool:
        """まだ有効なジョブかどうか。"""
        with self._cond:
            self._pending.discard((job.epoch, job.row))
            return job.epoch == self._epoch


class _ThumbThread(QThread):
    def __init__(self, service: ThumbnailService):
        super().__init__()
        self._service = service

    def run(self) -> None:  # noqa: D102
        while True:
            job = self._service._next_job()
            if job is None:
                return
            alive = self._service._job_done(job)
            if not alive:
                continue
            img = load_thumbnail(job.path, job.edge)
            if job.epoch == self._service._epoch:
                self._service.thumbnail.emit(job.epoch, job.row, img)


# --------------------------------------------------------------------------
# 拡大表示用の画像読み込み
# --------------------------------------------------------------------------


class LargeImageWorker(QThread):
    """拡大表示用の画像を1枚ずつ読み込む。"""

    loaded = Signal(int, str, object)  # epoch, path, QImage
    failed = Signal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cond = threading.Condition()
        self._pending: tuple[int, str] | None = None
        self._running = True

    def request(self, epoch: int, path: str) -> None:
        with self._cond:
            self._pending = (epoch, path)
            self._cond.notify_all()

    def stop(self) -> None:
        with self._cond:
            self._running = False
            self._cond.notify_all()
        self.wait(2000)

    def run(self) -> None:  # noqa: D102
        from .imaging import load_full_image

        while True:
            with self._cond:
                while self._running and self._pending is None:
                    self._cond.wait(0.2)
                if not self._running:
                    return
                epoch, path = self._pending
                self._pending = None
            try:
                img = load_full_image(path)
            except Exception as exc:  # noqa: BLE001
                self.failed.emit(epoch, str(exc))
                continue
            with self._cond:
                cancelled = not self._running or (self._pending is not None)
            if cancelled:
                continue
            self.loaded.emit(epoch, path, img)


# --------------------------------------------------------------------------
# 情報キャッシュの読み書き（ディスクに保存して2回目以降を高速化）
# --------------------------------------------------------------------------


class MetaCache:
    """簡易キャッシュ。パス + サイズ + 更新時刻をキーにする。"""

    def __init__(self, max_items: int = 20000):
        self._data: dict[tuple, ExifInfo] = {}
        self._order: list[tuple] = []
        self._max = max_items

    def get(self, path: str, size: int, mtime: float) -> ExifInfo | None:
        return self._data.get((os.path.normcase(path), size, int(mtime)))

    def put(self, path: str, size: int, mtime: float, info: ExifInfo) -> None:
        key = (os.path.normcase(path), size, int(mtime))
        if key not in self._data:
            self._order.append(key)
            if len(self._order) > self._max:
                old = self._order.pop(0)
                self._data.pop(old, None)
        self._data[key] = info
