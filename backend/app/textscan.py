"""文章中に含まれる個人情報の検出。

ドキュメント（テキスト・Markdown・Excel の表以外の部分）や、DB の備考欄などの自由記述に使う。
「氏名：山田太郎」のような項目名と値の組、敬称付きの氏名（山田様）、電話番号・メールアドレス等の
形式から検出し、確からしさに応じて「自動（auto）」と「要確認（review）」に分ける。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .categories import (
    PREFECTURE_RE,
    SURNAMES,
    digits_only,
    is_organization,
    is_valid_luhn,
    is_valid_my_number,
    person_name_score,
)

AUTO_THRESHOLD = 0.7
REVIEW_THRESHOLD = 0.35


@dataclass(frozen=True)
class TextMatch:
    start: int
    end: int
    category: str
    score: float
    reason: str

    @property
    def level(self) -> str:
        return "auto" if self.score >= AUTO_THRESHOLD else "review"


_D = r"[0-9０-９]"
_SEP = r"[-‐－−ー]"
_KANJI = r"[一-鿿㐀-䶿豈-﫿々〆ヶ]"

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
# 区切り付きの電話番号（03-1234-5678 / 090-1234-5678 / (03)1234-5678 / +81-3-1234-5678）
_PHONE = re.compile(
    rf"(?<![0-9０-９\-])(?:(?:\+81|＋８１)[\s\-]?{_D}{{1,4}}|[0０]{_D}{{1,4}}|[(（][0０]{_D}{{1,4}}[)）])"
    rf"(?:{_SEP}|\s|(?<=[)）]))?{_D}{{1,4}}{_SEP}{_D}{{3,4}}(?![0-9０-９])"
)
# 区切りなしの電話番号（0312345678 / 09012345678）
_PHONE_PLAIN = re.compile(rf"(?<![0-9０-９])[0０]{_D}{{9,10}}(?![0-9０-９])")
_PHONE_CONTEXT = re.compile(r"(TEL|Tel|tel|ＴＥＬ|電話|携帯|FAX|Fax|ＦＡＸ|☎|℡|連絡先)[\s:：.]*$")
_POSTAL_MARK = re.compile(rf"〒\s*{_D}{{3}}{_SEP}?{_D}{{4}}(?![0-9０-９])")
_POSTAL = re.compile(rf"(?<![0-9０-９\-])({_D}{{3}}){_SEP}({_D}{{4}})(?![0-9０-９\-])")
_DIGIT_RUN = re.compile(rf"(?<![0-9０-９])(?:{_D}[\s\-]?){{11,18}}{_D}(?![0-9０-９])")
_ADDRESS = re.compile(
    rf"{PREFECTURE_RE}[^\s、。,，「」『』()（）<>【】|｜]{{1,8}}?[市区町村郡]"
    r"[^\s、。,，「」『』()（）<>【】|｜]*"
)
_ADDRESS_NO_PREF = re.compile(
    rf"(?<!{_KANJI}){_KANJI}{{1,4}}[市区](?:{_KANJI}|[ぁ-んァ-ヶ]){{1,8}}{_D}{{1,4}}(?:{_SEP}|丁目){_D}{{1,4}}"
    r"[^\s、。,，「」『』()（）<>【】|｜]*"
)
_HONORIFIC = re.compile(
    rf"(?<!{_KANJI})({_KANJI}{{1,4}}(?:[ 　]{_KANJI}{{1,4}})?)[ 　]?(様|さま|殿|さん|くん|君|氏|先生)(?![式子相々方])"
)
_HONORIFIC_KANA = re.compile(r"(?<![ァ-ヴー])([ァ-ヴー]{2,8}(?:[ 　][ァ-ヴー]{2,8})?)[ 　]?(様|さま|さん)")
_FULLNAME_SPACED = re.compile(rf"(?<!{_KANJI})({_KANJI}{{1,3}})[ 　]({_KANJI}{{1,3}})(?!{_KANJI})")
# 敬称の前にあっても氏名ではない語
_NOT_NAME_BEFORE_HONORIFIC = re.compile(
    r"(客|皆|各|奥|神|王|仏|殿|同|貴|御|お|ご|者|員|長|方|位|家|人|主|先|生|師|士|嬢|子供|社|店|局|部|課|係|会|様|"
    r"担当|先方|当方|弊社|御社|貴社|両親|父|母|兄|姉|弟|妹|夫|妻|息子|娘|孫|祖父|祖母|皆様|各位|関係|来場|参加|利用|"
    r"年|月|日|時|分|円|件|名|個|回|本|枚|台|点|号|番|丁目|〇|○|×|●|◯|＊|\*)$"
)

# 項目名と値の組（氏名：山田太郎、TEL 03-1234-5678 など）。値は同じ行の区切りまで。
_LABELS: list[tuple[str, str]] = [
    (r"氏名|お名前|名前|姓名|フルネーム|宛名|名義(人)?|契約者名?|申込者名?|患者名|顧客名|会員名|社員名", "name"),
    (r"フリガナ|ふりがな|カナ氏名|氏名カナ|氏名（カナ）|氏名\(カナ\)", "name"),
    (r"担当者?名?|作成者|承認者|連絡者|依頼者", "name"),
    (r"住所|ご住所|現住所|所在地|送付先|お届け先|届け先|配送先|請求先住所", "address"),
    (r"電話番号|電話|携帯番号|携帯電話|携帯|TEL|Tel|ＴＥＬ|FAX|Fax|ＦＡＸ|連絡先", "phone"),
    (r"メールアドレス|メール|E-?mail|e-?mail|Ｅメール|mail", "email"),
    (r"生年月日|誕生日", "birth_date"),
    (r"郵便番号|〒", "postal"),
    (r"マイナンバー|個人番号", "my_number"),
    (r"口座番号", "bank_account"),
    (r"カード番号|クレジットカード番号", "card"),
    (r"パスワード|暗証番号|PW|Password|password", "password"),
    (r"(顧客|会員|社員|従業員|患者|利用者)(番号|ID|ＩＤ|コード)|ログインID|ユーザーID", "personal_id"),
]
_LABEL_VALUE = re.compile(
    r"(?:^|(?<=[\s　|｜,，、。(（\[【]))(?P<label>"
    + "|".join(f"(?:{p})" for p, _ in _LABELS)
    + r")[ \t　]*(?:[:：｜|=＝]|(?<=TEL|Tel|FAX|Fax)[ .　])[ \t　]*"
    # 値は行末・区切り記号・閉じ括弧、または次の「項目名：」の手前まで
    r"(?P<value>[^\r\n\t｜|,，、。()（）「」『』【】\[\]]+?)"
    r"(?=[ \t　]+[^\s:：｜|]{1,12}[:：]|[ \t　]*(?:[\r\n\t｜|,，、。()（）「」『』【】\[\]]|$))"
)
_LABEL_CATEGORY = [(re.compile(rf"^(?:{p})$"), c) for p, c in _LABELS]


def _label_category(label: str) -> str | None:
    for pattern, code in _LABEL_CATEGORY:
        if pattern.match(label):
            return code
    return None


def _value_span(m: re.Match[str]) -> tuple[int, int]:
    """値の前後の空白・末尾の敬称を除いた範囲を返す。"""
    start, end = m.span("value")
    text = m.group("value")
    stripped_left = len(text) - len(text.lstrip(" 　"))
    text = text.strip(" 　")
    start += stripped_left
    end = start + len(text)
    for suffix in ("様", "さま", "殿", "さん"):
        if text.endswith(suffix) and len(text) > len(suffix):
            end -= len(suffix)
            break
    return start, end


def _candidates(text: str) -> list[TextMatch]:
    found: list[TextMatch] = []
    add = found.append

    for m in _LABEL_VALUE.finditer(text):
        code = _label_category(m.group("label"))
        if code is None:
            continue
        start, end = _value_span(m)
        if end <= start:
            continue
        value = text[start:end]
        # 「担当：営業部」など、項目名からは人か判断できないものは値で判断する
        if code == "name" and is_organization(value):
            continue
        if m.group("label").startswith(("担当", "作成者", "承認者", "連絡者", "依頼者")):
            score = 0.8 if person_name_score(value) >= 0.6 else 0.45
        elif code == "name" and person_name_score(value) == 0 and re.search(r"[0-9０-９@]", value):
            score = 0.45
        else:
            score = 0.85
        add(TextMatch(start, end, code, score, f"項目名「{m.group('label')}」の値"))

    for m in _EMAIL.finditer(text):
        add(TextMatch(m.start(), m.end(), "email", 0.95, "メールアドレスの形式"))

    for m in _POSTAL_MARK.finditer(text):
        add(TextMatch(m.start(), m.end(), "postal", 0.9, "〒付きの郵便番号"))

    for m in _PHONE.finditer(text):
        d = digits_only(m.group())
        if d.startswith("81"):
            d = "0" + d[2:]
        if len(d) in (10, 11):
            add(TextMatch(m.start(), m.end(), "phone", 0.85, "電話番号の形式"))

    for m in _PHONE_PLAIN.finditer(text):
        context = _PHONE_CONTEXT.search(text[max(0, m.start() - 8) : m.start()])
        if context:
            add(TextMatch(m.start(), m.end(), "phone", 0.85, f"「{context.group(1)}」に続く番号"))
        else:
            add(TextMatch(m.start(), m.end(), "phone", 0.45, "電話番号の可能性がある 10〜11 桁の数字"))

    for m in _DIGIT_RUN.finditer(text):
        d = digits_only(m.group())
        if len(d) == 12 and is_valid_my_number(d):
            add(TextMatch(m.start(), m.end(), "my_number", 0.9, "マイナンバーの形式（検査用数字が一致）"))
        elif is_valid_luhn(d) and 14 <= len(d) <= 16:
            add(TextMatch(m.start(), m.end(), "card", 0.8, "カード番号の形式（Luhn 検査が一致）"))

    for m in _POSTAL.finditer(text):
        add(TextMatch(m.start(), m.end(), "postal", 0.45, "郵便番号の可能性がある「3桁-4桁」の数字"))

    for m in _ADDRESS.finditer(text):
        has_number = re.search(r"[0-9０-９]|丁目|番地|[一二三四五六七八九十]+番", m.group())
        if has_number:
            add(TextMatch(m.start(), m.end(), "address", 0.85, "都道府県から始まる番地付きの住所"))
        else:
            add(TextMatch(m.start(), m.end(), "address", 0.4, "都道府県・市区町村名（番地なし）"))

    for m in _ADDRESS_NO_PREF.finditer(text):
        add(TextMatch(m.start(), m.end(), "address", 0.55, "市区名から始まる番地付きの住所"))

    for m in _HONORIFIC.finditer(text):
        name = m.group(1)
        if _NOT_NAME_BEFORE_HONORIFIC.search(name) or len(name.replace(" ", "").replace("　", "")) < 1:
            continue
        surname = re.split(r"[ 　]", name)[0]
        known = any(surname[:n] in SURNAMES for n in (3, 2, 1) if len(surname) >= n)
        if known:
            add(TextMatch(m.start(1), m.end(1), "name", 0.8, f"敬称「{m.group(2)}」付きの氏名（よくある姓）"))
        else:
            add(TextMatch(m.start(1), m.end(1), "name", 0.5, f"敬称「{m.group(2)}」の前の語"))

    for m in _HONORIFIC_KANA.finditer(text):
        add(TextMatch(m.start(1), m.end(1), "name", 0.5, f"敬称「{m.group(2)}」付きのカタカナ"))

    for m in _FULLNAME_SPACED.finditer(text):
        if m.group(1) in SURNAMES:
            add(TextMatch(m.start(), m.end(), "name", 0.55, "よくある姓＋空白＋名の並び"))

    return found


def find_pii(text: str, min_score: float = REVIEW_THRESHOLD) -> list[TextMatch]:
    """文章中の個人情報を検出する。重なりは確からしさの高いもの（同点なら長いもの）を優先する。"""
    if not text or len(text) < 2:
        return []
    cands = [c for c in _candidates(text) if c.score >= min_score and c.end > c.start]
    cands.sort(key=lambda c: (-c.score, -(c.end - c.start), c.start))
    chosen: list[TextMatch] = []
    for c in cands:
        if all(c.end <= o.start or c.start >= o.end for o in chosen):
            chosen.append(c)
    chosen.sort(key=lambda c: c.start)
    return chosen
