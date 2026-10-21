"""SQL 形式の出力。

1. マスク済みダンプ（INSERT 文）
   DB から読み出した値を Python 側でマスクし、テスト環境に投入できる INSERT 文として出力する。
   Excel 出力と同じマスク関数を使うため、結果は Excel と一致する。

2. マスキング用 UPDATE 文
   本番データをコピーしたテスト環境で実行し、その場でデータをマスクするための SQL。
   データは含まず、各規則を DB の関数（REGEXP_REPLACE 等）で表現する。

どちらも列のデータ型に合わせて値を調整する（数値・日付型の列に文字列のマスク結果は
格納できないため、NULL・年初日などに置き換え、その旨をファイル内にコメントで残す）。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from .masking import RULE_DEFINITIONS, _FAKE_MEI, _FAKE_SEI, _to_text, build_masker
from .schemas import ColumnInfo, MaskRule

_RULE_LABELS = {r["type"]: r["label"] for r in RULE_DEFINITIONS}

# ---------------------------------------------------------------------------
# データ型の分類
# ---------------------------------------------------------------------------


@dataclass
class SqlColumn:
    name: str
    data_type: str
    nullable: bool
    is_pk: bool
    tclass: str  # text / number / date / timestamp / timestamptz / time / interval / binary / bool / json / array / other
    max_len: int | None = None
    byte_semantics: bool = False
    national: bool = False
    is_lob: bool = False
    # 数値型の整数部の桁数（ハッシュ値を数値で格納する場合に使用）
    num_digits: int = 15


def classify(db_type: str, info: ColumnInfo) -> SqlColumn:
    t = info.data_type.strip()
    u = t.upper()
    col = SqlColumn(info.name, t, info.nullable, info.is_pk, "other")
    m_len = re.search(r"\((\d+)(\s+(CHAR|BYTE))?\)", u)
    if db_type == "oracle":
        if re.match(r"N?(VARCHAR2|CHAR)\b", u) or u.startswith("NCHAR") or u.startswith("NVARCHAR2"):
            col.tclass = "text"
            col.national = u.startswith("N")
            if m_len:
                col.max_len = int(m_len.group(1))
                # NCHAR 系は常に文字数、それ以外は CHAR 指定がなければバイト数
                col.byte_semantics = not col.national and m_len.group(3) != "CHAR"
        elif u in ("CLOB", "NCLOB", "LONG"):
            col.tclass, col.is_lob, col.national = "text", True, u == "NCLOB"
        elif re.match(r"(NUMBER|FLOAT|BINARY_FLOAT|BINARY_DOUBLE|INTEGER)", u):
            col.tclass = "number"
            col.num_digits = _num_digits(u, 15)
        elif u == "DATE":
            col.tclass = "date_oracle"
        elif u.startswith("TIMESTAMP"):
            col.tclass = "timestamptz" if u.endswith("WITH TIME ZONE") else "timestamp"
        elif re.match(r"(RAW|LONG RAW|BLOB|BFILE)", u):
            col.tclass, col.is_lob = "binary", u in ("BLOB", "BFILE")
        elif u.startswith("INTERVAL"):
            col.tclass = "interval"
        elif u == "BOOLEAN":
            col.tclass = "bool"
        elif u == "JSON":
            col.tclass = "json"
    else:
        if u.endswith("[]"):
            col.tclass = "array"
        elif re.match(r"(CHARACTER VARYING|VARCHAR|CHARACTER|CHAR|BPCHAR|TEXT|CITEXT|NAME)\b", u):
            col.tclass = "text"
            if m_len:
                col.max_len = int(m_len.group(1))
        elif re.match(r"(SMALLINT|INTEGER|BIGINT|NUMERIC|DECIMAL|REAL|DOUBLE PRECISION)", u):
            col.tclass = "number"
            col.num_digits = {"SMALLINT": 4, "INTEGER": 9, "BIGINT": 15}.get(u, _num_digits(u, 15))
        elif u == "DATE":
            col.tclass = "date"
        elif u.startswith("TIMESTAMP"):
            col.tclass = "timestamptz" if "WITH TIME ZONE" in u else "timestamp"
        elif u.startswith("TIME"):
            col.tclass = "time"
        elif u.startswith("INTERVAL"):
            col.tclass = "interval"
        elif u == "BYTEA":
            col.tclass = "binary"
        elif u == "BOOLEAN":
            col.tclass = "bool"
        elif u in ("JSON", "JSONB"):
            col.tclass = "json"
    return col


def _num_digits(u: str, default: int) -> int:
    m = re.search(r"\((\d+)(?:\s*,\s*(-?\d+))?\)", u)
    if not m:
        return default
    digits = int(m.group(1)) - max(int(m.group(2) or 0), 0)
    return max(1, min(digits, 15))


_DATE_CLASSES = ("date", "date_oracle", "timestamp", "timestamptz")


# ---------------------------------------------------------------------------
# 列ごとの処理方針（型に合わないマスクの置き換え）
# ---------------------------------------------------------------------------


@dataclass
class ColumnPlan:
    col: SqlColumn
    rule: MaskRule | None
    # keep=そのまま / mask=規則を適用 / null=NULL / const=固定値 / trunc_year=年初日に切り捨て
    # numhash=ハッシュ値を列の桁数に収まる数値にする
    action: str
    const: Any = None
    note: str | None = None
    masker: Callable[[Any], Any] | None = None
    salt: str = ""

    @property
    def rule_label(self) -> str:
        return _RULE_LABELS.get(self.rule.type, self.rule.type) if self.rule else ""


def _fallback(col: SqlColumn, rule: MaskRule, reason: str) -> ColumnPlan:
    """型に合わない規則の代わりに NULL（NOT NULL 列なら型ごとの固定値）にする。"""
    label = _RULE_LABELS.get(rule.type, rule.type)
    if col.is_pk:
        # 主キーを NULL・固定値にすると一意制約に違反するため、変更しない
        return ColumnPlan(col, rule, "keep", note=f"⚠ 主キーの列のため「{label}」を適用せず、元の値のままにします")
    if col.nullable:
        return ColumnPlan(col, rule, "null", note=f"{reason}「{label}」の代わりに NULL にします")
    if col.tclass == "number":
        return ColumnPlan(col, rule, "const", Decimal(0), note=f"{reason}「{label}」の代わりに 0 にします（NOT NULL 列）")
    if col.tclass in _DATE_CLASSES:
        return ColumnPlan(col, rule, "trunc_year", note=f"{reason}「{label}」の代わりに年初日（1月1日）にします（NOT NULL 列）")
    if col.tclass == "bool":
        return ColumnPlan(col, rule, "const", False, note=f"{reason}「{label}」の代わりに FALSE にします（NOT NULL 列）")
    return ColumnPlan(col, rule, "keep", note=f"⚠ {reason}マスクできません（NOT NULL 列のため元の値のまま）。手動で対応してください")


def _parse_number(text: Any) -> Decimal | None:
    try:
        num = Decimal(str(text).replace(",", ""))
        return num if num.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _parse_date(text: Any) -> dt.datetime | None:
    s = str(text).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def plan_column(col: SqlColumn, rule: MaskRule | None, salt: str = "") -> ColumnPlan:
    if rule is None or rule.type == "none":
        return ColumnPlan(col, None, "keep")
    if rule.type == "null":
        if col.nullable:
            return ColumnPlan(col, rule, "null")
        if col.tclass == "text":
            return ColumnPlan(col, rule, "const", "＊" if not col.byte_semantics or (col.max_len or 3) >= 3 else "*",
                              note="NOT NULL 列のため、NULL の代わりに「＊」にします")
        return _fallback(col, rule, "NOT NULL 列のため、")
    if col.tclass == "text":
        if col.is_lob and rule.type in ("hash", "fake_name"):
            return ColumnPlan(col, MaskRule(type="full"), "mask", masker=build_masker(MaskRule(type="full"), salt),
                              note="LOB 列のためハッシュ化できず、全桁マスクにします")
        return ColumnPlan(col, rule, "mask", masker=build_masker(rule, salt))
    if col.tclass == "number":
        if rule.type == "round_number":
            return ColumnPlan(col, rule, "mask", masker=build_masker(rule, salt))
        if rule.type == "hash" and not col.is_pk:
            return ColumnPlan(col, rule, "numhash", col.num_digits, salt=salt,
                              note=f"数値型の列のため、ハッシュ値を {col.num_digits} 桁以内の数値にします（同じ値は同じ数値）")
        if rule.type == "fixed":
            num = _parse_number(rule.params.get("value", ""))
            if num is not None:
                return ColumnPlan(col, rule, "const", num)
        return _fallback(col, rule, "数値型の列のため、")
    if col.tclass in _DATE_CLASSES:
        if rule.type == "date_year":
            return ColumnPlan(col, rule, "trunc_year")
        if rule.type == "fixed":
            d = _parse_date(rule.params.get("value", ""))
            if d is not None:
                return ColumnPlan(col, rule, "const", d.date() if col.tclass == "date" else d)
        return _fallback(col, rule, "日付型の列のため、")
    if rule.type == "fixed" and col.tclass in ("json", "other", "time", "interval"):
        return ColumnPlan(col, rule, "const", str(rule.params.get("value", "")))
    return _fallback(col, rule, "この型の列には、")


def _fit_text(text: str, col: SqlColumn) -> str:
    """列の最大長（文字数またはバイト数）に収まるよう切り詰める。"""
    if not col.max_len:
        return text
    if col.byte_semantics:
        data = text.encode("utf-8")
        if len(data) <= col.max_len:
            return text
        return data[: col.max_len].decode("utf-8", errors="ignore")
    return text[: col.max_len]


def _trunc_year(value: Any) -> Any:
    if isinstance(value, dt.datetime):
        return value.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    if isinstance(value, dt.date):
        return value.replace(month=1, day=1)
    return value


def numeric_hash(value: Any, salt: str, digits: int) -> int:
    """SHA-256 の先頭 15 桁（16 進）を整数にし、digits 桁に収める。"""
    text = _to_text(value)
    if isinstance(value, Decimal) and value == value.to_integral_value():
        text = str(int(value))
    return int(hashlib.sha256((salt + text).encode("utf-8")).hexdigest()[:15], 16) % (10**digits)


def apply_plan(plan: ColumnPlan, value: Any) -> Any:
    """INSERT 文用に 1 値を変換する。"""
    if value is None and plan.action != "const":
        return None
    if plan.action == "keep":
        return value
    if plan.action == "null":
        return None
    if plan.action == "const":
        return plan.const if value is not None or not plan.col.nullable else None
    if plan.action == "trunc_year":
        return _trunc_year(value)
    if plan.action == "numhash":
        return numeric_hash(value, plan.salt, plan.const)
    masked = plan.masker(value) if plan.masker else value
    if masked is None:
        return None
    if plan.col.tclass == "text":
        return _fit_text(masked if isinstance(masked, str) else str(masked), plan.col)
    return masked


# ---------------------------------------------------------------------------
# リテラル（INSERT 文の値）
# ---------------------------------------------------------------------------

_CHUNK = 500  # SQL*Plus の 1 行の長さ制限を超えないよう、長い文字列は分割する


def _q(text: str) -> str:
    return "'" + text.replace("\x00", "").replace("'", "''") + "'"


def _ora_text(text: str, col: SqlColumn) -> str:
    prefix = "N" if col.national else ""
    if len(text) <= _CHUNK:
        return prefix + _q(text)
    parts = [text[i : i + _CHUNK] for i in range(0, len(text), _CHUNK)]
    if col.is_lob:
        fn = "TO_NCLOB" if col.national else "TO_CLOB"
        return "\n    || ".join(f"{fn}({prefix}{_q(p)})" for p in parts)
    return "\n    || ".join(prefix + _q(p) for p in parts)


def _pg_array(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return "{" + ",".join(_pg_array(v) for v in value) + "}"
    if value is None:
        return "NULL"
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


class LiteralError(Exception):
    pass


def literal(db_type: str, col: SqlColumn, value: Any) -> str:
    if value is None:
        return "NULL"
    ora = db_type == "oracle"
    if isinstance(value, bool):
        if col.tclass == "number":
            return "1" if value else "0"
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, Decimal)):
        if isinstance(value, Decimal) and not value.is_finite():
            return "NULL"
        text = format(value, "f") if isinstance(value, Decimal) else str(value)
        return text if col.tclass in ("number", "other", "bool") else _q(text) if not ora else _ora_text(text, col)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            if ora:
                return "BINARY_DOUBLE_NAN" if math.isnan(value) else ("-" if value < 0 else "") + "BINARY_DOUBLE_INFINITY"
            return "'NaN'" if math.isnan(value) else ("'-Infinity'" if value < 0 else "'Infinity'")
        return repr(value)
    if isinstance(value, dt.datetime):
        if ora:
            if col.tclass == "date_oracle":
                return f"TO_DATE('{value:%Y-%m-%d %H:%M:%S}', 'YYYY-MM-DD HH24:MI:SS')"
            if value.tzinfo is not None:
                off = value.strftime("%z")
                return f"TO_TIMESTAMP_TZ('{value:%Y-%m-%d %H:%M:%S.%f} {off[:3]}:{off[3:]}', 'YYYY-MM-DD HH24:MI:SS.FF6 TZH:TZM')"
            return f"TO_TIMESTAMP('{value:%Y-%m-%d %H:%M:%S.%f}', 'YYYY-MM-DD HH24:MI:SS.FF6')"
        return _q(value.isoformat(sep=" "))
    if isinstance(value, dt.date):
        if ora:
            return f"TO_DATE('{value:%Y-%m-%d}', 'YYYY-MM-DD')"
        return _q(value.isoformat())
    if isinstance(value, dt.time):
        return _q(value.isoformat())
    if isinstance(value, dt.timedelta):
        if ora:
            return f"NUMTODSINTERVAL({value.total_seconds()}, 'SECOND')"
        return _q(f"{value.total_seconds()} seconds")
    if isinstance(value, (bytes, bytearray, memoryview)):
        data = bytes(value)
        if ora:
            if len(data) > 2000:
                raise LiteralError(f"{len(data):,} バイトのバイナリは INSERT 文で出力できないため NULL にしました")
            return f"HEXTORAW('{data.hex().upper()}')"
        return _q("\\x" + data.hex())
    if isinstance(value, (dict, list, tuple)):
        if not ora and col.tclass == "array":
            return _q(_pg_array(value))
        text = json.dumps(value, ensure_ascii=False, default=str)
        return _ora_text(text, col) if ora else _q(text)
    if isinstance(value, uuid.UUID):
        return _q(str(value))
    text = value if isinstance(value, str) else str(value)
    return _ora_text(text, col) if ora else _q(text)


# ---------------------------------------------------------------------------
# SQL 式（UPDATE 文）
# ---------------------------------------------------------------------------

_D = "[0-9０-９]"
_ND = "[^0-9０-９]"
_SPACES = "[:space:]　"


class ExprBuilder:
    """マスキング規則を、DB の組み込み関数による SQL 式に変換する。"""

    def __init__(self, db_type: str, salt: str = ""):
        self.ora = db_type == "oracle"
        self.salt = salt

    # ---- 基本関数 ----
    def length(self, e: str) -> str:
        return f"LENGTH({e})" if self.ora else f"length({e})"

    def substr(self, e: str, start: str | int, length: str | int | None = None) -> str:
        fn = "SUBSTR" if self.ora else "substr"
        return f"{fn}({e}, {start})" if length is None else f"{fn}({e}, {start}, {length})"

    def rx_replace(self, e: str, pattern: str, repl: str) -> str:
        if self.ora:
            return f"REGEXP_REPLACE({e}, {_q(pattern)}, {repl})"
        return f"regexp_replace({e}, {_q(pattern)}, {repl}, 'g')"

    def rx_substr(self, e: str, pattern: str) -> str:
        """一致した部分（なければ空文字）。"""
        if self.ora:
            return f"REGEXP_SUBSTR({e}, {_q(pattern)})"
        return f"COALESCE(substring({e} from {_q(pattern)}), '')"

    def rx_like(self, e: str, pattern: str) -> str:
        return f"REGEXP_LIKE({e}, {_q(pattern)})" if self.ora else f"{e} ~ {_q(pattern)}"

    def nvl_len(self, e: str) -> str:
        return f"NVL(LENGTH({e}), 0)" if self.ora else f"length({e})"

    def trim(self, e: str) -> str:
        return self.rx_replace(e, f"^[{_SPACES}]+|[{_SPACES}]+$", "''")

    def cat(self, *parts: str) -> str:
        parts = tuple(p for p in parts if p)
        if self.ora:
            return " || ".join(parts)
        return "(" + " || ".join(parts) + ")"

    def digit_count(self, e: str) -> str:
        if self.ora:
            return f"REGEXP_COUNT({e}, {_q(_D)})"
        return f"length(regexp_replace({e}, {_q(_ND)}, '', 'g'))"

    def sha256_hex(self, e: str) -> str:
        if self.ora:
            return f"RAWTOHEX(STANDARD_HASH({_q(self.salt)} || {e}, 'SHA256'))"
        return f"encode(sha256(convert_to({_q(self.salt)} || {e}, 'UTF8')), 'hex')"

    # ---- マスク部品 ----
    def mask_all(self, e: str, char: str | None = None) -> str:
        """空白以外を伏せ字にする。全角（非 ASCII）は「＊」、半角は「*」。"""
        if char:
            return self.rx_replace(e, f"[^{_SPACES}]", _q(char))
        # 半角カナ（｡〜ﾟ）は半角の伏せ字にする
        wide = "[^ -~｡-ﾟ" + _SPACES + "]" if self.ora else "[^\\x01-\\x7e｡-ﾟ" + _SPACES + "]"
        return self.rx_replace(self.rx_replace(e, wide, "'＊'"), "[!-~｡-ﾟ]", "'*'")

    def mask_digits(self, e: str) -> str:
        return self.rx_replace(self.rx_replace(e, "[0-9]", "'*'"), "[０-９]", "'＊'")

    def case(self, *whens: tuple[str, str], default: str) -> str:
        body = " ".join(f"WHEN {c} THEN {v}" for c, v in whens)
        return f"CASE {body} ELSE {default} END"

    # ---- 各規則 ----
    def full(self, c: str, p: dict) -> str:
        return self.mask_all(c, p.get("char") or None)

    def partial(self, c: str, p: dict) -> str:
        h = max(int(p.get("keep_head", 1) or 0), 0)
        t = max(int(p.get("keep_tail", 0) or 0), 0)
        n = self.length(c)
        head = self.substr(c, 1, h) if h else ""
        mid = self.mask_all(self.substr(c, h + 1, f"{n} - {h + t}"))
        tail = self.substr(c, f"{n} - {t - 1}") if t else ""
        return self.case((f"{n} > {h + t}", self.cat(head, mid, tail)), default=self.mask_all(c))

    def name(self, c: str, p: dict) -> str:
        s = self.trim(c)
        k = int(p.get("keep_head", 1) or 1)
        n = self.length(s)
        if self.ora:
            pos = f"REGEXP_INSTR({s}, '[ 　]')"
        else:
            pos = f"COALESCE(LEAST(NULLIF(strpos({s}, ' '), 0), NULLIF(strpos({s}, '　'), 0)), 0)"
        keep = f"LEAST({k}, {n} - 1)"
        return self.case(
            (f"{n} <= 1", self.mask_all(s)),
            (f"{pos} > 1", self.cat(self.substr(s, 1, f"{pos} - 1"), self.mask_all(self.substr(s, pos)))),
            default=self.cat(self.substr(s, 1, keep), self.mask_all(self.substr(s, f"{keep} + 1"))),
        )

    def email(self, c: str, p: dict) -> str:
        if self.ora:
            at = f"INSTR({c}, '@', -1)"
            stars = f"RPAD('*', {at} - 2, '*')"
        else:
            at = f"(CASE WHEN strpos({c}, '@') = 0 THEN 0 ELSE length({c}) - strpos(reverse({c}), '@') + 1 END)"
            stars = f"repeat('*', {at} - 2)"
        domain = self.substr(c, at)
        if p.get("mask_domain"):
            domain = self.cat("'@'", self.rx_replace(self.substr(c, f"{at} + 1"), "[^.]", "'*'"))
        return self.case(
            (f"{at} = 0", self.mask_all(c)),
            (f"{at} <= 2", self.cat("'*'", domain)),
            default=self.cat(self.substr(c, 1, 1), stars, domain),
        )

    def digits(self, c: str, p: dict, head: int | None = None, tail: int | None = None) -> str:
        h = max(int(p.get("keep_head", 0) or 0), 0) if head is None else head
        t = max(int(p.get("keep_tail", 4) or 0), 0) if tail is None else tail
        n = self.digit_count(c)
        total = self.length(c)
        # PostgreSQL の substring はグループがあるとその部分を返すため、非キャプチャにする
        g = "(" if self.ora else "(?:"
        pre = self.rx_substr(c, f"^{g}{_ND}*{_D}){{{h}}}") if h else ""
        suf = self.rx_substr(c, f"{g}{_D}{_ND}*){{{t}}}$") if t else ""
        a = self.nvl_len(pre) if h else "0"
        sl = self.nvl_len(suf) if t else "0"
        middle = self.mask_digits(self.substr(c, f"{a} + 1", f"{total} - {a} - {sl}"))
        parts = [self.substr(c, 1, a) if h else "", middle, self.substr(c, f"{total} - {sl} + 1") if t else ""]
        return self.case(
            (f"{n} = 0", self.mask_all(c)),
            (f"{n} <= {h + t}", self.mask_digits(c)),
            default=self.cat(*parts),
        )

    def postal(self, c: str, p: dict) -> str:
        return self.digits(c, p, head=3, tail=0)

    def address(self, c: str, p: dict) -> str:
        s = self.trim(c)
        pref = self.cat(self.rx_substr(s, "^(北海道|東京都|京都府|大阪府)"), self.rx_substr(s, "^.{2,3}?県"))
        if self.ora:
            # Oracle では空文字は NULL のため、連結の結果で判定できる
            pref = f"COALESCE({self.rx_substr(s, '^(北海道|東京都|京都府|大阪府)')}, {self.rx_substr(s, '^.{2,3}?県')})"
        rest = self.substr(s, f"{self.nvl_len(pref)} + 1")
        # Python の正規表現（左の候補を優先・最短一致）と同じ結果になるよう、候補ごとに評価する
        branches = ["^.{1,6}?郡.{1,5}?[町村]", "^.{1,5}?市.{1,4}?区", "^.{1,6}?[市区町村]"]
        if self.ora:
            city = "COALESCE(" + ", ".join(self.rx_substr(rest, b) for b in branches) + ")"
        else:
            subs = [f"NULLIF({self.rx_substr(rest, b)}, '')" for b in branches]
            city = "COALESCE(" + ", ".join(subs) + ", '')"
        kept = self.cat(pref, city)
        fill = p.get("fill")
        fill = "＊＊＊＊" if fill is None else str(fill)
        kept_len = self.nvl_len(kept)
        return self.case(
            (f"{kept_len} = 0", self.partial(s, {"keep_head": 3, "keep_tail": 0})),
            (f"{kept_len} < {self.length(s)}", self.cat(kept, _q(fill)) if fill else kept),
            default=kept,
        )

    def date_year(self, c: str, p: dict) -> str:
        s = self.trim(c)
        g = "(" if self.ora else "(?:"
        wareki = f"^{g}明治|大正|昭和|平成|令和|[MTSHR])[ 　]*[0-9０-９元]{{1,2}}[ 　]*年?"
        return self.case(
            (self.rx_like(s, f"^{_D}{{4}}"), self.cat(self.substr(s, 1, 4), self.mask_digits(self.substr(s, 5)))),
            (self.rx_like(s, wareki), self.cat(self.rx_substr(s, wareki), "'＊＊月＊＊日'")),
            default=self.mask_all(s),
        )

    def round_number(self, c: str, p: dict) -> str:
        d = int(p.get("digits", -3) or 0)
        num_re = "^-?[0-9]+(\\.[0-9]+)?$"
        if self.ora:
            return self.case((self.rx_like(c, num_re), f"TO_CHAR(ROUND(TO_NUMBER({c}), {d}))"), default=self.mask_all(c))
        return self.case((self.rx_like(c, num_re), f"round(({c})::numeric, {d})::text"), default=self.mask_all(c))

    def hash(self, c: str, p: dict) -> str:
        n = max(4, min(int(p.get("length", 16) or 16), 64))
        h = self.sha256_hex(c)
        return f"LOWER(SUBSTR({h}, 1, {n}))" if self.ora else f"substr({h}, 1, {n})"

    def fake_name(self, c: str, p: dict) -> str:
        idx = 1 if p.get("kind") == "kana" else 0
        sep = p.get("separator", "　")
        h = self.sha256_hex(c)

        def pick(names: list[tuple[str, str]], byte: int) -> str:
            if self.ora:
                b = f"MOD(TO_NUMBER(SUBSTR({h}, {byte * 2 + 1}, 2), 'XX'), {len(names)})"
                return "CASE " + b + " " + " ".join(f"WHEN {i} THEN {_q(n[idx])}" for i, n in enumerate(names)) + " END"
            arr = "ARRAY[" + ", ".join(_q(n[idx]) for n in names) + "]"
            return f"({arr})[get_byte(decode({h}, 'hex'), {byte}) % {len(names)} + 1]"

        return self.cat(pick(_FAKE_SEI, 0), _q(sep) if sep else "", pick(_FAKE_MEI, 1))

    def fixed(self, c: str, p: dict) -> str:
        return _q(str(p.get("value", "＊＊＊")))

    def text_pii(self, c: str, p: dict) -> str:
        """文中の個人情報（簡易版）。

        メールアドレス・電話番号・郵便番号・10 桁以上の数字・敬称（様・さん等）の前の漢字のみ。
        Python 版より検出範囲が狭く、「お客様」等も伏せる（多めに伏せる側に倒す）。
        """
        e = self.rx_replace(c, "[一-龥々]{1,4}(様|さま|殿|さん|氏)", "'＊＊\\1'")
        e = self.rx_replace(e, "[A-Za-z0-9._%+-]+@", "'***@'")
        e = self.rx_replace(e, "0[0-9]{1,4}[-(（][0-9]{1,4}[-)）]([0-9]{3,4})", "'**-****-\\1'")
        e = self.rx_replace(e, "(〒 ?[0-9]{3})-?[0-9]{4}", "'\\1-****'")
        return self.rx_replace(e, "[0-9]{10,}", "'**********'")

    def build(self, rule: MaskRule, c: str) -> str:
        fn = getattr(self, rule.type, None)
        if fn is None or rule.type in ("build", "case", "cat"):
            raise ValueError(f"UPDATE 文に変換できない規則です: {rule.type}")
        return fn(c, rule.params or {})


def _fit_expr(eb: ExprBuilder, expr: str, col: SqlColumn) -> str:
    if not col.max_len or col.is_lob:
        return expr
    if eb.ora:
        return f"{'SUBSTRB' if col.byte_semantics else 'SUBSTR'}({expr}, 1, {col.max_len})"
    return f"left({expr}, {col.max_len})"


def update_expr(db_type: str, plan: ColumnPlan, quoted: str, salt: str = "") -> str | None:
    """1 列分の SET 句の右辺。変更しない列は None。"""
    eb = ExprBuilder(db_type, salt)
    col = plan.col
    if plan.action == "keep":
        return None
    if plan.action == "null":
        return "NULL"
    if plan.action == "const":
        return f"CASE WHEN {quoted} IS NULL THEN NULL ELSE {literal(db_type, col, plan.const)} END" if col.nullable else literal(db_type, col, plan.const)
    if plan.action == "trunc_year":
        if eb.ora:
            return f"TRUNC({quoted}, 'YYYY')"
        return f"date_trunc('year', {quoted})::date" if col.tclass == "date" else f"date_trunc('year', {quoted})"
    if plan.action == "numhash":
        h = eb.sha256_hex(f"TO_CHAR({quoted})" if eb.ora else f"({quoted})::text")
        if eb.ora:
            return f"MOD(TO_NUMBER(SUBSTR({h}, 1, 15), 'XXXXXXXXXXXXXXX'), {10 ** plan.const})"
        return f"(('x' || substr({h}, 1, 15))::bit(60)::bigint % {10 ** plan.const})"
    rule = plan.rule
    assert rule is not None
    if col.tclass == "number":  # round_number のみ
        d = int(rule.params.get("digits", -3) or 0)
        return f"ROUND({quoted}, {d})" if eb.ora else f"round(({quoted})::numeric, {d})"
    expr = eb.build(rule, quoted)
    expr = _fit_expr(eb, expr, col)
    return f"CASE WHEN {quoted} IS NULL THEN NULL ELSE {expr} END"


def wrap_sql(sql: str, width: int = 160) -> str:
    """長い行を、文字列リテラルの外にある空白で折り返す（SQL*Plus の行長制限対策）。

    データを含まない SQL（UPDATE 文）にのみ使う（リテラル内の改行を考慮しないため）。
    """
    out: list[str] = []
    for line in sql.split("\n"):
        if len(line) <= width:
            out.append(line)
            continue
        indent = " " * min(len(line) - len(line.lstrip()) + 4, 12)
        current, in_quote = "", False
        for ch in line:
            if ch == "'":
                in_quote = not in_quote
            if ch == " " and not in_quote and len(current) >= width:
                out.append(current.rstrip())
                current = indent
                continue
            current += ch
        out.append(current)
    return "\n".join(out)
