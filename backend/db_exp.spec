# -*- mode: python ; coding: utf-8 -*-
# PyInstaller ビルド定義（単一 exe ファイルを生成する）
#
# 使い方（backend ディレクトリで実行）:
#   pyinstaller --noconfirm db_exp.spec
# 事前に frontend で `npm run build` を実行し、frontend/dist を作成しておくこと。

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve()
DIST = ROOT.parent / "frontend" / "dist"
if not (DIST / "index.html").exists():
    raise SystemExit(f"フロントエンドのビルド成果物がありません: {DIST}\n先に frontend で npm run build を実行してください。")

datas = [(str(DIST), "static")]
binaries = []
hiddenimports = []

# 動的に読み込まれるモジュールを明示的に同梱する
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("oracledb")
hiddenimports += collect_submodules("app")
# ファイルのアップロード（multipart/form-data）の解析に使用
hiddenimports += collect_submodules("python_multipart")
# cryptography は oracledb の Thin モードが内部（C拡張）から遅延 import するため、
# 自動解析では検出されない。明示しないと exe で DPY-3016 エラーになる。
for pkg in ("psycopg", "psycopg_binary", "cryptography"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["run.py"],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "IPython", "matplotlib", "numpy", "pandas"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="db-exp",
    debug=False,
    strip=False,
    upx=False,
    # コンソールを表示する（閉じるとアプリが終了する。ログ・URL の確認にも使用）
    console=True,
)
