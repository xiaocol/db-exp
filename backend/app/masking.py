"""日本語データ向けのマスキング（脱敏）処理。

方針:
- 全角文字は全角「＊」、半角文字は半角「*」で置換し、見た目の桁数を保つ。
- 電話番号・カード番号などは区切り文字（ハイフン等）を残して数字のみ伏せる。
- 氏名は姓を残し名を伏せる、住所は都道府県＋市区町村まで残す等、
  業務での確認に必要な最低限の情報だけを残す。
- ハッシュ化・ダミー氏名は同じ入力に対して常に同じ出力となる（決定的）ため、
  テーブル間の突合せキーとしても利用できる。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable

from .schemas import MaskRule

MASK_HALF = "*"
MASK_FULL = "＊"

MaskFunc = Callable[[Any], Any]


# ---------------------------------------------------------------------------
# 文字幅ユーティリティ
# ---------------------------------------------------------------------------


def is_wide(ch: str) -> bool:
    """全角（East Asian Width が W / F / A）かどうか。"""
    return unicodedata.east_asian_width(ch) in ("W", "F", "A")


def display_width(text: str) -> int:
    """全角を 2、半角を 1 として表示幅を数える（Excel の列幅計算にも使用）。"""
    return sum(2 if is_wide(c) else 1 for c in text)


def mask_char(ch: str, mask: str | None = None) -> str:
    """1 文字を伏せ字に置換する。空白類はそのまま残す。"""
    if ch.isspace():
        return ch
    if mask:
        return mask
    return MASK_FULL if is_wide(ch) else MASK_HALF


def mask_all(text: str, mask: str | None = None) -> str:
    return "".join(mask_char(c, mask) for c in text)


def _to_text(value: Any) -> str:
    """マスク対象の値を文字列化する。日付は日本で一般的な書式にする。"""
    if isinstance(value, dt.datetime):
        return value.strftime("%Y/%m/%d %H:%M:%S")
    if isinstance(value, dt.date):
        return value.strftime("%Y/%m/%d")
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


# ---------------------------------------------------------------------------
# 各マスキング規則の実装
# ---------------------------------------------------------------------------


def _full(value: Any, params: dict) -> Any:
    """全桁マスク（桁数保持）。"""
    return mask_all(_to_text(value), params.get("char") or None)


def _partial(value: Any, params: dict) -> Any:
    """先頭 N 文字・末尾 M 文字を残してマスク。"""
    text = _to_text(value)
    head = max(int(params.get("keep_head", 1) or 0), 0)
    tail = max(int(params.get("keep_tail", 0) or 0), 0)
    if head + tail >= len(text):
        # 残す文字数が全長以上の場合でも、最低 1 文字は伏せる
        if len(text) <= 1:
            return mask_all(text)
        head = min(head, len(text) - 1)
        tail = min(tail, len(text) - head - 1)
    middle = text[head : len(text) - tail if tail else len(text)]
    return text[:head] + mask_all(middle) + (text[len(text) - tail :] if tail else "")


def _digits(value: Any, params: dict) -> Any:
    """数字のみを伏せ、ハイフン・括弧・空白などの区切りは残す。

    電話番号（末尾4桁表示）、郵便番号（上3桁表示）、
    カード番号・口座番号（末尾4桁表示）などに使用する。全角数字にも対応。
    """
    text = _to_text(value)
    head = max(int(params.get("keep_head", 0) or 0), 0)
    tail = max(int(params.get("keep_tail", 4) or 0), 0)
    positions = [i for i, c in enumerate(text) if c.isdigit()]
    if not positions:
        return mask_all(text)
    total = len(positions)
    if head + tail >= total:
        # 数字が少なすぎる場合は全て伏せる（情報漏えい防止を優先）
        head, tail = 0, 0
    keep = set(positions[:head]) | set(positions[total - tail :] if tail else [])
    chars = list(text)
    for i in positions:
        if i not in keep:
            chars[i] = mask_char(chars[i])
    return "".join(chars)


_NAME_SPLIT = re.compile(r"([ 　]+)")


def _name(value: Any, params: dict) -> Any:
    """氏名マスク。姓（最初の区切りまで）を残し、以降を伏せる。

    例) 山田 太郎 → 山田 ＊＊ / ヤマダ　タロウ → ヤマダ　＊＊＊
        区切りが無い場合（山田太郎）は先頭 1 文字のみ残す → 山＊＊＊
    """
    text = _to_text(value).strip()
    if not text:
        return text
    parts = _NAME_SPLIT.split(text)
    if len(parts) >= 3:
        return parts[0] + "".join(p if _NAME_SPLIT.fullmatch(p) else mask_all(p) for p in parts[1:])
    keep = int(params.get("keep_head", 1) or 1)
    keep = min(keep, max(len(text) - 1, 0))
    return text[:keep] + mask_all(text[keep:])


def _email(value: Any, params: dict) -> Any:
    """メールアドレス。ローカル部の先頭 1 文字とドメインを残す。"""
    text = _to_text(value)
    if "@" not in text:
        return mask_all(text)
    local, domain = text.rsplit("@", 1)
    if params.get("mask_domain"):
        domain = ".".join(mask_all(p) if i < len(domain.split(".")) - 1 else p for i, p in enumerate(domain.split(".")))
    if len(local) <= 1:
        return MASK_HALF + "@" + domain
    return local[0] + MASK_HALF * (len(local) - 1) + "@" + domain


# 都道府県（「京都府」を「京都」+「府」と誤認しないよう先に完全一致で判定）
_PREFECTURE = re.compile(r"^(北海道|東京都|京都府|大阪府|.{2,3}?県)")
# 市区町村: 郡＋町村 / 政令市＋区 / 単独の市区町村
_MUNICIPALITY = re.compile(r"^(.{1,6}?郡.{1,5}?[町村]|.{1,5}?市.{1,4}?区|.{1,6}?[市区町村])")


def _address(value: Any, params: dict) -> Any:
    """住所。都道府県＋市区町村までを残し、以降（町名・番地・建物名）を伏せる。

    例) 東京都千代田区丸の内1-1-1 → 東京都千代田区＊＊＊＊
    """
    text = _to_text(value).strip()
    if not text:
        return text
    # 先頭の郵便番号表記（〒123-4567 ）は住所判定の邪魔になるため除外して伏せる
    prefix = ""
    m_zip = re.match(r"^(〒?\s*[0-9０-９]{3}[-－ー]?[0-9０-９]{4}\s*)", text)
    if m_zip:
        prefix = _digits(m_zip.group(1), {"keep_head": 3, "keep_tail": 0})
        text = text[m_zip.end() :]
    kept = ""
    m_pref = _PREFECTURE.match(text)
    rest = text
    if m_pref:
        kept = m_pref.group(1)
        rest = text[m_pref.end() :]
    m_city = _MUNICIPALITY.match(rest)
    if m_city:
        kept += m_city.group(1)
        rest = rest[m_city.end() :]
    if not kept:
        # 住所として解釈できない場合は先頭 3 文字のみ残す
        return _partial(text, {"keep_head": 3, "keep_tail": 0})
    fill = params.get("fill")
    if fill is None:
        fill = MASK_FULL * 4
    return prefix + kept + (fill if rest else "")


def _date_year(value: Any, params: dict) -> Any:
    """生年月日など。年のみ残し月日を伏せる → 1985/**/**

    文字列の場合は区切り文字と桁数を保つ（19850401 → 1985****、1985-04-01 → 1985-**-**）。
    """
    if isinstance(value, (dt.date, dt.datetime)):
        return f"{value.year:04d}/**/**"
    text = _to_text(value).strip()
    m = re.match(r"^([0-9０-９]{4})", text)
    if m:
        rest = "".join(mask_char(c) if c.isdigit() else c for c in text[4:])
        return m.group(1) + rest
    # 和暦（昭和60年1月1日 など）は元号＋年まで残す
    m = re.match(r"^\s*((?:明治|大正|昭和|平成|令和|[MTSHR])\s*[0-9０-９元]{1,2}\s*年?)", text)
    if m:
        return m.group(1) + "＊＊月＊＊日"
    return mask_all(text)


def _hash(value: Any, params: dict, salt: str = "") -> Any:
    """SHA-256 による仮名化（先頭 N 桁の16進）。同一値は同一ハッシュになる。"""
    length = int(params.get("length", 16) or 16)
    digest = hashlib.sha256((salt + _to_text(value)).encode("utf-8")).hexdigest()
    return digest[: max(4, min(length, 64))]


_FAKE_SEI = [
    ("佐藤", "サトウ"), ("鈴木", "スズキ"), ("高橋", "タカハシ"), ("田中", "タナカ"),
    ("伊藤", "イトウ"), ("渡辺", "ワタナベ"), ("山本", "ヤマモト"), ("中村", "ナカムラ"),
    ("小林", "コバヤシ"), ("加藤", "カトウ"), ("吉田", "ヨシダ"), ("山田", "ヤマダ"),
    ("佐々木", "ササキ"), ("山口", "ヤマグチ"), ("松本", "マツモト"), ("井上", "イノウエ"),
    ("木村", "キムラ"), ("林", "ハヤシ"), ("斎藤", "サイトウ"), ("清水", "シミズ"),
]
_FAKE_MEI = [
    ("太郎", "タロウ"), ("花子", "ハナコ"), ("一郎", "イチロウ"), ("美咲", "ミサキ"),
    ("健太", "ケンタ"), ("陽菜", "ヒナ"), ("翔太", "ショウタ"), ("結衣", "ユイ"),
    ("大輔", "ダイスケ"), ("さくら", "サクラ"), ("拓也", "タクヤ"), ("愛", "アイ"),
    ("直樹", "ナオキ"), ("由美", "ユミ"), ("誠", "マコト"), ("恵子", "ケイコ"),
    ("隆", "タカシ"), ("真由美", "マユミ"), ("浩二", "コウジ"), ("彩", "アヤ"),
]


def _fake_name(value: Any, params: dict, salt: str = "") -> Any:
    """ダミー氏名に置換する。元の値から決定的に選ぶため、同じ人は同じ偽名になる。

    params.kind: kanji（漢字, 既定）/ kana（全角カナ）
    """
    digest = hashlib.sha256((salt + _to_text(value)).encode("utf-8")).digest()
    sei = _FAKE_SEI[digest[0] % len(_FAKE_SEI)]
    mei = _FAKE_MEI[digest[1] % len(_FAKE_MEI)]
    idx = 1 if params.get("kind") == "kana" else 0
    sep = params.get("separator", "　")
    return f"{sei[idx]}{sep}{mei[idx]}"


def _fixed(value: Any, params: dict) -> Any:
    """固定文字列に置換。"""
    return params.get("value", "＊＊＊")


def _null(value: Any, params: dict) -> Any:
    """空（NULL）にする。"""
    return None


def _round_number(value: Any, params: dict) -> Any:
    """数値の丸め（金額・年収などの概数化）。digits=-3 なら千の位で四捨五入する。"""
    digits = int(params.get("digits", -3) or 0)
    try:
        num = Decimal(_to_text(value).replace(",", ""))
        if not num.is_finite():
            raise ValueError
    except Exception:  # noqa: BLE001 - 数値に変換できない値は全マスク
        return mask_all(_to_text(value))
    # SQL の ROUND と結果をそろえるため、銀行丸めではなく四捨五入にする
    rounded = num.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    if digits <= 0:
        return int(rounded)
    return float(rounded)


def mask_text_pii(text: str, include_review: bool = True, salt: str = "") -> str:
    """文章中で検出した個人情報のみを、カテゴリごとの既定規則でマスクする。"""
    from .categories import CATEGORY_BY_CODE
    from .textscan import find_pii

    matches = find_pii(text)
    if not include_review:
        matches = [m for m in matches if m.level == "auto"]
    out, pos = [], 0
    for m in matches:
        cat = CATEGORY_BY_CODE[m.category]
        masker = build_masker(MaskRule(type=cat.rule, params=dict(cat.params)), salt)
        fragment = text[m.start : m.end]
        masked = masker(fragment) if masker else fragment
        out.append(text[pos : m.start])
        out.append(mask_all(fragment) if masked is None or not isinstance(masked, str) else masked)
        pos = m.end
    out.append(text[pos:])
    return "".join(out)


def _text_pii(value: Any, params: dict, salt: str = "") -> Any:
    """自由記述欄。文中の氏名・電話番号・メールアドレス等のみを伏せる。"""
    include_review = params.get("include_review", True) not in (False, "false", 0, "0")
    return mask_text_pii(_to_text(value), include_review, salt)


# ---------------------------------------------------------------------------
# 規則定義（フロントエンドの選択肢にも使用）
# ---------------------------------------------------------------------------

RULE_DEFINITIONS: list[dict[str, Any]] = [
    {"type": "none", "label": "そのまま出力", "example": "", "params": []},
    {
        "type": "full",
        "label": "全桁マスク",
        "example": "山田太郎 → ＊＊＊＊",
        "params": [{"key": "char", "label": "伏せ字（空欄=自動）", "kind": "text", "default": ""}],
    },
    {
        "type": "partial",
        "label": "部分マスク（先頭/末尾を残す）",
        "example": "ABC12345 → A******5",
        "params": [
            {"key": "keep_head", "label": "先頭に残す文字数", "kind": "number", "default": 1},
            {"key": "keep_tail", "label": "末尾に残す文字数", "kind": "number", "default": 0},
        ],
    },
    {
        "type": "name",
        "label": "氏名（姓のみ残す）",
        "example": "山田 太郎 → 山田 ＊＊",
        "params": [],
    },
    {
        "type": "fake_name",
        "label": "ダミー氏名に置換",
        "example": "山田 太郎 → 佐藤　花子",
        "params": [
            {
                "key": "kind",
                "label": "表記",
                "kind": "select",
                "default": "kanji",
                "options": [{"value": "kanji", "label": "漢字"}, {"value": "kana", "label": "カナ"}],
            }
        ],
    },
    {
        "type": "email",
        "label": "メールアドレス",
        "example": "taro@example.co.jp → t***@example.co.jp",
        "params": [],
    },
    {
        "type": "digits",
        "label": "数字のみマスク（電話・カード番号等）",
        "example": "03-1234-5678 → **-****-5678",
        "params": [
            {"key": "keep_head", "label": "先頭に残す桁数", "kind": "number", "default": 0},
            {"key": "keep_tail", "label": "末尾に残す桁数", "kind": "number", "default": 4},
        ],
    },
    {
        "type": "postal",
        "label": "郵便番号（上3桁のみ）",
        "example": "123-4567 → 123-****",
        "params": [],
    },
    {
        "type": "address",
        "label": "住所（市区町村まで残す）",
        "example": "東京都千代田区丸の内1-1 → 東京都千代田区＊＊＊＊",
        "params": [],
    },
    {
        "type": "date_year",
        "label": "日付（年のみ残す）",
        "example": "1985/04/01 → 1985/**/**",
        "params": [],
    },
    {
        "type": "round_number",
        "label": "数値の丸め",
        "example": "5,234,567 → 5,235,000",
        "params": [{"key": "digits", "label": "丸め桁（-3=千の位）", "kind": "number", "default": -3}],
    },
    {
        "type": "hash",
        "label": "ハッシュ化（仮名化）",
        "example": "山田太郎 → 3f2a9c1b7d4e8a60",
        "params": [{"key": "length", "label": "桁数", "kind": "number", "default": 16}],
    },
    {
        "type": "text_pii",
        "label": "文中の個人情報のみマスク（備考欄等）",
        "example": "山田様 TEL 03-1234-5678 → 山＊様 TEL **-****-5678",
        "params": [
            {
                "key": "include_review",
                "label": "対象",
                "kind": "select",
                "default": "true",
                "options": [
                    {"value": "true", "label": "可能性があるものも含める"},
                    {"value": "false", "label": "確度の高いものだけ"},
                ],
            }
        ],
    },
    {
        "type": "fixed",
        "label": "固定値に置換",
        "example": "任意の値 → ＊＊＊",
        "params": [{"key": "value", "label": "置換後の値", "kind": "text", "default": "＊＊＊"}],
    },
    {"type": "null", "label": "空欄（NULL）にする", "example": "任意の値 → (空)", "params": []},
]

_SIMPLE_RULES: dict[str, Callable[[Any, dict], Any]] = {
    "full": _full,
    "partial": _partial,
    "name": _name,
    "email": _email,
    "digits": _digits,
    "postal": lambda v, p: _digits(v, {"keep_head": 3, "keep_tail": 0}),
    "address": _address,
    "date_year": _date_year,
    "round_number": _round_number,
    "fixed": _fixed,
    "null": _null,
}

_SALTED_RULES: dict[str, Callable[[Any, dict, str], Any]] = {
    "hash": _hash,
    "fake_name": _fake_name,
    "text_pii": _text_pii,
}

VALID_RULE_TYPES = {"none", *_SIMPLE_RULES, *_SALTED_RULES}


def build_masker(rule: MaskRule | None, salt: str = "") -> MaskFunc | None:
    """規則からマスク関数を生成する。マスク不要なら None を返す。

    NULL はどの規則でも NULL のまま返す（「値が無い」こと自体は秘匿情報ではないため）。
    """
    if rule is None or rule.type == "none":
        return None
    params = rule.params or {}
    if rule.type in _SIMPLE_RULES:
        fn = _SIMPLE_RULES[rule.type]

        def masker(value: Any) -> Any:
            return None if value is None else fn(value, params)

        return masker
    if rule.type in _SALTED_RULES:
        sfn = _SALTED_RULES[rule.type]

        def salted(value: Any) -> Any:
            return None if value is None else sfn(value, params, salt)

        return salted
    raise ValueError(f"不明なマスキング規則です: {rule.type}")


# ---------------------------------------------------------------------------
# 列名・コメントからのマスキング規則の自動推定
# ---------------------------------------------------------------------------


def suggest_rule(column_name: str, comment: str | None, data_type: str = "") -> MaskRule | None:
    """列名・コメント（論理名）だけから、自動でマスクすべき列の規則を推定する。

    値を見ない簡易判定のため、確度の高いもの（自動判定）のみを返す。
    サンプル値も使った判定は detector.analyze_column を使用する。
    """
    from .detector import analyze_column

    verdict = analyze_column(column_name, comment, data_type)
    return verdict.rule if verdict.level == "auto" else None
