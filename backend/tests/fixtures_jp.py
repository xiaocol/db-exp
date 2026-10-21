"""結合テスト用の日本語サンプルデータ（架空の個人情報）。"""

import datetime as dt

TABLE = "DBEXP_T_KOKYAKU"

# (列名, Oracle の型, PostgreSQL の型, コメント)
COLUMNS = [
    ("KOKYAKU_ID", "NUMBER(10) PRIMARY KEY", "integer PRIMARY KEY", "顧客ID"),
    ("SHIMEI", "VARCHAR2(40 CHAR)", "varchar(40)", "氏名"),
    ("SHIMEI_KANA", "VARCHAR2(60 CHAR)", "varchar(60)", "氏名カナ"),
    ("TEL_NO", "VARCHAR2(20)", "varchar(20)", "電話番号"),
    ("MAIL_ADDR", "VARCHAR2(100)", "varchar(100)", "メールアドレス"),
    ("ZIP_CD", "CHAR(8)", "char(8)", "郵便番号"),
    ("JUSHO", "VARCHAR2(200 CHAR)", "varchar(200)", "住所"),
    ("BIRTH_DT", "DATE", "date", "生年月日"),
    ("SEIBETSU", "CHAR(1)", "char(1)", "性別"),
    ("NENSHU", "NUMBER(12)", "numeric(12)", "年収"),
    ("BIKO", "VARCHAR2(4000)", "text", "備考"),
    ("MAIL_HAISHIN_FLG", "CHAR(1) NOT NULL", "char(1) NOT NULL", "メール配信フラグ"),
    ("TOROKU_DT", "TIMESTAMP", "timestamp", "登録日時"),
]

SEI = [("山田", "ヤマダ"), ("佐藤", "サトウ"), ("鈴木", "スズキ"), ("田中", "タナカ"), ("高橋", "タカハシ")]
MEI = [("太郎", "タロウ"), ("花子", "ハナコ"), ("一郎", "イチロウ"), ("美咲", "ミサキ")]
ADDR = ["東京都千代田区丸の内1-1-1", "大阪府大阪市北区梅田2-2-2 梅田ビル5F", "神奈川県横浜市中区山下町3",
        "北海道札幌市中央区北一条西2丁目", "長野県北佐久郡軽井沢町1-2"]
BIKO = ["特になし", "山田様より電話あり。折り返し 090-1234-5678 まで", "", "連絡は taro@example.com へ", None]


def rows(n: int = 20) -> list[tuple]:
    out = []
    for i in range(n):
        sei, mei = SEI[i % len(SEI)], MEI[i % len(MEI)]
        out.append((
            i + 1,
            f"{sei[0]} {mei[0]}",
            f"{sei[1]} {mei[1]}",
            f"0{3 + i % 6}-{1000 + i:04d}-{5000 + i:04d}" if i % 3 else f"090-{1000 + i:04d}-{2000 + i:04d}",
            f"user{i}@example.co.jp",
            f"{100 + i:03d}-{1000 + i:04d}",
            ADDR[i % len(ADDR)],
            dt.date(1970 + i, 1 + i % 12, 1 + i % 28),
            "1" if i % 2 else "2",
            3_000_000 + i * 123_456,
            BIKO[i % len(BIKO)],
            "1" if i % 2 else "0",
            dt.datetime(2024, 4, 1, 9, 30, i),
        ))
    return out


def create(conn, db_type: str) -> None:
    ora = db_type == "oracle"
    with conn.cursor() as cur:
        try:
            cur.execute(f"DROP TABLE {TABLE}" + ("" if ora else " CASCADE"))
        except Exception:  # noqa: BLE001
            conn.rollback()
        cols = ", ".join(f"{n} {o if ora else p}" for n, o, p, _ in COLUMNS)
        cur.execute(f"CREATE TABLE {TABLE} ({cols})")
        cur.execute(f"COMMENT ON TABLE {TABLE} IS '顧客マスタ'")
        for n, _, _, c in COLUMNS:
            cur.execute(f"COMMENT ON COLUMN {TABLE}.{n} IS '{c}'")
        insert_rows(conn, db_type, rows())
    conn.commit()


def insert_rows(conn, db_type: str, data: list[tuple]) -> None:
    ora = db_type == "oracle"
    marks = ", ".join(f":{i + 1}" if ora else "%s" for i in range(len(COLUMNS)))
    with conn.cursor() as cur:
        cur.executemany(f"INSERT INTO {TABLE} VALUES ({marks})", data)


def fetch_all(conn) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT * FROM {TABLE} ORDER BY KOKYAKU_ID")
        return [tuple(r) for r in cur.fetchall()]
