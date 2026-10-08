"""Windows 用の実行ファイル（.exe）を作るスクリプト.

PyInstaller を使って、Python が入っていない PC でも動く単体アプリを作る。

使い方（Windows のコマンドプロンプト / PowerShell）:
    python tools/build_exe.py                  # 迷ったらこれ
    python tools/build_exe.py --onefile        # 1つの exe にまとめる（起動が遅くなる）
    python tools/build_exe.py --console        # 起動しないときの調査用（黒い画面にエラーが出ます）
    python tools/build_exe.py --debug          # 画面を出さずに読み込みチェックだけ行う

成果物:
    dist/SDフォトビューア/SDフォトビューア.exe

補足:
    - Python 3.10.0 の `dis` の不具合（bpo-45757）は自動で回避します
    - アイコンは assets/app.ico（無ければ tools/make_icon.py で生成）を使います
    - exe と同じフォルダに `ログを保存.txt` を置くので、起動しないときは
      その手順で SDPhotoViewer.log を送ってもらえれば原因を特定できます
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_NAME = "SDフォトビューア"
HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_pyinstaller_entry.py")
ICON = os.path.join(ROOT, "assets", "app.ico")
ICON_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "make_icon.py")

# 同梱しない（アプリが使わない）ライブラリ。
# 入っていても配布物に入れないことで、ZIP を小さく保つ。
UNUSED_MODULES = (
    "numba", "llvmlite",                    # 数値計算の高速化（未使用）
    "scipy", "pandas", "matplotlib",        # 科学計算・グラフ（未使用）
    "IPython", "jedi", "parso",             # 対話実行環境（未使用）
    "jupyter", "jupyter_client", "jupyter_core", "notebook", "nbformat", "nbconvert",
    "torch", "tensorflow", "keras", "cv2", "skimage",
    "pytest", "sphinx", "docutils",
    "tkinter", "_tkinter", "pydoc_data",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
)

LICENSE_COMPONENTS = (
    ("PySide6", "LGPL-3.0.txt", "Qt for Python / Qt（LGPLv3。DLL は _internal 内に別ファイルとして同梱）"),
    ("PySide6-Fluent-Widgets", "GPL-3.0.txt", "Fluent 風の部品（GPLv3）"),
    ("imageio-ffmpeg", "FFMPEG-GPL.txt", "動画のサムネイル用 ffmpeg（GPLv3 ビルドを同梱）"),
)

FFMPEG_NOTE = """ffmpeg（動画のサムネイル用）について
=====================================

このアプリは動画のサムネイルを作るために ffmpeg を使います。
同梱している ffmpeg の実行ファイルは GPLv3 のビルドです
（imageio-ffmpeg に同梱されているものをそのまま入れています）。

・ffmpeg のライセンス: GNU General Public License version 3
   正文は licenses/GPL-3.0.txt にあります
・ffmpeg のソースコードの入手先:
   https://ffmpeg.org/download.html
   同梱ビルドの入手元: https://johnvansickle.com/ffmpeg/
・アプリは ffmpeg を「別のプログラム」として呼び出しているだけなので、
  アプリ本体のライセンスは GPL である必要はありません。
"""

README_TEXT = """SD フォトビューア：起動しないときの調べ方
================================================

1. このフォルダにある「SDフォトビューア.exe」をダブルクリックしてください。
   （フォルダごとデスクトップなどに移動してから実行してもかまいません）

2. それでも画面が出ない場合は、同じフォルダに
   「SDPhotoViewer.log」というファイルが作られていないか確認してください。
   - できていたら、そのファイルをそのまま送ってください（原因が書かれています）
   - できていない場合は、次のコマンドを実行して、黒い画面に出た内容を送ってください

       SDフォトビューア.exe

   （コマンドプロンプトの使い方: このフォルダの何もないところを右クリック →
     「ターミナルで開く」または「PowerShell ウィンドウをここで開く」→ 上を入力）

3. 「アプリが起動できない」と出る場合は、次の2つを試してください。
   - フォルダとファイルの名前をすべて半角英数字にする
     （例: C:\\SDPV\\SDPhotoViewer.exe）
     ※ 日本語のフォルダ名や、OneDrive の中で実行すると失敗することがあります
   - ウイルス対策ソフトの「隔離」に入っていないか確認する
     （PyInstaller 製の exe は誤検知されやすいため、除外設定をしてください）

4. Windows の SmartScreen の警告が出る場合は、
   画面の「詳細情報」→「実行」を選んでください
   （署名のないアプリのため警告が出ます）

5. 起動はするが画面が真っ白／固まる場合は、
   コンソール付きで作り直すと原因が見えます:
       python tools\\build_exe.py --console
"""


def module_exists(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def load_helper():
    """回避用ヘルパー（_pyinstaller_entry.py）を読み込む。読めなければ None。"""
    try:
        spec = importlib.util.spec_from_file_location("_sdv_pyinstaller_entry", HELPER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:  # noqa: BLE001 - ヘルパーが無い/壊れていても通常経路で続行する
        return None


def needs_dis_workaround() -> bool:
    """Python 3.10.0 の dis の不具合（bpo-45757）に当たるかどうか。

    この環境では PyInstaller の解析が ``IndexError: tuple index out of range``
    で落ちるため、回避用のヘルパー経由で実行する。
    """
    helper = load_helper()
    return bool(helper and helper._dis_needs_fix())


def ensure_icon() -> str:
    """アイコンを用意する（無ければ生成）。作れなければ空文字を返す。"""
    if os.path.exists(ICON):
        return ICON
    try:
        subprocess.run([sys.executable, ICON_SCRIPT], check=True, cwd=ROOT)
    except Exception:  # noqa: BLE001
        return ""
    return ICON if os.path.exists(ICON) else ""


def collect_licenses(dist_dir: str) -> int:
    """配布物にライセンス文を入れる（配布時の条件を満たすため）。

    - 各ライブラリのライセンス文（インストール先から拾う）
    - GPLv3 / LGPLv3 の正文と、どれが何のライセンスかの一覧
    """
    import importlib.metadata as md

    out = os.path.join(dist_dir, "licenses")
    os.makedirs(out, exist_ok=True)
    count = 0

    # 1) このリポジトリに置いてある正文
    for name in ("GPL-3.0.txt", "LGPL-3.0.txt"):
        src = os.path.join(ROOT, "licenses", name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(out, name))
            count += 1

    # 2) インストールされているライブラリのライセンス文
    wanted = {
        "pillow": "Pillow.txt",
        "pillow_heif": "pillow-heif.txt",
        "numpy": "numpy.txt",
        "imageio_ffmpeg": "imageio-ffmpeg.txt",
        "rawpy": "rawpy.txt",
    }

    def _copy(src, dest_name: str) -> int:
        try:
            if src and src.exists() and src.is_file():
                shutil.copy2(src, os.path.join(out, dest_name))
                return 1
        except OSError:
            pass
        return 0

    for dist in md.distributions():
        name = (dist.metadata.get("Name") or "").lower().replace("-", "_")
        if name not in wanted:
            continue
        main_done = False
        for f in dist.files or []:
            upper = str(f).upper()
            if "LICENSE" not in upper and "COPYING" not in upper:
                continue
            if "DIST-INFO" not in upper and "EGG-INFO" not in upper:
                continue  # 配布物のライセンス文は dist-info の中に入っている
            if not main_done and "BUNDLED" not in upper:
                count += _copy(f.locate(), wanted[name])
                main_done = True
            elif "BUNDLED" in upper:
                # 同梱物（libheif など）のライセンスも一緒に入れておく
                stem = wanted[name].removesuffix(".txt")
                count += _copy(f.locate(), f"{stem}-bundled.txt")

    # 3) ffmpeg の注意書き
    with open(os.path.join(out, "FFMPEG-GPL.txt"), "w", encoding="utf-8") as handle:
        handle.write(FFMPEG_NOTE)
    count += 1

    # 4) どれが何のライセンスかの一覧
    lines = ["SD フォトビューア：同梱ライブラリのライセンス", "=" * 50, ""]
    lines.append("■ アプリ本体")
    lines.append("  このアプリ（SD フォトビューア）は GNU General Public License v3.0 (GPLv3)")
    lines.append("  で公開しています。正文は、アプリと同じフォルダの LICENSE と、この")
    lines.append("  フォルダの GPL-3.0.txt にあります。")
    lines.append("")
    lines.append("■ 同梱ライブラリ")
    lines.append("  このフォルダのファイルは、アプリに同梱しているライブラリのライセンス文です。")
    lines.append("詳しくは、アプリと同じフォルダの THIRD_PARTY_LICENSES.md をお読みください。")
    lines.append("")
    for component, filename, note in LICENSE_COMPONENTS:
        lines.append(f"・{component}: {filename}\n    {note}")
    lines.append("・Pillow / pillow-heif / numpy / imageio-ffmpeg: 同名のテキストファイル")
    lines.append("")
    lines.append("配布するときは、この licenses フォルダと THIRD_PARTY_LICENSES.md を")
    lines.append("アプリ本体と一緒に配ってください。")
    with open(os.path.join(out, "README.txt"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    count += 1
    return count


def check_imports() -> None:
    """exe に必要なライブラリを読み込めるか確認する（起動失敗の予備チェック）。"""
    print("[確認] 必要なライブラリを読み込めるかテストします...")
    checks = [
        ("PySide6.QtWidgets", True),
        ("PySide6.QtSvg", True),
        ("PySide6.QtNetwork", True),
        ("qfluentwidgets", True),
        ("PIL", True),
        ("PIL.Image", True),
        ("pillow_heif", False),
        ("rawpy", False),
        ("numpy", False),
        ("imageio_ffmpeg", False),
    ]
    failed_required = []
    for name, required in checks:
        try:
            __import__(name)
            print(f"    OK   {name}")
        except Exception as exc:  # noqa: BLE001
            mark = "NG  " if required else "なし "
            print(f"    {mark} {name} ({exc})")
            if required:
                failed_required.append(name)
    if failed_required:
        print()
        print("必須ライブラリが読み込めません:", ", ".join(failed_required))
        print("  python -m pip install -r requirements.txt  を実行してください。")
    else:
        print("    → 必須ライブラリはすべて読み込めました。")


def main() -> int:
    parser = argparse.ArgumentParser(description="PyInstaller で exe を作成する")
    parser.add_argument("--onefile", action="store_true", help="1つの exe にまとめる（起動が少し遅くなる）")
    parser.add_argument("--name", default=DEFAULT_NAME)
    parser.add_argument("--icon", default="", help=".ico ファイルを指定（既定: assets/app.ico）")
    parser.add_argument(
        "--console",
        action="store_true",
        help="調査用に黒い画面（コンソール）付きで作る。この画面を閉じるとアプリも終了します",
    )
    parser.add_argument("--debug", action="store_true", help="画面を出さず、読み込みチェックだけ行う")
    args = parser.parse_args()

    if args.debug:
        check_imports()
        return 0

    if not module_exists("PyInstaller"):
        print("PyInstaller が必要です:  pip install pyinstaller")
        return 1

    # 調査用（--console）のときは、通常の exe を上書きしないよう別名にする
    name = args.name
    if args.console and args.name == DEFAULT_NAME:
        name = f"{DEFAULT_NAME}（デバッグ）"

    if args.console:
        print("※ --console を指定したので、エラーメッセージが見える「黒い画面つき」で作ります。")
        print("   ダブルクリックで起動したときは、その画面は自動的に隠れます（アプリの動作は同じ）。")
        print("   ターミナルから実行すると、その画面にエラーが出ます。")
        print(f"   出力名: {name}.exe")
        print()

    check_imports()
    print()

    # Python 3.10.0 では dis の不具合を避けるヘルパー経由で PyInstaller を呼ぶ
    if needs_dis_workaround() and os.path.exists(HELPER):
        print("Python 3.10.0 の dis の不具合（bpo-45757）を回避してビルドします。")
        print("Python 3.10.11 以降に更新すると、この回避処理は不要になります。")
        entry = [sys.executable, HELPER]
    else:
        entry = [sys.executable, "-m", "PyInstaller"]

    icon = args.icon or ensure_icon()

    cmd = [
        *entry,
        "--noconfirm",
        "--clean",
        "--windowed" if not args.console else "--console",
        "--name",
        name,
        "--collect-all",
        "qfluentwidgets",
        "--collect-all",
        "PIL",
    ]
    cmd += ["--onefile"] if args.onefile else ["--onedir"]

    # 任意ライブラリ（入っている場合のみ同梱する）
    optional = []
    if module_exists("pillow_heif"):
        cmd += ["--collect-all", "pillow_heif"]
        optional.append("HEIC/HIF")
    if module_exists("rawpy"):
        cmd += ["--collect-all", "rawpy"]
    if module_exists("numpy"):
        cmd += ["--collect-all", "numpy", "--hidden-import", "numpy"]
        optional.append("RAW")
    if module_exists("imageio_ffmpeg"):
        # ffmpeg 本体（binaries フォルダの実行ファイル）も一緒に同梱する
        cmd += ["--collect-all", "imageio_ffmpeg"]
        optional.append("動画")

    # このアプリで使わない大きなライブラリを除外する
    # （開発 PC に numba や scipy などが入っていると、それごと同梱されて
    #   配布物が数百 MB になってしまうため）
    for module in UNUSED_MODULES:
        cmd += ["--exclude-module", module]

    if icon and os.path.exists(icon):
        cmd += ["--icon", os.path.abspath(icon)]
        # タイトルバー / タスクバー用にもアイコンを同梱する
        cmd += ["--add-data", f"{os.path.abspath(icon)}:assets"]
        png = os.path.join(os.path.dirname(icon), "app.png")
        if os.path.exists(png):
            cmd += ["--add-data", f"{os.path.abspath(png)}:assets"]
        print("アイコン:", os.path.relpath(icon, ROOT), "（exe に埋め込み + 同梱）")
    else:
        print("アイコン: 見つかりません（既定のアイコンでビルドします）")

    cmd.append(os.path.join(ROOT, "app.py"))

    print("実行:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT, check=False)
    if result.returncode != 0:
        print()
        print("ビルドに失敗しました。上のログの最後の 20 行ほどを送ってもらえれば調べます。")
        return result.returncode

    # 通常版を作ったときは、迷わないように調査用の出力を片付ける
    if not args.console:
        stale = os.path.join(ROOT, "dist", f"{DEFAULT_NAME}（デバッグ）")
        if os.path.isdir(stale):
            shutil.rmtree(stale, ignore_errors=True)
            print("調査用の「（デバッグ）」フォルダを削除しました（普段は使いません）")

    # ドキュメント・案内・ライセンス文をコピー
    dist_dir = os.path.join(ROOT, "dist", name)
    if os.path.isdir(dist_dir):
        copied_docs = []
        for doc in ("はじめにお読みください.md", "使い方.md", "THIRD_PARTY_LICENSES.md", "LICENSE"):
            src = os.path.join(ROOT, doc)
            if os.path.exists(src):
                shutil.copy2(src, dist_dir)
                copied_docs.append(doc)
        # 「はじめにお読みください」はメモ帳でも開けるように .txt でも入れる
        guide = os.path.join(ROOT, "はじめにお読みください.md")
        if os.path.exists(guide):
            with open(guide, encoding="utf-8") as handle:
                text = handle.read()
            with open(os.path.join(dist_dir, "はじめにお読みください.txt"), "w", encoding="utf-8") as handle:
                handle.write(text)
            copied_docs.append("はじめにお読みください.txt（メモ帳用）")
        readme_path = os.path.join(dist_dir, "ログを保存.txt")
        with open(readme_path, "w", encoding="utf-8") as handle:
            handle.write(README_TEXT)
        copied = collect_licenses(dist_dir)
        print("同梱:", f"{' / '.join(copied_docs)} / ログを保存.txt / ライセンス文 {copied} 件")

    exe_file = f"{name}.exe" if os.name == "nt" else name
    exe_path = os.path.abspath(os.path.join(dist_dir, exe_file))
    line = "=" * 72
    print()
    print(line)
    if args.console:
        print(" できあがり（調査用・黒い画面つき）")
        print("   ダブルクリックで起動したときは黒い画面は自動で隠れます。")
        print(f"   {exe_path}")
        print("   ※ 普段使い用は build_windows.bat で作る通常版です。")
    else:
        print(" できあがり。このファイルを使います（黒い画面は出ません）")
        print(f"   {exe_path}")
        print("   エクスプローラーでこのファイルをダブルクリックしてください。")
    print(line)
    print("  ・dist の中のフォルダごと（_internal も一緒に）移動・コピーしてください")
    print("  ・build フォルダは作業用です。開く必要はありません")
    print(f"  ・同梱した形式: JPEG/PNG ほか（Qt）{' / ' + ' / '.join(optional) if optional else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
