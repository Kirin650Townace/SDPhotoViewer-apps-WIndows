"""PyInstaller を「Python 3.10.0 の dis バグ」を回避して起動するヘルパー.

背景
----
Python 3.10.0 の標準ライブラリ ``dis._unpack_opargs()`` には、``else`` 側で
``extended_arg`` をリセットし忘れている不具合があります
（CPython bpo-45757 / PyInstaller #6301）。このせいで PyInstaller のモジュール
解析が次のエラーで落ちます。

    File "...\\lib\\dis.py", line 292, in _get_const_info
        argval = const_list[const_index]
    IndexError: tuple index out of range

Python 3.10.1 以降では修正済みです。このスクリプトは **Python 本体の
ファイルを書き換えずに**、実行時だけ dis を直してから
``python -m PyInstaller`` と同じ処理を実行します。

（3.10.0 以外では何もしません。3.11 以降は dis の内部仕様が違うため、
 ここで手を入れてはいけません。）

使い方（tools/build_exe.py から自動で呼ばれます）::

    python tools/_pyinstaller_entry.py --noconfirm --clean --onedir app.py
"""

from __future__ import annotations

import dis
import runpy
import sys

_TARGET_VERSION = (3, 10)


def _dis_needs_fix(version=None) -> bool:
    """dis が 3.10.0 の不具合版かどうかを判定する。

    ``version`` はテスト用（省略時は実行中の Python のバージョン）。
    """
    current = tuple((sys.version_info if version is None else version)[:2])
    if current != _TARGET_VERSION:
        return False  # 3.10 以外は対象外（3.11 以降は実装が別物）

    unpack = getattr(dis, "_unpack_opargs", None)
    if unpack is None:
        return False
    try:
        import inspect

        source = inspect.getsource(unpack)
    except (OSError, TypeError):  # ソースが読めない環境では触らない
        return False
    # 修正済みの実装では「extended_arg = 0」が初期化と else 側の 2 回現れる
    return source.count("extended_arg = 0") < 2


def fixed_unpack_opargs(code):
    """修正版の命令列パーサ（Python 3.10.1 と同じ内容）。"""
    extended_arg = 0
    for i in range(0, len(code), 2):
        op = code[i]
        if op >= dis.HAVE_ARGUMENT:
            arg = code[i + 1] | extended_arg
            extended_arg = (arg << 8) if op == dis.EXTENDED_ARG else 0
        else:
            arg = None
            extended_arg = 0  # ← 3.10.0 で抜けていたリセット（不具合の正体）
        yield (i, op, arg)


def apply_workaround(version=None) -> bool:
    """dis の不具合を実行時に直す（直した場合は True）。``version`` はテスト用。"""
    if not _dis_needs_fix(version):
        return False

    dis._unpack_opargs = fixed_unpack_opargs  # type: ignore[attr-defined]
    cache_clear = getattr(dis.get_instructions, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()
    return True


def main() -> int:
    if apply_workaround():
        print(
            "[情報] Python 3.10.0 の既知の不具合（dis / bpo-45757）を回避してビルドします。\n"
            "       Python 本体は書き換えていません。3.10.11 以降へ更新すると不要になります。"
        )
    # `python -m PyInstaller` と同じ挙動にする
    sys.argv = ["pyinstaller", *sys.argv[1:]]
    runpy.run_module("PyInstaller", run_name="__main__", alter_sys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
