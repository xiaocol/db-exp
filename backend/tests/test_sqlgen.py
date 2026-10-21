"""SQL 出力（リテラル・型に合わせた置き換え・UPDATE 式）の単体テスト。"""

import datetime as dt
from decimal import Decimal

import pytest

from app import sqlgen
from app.schemas import ColumnInfo, MaskRule


def col(data_type, db="oracle", nullable=True, is_pk=False, name="C"):
    return sqlgen.classify(db, ColumnInfo(name=name, data_type=data_type, nullable=nullable, is_pk=is_pk, position=1))


def rule(t, **p):
    return MaskRule(type=t, params=p)


def test_classify_lengths():
    c = col("VARCHAR2(20)")
    assert (c.tclass, c.max_len, c.byte_semantics) == ("text", 20, True)
    c = col("VARCHAR2(20 CHAR)")
    assert (c.max_len, c.byte_semantics) == (20, False)
    assert col("NVARCHAR2(10)").national
    assert col("character varying(30)", "postgresql").max_len == 30
    assert col("NUMBER(10,2)").num_digits == 8
    assert col("integer", "postgresql").num_digits == 9
    assert col("timestamp(6) with time zone", "postgresql").tclass == "timestamptz"


def test_text_is_truncated_to_byte_length():
    plan = sqlgen.plan_column(col("VARCHAR2(10)"), rule("fake_name"), "s")
    out = sqlgen.apply_plan(plan, "山田太郎")
    assert len(out.encode("utf-8")) <= 10


def test_number_and_date_fallbacks():
    plan = sqlgen.plan_column(col("NUMBER(10)"), rule("full"))
    assert plan.action == "null" and plan.note
    plan = sqlgen.plan_column(col("NUMBER(10)", nullable=False), rule("full"))
    assert plan.action == "const" and plan.const == 0
    plan = sqlgen.plan_column(col("DATE"), rule("date_year"))
    assert sqlgen.apply_plan(plan, dt.datetime(1985, 4, 1, 10)) == dt.datetime(1985, 1, 1)
    plan = sqlgen.plan_column(col("NUMBER(8)"), rule("hash"), "s")
    v = sqlgen.apply_plan(plan, Decimal(12345))
    assert plan.action == "numhash" and 0 <= v < 10**8
    assert v == sqlgen.apply_plan(plan, Decimal(12345))


def test_primary_key_is_kept_when_rule_does_not_fit():
    plan = sqlgen.plan_column(col("NUMBER(10)", nullable=False, is_pk=True), rule("hash"))
    assert plan.action == "keep" and "主キー" in plan.note


def test_not_null_text_column_with_null_rule():
    plan = sqlgen.plan_column(col("VARCHAR2(20)", nullable=False), rule("null"))
    assert sqlgen.apply_plan(plan, "x") == "＊"


@pytest.mark.parametrize(
    ("db", "data_type", "value", "expected"),
    [
        ("oracle", "VARCHAR2(10)", "It's", "'It''s'"),
        ("oracle", "NVARCHAR2(10)", "山田", "N'山田'"),
        ("oracle", "DATE", dt.datetime(2024, 1, 2, 3, 4, 5), "TO_DATE('2024-01-02 03:04:05', 'YYYY-MM-DD HH24:MI:SS')"),
        ("oracle", "NUMBER", Decimal("1.50"), "1.50"),
        ("oracle", "RAW(4)", b"\x01\xff", "HEXTORAW('01FF')"),
        ("postgresql", "text", "a\\b", "'a\\b'"),
        ("postgresql", "date", dt.date(2024, 1, 2), "'2024-01-02'"),
        ("postgresql", "boolean", True, "TRUE"),
        ("postgresql", "bytea", b"\x01", "'\\x01'"),
        ("postgresql", "text[]", ["a", 'b"c', None], '\'{"a","b\\"c",NULL}\''),
        ("postgresql", "jsonb", {"k": "値"}, "'{\"k\": \"値\"}'"),
    ],
)
def test_literal(db, data_type, value, expected):
    assert sqlgen.literal(db, col(data_type, db), value) == expected


def test_long_oracle_text_is_split():
    lit = sqlgen.literal("oracle", col("CLOB"), "あ" * 1200)
    assert lit.count("TO_CLOB(") == 3
    assert all(len(line) < 1000 for line in lit.split("\n"))


def test_update_expr_keeps_nulls_and_fits_length():
    plan = sqlgen.plan_column(col("VARCHAR2(20)"), rule("name"))
    expr = sqlgen.update_expr("oracle", plan, '"C"')
    assert expr.startswith('CASE WHEN "C" IS NULL THEN NULL') and "SUBSTRB(" in expr
    plan = sqlgen.plan_column(col("varchar(20)", "postgresql"), rule("email"))
    assert "left(" in sqlgen.update_expr("postgresql", plan, '"c"')


def test_wrap_sql_does_not_break_literals():
    sql = "SELECT " + ", ".join(f"'a b c {i}'" for i in range(100))
    wrapped = sqlgen.wrap_sql(sql, 80)
    assert wrapped.replace("\n", " ").count("'a b c 99'") == 1
    assert all(line.count("'") % 2 == 0 for line in wrapped.split("\n"))
