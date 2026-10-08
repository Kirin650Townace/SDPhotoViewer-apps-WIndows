"""スクリーンショットを保存する（開発用 / 動作確認用）.

実際にアプリを起動して、サンプルフォルダを読み込ませた状態を画像に保存する。

使い方:
    QT_QPA_PLATFORM=offscreen python tools/screenshot.py
    python tools/screenshot.py --path D:/DCIM --out docs
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QSettings, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from qfluentwidgets import Theme, setTheme, setThemeColor  # noqa: E402

from sdphotoviewer import i18n, theme as theme_utils  # noqa: E402
from sdphotoviewer.mainwindow import SDPhotoViewerWindow  # noqa: E402


def _load_fonts() -> None:
    font_dir = os.environ.get("SDPV_FONT_DIR")
    if font_dir and os.path.isdir(font_dir):
        for name in sorted(os.listdir(font_dir)):
            if name.lower().endswith((".ttc", ".otf", ".ttf")):
                QFontDatabase.addApplicationFont(os.path.join(font_dir, name))


def main() -> int:
    parser = argparse.ArgumentParser()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser.add_argument("--path", default=os.path.join(root, "sample_sd"))
    parser.add_argument("--out", default=os.path.join(root, "docs"))
    parser.add_argument("--size", default="1560x1000")
    parser.add_argument("--wait", type=int, default=6000)
    parser.add_argument("--lang", choices=["ja", "en"], default="ja", help="撮影する表示言語")
    parser.add_argument("--keep-settings", action="store_true", help="保存された設定をそのまま使う（既定はリセット）")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    if not args.keep_settings:
        # 保存された絞り込みが残っていると撮影結果が変わってしまうため、いったん消す
        settings = QSettings("SDPhotoViewer", "SDPhotoViewer")
        for key in (
            "filters/kinds",
            "filters/camera",
            "filters/period",
            "filters/date_from",
            "filters/date_to",
            "filters/gps",
            "filters/folder",
        ):
            settings.remove(key)
    width, height = (int(v) for v in args.size.lower().split("x"))
    i18n.set_language(args.lang)

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    _load_fonts()
    theme_utils.install_fonts()
    app.setFont(theme_utils.ui_font())
    setThemeColor("#0067C0")

    window = SDPhotoViewerWindow(initial_path=args.path)
    window.resize(width, height)
    window.show()

    def shot(name: str) -> None:
        window.grab().save(os.path.join(args.out, name))
        print("saved:", os.path.join(args.out, name))

    def save_light() -> None:
        shot("screenshot_light.png")

    def save_detailed() -> None:
        window.gallery.set_detailed(True)
        shot("screenshot_detailed.png")
        window.gallery.set_detailed(False)

    def to_dark() -> None:
        setTheme(Theme.DARK, save=False)
        window._refresh_theme()

    def save_dark() -> None:
        shot("screenshot_dark.png")

    def back_to_light() -> None:
        setTheme(Theme.LIGHT, save=False)
        window._refresh_theme()

    def save_videos() -> None:
        """動画だけに絞り込んだギャラリー。"""
        for key, box in window.sidebar._kind_checks.items():
            box.setChecked(key == "video")
        window._apply_filters()
        shot("screenshot_videos.png")

    def back_to_photos() -> None:
        window.sidebar.reset_filters()
        window._apply_filters()

    def open_viewer_shot() -> None:
        proxy = window.proxy
        entries = [proxy.index(r, 0).data(Qt.ItemDataRole.UserRole + 1) for r in range(min(8, proxy.rowCount()))]
        entries = [e for e in entries if e is not None]
        if entries:
            window.gallery.view.setCurrentIndex(proxy.index(0, 0))
            window.open_viewer(entries)

    def save_viewer() -> None:
        if window._viewer is not None:
            window._viewer.resize(1360, 860)
            window._viewer.grab().save(os.path.join(args.out, "screenshot_viewer.png"))
            print("saved:", os.path.join(args.out, "screenshot_viewer.png"))

    def to_dark_viewer() -> None:
        """ダークテーマに切り替えて、ビューアを開き直す。"""
        setTheme(Theme.DARK, save=False)
        window._refresh_theme()
        app.processEvents()
        if window._viewer is None:  # テーマ切替で閉じてしまった場合は開き直す
            open_viewer_shot()

    def save_viewer_dark() -> None:
        viewer = window._viewer
        if viewer is None:
            print("skip: ダークテーマのビューアは撮影できませんでした（ビューアが開いていません）")
            return
        viewer.resize(1360, 860)
        app.processEvents()
        viewer.grab().save(os.path.join(args.out, "screenshot_viewer_dark.png"))
        print("saved:", os.path.join(args.out, "screenshot_viewer_dark.png"))
        viewer.close()

    def finish() -> None:
        window.close()
        app.quit()

    if args.lang == "en":
        # 英語表示はウィンドウを作り直す必要があるため、単独で撮影する
        QTimer.singleShot(args.wait, lambda: shot("screenshot_english.png"))
        QTimer.singleShot(args.wait + 600, finish)
        return app.exec()


    wait = args.wait
    QTimer.singleShot(wait, save_light)
    QTimer.singleShot(wait + 700, save_detailed)
    QTimer.singleShot(wait + 1300, to_dark)
    QTimer.singleShot(wait + 2100, save_dark)
    QTimer.singleShot(wait + 2400, back_to_light)
    QTimer.singleShot(wait + 3000, save_videos)
    QTimer.singleShot(wait + 3600, back_to_photos)
    QTimer.singleShot(wait + 4300, open_viewer_shot)
    QTimer.singleShot(wait + 7500, save_viewer)
    QTimer.singleShot(wait + 8100, to_dark_viewer)
    QTimer.singleShot(wait + 9900, save_viewer_dark)
    QTimer.singleShot(wait + 10600, finish)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
