"""個人情報のカテゴリ定義と、値の形式チェック。

自動判定（detector.py）と文中検出（textscan.py）の両方から参照する。
各カテゴリは「既定のマスキング規則」「列名・論理名のパターン」「値の形式チェック」を持つ。
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable

# ---------------------------------------------------------------------------
# 値の形式チェック（戻り値は 0〜1 の確からしさ）
# ---------------------------------------------------------------------------

PREFECTURES = (
    "北海道 青森県 岩手県 宮城県 秋田県 山形県 福島県 茨城県 栃木県 群馬県 埼玉県 千葉県 東京都 神奈川県 "
    "新潟県 富山県 石川県 福井県 山梨県 長野県 岐阜県 静岡県 愛知県 三重県 滋賀県 京都府 大阪府 兵庫県 "
    "奈良県 和歌山県 鳥取県 島根県 岡山県 広島県 山口県 徳島県 香川県 愛媛県 高知県 福岡県 佐賀県 長崎県 "
    "熊本県 大分県 宮崎県 鹿児島県 沖縄県"
).split()
PREFECTURE_RE = "(?:" + "|".join(PREFECTURES) + ")"

# 日本で多い姓（上位約 200）。氏名らしさの判定にのみ使用する。
SURNAMES = frozenset(
    """
    佐藤 鈴木 高橋 田中 伊藤 渡辺 渡邊 渡邉 山本 中村 小林 加藤 吉田 山田 佐々木 山口 松本 井上 木村 林 斎藤 斉藤
    齋藤 清水 山崎 森 池田 橋本 阿部 石川 山下 中島 石井 小川 前田 岡田 長谷川 藤田 後藤 近藤 村上 遠藤 青木
    坂本 斉木 福田 太田 西村 藤井 金子 岡本 藤原 中野 三浦 原田 中川 松田 竹内 小野 田村 中山 和田 石田 森田
    上田 原 内田 柴田 酒井 宮崎 横山 高木 安藤 宮本 大野 小島 谷口 今井 工藤 高田 増田 丸山 杉山 村田 大塚
    新井 小山 平野 藤本 河野 上野 野口 武田 松井 千葉 岩崎 菅原 木下 久保 佐野 野村 松尾 市川 菊地 杉本 古川
    大西 島田 水野 桜井 高野 渡部 吉川 山内 西田 飯田 菊池 西川 小松 北村 安田 五十嵐 川口 平田 関 中田 久保田
    服部 東 岩田 土屋 川崎 福島 本田 辻 樋口 秋山 田口 永井 山中 中西 吉村 川上 石原 大橋 松岡 馬場 浅野 荒木
    大久保 野田 小沢 小澤 田辺 川村 星野 黒田 堀 尾崎 望月 永田 熊谷 内藤 松村 西山 大谷 平井 大島 岩本 片山
    本間 早川 横田 岡崎 荒井 大石 鎌田 成田 宮田 小田 石橋 篠原 須藤 河合 萩原 高山 大森 小池 吉岡 宮下 富田
    稲垣 大川 中井 志村 佐久間 今村 松下 堀内 西 南 北 浜田 濱田 吉野 内山 桑原 堤 長田 奥村 浅井 広瀬 廣瀬
    """.split()
)

_KANJI = r"[一-鿿㐀-䶿豈-﫿々〆ヶ]"
_KATAKANA = r"[ァ-ヴー]"
_HIRAGANA = r"[ぁ-ゖー]"
_KANJI_NAME = re.compile(rf"^({_KANJI}{{1,4}})[ 　]+({_KANJI}{{1,4}})$")
_KANJI_NAME_NOSPACE = re.compile(rf"^{_KANJI}{{2,5}}$")
_KANA_NAME = re.compile(rf"^{_KATAKANA}{{1,8}}[ 　]+{_KATAKANA}{{1,8}}$")
_HIRA_NAME = re.compile(rf"^{_HIRAGANA}{{1,8}}[ 　]+{_HIRAGANA}{{1,8}}$")
_ROMAN_NAME = re.compile(r"^[A-Z][a-z]+ [A-Z][a-z]+$|^[A-Z]+ [A-Z]+$")
# 組織名・施設名などは氏名ではない
_NOT_PERSON = re.compile(
    r"株式会社|有限会社|合同会社|[(（]株[)）]|㈱|㈲|会社|銀行|支店|営業所|事業所|センター|病院|医院|クリニック|学校|大学|"
    r"協会|組合|財団|法人|省|庁|役所|役場|店|部|課|室|係|グループ|チーム|工場|倉庫|ビル|マンション"
)

_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+$")
_PHONE_SEP = re.compile(r"[\s\-‐－−ー()（）]")
_POSTAL_HYPHEN = re.compile(r"^〒?\s*\d{3}[-‐－−ー]\d{4}$")
_POSTAL_PLAIN = re.compile(r"^〒?\s*\d{7}$")
_IPV4 = re.compile(r"^(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)$")
_ADDRESS_BODY = re.compile(r"^.{1,8}?[市区町村郡].*?(\d|丁目|番地|番|号)")
_DATE_TEXT = re.compile(
    r"^(\d{4})[/\-.年](\d{1,2})[/\-.月](\d{1,2})日?(?:[ T].*)?$|^(\d{4})(\d{2})(\d{2})$"
)
_WAREKI = re.compile(r"^(明治|大正|昭和|平成|令和|[MTSHR])\s*(\d{1,2}|元)\s*[年./\-]")


def normalize(value: Any) -> str:
    """判定用に文字列化し、全角英数字を半角にそろえる（NFKC）。"""
    if value is None:
        return ""
    if isinstance(value, dt.datetime):
        return value.strftime("%Y/%m/%d %H:%M:%S")
    if isinstance(value, dt.date):
        return value.strftime("%Y/%m/%d")
    if isinstance(value, (bytes, bytearray, memoryview)):
        return ""
    return unicodedata.normalize("NFKC", str(value)).strip()


def digits_only(text: str) -> str:
    return "".join(c for c in text if c.isdigit())


def is_valid_my_number(digits: str) -> bool:
    """個人番号（12 桁）のチェックデジットを検証する。"""
    if len(digits) != 12 or not digits.isdigit() or len(set(digits)) == 1:
        return False
    body = [int(c) for c in digits[:11]]
    # P_n: 検査用数字の 1 つ左から数えて n 桁目、Q_n: n<=6 なら n+1、それ以外は n-5
    total = sum(p * (n + 1 if n <= 6 else n - 5) for n, p in enumerate(reversed(body), start=1))
    rem = total % 11
    check = 0 if rem <= 1 else 11 - rem
    return check == int(digits[11])


def is_valid_luhn(digits: str) -> bool:
    """クレジットカード番号のチェックデジット（Luhn）を検証する。"""
    if not 13 <= len(digits) <= 19 or not digits.isdigit() or len(set(digits)) == 1:
        return False
    total = 0
    for i, c in enumerate(reversed(digits)):
        d = int(c)
        if i % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def check_email(text: str) -> float:
    return 1.0 if _EMAIL.match(text) else 0.0


def check_phone(text: str) -> float:
    """日本の電話番号（固定 10 桁・携帯 11 桁・+81 形式）。"""
    if not re.fullmatch(r"[\d\s\-‐－−ー()（）+]+", text):
        return 0.0
    d = digits_only(text)
    if d.startswith("81") and text.lstrip().startswith("+"):
        d = "0" + d[2:]
    if not d.startswith("0") or d.startswith("00") or len(d) not in (10, 11):
        return 0.0
    if len(d) == 11 and not re.match(r"0[5789]0", d):
        return 0.3
    # 区切りがある方が電話番号らしい（区切りなしは注文番号等の可能性）
    return 1.0 if _PHONE_SEP.search(text) else 0.7


def check_postal(text: str) -> float:
    if _POSTAL_HYPHEN.match(text):
        return 1.0
    if _POSTAL_PLAIN.match(text):
        return 0.4
    return 0.0


def check_my_number(text: str) -> float:
    if not re.fullmatch(r"\d{4}[\s\-]?\d{4}[\s\-]?\d{4}", text):
        return 0.0
    return 1.0 if is_valid_my_number(digits_only(text)) else 0.0


def check_card(text: str) -> float:
    if not re.fullmatch(r"[\d\s\-]{13,23}", text):
        return 0.0
    return 1.0 if is_valid_luhn(digits_only(text)) else 0.0


def check_address(text: str) -> float:
    text = re.sub(r"^〒?\s*\d{3}-?\d{4}\s*", "", text)
    if re.match(PREFECTURE_RE, text):
        return 1.0 if len(text) > 4 else 0.3
    if _ADDRESS_BODY.match(text):
        return 0.6
    return 0.0


def person_name_score(text: str) -> float:
    """氏名らしさ。姓の辞典・文字種・区切り（空白）から推定する。"""
    if not text or len(text) > 20 or _NOT_PERSON.search(text):
        return 0.0
    m = _KANJI_NAME.match(text)
    if m:
        return 1.0 if m.group(1) in SURNAMES else 0.6
    if text in SURNAMES:
        return 0.6
    if _KANJI_NAME_NOSPACE.match(text):
        for n in (3, 2, 1):
            if text[:n] in SURNAMES and len(text) - n >= 1:
                return 0.7
        return 0.0
    if _KANA_NAME.match(text) or _HIRA_NAME.match(text):
        return 0.8
    if _ROMAN_NAME.match(text):
        return 0.4
    return 0.0


def is_organization(text: str) -> bool:
    """会社・部署・施設など、人以外の名称か。"""
    return bool(_NOT_PERSON.search(text))


def check_ipv4(text: str) -> float:
    return 1.0 if _IPV4.match(text) else 0.0


def is_date_like(value: Any) -> bool:
    if isinstance(value, (dt.date, dt.datetime)):
        return True
    text = normalize(value)
    return bool(_DATE_TEXT.match(text) or _WAREKI.match(text))


def check_birth_date(value: Any) -> float:
    """日付であり、かつ生年月日として妥当な範囲（1900 年〜現在）か。"""
    if isinstance(value, (dt.date, dt.datetime)):
        year = value.year
    else:
        text = normalize(value)
        if _WAREKI.match(text):
            return 1.0
        m = _DATE_TEXT.match(text)
        if not m:
            return 0.0
        year = int(m.group(1) or m.group(4))
    return 1.0 if 1900 <= year <= dt.date.today().year else 0.0


# ---------------------------------------------------------------------------
# カテゴリ定義
# ---------------------------------------------------------------------------

# 列名（物理名）のパターンは「単語の区切り」で判定するため、
# CamelCase を SNAKE_CASE に変換したうえで大文字にして照合する。
B = r"(?:^|_)"
E = r"(?=_|$|\d)"


@dataclass(frozen=True)
class Category:
    code: str
    label: str
    rule: str
    params: dict[str, Any] = field(default_factory=dict)
    # 論理名（コメント）・日本語の列名に対するパターン
    jp_strong: str | None = None
    jp_weak: str | None = None
    # 物理名に対するパターン
    col_strong: str | None = None
    col_weak: str | None = None
    # 値の形式チェックと、その根拠の強さ（値だけで判断できる度合い）
    value_check: Callable[[Any], float] | None = None
    value_weight: float = 0.0
    # 文字列でのみ格納されるはずのカテゴリ（数値型・日付型の列なら可能性が低い）
    text_only: bool = True
    # 業務判断が必要なため、自動ではマスクせず常に「要確認」とする
    review_only: bool = False
    # 「_CD」「区分」など、区分値を示す語による減点の対象外
    allow_code_words: bool = False
    description: str = ""


CATEGORIES: list[Category] = [
    Category(
        "password", "パスワード・暗証番号", "null",
        jp_strong=r"パスワード|暗証|セキュリティコード|秘密の質問",
        col_strong=rf"{B}(PASSWORD|PASSWD|PWD|PASS_?WORD|PASSCODE|PIN_?(CODE|NO)?|ANSHO_?(NO|BANGO)?|CVV|CVC|SECURITY_?CODE|SECRET){E}",
        description="ハッシュ値であっても出力しない（空欄）",
    ),
    Category(
        "my_number", "マイナンバー（個人番号）", "full",
        jp_strong=r"マイナンバー|個人番号|マイナ番号",
        col_strong=rf"{B}(MY_?NUMBER|MY_?NO|MYNO|KOJIN_?(NO|BANGO|NUM))",
        value_check=lambda v: check_my_number(normalize(v)), value_weight=0.85, text_only=False,
    ),
    Category(
        "id_document", "公的な証明書番号（免許証・旅券・保険証等）", "full",
        jp_strong=r"免許証|運転免許|旅券|パスポート|保険証|被保険者(番号|記号)|基礎年金|年金番号|在留カード|住民票コード|健康保険|保険者番号",
        col_strong=rf"{B}(LICENSE|LICENCE|DRIVER_?LICEN[CS]E|PASSPORT|MENKYO|HOKEN_?(NO|SHO|BANGO|KIGO)|HIHOKEN|NENKIN|ZAIRYU|JUMINHYO)",
        text_only=False,
    ),
    Category(
        "card", "クレジットカード番号", "digits", {"keep_head": 0, "keep_tail": 4},
        jp_strong=r"カード番号|クレジット",
        col_strong=rf"{B}(CARD_?(NO|NUM|NUMBER|BANGO)|CREDIT_?(CARD)?|CC_?(NO|NUM)|PAN){E}",
        value_check=lambda v: check_card(normalize(v)), value_weight=0.8, text_only=False,
    ),
    Category(
        "bank_account", "口座番号", "digits", {"keep_head": 0, "keep_tail": 0},
        jp_strong=r"口座番号|預金番号|口座(No|NO|ＮＯ)",
        jp_weak=r"口座",
        col_strong=rf"{B}(KOU?ZA_?(NO|BANGO|NUM)?|BANK_?ACC(OUN)?T(_?(NO|NUM|NUMBER))?|ACC(OUN)?T_?(NO|NUM|NUMBER)|YOKIN_?NO){E}",
        text_only=False,
    ),
    Category(
        "email", "メールアドレス", "email",
        jp_strong=r"メール|ｅメール|Ｅメール|電子メール|mail|MAIL|Mail",
        col_strong=rf"{B}(E_?MAIL|MAIL)(_?(ADDR|ADDRESS|AD|ADR))?{E}|{B}MAILADDR",
        value_check=lambda v: check_email(normalize(v)), value_weight=0.95,
    ),
    Category(
        "phone", "電話番号", "digits", {"keep_head": 0, "keep_tail": 4},
        jp_strong=r"電話|携帯|ＴＥＬ|TEL|Tel|ＦＡＸ|FAX|Fax|ファックス|ファクス",
        jp_weak=r"連絡先",
        col_strong=rf"{B}(TEL|TELNO|PHONE|FAX|DENWA|KEITAI|MOBILE|CELL|CELLPHONE|PHONENO)(_?(NO|NUM|NUMBER|BANGO))?{E}",
        col_weak=rf"{B}(CONTACT|RENRAKUSAKI){E}",
        value_check=lambda v: check_phone(normalize(v)), value_weight=0.8, text_only=False,
    ),
    Category(
        "postal", "郵便番号", "postal",
        jp_strong=r"郵便|〒",
        col_strong=rf"{B}(ZIP|ZIPCODE|POST(AL)?_?(CODE|CD|NO|NUM)|POSTCODE|YUBIN|YUBINNO|YUUBIN)(_?(NO|CD|CODE))?{E}",
        value_check=lambda v: check_postal(normalize(v)), value_weight=0.6, text_only=False, allow_code_words=True,
    ),
    Category(
        "address", "住所", "address",
        jp_strong=r"住所|所在地|居所|番地|送付先|届け?先|配送先|請求先住所|現住所|本籍地",
        jp_weak=r"建物名|マンション名|方書|丁目|町名",
        col_strong=rf"{B}(?<!MAIL_)(?<!IP_)(ADDR|ADDRESS|ADR|JU?USHO|JYUSHO|JUSYO|BANCHI)(\d|_?(1|2|3|KANJI|KANA))?{E}",
        col_weak=rf"{B}(BUILDING|TATEMONO|KATAGAKI|CHOME|STREET){E}",
        value_check=lambda v: check_address(normalize(v)), value_weight=0.8,
    ),
    Category(
        "birth_date", "生年月日", "date_year",
        jp_strong=r"生年月日|誕生日|生年|誕生",
        col_strong=rf"{B}(BIRTH|BIRTHDAY|BIRTH_?DATE|BIRTHDATE|DOB|DATE_OF_BIRTH|SEINENGAPPI|SEINEN|TANJ[OY]U?BI)(_?(DATE|YMD|DT|YYYYMMDD))?{E}",
        value_check=check_birth_date, value_weight=0.0, text_only=False,
    ),
    Category(
        "name", "氏名", "name",
        jp_strong=(
            r"氏名|姓名|名前|フルネーム|フリガナ|ふりがな|カナ氏名|宛名|名義|^姓$|^名$|^姓[（(]|^名[（(]|^氏$|"
            r"(顧客|会員|社員|従業員|職員|担当者|契約者|患者|利用者|申込者|申請者|代表者|保護者|受取人|被保険者|"
            r"学生|生徒|児童|本人|家族|配偶者|応募者|入居者|購入者|注文者|加入者|受診者|請求者|依頼者|相談者|"
            r"送付先|届け?先|配送先|請求先|連絡先|緊急連絡先|紹介者|保証人|世帯主|入力者|作成者|承認者|"
            r"ユーザー?|ユーザ)(名|氏名|の氏名|カナ|名カナ)"
        ),
        jp_weak=r"名$|名[（(]|名称$|ネーム",
        col_strong=(
            rf"{B}(SHIMEI|SIMEI|SEIMEI|FULL_?NAME|FIRST_?NAME|LAST_?NAME|GIVEN_?NAME|FAMILY_?NAME|MIDDLE_?NAME|SURNAME|"
            r"MEIGI|ATENA|FURIGANA)|"
            rf"{B}(SEI|MEI)(_?(KANJI|KANA|KN|KJ))?{E}|"
            rf"{B}(CUST|CUSTOMER|KOKYAKU|KOKYAKU_?SHA|MEMBER|KAIIN|USER|EMP|EMPLOYEE|SHAIN|STAFF|TANTO|TANTOSHA|"
            r"KEIYAKU|KEIYAKUSHA|KANJA|PATIENT|PERSON|CONTACT|APPLICANT|MOSHIKOMI|UKETORI|DAIHYO|HOGOSHA|STUDENT|SEITO|"
            rf"RECIPIENT|RECEIVER|SENDER|BUYER|ORDERER|ACCOUNT_?HOLDER){B}?(NAME|NM|MEI|SHIMEI)(_?(KANJI|KANA|KN|KJ))?{E}|"
            rf"{B}(NAME|NM)_?(KANJI|KANA|KN|KJ){E}|{B}KANA_?(NAME|NM|SHIMEI){E}"
        ),
        col_weak=rf"{B}(NAME|NM|SHIMEI_?\w*){E}",
        value_check=lambda v: person_name_score(normalize(v)), value_weight=0.6,
    ),
    Category(
        "sensitive", "要配慮個人情報（病歴・国籍等）", "full",
        jp_strong=r"病歴|病名|既往|診断|傷病|障害|障がい|国籍|本籍|人種|信条|宗教|犯罪|前科|健康状態|服薬|妊娠|血液型|身体|アレルギー",
        col_strong=rf"{B}(DISEASE|DIAGNOSIS|ILLNESS|MEDICAL|NATIONALITY|KOKUSEKI|HONSEKI|RELIGION|CRIMINAL|BLOOD_?TYPE|ALLERGY|DISABILITY|BYOMEI|SHINDAN){E}",
        text_only=False,
    ),
    Category(
        "personal_id", "個人を識別するID（顧客番号・社員番号等）", "hash", {"length": 16},
        jp_strong=r"(顧客|会員|社員|従業員|職員|患者|利用者|学籍|受験|被保険者|契約者|カルテ)(番号|ID|ＩＤ|コード|No|NO|ＮＯ)|ログインID|ログインＩＤ|ユーザーID|ユーザＩＤ|アカウント",
        col_strong=rf"{B}(CUST|CUSTOMER|KOKYAKU|MEMBER|KAIIN|USER|EMP|EMPLOYEE|SHAIN|STAFF|PATIENT|KANJA|LOGIN|ACCOUNT|KEIYAKUSHA|STUDENT|GAKUSEKI|KARTE)_?(ID|NO|CD|CODE|NUM|BANGO){E}",
        text_only=False, review_only=True, allow_code_words=True,
        description="他表との突合せキーの可能性があるため、マスクするかは人が判断する",
    ),
    Category(
        "gender", "性別", "full",
        jp_strong=r"性別", col_strong=rf"{B}(SEX|GENDER|SEIBETSU|SEIBETU){E}",
        text_only=False, review_only=True, allow_code_words=True,
    ),
    Category(
        "age", "年齢", "round_number", {"digits": -1},
        jp_strong=r"年齢|年令", col_strong=rf"{B}(AGE|NENREI){E}",
        text_only=False, review_only=True,
    ),
    Category(
        "income", "年収・給与等", "round_number", {"digits": -3},
        jp_strong=r"年収|月収|給与|給料|賞与|ボーナス|収入|所得|報酬|手当|資産|預金残高|借入",
        col_strong=rf"{B}(SALARY|INCOME|NENSHU|GESSHU|KYUYO|WAGE|BONUS|SHOTOKU|SHUNYU|ASSET|BALANCE|ZANDAKA){E}",
        text_only=False, review_only=True,
    ),
    Category(
        "ip_address", "IPアドレス", "full",
        jp_strong=r"IPアドレス|ＩＰアドレス|接続元",
        col_strong=rf"{B}(IP|IP_?ADDR|IP_?ADDRESS|IPADDR|REMOTE_?ADDR|CLIENT_?IP|SOURCE_?IP|SRC_?IP){E}",
        value_check=lambda v: check_ipv4(normalize(v)), value_weight=0.5, review_only=True,
    ),
    Category(
        "free_text", "自由記述（備考・メモ等）", "text_pii",
        jp_strong=r"備考|メモ|コメント|自由記述|自由記入|特記事項|摘要|問い?合わ?せ内容|ご?意見|ご?要望|本文|連絡事項|申し送り|相談内容|対応内容|経過|所見",
        jp_weak=r"内容|詳細|説明|理由",
        col_strong=rf"{B}(BIKO|BIKOU|MEMO|NOTE|NOTES|REMARK|REMARKS|COMMENT|COMMENTS|TEKIYO|TEKIYOU|FREE_?TEXT|INQUIRY|MESSAGE|BODY){E}",
        col_weak=rf"{B}(CONTENT|CONTENTS|NAIYO|NAIYOU|DESCRIPTION|DESC|DETAIL|DETAILS|SHOSAI|REASON|RIYU){E}",
        review_only=True,
        description="文中に含まれる氏名・電話番号等のみをマスクする",
    ),
]

CATEGORY_BY_CODE: dict[str, Category] = {c.code: c for c in CATEGORIES}

# 区分値・フラグ・件数などを示す語。列名に含まれる場合は個人情報そのものではない可能性が高い。
CODE_WORDS_JP = re.compile(r"区分|フラグ|コード|種別|有無|件数|状態|ステータス|方法|種類|形式|可否|希望|設定|回数|桁数|変更日|更新日|登録日|確認日|送信日|配信")
CODE_WORDS_COL = re.compile(rf"{B}(KBN|KUBUN|FLG|FLAG|CD|CODE|TYPE|TYP|CNT|COUNT|STATUS|STS|KIND|SHUBETSU|UMU|CHECK|CHK|VERIFIED|OPTIN|OPT_IN){E}")

# 「〇〇名」のうち、人以外を表すもの（氏名の弱い根拠から除外する）
NOT_PERSON_NAME_JP = re.compile(
    r"(会社|法人|企業|商品|品|製品|店|店舗|部署|部門|部|課|支店|支社|銀行|金融機関|業者|メーカー|ファイル|画面|テーブル|列|項目|帳票|"
    r"システム|プログラム|機能|サービス|プラン|コース|建物|物件|マンション|地名|町名|市区町村|都道府県|国|駅|学校|病院|施設|"
    r"拠点|事業所|団体|組織|役職|職種|科目|カテゴリ|分類|区分|種別|件|タイトル|題|名称|イベント|キャンペーン|プロジェクト|案件|"
    r"ブランド|ドメイン|ホスト|サーバ|DB|スキーマ|ジョブ|処理|帳|書類|資格|学部|学科|園|団地|路線|港|空港|系統|色|型|機種|端末|"
    r"アプリ|ツール|メニュー|ボタン|ラベル|シート|ブック|フォルダ|パス|キー|ロール|権限|グループ|チーム|班|クラス|ランク|通貨|単位|曜日)"
    r"(名|名称|名[（(].*)?$"
)
NOT_PERSON_NAME_COL = re.compile(
    rf"{B}(ITEM|PROD|PRODUCT|SHOHIN|GOODS|COMPANY|KAISHA|CORP|CORPORATION|SHOP|TENPO|STORE|DEPT|DEPARTMENT|BUSHO|BRANCH|SHITEN|"
    r"BANK|GINKO|FILE|TABLE|TBL|COLUMN|COL|SCREEN|GAMEN|SYSTEM|SYS|SERVICE|PLAN|COURSE|CATEGORY|CTGRY|CLASS|TYPE|KBN|BUILDING|"
    r"TATEMONO|CITY|PREF|TOWN|STATION|EKI|SCHOOL|HOSPITAL|ORG|GROUP|GRP|ROLE|TITLE|MAKER|VENDOR|SUPPLIER|TORIHIKISAKI|APP|JOB|"
    r"HOST|DB|SCHEMA|EVENT|CAMPAIGN|PROJECT|PJ|BRAND|DOMAIN|SERVER|PROC|PROGRAM|PGM|MENU|SHEET|FOLDER|DIR|PATH|KEY|TEAM|"
    rf"RANK|UNIT|CURRENCY|COLOR|MODEL|DEVICE|TAG|LABEL|FIELD|ATTR|PARAM|MODULE|REPORT|CHOHYO|KAMOKU|SHIKAKU|RIYU|SHIHARAI){B}?"
)


def category_list() -> list[dict[str, Any]]:
    """画面表示用のカテゴリ一覧。"""
    return [
        {
            "code": c.code,
            "label": c.label,
            "rule": {"type": c.rule, "params": dict(c.params)},
            "review_only": c.review_only,
            "description": c.description,
        }
        for c in CATEGORIES
    ]
