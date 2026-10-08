"""任意ライブラリ（HEIC / RAW / 動画対応）の検出と登録."""

from __future__ import annotations

import os
import shutil
import sys
import warnings

# ---- HEIC/HEIF (pillow-heif) ----
PILLOW_HEIF_AVAILABLE = False
try:  # pragma: no cover - 環境依存
    import pillow_heif

    pillow_heif.register_heif_opener()
    PILLOW_HEIF_AVAILABLE = True
except Exception:  # noqa: BLE001
    pass

# ---- RAW (rawpy / libraw) ----
RAWPY_AVAILABLE = False
try:  # pragma: no cover - 環境依存
    import rawpy  # noqa: F401

    RAWPY_AVAILABLE = True
except Exception:  # noqa: BLE001
    pass

warnings.filterwarnings("ignore", module="PIL")


# ---- 動画のサムネイル (ffmpeg) ----
_FFMPEG_PATH: str | None = None
_FFMPEG_CHECKED = False


def ffmpeg_path() -> str | None:
    """ffmpeg の実行ファイルを探す（無ければ None）。

    探す順番:
      1. PATH 上の ffmpeg
      2. imageio-ffmpeg（pip install imageio-ffmpeg で同梱される）
      3. Windows でよくあるインストール先
    """
    global _FFMPEG_PATH, _FFMPEG_CHECKED
    if _FFMPEG_CHECKED:
        return _FFMPEG_PATH
    _FFMPEG_CHECKED = True

    found = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if found:
        _FFMPEG_PATH = found
        return _FFMPEG_PATH

    try:  # pragma: no cover - 環境依存
        import imageio_ffmpeg

        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and os.path.exists(path):
            _FFMPEG_PATH = path
            return _FFMPEG_PATH
    except Exception:  # noqa: BLE001
        pass

    if sys.platform.startswith("win"):  # pragma: no cover - 環境依存
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\ffmpeg\bin\ffmpeg.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\ffmpeg\bin\ffmpeg.exe"),
            os.path.expandvars(r"%LocalAppData%\Microsoft\WinGet\Links\ffmpeg.exe"),
            r"C:\ffmpeg\bin\ffmpeg.exe",
        ]
        for path in candidates:
            if path and os.path.exists(path):
                _FFMPEG_PATH = path
                return _FFMPEG_PATH
    return None


def has_ffmpeg() -> bool:
    return ffmpeg_path() is not None


def video_status_text() -> str:
    return "対応" if has_ffmpeg() else "未導入（pip install imageio-ffmpeg）"


def heif_status_text() -> str:
    return "対応" if PILLOW_HEIF_AVAILABLE else "未導入（pip install pillow-heif）"


def raw_status_text() -> str:
    return "対応" if RAWPY_AVAILABLE else "未導入（pip install rawpy）"


# ---- 同梱リソース（アイコンなど） ----


def resource_path(relative: str) -> str:
    """同梱したリソース（assets/…）の実パスを返す。

    - exe（PyInstaller）で動いているときは展開先（sys._MEIPASS）を見る
    - Python から実行しているときはリポジトリ直下を見る
    """
    candidates = []
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidates.append(os.path.join(base, relative))
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates.append(os.path.join(root, relative))
    if getattr(sys, "frozen", False):
        candidates.append(os.path.join(os.path.dirname(sys.executable), relative))
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0]


def app_icon():
    """アプリのアイコンを返す（assets/app.ico が無ければ空の QIcon）。"""
    from PySide6.QtGui import QIcon

    path = resource_path(os.path.join("assets", "app.ico"))
    return QIcon(path) if os.path.exists(path) else QIcon()
