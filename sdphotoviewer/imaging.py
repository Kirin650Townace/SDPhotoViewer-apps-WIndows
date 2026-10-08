"""画像・動画の読み込み（サムネイル / 原寸表示）.

Qt で読める形式は高速な QImageReader、HEIC は Pillow + pillow-heif、
RAW は rawpy（任意）、動画のサムネイルは ffmpeg（任意）を使う。
"""

from __future__ import annotations

import os
import re
import subprocess

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QImageReader

from . import i18n
from .compat import PILLOW_HEIF_AVAILABLE, RAWPY_AVAILABLE, ffmpeg_path, has_ffmpeg

# 表示できる写真の拡張子
JPEG_EXTENSIONS = {".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
HEIF_EXTENSIONS = {".heic", ".heif", ".hif", ".avif"}
RAW_EXTENSIONS = {
    ".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".orf", ".rw2",
    ".raf", ".dng", ".pef", ".srw", ".x3f", ".3fr", ".fff", ".iiq", ".mos", ".mrw",
    ".rwl", ".kdc", ".dcr", ".erf", ".mef", ".raw",
}
# 動画（サムネイル表示に対応）
VIDEO_EXTENSIONS = {
    ".mp4", ".m4v", ".mov", ".m2ts", ".mts", ".avi", ".mkv", ".wmv", ".mpg", ".mpeg",
    ".3gp", ".3g2", ".asf", ".flv", ".webm", ".vob", ".mod", ".tod", ".mxf", ".divx", ".ogv",
}
PHOTO_EXTENSIONS = JPEG_EXTENSIONS | HEIF_EXTENSIONS | RAW_EXTENSIONS
MEDIA_EXTENSIONS = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS

# サムネイルの長辺（DPI に応じて呼び出し側で調整する）
THUMB_EDGE = 512


def kind_of(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in RAW_EXTENSIONS:
        return "raw"
    if ext in HEIF_EXTENSIONS:
        return "heic"
    if ext in JPEG_EXTENSIONS:
        return "jpeg"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    return "other"


def is_photo(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in PHOTO_EXTENSIONS


def is_video(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS


def is_media(path: str) -> bool:
    """写真または動画（一覧に出す対象）かどうか。"""
    return os.path.splitext(path)[1].lower() in MEDIA_EXTENSIONS


def kind_label(kind: str) -> str:
    return i18n.tr(f"kind.{kind}") if kind in ("jpeg", "heic", "raw", "video", "other") else kind.upper()


def video_kind_label(path: str) -> str:
    """動画のチップに出す表記（MP4 / MOV など）。"""
    ext = os.path.splitext(path)[1].lstrip(".").upper()
    return ext or i18n.tr("kind.video")


# --------------------------------------------------------------------------
# 読み込み本体
# --------------------------------------------------------------------------


def load_thumbnail(path: str, max_edge: int = THUMB_EDGE) -> QImage | None:
    """サムネイル用の画像を読み込む（縮小済み）。動画は ffmpeg で 1 フレーム取り出す。"""
    kind = kind_of(path)
    if kind == "video":
        return load_video_thumbnail(path, max_edge)
    if kind == "raw" and RAWPY_AVAILABLE:
        img = _load_raw(path, max_edge)
        if img is not None and not img.isNull():
            return img
    if kind == "heic":
        return _load_pillow(path, max_edge)
    img = _load_qt(path, max_edge)
    if img is not None:
        return img
    img = _load_pillow(path, max_edge)
    if img is not None:
        return img
    if kind == "raw":
        return _load_raw(path, max_edge)
    return None


def load_full_image(path: str, max_edge: int | None = None) -> QImage | None:
    """拡大表示用の画像を読み込む。動画は大きめの 1 フレームを取り出す。"""
    kind = kind_of(path)
    if kind == "video":
        return load_video_thumbnail(path, max_edge or 1920)
    if kind == "raw" and RAWPY_AVAILABLE:
        img = _load_raw(path, max_edge, full=True)
        if img is not None and not img.isNull():
            return img
    if kind == "heic":
        return _load_pillow(path, max_edge)
    img = _load_qt(path, max_edge)
    if img is not None:
        return img
    img = _load_pillow(path, max_edge)
    if img is not None:
        return img
    if kind == "raw":
        return _load_raw(path, max_edge, full=True)
    return None


# --------------------------------------------------------------------------
# 動画（ffmpeg）
# --------------------------------------------------------------------------

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_RESOLUTION_RE = re.compile(r"Video:.*?, (\d{2,5})x(\d{2,5})")


def load_video_thumbnail(path: str, max_edge: int = THUMB_EDGE) -> QImage | None:
    """ffmpeg で動画の 1 フレームを取り出す。"""
    exe = ffmpeg_path()
    if not exe:
        return None
    # 冒頭は真っ暗なことが多いので 1 秒地点（短い動画は 0 秒）から取る
    for seek in ("1", "0"):
        image = _grab_frame(exe, path, seek, max_edge)
        if image is not None and not image.isNull():
            if image.width() == 0 or image.height() == 0:
                continue
            # 真っ黒なフレームなら 0 秒地点も試す
            if seek == "1" and _is_mostly_black(image):
                alternative = _grab_frame(exe, path, "0", max_edge)
                if alternative is not None and not alternative.isNull():
                    return alternative
            return image
    return None


def _grab_frame(exe: str, path: str, seek: str, max_edge: int | None) -> QImage | None:
    scale = f"scale='min({max_edge},iw)':-2" if max_edge else "scale=iw:ih"
    cmd = [
        exe, "-v", "error", "-nostdin",
        "-ss", seek,
        "-i", path,
        "-frames:v", "1",
        "-vf", scale,
        "-f", "image2pipe",
        "-vcodec", "png",
        "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    image = QImage.fromData(result.stdout, "PNG")
    if image.isNull():
        return None
    if max_edge and (image.width() > max_edge or image.height() > max_edge):
        image = image.scaled(max_edge, max_edge, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return image


def _is_mostly_black(image: QImage, threshold: int = 18) -> bool:
    """ほぼ真っ黒なフレームかどうか（サムネイルの見栄え確認用）。"""
    try:
        small = image.scaled(16, 16, Qt.IgnoreAspectRatio, Qt.FastTransformation)
        total = 0
        count = 0
        for y in range(small.height()):
            for x in range(small.width()):
                color = small.pixelColor(x, y)
                total += (color.red() + color.green() + color.blue()) / 3
                count += 1
        return count > 0 and (total / count) < threshold
    except Exception:  # noqa: BLE001
        return False


def video_info(path: str) -> dict:
    """ffmpeg から再生時間と解像度を取得する（取れなければ空の辞書）。"""
    exe = ffmpeg_path()
    info: dict = {}
    if not exe:
        return info
    try:
        result = subprocess.run(
            [exe, "-hide_banner", "-i", path],
            capture_output=True, timeout=20, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return info
    text = (result.stderr or b"").decode("utf-8", "ignore")
    match = _DURATION_RE.search(text)
    if match:
        hours, minutes, seconds = match.groups()
        info["duration"] = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    match = _RESOLUTION_RE.search(text)
    if match:
        info["width"], info["height"] = int(match.group(1)), int(match.group(2))
    return info


def fmt_duration(seconds: float | None) -> str:
    """秒数を 1:23 / 1:02:03 の形式にする。"""
    if seconds is None:
        return ""
    seconds = int(round(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def embedded_preview(path: str) -> QImage | None:
    """RAW に埋め込まれたプレビュー画像を取り出す（高速表示用）。"""
    if not RAWPY_AVAILABLE:
        return None
    try:  # pragma: no cover - 環境依存
        import rawpy

        with rawpy.imread(path) as raw:
            thumb = raw.extract_thumb()
            if thumb.format == rawpy.ThumbFormat.JPEG:
                img = QImage.fromData(bytes(thumb.data))
                return img if not img.isNull() else None
            if thumb.format == rawpy.ThumbFormat.BITMAP:
                return _numpy_to_qimage(thumb.data)
    except Exception:  # noqa: BLE001
        return None
    return None


def _load_qt(path: str, max_edge: int | None) -> QImage | None:
    try:
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        size = reader.size()
        if max_edge and size.isValid() and (size.width() > max_edge or size.height() > max_edge):
            scaled = size.scaled(QSize(max_edge, max_edge), Qt.KeepAspectRatio)
            reader.setScaledSize(scaled)
        img = reader.read()
        if img.isNull():
            return None
        if max_edge and (img.width() > max_edge or img.height() > max_edge):
            img = img.scaled(max_edge, max_edge, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return img
    except Exception:  # noqa: BLE001
        return None


def _load_pillow(path: str, max_edge: int | None) -> QImage | None:
    try:
        from PIL import Image, ImageOps

        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            if max_edge:
                im.thumbnail((max_edge, max_edge), Image.BILINEAR)
            return _pil_to_qimage(im)
    except Exception:  # noqa: BLE001
        return None


def _load_raw(path: str, max_edge: int | None, full: bool = False) -> QImage | None:
    if not RAWPY_AVAILABLE:
        return None
    try:  # pragma: no cover - 環境依存
        import rawpy

        with rawpy.imread(path) as raw:
            if not full:
                try:
                    thumb = raw.extract_thumb()
                    if thumb.format == rawpy.ThumbFormat.JPEG:
                        img = QImage.fromData(bytes(thumb.data))
                        if not img.isNull():
                            if max_edge and (img.width() > max_edge or img.height() > max_edge):
                                img = img.scaled(max_edge, max_edge, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                            return img
                    elif thumb.format == rawpy.ThumbFormat.BITMAP:
                        img = _numpy_to_qimage(thumb.data)
                        if img is not None and not img.isNull():
                            if max_edge and (img.width() > max_edge or img.height() > max_edge):
                                img = img.scaled(max_edge, max_edge, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                            return img
                except Exception:  # noqa: BLE001
                    pass
            half = bool(max_edge and max_edge <= 1400)
            rgb = raw.postprocess(half_size=half, use_camera_wb=True, output_bps=8)
            img = _numpy_to_qimage(rgb)
            if img is not None and max_edge and (img.width() > max_edge or img.height() > max_edge):
                img = img.scaled(max_edge, max_edge, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            return img
    except Exception:  # noqa: BLE001
        return None


def _pil_to_qimage(im) -> QImage:
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA" if "A" in im.mode or im.mode == "P" else "RGB")
    if im.mode == "RGB":
        data = im.tobytes("raw", "RGB")
        return QImage(data, im.width, im.height, im.width * 3, QImage.Format_RGB888).copy()
    data = im.tobytes("raw", "RGBA")
    return QImage(data, im.width, im.height, im.width * 4, QImage.Format_RGBA8888).copy()


def _numpy_to_qimage(arr) -> QImage | None:  # pragma: no cover - 環境依存
    try:
        import numpy as np

        arr = np.ascontiguousarray(arr)
        if arr.ndim == 2:
            h, w = arr.shape
            return QImage(arr.data, w, h, w, QImage.Format_Grayscale8).copy()
        h, w, ch = arr.shape
        if ch == 3:
            return QImage(arr.data, w, h, w * 3, QImage.Format_RGB888).copy()
        if ch == 4:
            return QImage(arr.data, w, h, w * 4, QImage.Format_RGBA8888).copy()
    except Exception:  # noqa: BLE001
        return None
    return None


def support_summary() -> str:
    """ステータスバーなどに出す対応状況。"""
    return i18n.tr(
        "format.support",
        heic=i18n.tr("format.yes") if PILLOW_HEIF_AVAILABLE else i18n.tr("format.no_heif"),
        raw=i18n.tr("format.yes") if RAWPY_AVAILABLE else i18n.tr("format.no_rawpy"),
        video=i18n.tr("format.yes") if has_ffmpeg() else i18n.tr("format.no_video"),
    )
