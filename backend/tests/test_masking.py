"""マスキング処理の単体テスト。"""

import datetime as dt
from decimal import Decimal

import pytest

from app.db.base import DbError, validate_fragment
from app.exporter import safe_sheet_name, to_excel_value
from app.masking import build_masker, display_width, suggest_rule
from app.schemas import MaskRule


def m(rule_type: str, value, /, **params):
    fn = build_masker(MaskRule(type=rule_type, params=params), salt="s")
    return fn(value) if fn else value


def test_none_rule_returns_none_masker():
    assert build_masker(MaskRule(type="none")) is None
    assert build_masker(None) is None


def test_null_value_stays_null():
    assert m("full", None) is None
    assert m("name", None) is None


def test_full_keeps_width():
    assert m("full", "山田太郎") == "＊＊＊＊"
    assert m("full", "ABC") == "***"
    assert m("full", "ｱｲｳ") == "***"  # 半角カナは半角
    assert m("full", "abc", char="#") == "###"


def test_partial():
    assert m("partial", "ABC12345", keep_head=1, keep_tail=1) == "A******5"
    assert m("partial", "東京都港区", keep_head=2, keep_tail=0) == "東京＊＊＊"
    # 残す文字数が全長以上でも全て露出しない
    assert m("partial", "AB", keep_head=5) == "A*"


def test_name():
    assert m("name", "山田 太郎") == "山田 ＊＊"
    assert m("name", "ヤマダ　タロウ") == "ヤマダ　＊＊＊"
    assert m("name", "山田太郎") == "山＊＊＊"
    assert m("name", "Taro Yamada") == "Taro ******"


def test_email():
    assert m("email", "taro@example.co.jp") == "t***@example.co.jp"
    assert m("email", "a@b.jp") == "*@b.jp"
    assert m("email", "not-an-email") == "************"


def test_digits_phone_and_card():
    assert m("digits", "03-1234-5678", keep_tail=4) == "**-****-5678"
    assert m("digits", "090(1234)5678", keep_tail=4) == "***(****)5678"
    # 全角数字は全角で伏せる
    assert m("digits", "０３－１２３４－５６７８", keep_tail=4) == "＊＊－＊＊＊＊－５６７８"
    assert m("digits", "4111 1111 1111 1234", keep_tail=4) == "**** **** **** 1234"
    assert m("digits", 312345678, keep_tail=4) == "*****5678"


def test_postal():
    assert m("postal", "123-4567") == "123-****"
    assert m("postal", "〒１００－０００５") == "〒１００－＊＊＊＊"


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ("東京都千代田区丸の内1-1-1", "東京都千代田区＊＊＊＊"),
        ("神奈川県横浜市中区山下町1", "神奈川県横浜市中区＊＊＊＊"),
        ("北海道札幌市北区北8条西5丁目", "北海道札幌市北区＊＊＊＊"),
        ("千葉県市川市八幡1-1", "千葉県市川市＊＊＊＊"),
        ("京都府京都市左京区吉田本町", "京都府京都市左京区＊＊＊＊"),
        ("長野県北佐久郡軽井沢町大字軽井沢", "長野県北佐久郡軽井沢町＊＊＊＊"),
        ("〒100-0005 東京都千代田区丸の内1-1", "〒100-**** 東京都千代田区＊＊＊＊"),
        ("大阪府", "大阪府"),
    ],
)
def test_address(src, expected):
    assert m("address", src) == expected


def test_date_year():
    assert m("date_year", dt.date(1985, 4, 1)) == "1985/**/**"
    assert m("date_year", dt.datetime(1985, 4, 1, 10, 0)) == "1985/**/**"
    # 文字列は区切り・桁数を保つ（列の長さを超えないようにするため）
    assert m("date_year", "１９８５年４月１日") == "１９８５年＊月＊日"
    assert m("date_year", "19850401") == "1985****"
    assert m("date_year", "1985-04-01") == "1985-**-**"
    assert m("date_year", "昭和60年4月1日") == "昭和60年＊＊月＊＊日"


def test_hash_is_deterministic():
    a = m("hash", "山田太郎")
    assert a == m("hash", "山田太郎")
    assert a != m("hash", "山田花子")
    assert len(a) == 16
    other_salt = build_masker(MaskRule(type="hash"), salt="other")("山田太郎")
    assert other_salt != a


def test_fake_name():
    v = m("fake_name", "山田 太郎")
    assert v == m("fake_name", "山田 太郎")
    assert "　" in v
    kana = m("fake_name", "山田 太郎", kind="kana")
    assert all("ァ" <= c <= "ヶ" or c in "ー　" for c in kana)


def test_round_number_and_fixed_and_null():
    assert m("round_number", Decimal("5234567"), digits=-3) == 5235000
    assert m("fixed", "x", value="秘") == "秘"
    assert m("null", "x") is None


def test_unknown_rule_raises():
    with pytest.raises(ValueError):
        build_masker(MaskRule(type="nope"))


@pytest.mark.parametrize(
    ("name", "comment", "expected"),
    [
        ("CUST_NM", "顧客名", "name"),
        ("SHIMEI_KANA", None, "name"),
        ("TEL_NO", None, "digits"),
        ("COL1", "電話番号", "digits"),
        ("MAIL_ADDR", "メールアドレス", "email"),
        ("ZIP_CD", None, "postal"),
        ("JUSHO1", None, "address"),
        ("BIRTH_DT", None, "date_year"),
        ("LOGIN_PWD", None, "null"),
        ("MY_NUMBER", None, "full"),
        ("PRODUCT_NAME", "商品名", None),
        ("UPDATE_DATE", "更新日", None),
    ],
)
def test_suggest_rule(name, comment, expected):
    rule = suggest_rule(name, comment)
    assert (rule.type if rule else None) == expected


def test_display_width():
    assert display_width("ABC") == 3
    assert display_width("日本語") == 6
    assert display_width("ｱｲｳ") == 3


def test_to_excel_value():
    assert to_excel_value(Decimal("123")) == 123
    assert to_excel_value(Decimal("1.5")) == 1.5
    # 15 桁を超える数値は精度維持のため文字列
    assert to_excel_value(Decimal("1234567890123456789")) == "1234567890123456789"
    assert to_excel_value("a\x01b") == "ab"
    tz = dt.datetime(2024, 1, 1, 9, tzinfo=dt.timezone(dt.timedelta(hours=9)))
    assert to_excel_value(tz) == tz.astimezone().replace(tzinfo=None)
    assert to_excel_value(b"\x01\xff") == "01FF"
    assert to_excel_value({"名前": "太郎"}) == '{"名前": "太郎"}'


def test_safe_sheet_name():
    used: set[str] = set()
    assert safe_sheet_name("顧客/マスタ", used) == "顧客_マスタ"
    assert safe_sheet_name("顧客/マスタ", used) == "顧客_マスタ_2"
    assert len(safe_sheet_name("X" * 40, used)) == 31


def test_validate_fragment():
    assert validate_fragment("  STATUS = '1';  ", "WHERE") == "STATUS = '1'"
    assert validate_fragment("NAME = 'a;b'", "WHERE") == "NAME = 'a;b'"
    assert validate_fragment("UPDATE_DATE > SYSDATE - 1", "WHERE") is not None
    assert validate_fragment("", "WHERE") is None
    for bad in ["1=1; DROP TABLE T", "1=1 -- x", "1=1 /* */", "ID IN (DELETE FROM T)"]:
        with pytest.raises(DbError):
            validate_fragment(bad, "WHERE")
