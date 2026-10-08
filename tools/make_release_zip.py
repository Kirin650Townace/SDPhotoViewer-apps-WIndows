"""配布用の ZIP を作る（GitHub の Releases にそのまま添付できる形）.

使い方:
    python tools/make_release_zip.py            # dist の中身を ZIP にする
    python tools/make_release_zip.py --open     # 作ったあとフォルダを開く

先に `build_windows.bat`（または `python tools/build_exe.py`）で exe を作っておくこと。
できあがりは `release/` フォルダに `SDフォトビューア_v1.0_windows.zip` として入ります。
"""

from __future__ import annotations

import argparse
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

APP_DIR_NAME = "SDフォトビューア"

# 配布物に入れないもの（利用者には不要）
EXCLUDE_NAMES = {"SDPhotoViewer.log", "config"}
EXCLUDE_EXTS = {".spec", ".pyc"}


def find_app_dir() -> str:
    """ビルド済みのアプリフォルダ（dist/...）を返す。"""
    dist = os.path.join(ROOT, "dist")
    if not os.path.isdir(dist):
        return ""
    # 通常版 → デバッグ版 → そのほか の順に探す
    for name in (APP_DIR_NAME, f"{APP_DIR_NAME}（デバッグ）"):
        path = os.path.join(dist, name)
        if os.path.isdir(path):
            return path
    for name in sorted(os.listdir(dist)):
        path = os.path.join(dist, name)
        if os.path.isdir(path) and os.path.exists(os.path.join(path, f"{name}.exe")):
            return path
    return ""


def app_version() -> str:
    try:
        from sdphotoviewer import __version__  # noqa: PLC0415

        return __version__
    except Exception:  # noqa: BLE001 - 取れなくても続行する
        return "1.0"


def make_zip(app_dir: str, out_path: str) -> int:
    """フォルダの中身を ZIP にまとめる（除外ルールつき）。戻り値は入れたファイル数。"""
    count = 0
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for folder, dirs, files in os.walk(app_dir):
            # 除外フォルダ（__pycache__ など）は降りない
            dirs[:] = [d for d in dirs if d not in EXCLUDE_NAMES and d != "__pycache__"]
            for name in sorted(files):
                src = os.path.join(folder, name)
                rel = os.path.relpath(src, app_dir)
                if name in EXCLUDE_NAMES or os.path.splitext(name)[1].lower() in EXCLUDE_EXTS:
                    continue
                archive.write(src, os.path.join(APP_DIR_NAME, rel))
                count += 1
    return count


def open_folder(path: str) -> None:
    """フォルダをエクスプローラーで開く（Windows のみ）。"""
    try:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
        elif sys.platform == "darwin":
            import subprocess  # noqa: PLC0415

            subprocess.Popen(["open", path])  # noqa: S603,S607
        else:
            import subprocess  # noqa: PLC0415

            subprocess.Popen(["xdg-open", path])  # noqa: S603,S607
    except Exception:  # noqa: BLE001 - 開けなくても問題ない
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="配布用の ZIP を作ります")
    parser.add_argument("--open", action="store_true", help="作ったあとフォルダを開く")
    args = parser.parse_args()

    app_dir = find_app_dir()
    if not app_dir:
        print("先にビルドしてください:  build_windows.bat  または  python tools\\build_exe.py")
        return 1

    version = app_version()
    out_dir = os.path.join(ROOT, "release")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"SDフォトビューア_v{version}_windows.zip")

    # 古い ZIP は消してから作り直す（中身が混ざらないように）
    for name in os.listdir(out_dir):
        if name.startswith("SDフォトビューア_v") and name.endswith(".zip"):
            os.remove(os.path.join(out_dir, name))

    count = make_zip(app_dir, out_path)
    size_mb = os.path.getsize(out_path) / (1024 * 1024)

    if not os.path.exists(os.path.join(app_dir, "ログを保存.txt")):
        print("※ `ログを保存.txt` が見つかりません。ビルドが最後まで終わっているか確認してください")

    print()
    print("=" * 72)
    print("  配布用の ZIP ができました（GitHub の Releases にそのまま添付できます）")
    print(f"   {out_path}")
    print(f"   {count} ファイル / 約 {size_mb:.1f} MB")
    print("=" * 72)
    print("  ・中に入っているのはアプリ一式（exe / _internal / 説明書 / ライセンス）です")
    print("  ・配布先（GitHub）では Releases → Draft a new release → この ZIP を添付")
    print("  ・ZIP 名を変えるときは sdphotoviewer/__init__.py の __version__ を変えてから実行")

    if args.open:
        open_folder(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
