"""自動判定（列・文中）の単体テスト。"""

import datetime as dt

import pytest

from app.categories import is_valid_luhn, is_valid_my_number, person_name_score
from app.detector import analyze_column
from app.textscan import find_pii


def level(name, comment=None, data_type="VARCHAR2(100)", samples=(), **kw):
    v = analyze_column(name, comment, data_type, list(samples), **kw)
    return v.level, v.category


@pytest.mark.parametrize(
    ("name", "comment", "samples", "expected"),
    [
        ("CUST_NM", "顧客名", ["山田 太郎", "佐藤 花子"] * 5, ("auto", "name")),
        ("TEL_NO", None, ["03-1234-5678", "090-1111-2222"] * 5, ("auto", "phone")),
        ("COL7", None, ["a@example.com", "b@test.co.jp"] * 5, ("auto", "email")),
        ("ZIP_CD", None, ["100-0001"] * 10, ("auto", "postal")),
        ("JUSHO1", "住所1", ["東京都千代田区丸の内1-1-1"] * 10, ("auto", "address")),
        ("MY_NO", "個人番号", ["123456789018"] * 10, ("auto", "my_number")),
        ("CARD_NO", None, ["4111111111111111"] * 10, ("auto", "card")),
        ("BIKO", "備考", ["山田様より電話 090-1234-5678", "なし"] * 5, ("auto", "free_text")),
        # 人が判断するもの
        ("SHAIN_NO", "社員番号", ["E0001"] * 10, ("review", "personal_id")),
        ("SEIBETSU", "性別", ["1", "2"] * 5, ("review", "gender")),
        ("NAME", None, ["A定食", "B定食"] * 5, ("review", "name")),
        ("BIKO", "備考", ["特になし", "来店予定"] * 5, ("review", "free_text")),
        # 対象外
        ("TEL_KBN", "電話区分", ["1", "2"] * 5, (None, None)),
        ("MAIL_FLG", "メール配信フラグ", ["0", "1"] * 5, (None, None)),
        ("PRODUCT_NAME", "商品名", ["りんご"] * 10, (None, None)),
        ("会社名", None, ["株式会社テスト"] * 10, (None, None)),
        ("KOZA_SHUBETSU", "口座種別", ["1"] * 10, (None, None)),
    ],
)
def test_analyze_column(name, comment, samples, expected):
    assert level(name, comment, samples=samples) == expected


def test_value_only_detection_without_name():
    assert level("UNKNOWN", samples=["4111111111111111", "5555555555554444"] * 5) == ("auto", "card")


def test_name_contradicted_by_values_goes_to_review():
    assert level("TEL", "電話", samples=[str(i) for i in range(20)]) == ("review", "phone")


def test_primary_key_is_never_auto():
    assert level("MAIL", "メールアドレス", samples=["a@example.com"] * 10, is_pk=True)[0] == "review"


def test_date_column_birth():
    assert level("BIRTH_DT", "生年月日", "DATE", [dt.date(1985, 4, 1)] * 10) == ("auto", "birth_date")
    assert level("INS_DATE", "登録日", "DATE", [dt.date(2024, 4, 1)] * 10) == (None, None)


def test_check_digits():
    assert is_valid_my_number("123456789018")
    assert not is_valid_my_number("123456789012")
    assert is_valid_luhn("4111111111111111")
    assert not is_valid_luhn("4111111111111112")


def test_person_name_score():
    assert person_name_score("山田 太郎") == 1.0
    assert person_name_score("鈴木") > 0.5
    assert person_name_score("株式会社山田") == 0.0


def spans(text):
    return [(m.level, m.category, text[m.start : m.end]) for m in find_pii(text)]


def test_find_pii_label_values():
    text = "氏名：佐藤 花子　生年月日：1985/04/01　メール：hanako@example.jp"
    assert spans(text) == [
        ("auto", "name", "佐藤 花子"),
        ("auto", "birth_date", "1985/04/01"),
        ("auto", "email", "hanako@example.jp"),
    ]


def test_find_pii_value_ends_at_bracket():
    assert spans("担当者：高橋 健太（内線 1234）") == [("auto", "name", "高橋 健太")]


def test_find_pii_mixed_sentence():
    text = "お客様の山田太郎様（TEL: 03-1234-5678）より、〒100-0001 東京都千代田区千代田1-1 へ送付"
    found = spans(text)
    assert ("auto", "name", "山田太郎") in found
    assert ("auto", "phone", "03-1234-5678") in found
    assert ("auto", "postal", "〒100-0001") in found
    assert ("auto", "address", "東京都千代田区千代田1-1") in found


def test_find_pii_review_and_exclusions():
    assert spans("皆様へ。ご担当者様各位") == []
    assert spans("担当：営業部") == []
    assert spans("受付番号 123-4567") == [("review", "postal", "123-4567")]
    assert spans("マイナンバー 1234 5678 9018") == [("auto", "my_number", "1234 5678 9018")]
