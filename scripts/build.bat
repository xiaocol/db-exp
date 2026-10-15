@echo off
rem ============================================================
rem  DBエクスポートツール ビルドスクリプト（Windows 用）
rem  実行すると dist\db-exp.exe が生成されます。
rem  必要なもの: Node.js 20 以上 / Python 3.10 以上（python コマンド）
rem  ※ このファイルは Shift_JIS(CP932)・CRLF で保存しています。
rem ============================================================
setlocal
cd /d "%~dp0\.."

echo [1/3] フロントエンドをビルドしています...
pushd frontend
call npm ci || goto :error
call npm run build || goto :error
popd

echo [2/3] Python 仮想環境を準備しています...
pushd backend
if not exist .venv (
    python -m venv .venv || goto :error
)
call .venv\Scripts\python -m pip install --upgrade pip || goto :error
call .venv\Scripts\python -m pip install -r requirements-dev.txt || goto :error

echo [3/3] exe を生成しています...
call .venv\Scripts\pyinstaller --noconfirm --distpath ..\dist db_exp.spec || goto :error
popd

echo.
echo ビルドが完了しました: %cd%\dist\db-exp.exe
endlocal
exit /b 0

:error
echo.
echo ビルドに失敗しました。上のエラーメッセージを確認してください。
popd
endlocal
exit /b 1
