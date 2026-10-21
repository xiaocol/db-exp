"""ドキュメントのスキャン・マスク済み Markdown 出力のテスト。"""

import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DBEXP_DATA_DIR", str(tmp_path))
    from app.main import create_app

    return TestClient(create_app(), headers={"x-dbexp": "1"})


CSV = "顧客ID,氏名,電話番号,メールアドレス,備考\n" + "".join(
    f"{i},山田 太郎{i},03-1234-{5600 + i},taro{i}@example.com,{'田中様より連絡' if i % 2 else 'なし'}\n" for i in range(10)
)
TEXT = "打合せメモ\n参加者：佐藤 花子（営業部）\n連絡先 TEL 090-1234-5678\n受付番号 123-4567\n"


def make_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "顧客一覧"
    ws.append(["顧客一覧"])
    ws.append(["氏名", "住所", "生年月日"])
    for i in range(5):
        ws.append([f"鈴木 一郎{i}", f"東京都千代田区丸の内1-{i}", f"1980/01/0{i + 1}"])
    ws.append([])
    ws.append(["作成者：高橋 健太"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def scan(client, files):
    res = client.post("/api/documents/scan", files=[("files", (n, d)) for n, d in files])
    assert res.status_code == 200, res.text
    return res.json()


def test_scan_and_export_markdown(client):
    data = scan(client, [
        ("data/顧客.csv", CSV.encode("cp932")),
        ("memo.txt", TEXT.encode("utf-8")),
        ("一覧.xlsx", make_xlsx()),
        ("readme.md", "# 手順\n\n| 担当 | 電話 |\n| --- | --- |\n| 山田様 | 03-1111-2222 |\n".encode()),
        ("image.png", b"\x89PNG"),
    ])
    files = {f["name"]: f for f in data["files"]}
    assert files["data/顧客.csv"]["error"] is None
    assert files["image.png"]["error"]
    by = {(f["file"], f.get("column") or f.get("text") or f["category"]): f for f in data["findings"]}
    assert by[("data/顧客.csv", "氏名")]["level"] == "auto"
    assert by[("data/顧客.csv", "電話番号")]["category"] == "phone"
    assert by[("一覧.xlsx", "住所")]["level"] == "auto"
    review = [f for f in data["findings"] if f["level"] == "review"]
    assert any(f["file"] == "memo.txt" and f["text"] == "123-4567" for f in review)

    # 要確認の 1 件を「マスクしない」と判断して出力する
    keep = next(f for f in review if f["text"] == "123-4567")
    res = client.post(f"/api/documents/{data['scan_id']}/export", json={"decisions": {keep["id"]: {"mask": False}}})
    assert res.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(res.content))
    names = set(zf.namelist())
    assert {"data/顧客.md", "memo.md", "一覧.md", "readme.md", "マスキング結果一覧.md"} <= names
    csv_md = zf.read("data/顧客.md").decode()
    assert "山田 太郎" not in csv_md and "taro1@example.com" not in csv_md and "田中様" not in csv_md
    assert "| 顧客ID | 氏名 |" in csv_md
    memo = zf.read("memo.md").decode()
    assert "090-1234-5678" not in memo and "佐藤 花子" not in memo
    assert "123-4567" in memo  # 人が「マスクしない」と判断したもの
    xl = zf.read("一覧.md").decode()
    assert "## 顧客一覧" in xl and "丸の内" not in xl and "高橋 健太" not in xl
    md = zf.read("readme.md").decode()
    assert "# 手順" in md and "03-1111-2222" not in md
    report = zf.read("マスキング結果一覧.md").decode()
    assert "マスクしない" in report and "山田 太郎" not in report


def test_export_unknown_scan(client):
    res = client.post("/api/documents/" + "0" * 32 + "/export", json={})
    assert res.status_code == 400


def test_report_xlsx(client):
    data = scan(client, [("a.csv", CSV.encode())])
    res = client.post("/api/report", json={"findings": data["findings"], "decisions": {}})
    assert res.status_code == 200 and res.content[:2] == b"PK"
