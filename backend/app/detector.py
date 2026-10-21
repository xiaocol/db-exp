"""列（DB の列・ドキュメントの表の列）がマスキング対象かどうかの自動判定。

外部サービスには送信せず、ローカルの規則と辞書だけで判定する。

判定の考え方:
  1. 列名・論理名（コメント）のパターン …… 強い根拠 0.85 / 弱い根拠 0.45
  2. サンプル値の形式（電話番号・郵便番号・検査用数字など）…… 一致率 × カテゴリごとの重み
  3. 1 と 2 を「どちらかが当たれば高くなる」形で合成し、区分値を示す語・型の不一致・
     列名と値の矛盾があれば減点する。

  スコア 0.7 以上 → 自動でマスキング対象（auto）
  スコア 0.35 以上 → 人が判断する「要確認」（review）
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

from .categories import (
    CATEGORIES,
    CATEGORY_BY_CODE,
    CODE_WORDS_COL,
    CODE_WORDS_JP,
    NOT_PERSON_NAME_COL,
    NOT_PERSON_NAME_JP,
    Category,
    is_date_like,
    normalize,
)
from .schemas import MaskRule
from .textscan import AUTO_THRESHOLD, REVIEW_THRESHOLD, find_pii

STRONG = 0.85
WEAK = 0.45
MIN_SAMPLES = 5

Level = Literal["auto", "review"]


@dataclass
class Verdict:
    """1 列の判定結果。"""

    category: str | None = None
    label: str | None = None
    score: float = 0.0
    level: Level | None = None
    rule: MaskRule | None = None
    reasons: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)


def type_class(data_type: str) -> str:
    """データ型を大まかに分類する（text / number / date / binary / other）。"""
    t = (data_type or "").upper()
    if not t:
        return "text"
    if t.endswith("[]"):
        return "other"
    if re.match(r"(N?VARCHAR2?|N?CHAR|CHARACTER|N?CLOB|TEXT|LONG$|CITEXT|BPCHAR|STRING|NTEXT)", t):
        return "text"
    if re.match(r"(NUMBER|NUMERIC|DECIMAL|INT|INTEGER|BIGINT|SMALLINT|FLOAT|REAL|DOUBLE|BINARY_(FLOAT|DOUBLE)|MONEY|SERIAL)", t):
        return "number"
    if re.match(r"(DATE|TIMESTAMP)", t):
        return "date"
    if re.match(r"(BLOB|RAW|LONG RAW|BYTEA|BFILE|BINARY|VARBINARY)", t):
        return "binary"
    return "other"


def _column_tokens(name: str) -> str:
    """物理名を SNAKE_CASE の大文字に正規化する（custName → CUST_NAME）。"""
    name = unicodedata.normalize("NFKC", name or "")
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    name = re.sub(r"[\s\-.]+", "_", name)
    return name.upper()


def _name_signal(cat: Category, column: str, comment: str | None) -> tuple[float, str | None]:
    """列名・論理名からの根拠の強さと、一致した語句を返す。"""
    col = _column_tokens(column)
    # 日本語の列名（PostgreSQL では珍しくない）も論理名として扱う
    jp_targets = [t for t in (unicodedata.normalize("NFKC", comment or "").strip(), (column or "").strip()) if t]
    best, hit = 0.0, None
    for text in jp_targets:
        for pattern, strength in ((cat.jp_strong, STRONG), (cat.jp_weak, WEAK)):
            if pattern and strength > best:
                m = re.search(pattern, text, re.I)
                if m:
                    best, hit = strength, text
    for pattern, strength in ((cat.col_strong, STRONG), (cat.col_weak, WEAK)):
        if pattern and strength > best and re.search(pattern, col):
            best, hit = strength, column
    if best == 0:
        return 0.0, None

    if cat.code == "name":
        # 「商品名」「会社名」「PRODUCT_NAME」などは人の氏名ではない
        if any(NOT_PERSON_NAME_JP.search(t) for t in jp_targets) or NOT_PERSON_NAME_COL.search(col):
            if not (comment and re.search(cat.jp_strong or "", unicodedata.normalize("NFKC", comment))):
                return 0.0, None
    if not cat.allow_code_words:
        if any(CODE_WORDS_JP.search(t) for t in jp_targets) or CODE_WORDS_COL.search(col):
            # 「メール配信フラグ」「電話区分」などは値そのものが個人情報ではない
            return best * 0.4, hit
    return best, hit


def _value_signal(cat: Category, values: Sequence[Any]) -> tuple[float, float]:
    """サンプル値の一致率（0〜1）と、件数を考慮した根拠の強さを返す。"""
    if cat.value_check is None or not values:
        return 0.0, 0.0
    total = sum(cat.value_check(v) for v in values)
    ratio = total / len(values)
    if ratio < 0.2:
        return ratio, 0.0
    strength = cat.value_weight * ratio
    if len(values) < MIN_SAMPLES:
        strength *= len(values) / MIN_SAMPLES
    return ratio, strength


def _non_empty(samples: Sequence[Any]) -> list[Any]:
    out = []
    for v in samples:
        if v is None or isinstance(v, (bytes, bytearray, memoryview)):
            continue
        if isinstance(v, str) and not v.strip():
            continue
        out.append(v)
    return out


def _score_category(
    cat: Category, column: str, comment: str | None, tclass: str, values: list[Any]
) -> tuple[float, list[str]]:
    name_score, hit = _name_signal(cat, column, comment)
    ratio, value_score = _value_signal(cat, values)
    reasons: list[str] = []
    if hit is not None:
        if name_score >= STRONG:
            reasons.append(f"列名・論理名「{hit}」が{cat.label}を示す")
        elif name_score >= WEAK:
            reasons.append(f"列名・論理名「{hit}」が{cat.label}の可能性")
        else:
            reasons.append(f"列名・論理名「{hit}」は{cat.label}に関する区分値・フラグの可能性")
    if value_score > 0:
        reasons.append(f"サンプル値の {ratio:.0%} が{cat.label}の形式")
    score = 1 - (1 - name_score) * (1 - value_score)

    # 列名は該当するのに、値がまったく形式に合わない（例: TEL_KBN に 1/2 が入っている）
    if name_score >= STRONG and cat.value_check is not None and len(values) >= 10 and ratio < 0.05:
        if cat.code != "name" or all(re.fullmatch(r"[\d\s.\-]+", normalize(v)) for v in values):
            score = min(score, 0.5)
            reasons.append("ただしサンプル値は形式が一致しない")
    if cat.code == "birth_date" and name_score > 0 and values and not any(is_date_like(v) for v in values):
        score = min(score, 0.5)
        reasons.append("ただしサンプル値が日付ではない")

    if cat.text_only and tclass in ("number", "date", "binary"):
        score *= 0.3
    if tclass == "binary":
        score = 0.0
    if cat.review_only and score >= AUTO_THRESHOLD:
        score = AUTO_THRESHOLD - 0.01
        if cat.description:
            reasons.append(cat.description)
    return score, reasons


def _free_text_hits(values: list[Any]) -> tuple[int, set[str]]:
    """サンプル値（自由記述）の中に、確度の高い個人情報が含まれる件数と種類。"""
    count, kinds = 0, set()
    for v in values:
        if not isinstance(v, str) or len(v) < 6:
            continue
        # 値全体が電話番号等である場合は自由記述ではない（その形式の列として判定する）
        hits = [h for h in find_pii(v) if h.level == "auto" and (h.end - h.start) < len(v.strip()) * 0.8]
        if hits:
            count += 1
            kinds.update(CATEGORY_BY_CODE[h.category].label for h in hits)
    return count, kinds


def analyze_column(
    name: str,
    comment: str | None = None,
    data_type: str = "",
    samples: Sequence[Any] = (),
    *,
    is_pk: bool = False,
    context: Literal["db", "doc"] = "db",
) -> Verdict:
    """1 列を判定する。samples は先頭から取得した値（NULL 含む）。"""
    tclass = type_class(data_type)
    values = _non_empty(samples)[:500]
    scored: list[tuple[float, Category, list[str]]] = []
    for cat in CATEGORIES:
        if cat.code == "free_text":
            continue
        score, reasons = _score_category(cat, name, comment, tclass, values)
        if score >= REVIEW_THRESHOLD:
            scored.append((score, cat, reasons))

    # 自由記述欄: 文中に個人情報が見つかった場合のみ自動、それ以外は要確認（DB の列のみ）
    if context == "db" and tclass == "text":
        cat = CATEGORY_BY_CODE["free_text"]
        name_score, hit = _name_signal(cat, name, comment)
        hits, kinds = _free_text_hits(values)
        long_text = bool(values) and sum(len(str(v)) for v in values) / len(values) >= 30
        if hits:
            reasons = [f"サンプル値 {hits} 件の文中に{'・'.join(sorted(kinds))}を検出"]
            if hit:
                reasons.insert(0, f"列名・論理名「{hit}」が{cat.label}を示す")
            scored.append((0.8 if hits >= 2 or name_score else 0.72, cat, reasons))
        elif name_score >= WEAK or long_text:
            reasons = [f"列名・論理名「{hit}」が{cat.label}を示す" if hit else "長い文章が入っている列"]
            reasons.append("サンプル値には個人情報が見つからないが、他の行に含まれる可能性がある")
            scored.append((0.5 if name_score >= STRONG else 0.4, cat, reasons))

    if not scored:
        return Verdict()
    scored.sort(key=lambda s: -s[0])
    score, cat, reasons = scored[0]
    alternatives = [c.label for s, c, _ in scored[1:] if s >= REVIEW_THRESHOLD]
    # 候補が拮抗している場合は人が判断する
    if len(scored) > 1 and scored[1][0] >= score - 0.1 and scored[1][0] >= REVIEW_THRESHOLD and score >= AUTO_THRESHOLD:
        score = AUTO_THRESHOLD - 0.01
        reasons = [*reasons, f"他の候補（{scored[1][1].label}）とも判断できる"]
    if is_pk and score >= REVIEW_THRESHOLD:
        reasons = [*reasons, "主キーのため、マスクすると一意性や他表との突合せに影響する"]
        score = min(score, AUTO_THRESHOLD - 0.01)

    rule = MaskRule(type=cat.rule, params=dict(cat.params))
    return Verdict(
        category=cat.code,
        label=cat.label,
        score=round(score, 2),
        level="auto" if score >= AUTO_THRESHOLD else "review",
        rule=rule,
        reasons=reasons,
        alternatives=alternatives,
    )
