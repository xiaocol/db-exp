"""判定結果（Finding）の生成と、人の判断（Decision）の適用。"""

from __future__ import annotations

import hashlib
from typing import Any, Sequence

from .categories import CATEGORY_BY_CODE
from .detector import Verdict
from .masking import _to_text, build_masker
from .schemas import Decision, Finding, MaskRule

SAMPLE_COUNT = 3
SAMPLE_MAX_CHARS = 60


def make_id(*parts: Any) -> str:
    return hashlib.sha1("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def sample_values(values: Sequence[Any], limit: int = SAMPLE_COUNT) -> list[Any]:
    """重複を除いた空でない値を先頭から limit 件。"""
    seen: set[str] = set()
    out: list[Any] = []
    for v in values:
        if v is None or isinstance(v, (bytes, bytearray, memoryview)):
            continue
        text = _to_text(v).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(v)
        if len(out) >= limit:
            break
    return out


def _short(text: str) -> str:
    return text if len(text) <= SAMPLE_MAX_CHARS else text[: SAMPLE_MAX_CHARS - 1] + "…"


def masked_examples(rule: MaskRule | None, values: Sequence[Any], salt: str = "") -> list[str]:
    try:
        masker = build_masker(rule, salt)
    except ValueError:
        return []
    out = []
    for v in values:
        m = masker(v) if masker else v
        out.append("(NULL)" if m is None else _short(_to_text(m)))
    return out


def column_finding(
    *,
    source: str,
    file: str,
    column: str,
    verdict: Verdict,
    samples: Sequence[Any],
    comment: str | None = None,
    data_type: str | None = None,
    is_pk: bool = False,
    location: str | None = None,
    id_parts: Sequence[Any] = (),
) -> Finding:
    picked = sample_values(samples)
    assert verdict.rule is not None and verdict.category is not None and verdict.level is not None
    return Finding(
        id=make_id(source, "column", file, location or "", column, *id_parts),
        source=source,  # type: ignore[arg-type]
        target="column",
        level=verdict.level,
        category=verdict.category,
        category_label=verdict.label or CATEGORY_BY_CODE[verdict.category].label,
        score=verdict.score,
        reasons=verdict.reasons + ([f"他の候補: {'、'.join(verdict.alternatives)}"] if verdict.alternatives else []),
        rule=verdict.rule,
        file=file,
        location=location,
        column=column,
        column_comment=comment,
        data_type=data_type,
        is_pk=is_pk,
        samples=[_short(_to_text(v)) for v in picked],
        masked_samples=masked_examples(verdict.rule, picked),
    )


def effective_rule(finding: Finding, decisions: dict[str, Decision]) -> MaskRule | None:
    """人の判断を反映した規則。None ならマスクしない。

    判断が無い場合は、要確認も含めて推奨規則でマスクする（安全側）。
    """
    d = decisions.get(finding.id)
    if d is None:
        return finding.rule
    if not d.mask:
        return None
    return d.rule or finding.rule
