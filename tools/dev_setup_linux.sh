#!/usr/bin/env bash
# ============================================================
#  開発用: ヘッドレス Linux 環境（このサンドボックスなど）で
#  アプリを動かすためのセットアップ。
#
#  Windows で使う場合このスクリプトは不要です。
#  （run_windows.bat / python app.py を使ってください）
# ============================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "[1/3] Python ライブラリをインストール"
pip3 install --no-input -q PySide6 PySide6-Fluent-Widgets Pillow pillow-heif imageio-ffmpeg pyflakes

echo "[2/3] Qt が必要とする共有ライブラリと日本語フォントを取得"
mkdir -p /tmp/debs /tmp/sysroot
cd /tmp/debs
for p in libxkbcommon0 fonts-noto-cjk fonts-dejavu-core libgl1 libegl1 libdbus-1-3 libfontconfig1; do
    apt-get download "$p" >/dev/null 2>&1 || true
done
for f in libxkbcommon0*.deb fonts-dejavu-core*.deb libgl1*.deb libegl1*.deb libdbus-1-3*.deb libfontconfig1*.deb; do
    [ -f "$f" ] && dpkg-deb -x "$f" /tmp/sysroot/
done
if ls fonts-noto-cjk*.deb >/dev/null 2>&1; then
    dpkg-deb --fsys-tarfile fonts-noto-cjk*.deb | tar -x -C /tmp/sysroot \
        ./usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc 2>/dev/null || true
fi

echo "[3/3] 環境変数の設定（このシェル内）"
export LD_LIBRARY_PATH="/tmp/sysroot/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
export SDPV_FONT_DIR="/tmp/sysroot/usr/share/fonts/opentype/noto:/tmp/sysroot/usr/share/fonts/truetype/dejavu"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"

echo
echo "準備完了。以下のように実行してください:"
echo "  QT_QPA_PLATFORM=offscreen \\"
echo "  LD_LIBRARY_PATH=/tmp/sysroot/usr/lib/x86_64-linux-gnu \\"
echo "  SDPV_FONT_DIR=/tmp/sysroot/usr/share/fonts/opentype/noto:/tmp/sysroot/usr/share/fonts/truetype/dejavu \\"
echo "  python3 $ROOT/tools/selftest.py"
