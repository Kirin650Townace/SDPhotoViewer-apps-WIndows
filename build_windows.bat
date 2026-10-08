@echo off
rem ============================================================
rem  SD フォトビューア: 通常版の exe を作ります
rem
rem  ・黒い画面（コンソール）は出ません
rem  ・できあがるのは dist\SDフォトビューア\SDフォトビューア.exe
rem  ・ダブルクリックするだけでOKです
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0"
setlocal

echo.
echo ============================================================
echo  SD フォトビューア: 通常版の exe を作ります（黒い画面なし）
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [エラー] Python が見つかりません。https://www.python.org/downloads/ から
    echo          Python 3.10 以降をインストールしてください（"Add to PATH" にチェック）。
    pause
    exit /b 1
)

echo [1/4] 必要なライブラリをインストールします...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo [エラー] ライブラリのインストールに失敗しました。
    pause
    exit /b 1
)

echo.
echo [2/4] アイコンを用意します...
python tools\make_icon.py

echo.
echo [3/4] exe をビルドします（数分かかります）...
python tools\build_exe.py
if errorlevel 1 (
    echo [エラー] ビルドに失敗しました。上のログを送ってください。
    pause
    exit /b 1
)

echo.
echo [4/4] 完了しました。dist フォルダを開きます。
echo.
echo   使うファイル: dist\SDフォトビューア\SDフォトビューア.exe
echo   （この exe をダブルクリックしてください。黒い画面は出ません）
echo.
start "" explorer "%CD%\dist\SDフォトビューア"
echo dist フォルダを開きました。中の「SDフォトビューア.exe」をダブルクリックしてください。
echo.
pause
