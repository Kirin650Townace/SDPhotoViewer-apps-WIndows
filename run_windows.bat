@echo off
rem ============================================================
rem  SD フォトビューアを起動するバッチファイル
rem
rem  ・黒い画面（コンソール）は出ません（pythonw で起動します）
rem  ・ライブラリが足りないときだけ、この画面にメッセージが出ます
rem  ・exe 版（dist の中）を使う場合は、このファイルは不要です
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [エラー] Python が見つかりません。https://www.python.org/downloads/ から
    echo          Python 3.10 以降をインストールしてください。
    pause
    exit /b 1
)

rem ライブラリが揃っているか確認（そろっていれば何も表示せず起動して終了）
pythonw -c "import PySide6, qfluentwidgets, PIL, imageio_ffmpeg" 2>nul
if not errorlevel 1 (
    start "" pythonw app.py %*
    exit /b 0
)

echo 必要なライブラリをインストールします（初回のみ・数分かかることがあります）...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [エラー] インストールに失敗しました。上のメッセージを送ってください。
    pause
    exit /b 1
)

start "" pythonw app.py %*
echo 起動しました。この画面は閉じてかまいません。
exit /b 0
