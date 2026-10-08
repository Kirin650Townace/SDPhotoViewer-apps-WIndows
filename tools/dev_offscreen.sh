#!/usr/bin/env bash
# Linux サンドボックス / ヘッドレス環境で動作確認するための補助スクリプト。
# 通常の Windows では不要です（そのまま python app.py を実行してください）。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Qt が必要とする共有ライブラリと日本語フォント（パッケージを展開した場所）
export LD_LIBRARY_PATH="/tmp/sysroot/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
export SDPV_FONT_DIR="/tmp/sysroot/usr/share/fonts/opentype/noto:/tmp/sysroot/usr/share/fonts/truetype/dejavu"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"

exec python3 "$@"
