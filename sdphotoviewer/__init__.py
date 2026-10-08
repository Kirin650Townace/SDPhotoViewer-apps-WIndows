"""SD フォトビューア（カメラの SD カードの写真をタイル表示するアプリ）.

このソフトは GNU General Public License v3.0（GPLv3）で公開しています。
詳細は、プロジェクト直下の LICENSE と THIRD_PARTY_LICENSES.md をご覧ください。
"""

from __future__ import annotations

# 公開しているバージョン（配布名と合わせる）
__version__ = "1.0"

# ---- 公開（配布）用の情報 ------------------------------------------------
# 公開するときは、この 3 行を自分の名前と URL に書き換えてください。
# （アプリ内の「アプリについて」に表示されます）
COPYRIGHT_YEAR = "2026"
COPYRIGHT_HOLDER = "よづき"
CONTACT = "X (Twitter): @YoZKi_VRC"
CONTACT_URL = "https://www.twitter.com/YoZKi_VRC"
# ソースコードの公開先（GPLv3 の条件で、ここを公開しておく）
SOURCE_URL = "https://github.com/Kirin650Townace/SDPhotoViewer-apps-WIndows"

LICENSE_NAME = "GNU General Public License v3.0 (GPLv3)"


def copyright_line() -> str:
    """「Copyright (C) 2026 名前」の 1 行。"""
    return f"Copyright (C) {COPYRIGHT_YEAR} {COPYRIGHT_HOLDER}"


__all__ = [
    "__version__",
    "CONTACT",
    "CONTACT_URL",
    "COPYRIGHT_HOLDER",
    "COPYRIGHT_YEAR",
    "LICENSE_NAME",
    "SOURCE_URL",
    "copyright_line",
]
