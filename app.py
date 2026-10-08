"""SD フォトビューア 起動スクリプト.

Copyright (C) 2026 よづき

このプログラムはフリーソフトウェアです。GNU General Public License v3.0（GPLv3）の
条件のもとで、自由に再配布・改変できます。ただし無保証です（詳しくは LICENSE を参照）。


使い方:
    python app.py                  # 起動（前回のフォルダ / SD カードを自動で開く）
    python app.py D:\\DCIM          # 指定フォルダを開く
    python app.py --theme dark     # ダークテーマで起動

exe にして起動しないときは、`ログを保存.txt`（exe と同じフォルダの
`SDPhotoViewer.log`）にエラーの内容が残ります。
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback


def _log_dir() -> str:
    """ログを置くフォルダ。

    exe の場合は exe と同じフォルダ（`ログを保存.txt` で案内している場所）に、
    Python から起動した場合はリポジトリ直下に置く。
    """
    if getattr(sys, "frozen", False):  # PyInstaller で作った exe
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _write_log(text: str) -> str | None:
    """クラッシュ内容をログに残す（書き込めなければ何もしない）。"""
    for directory in (_log_dir(), os.path.expanduser("~")):
        if not directory:
            continue
        try:
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, "SDPhotoViewer.log")
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(text)
            return path
        except OSError:
            continue
    return None


def _notify_user(path: str | None) -> None:
    """エラーを画面でも知らせる（黒い画面の無い exe 用のダイアログ）。"""
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return
    message = "SD フォトビューアでエラーが発生しました。"
    if path:
        message += f"\n\n詳しい内容を次のファイルに記録しました:\n{path}"
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "SD フォトビューア", 0x10)
    except Exception:  # noqa: BLE001 - 表示できなくても記録は残っている
        pass


def _safe_print(text: str) -> None:
    """stderr が無い環境（--windowed の exe）でも落ちないように出力する。"""
    stream = getattr(sys, "stderr", None) or getattr(sys, "__stderr__", None)
    if stream is None:
        return
    try:
        print(text, file=stream)
    except Exception:  # noqa: BLE001
        pass


def _trim_log(path: str, keep: int = 64 * 1024) -> None:
    """ログが大きくなりすぎないように、古い部分を捨てる。"""
    try:
        with open(path, "rb") as handle:
            data = handle.read()
        if len(data) > keep:
            with open(path, "wb") as handle:
                handle.write(data[-keep:])
    except OSError:
        pass


def _log_startup(note: str = "") -> None:
    """起動した記録を残す（どのファイルから起動したかが分かるように）。"""
    import datetime

    line = (
        f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} 起動: "
        f"{sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__)}"
        f" / 実行形式={'exe' if getattr(sys, 'frozen', False) else 'python'}"
        f" / 引数={sys.argv[1:]}"
    )
    if note:
        line += f" / {note}"
    directory = _log_dir()
    path = os.path.join(directory, "SDPhotoViewer.log")
    _trim_log(path)
    try:
        os.makedirs(directory, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def _hide_own_console() -> bool:
    """自分専用のコンソール（黒い画面）を隠す。

    調査用にコンソール付きで作った exe をダブルクリックしたときに、
    黒い画面が残らないようにするための処理。

    ターミナルから起動した場合は **その画面はユーザーの操作画面** なので触らない
    （コンソールにぶら下がっているプロセスが自分だけのときだけ隠す）。
    隠したくないときは環境変数 SDPV_KEEP_CONSOLE=1 を付けて起動する。
    """
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return False
    if os.environ.get("SDPV_KEEP_CONSOLE"):
        return False
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        kernel32.GetConsoleProcessList.argtypes = [ctypes.POINTER(ctypes.c_ulong), ctypes.c_ulong]
        kernel32.GetConsoleProcessList.restype = ctypes.c_ulong
        # 64bit でもハンドルが壊れないように型を明示する
        kernel32.GetConsoleWindow.restype = ctypes.c_void_p
        user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.ShowWindow.restype = ctypes.c_bool

        hwnd = kernel32.GetConsoleWindow()
        if not hwnd:
            return False  # コンソールが無い（通常の exe）
        buffer = (ctypes.c_ulong * 32)()
        count = kernel32.GetConsoleProcessList(buffer, len(buffer))
        if count != 1:
            return False  # シェルなど他にも使っている画面 → 共有なので触らない
        user32.ShowWindow(hwnd, 0)  # SW_HIDE
        return True
    except Exception:  # noqa: BLE001 - 失敗しても起動は続ける
        return False


def _excepthook(exc_type, exc_value, exc_tb) -> None:
    """想定外のエラーで落ちたときの記録（Windows の exe では画面に何も出ないため）。"""
    import datetime
    import locale
    import platform

    body = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    header = (
        "\n" + "=" * 70 + "\n"
        f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n"
        f"アプリ: SD フォトビューア\n"
        f"Python: {sys.version.split()[0]}\n"
        f"OS: {platform.platform()}\n"
        f"実行形式: {'exe（PyInstaller）' if getattr(sys, 'frozen', False) else 'Python スクリプト'}\n"
        f"ファイルシステムの文字コード: {locale.getpreferredencoding(False)}\n"
        f"作業フォルダ: {os.getcwd()}\n"
        f"引数: {sys.argv[1:]}\n"
    )
    path = _write_log(header + "-" * 70 + "\n" + body)
    if path:
        _safe_print(f"エラーが発生しました。内容を次のファイルに記録しました: {path}")
    _safe_print(body)
    _notify_user(path)

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from qfluentwidgets import setThemeColor

from sdphotoviewer import compat, i18n, theme as theme_utils
from sdphotoviewer.mainwindow import SDPhotoViewerWindow


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SD カードの写真をタイル表示するビューア")
    parser.add_argument("path", nargs="?", help="起動時に開くフォルダ（省略時は自動検出）")
    parser.add_argument(
        "--theme",
        choices=["auto", "light", "dark"],
        default="auto",
        help="テーマ（auto = 前回の設定、未設定なら OS の設定に従う）",
    )
    parser.add_argument("--tile-size", type=int, default=0, help="タイルの幅（160〜400px）")
    parser.add_argument("--detailed", action="store_true", help="詳細 Exif 表示で起動する")
    parser.add_argument("--lang", choices=["ja", "en"], default="", help="表示言語（日本語 / English）")
    parser.add_argument("--font", action="append", default=[], help="追加で読み込むフォントファイル")
    return parser.parse_args(argv)


def _load_fonts(extra: list[str]) -> None:
    """日本語が正しく表示されるようフォントを補う。"""
    candidates = list(extra)
    font_dir = os.environ.get("SDPV_FONT_DIR")
    if font_dir and os.path.isdir(font_dir):
        for name in sorted(os.listdir(font_dir)):
            if name.lower().endswith((".ttc", ".otf", ".ttf")):
                candidates.append(os.path.join(font_dir, name))
    for path in candidates:
        if os.path.exists(path):
            QFontDatabase.addApplicationFont(path)


def main(argv: list[str] | None = None) -> int:
    # exe で起動しないときの原因を残す（既定の excepthook は画面に出ない）
    sys.excepthook = _excepthook

    # 調査用のコンソール付きビルドでも、ダブルクリック起動なら黒い画面を出さない
    hidden = _hide_own_console()
    _log_startup("黒い画面を自動で隠しました" if hidden else "")

    args = _parse_args(argv)

    # 表示言語（コマンドライン > 保存された設定 > OS の言語）
    i18n.set_language(args.lang or i18n.load_saved_language())

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    app.setApplicationName(i18n.tr("app.title"))
    app.setOrganizationName("SDPhotoViewer")
    _load_fonts(args.font)
    # 日本語環境で中国語フォント（Microsoft YaHei）が使われないようにする
    theme_utils.install_fonts()
    app.setFont(theme_utils.ui_font())

    # ウィンドウ / タスクバーのアイコン（assets/app.ico があれば使う）
    icon = compat.app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    setThemeColor("#0067C0")
    # 前回終了時のテーマを復元する（--theme light / dark で上書きできる）
    resolved_theme = theme_utils.apply_theme(args.theme)
    if args.theme == "auto":
        app.setProperty("sdv_theme", resolved_theme)

    window = SDPhotoViewerWindow(initial_path=args.path)
    if args.tile_size:
        window.gallery.set_zoom(args.tile_size)
    if args.detailed:
        window.gallery.set_detailed(True)
    window.show()

    if args.path:
        QTimer.singleShot(0, lambda: window.open_path(os.path.abspath(args.path)))

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
