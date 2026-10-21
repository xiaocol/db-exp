"""API の入出力モデル（Pydantic）。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

DbType = Literal["oracle", "postgresql"]


# ---------------------------------------------------------------------------
# 接続
# ---------------------------------------------------------------------------


class ConnectionBase(BaseModel):
    """接続プロファイルの共通項目。"""

    name: str = Field(..., min_length=1, max_length=100, description="表示名")
    db_type: DbType = "oracle"
    host: str = ""
    port: int | None = None
    # Oracle: サービス名 or SID / PostgreSQL: データベース名
    database: str = ""
    # Oracle の接続方式
    #   service_name : host:port/service_name
    #   sid          : host:port:SID
    #   dsn          : TNS 名や EZConnect 文字列を直接指定
    oracle_connect_type: Literal["service_name", "sid", "dsn"] = "service_name"
    dsn: str = ""
    username: str = ""
    save_password: bool = False


class ConnectionInput(ConnectionBase):
    """作成・更新・接続テスト時の入力。"""

    id: str | None = None
    password: str | None = None


class ConnectionProfile(ConnectionBase):
    """保存済み接続プロファイル（パスワードは返さない）。"""

    id: str
    has_saved_password: bool = False
    connected: bool = False


class ConnectRequest(BaseModel):
    password: str | None = None


class ConnectResult(BaseModel):
    ok: bool
    message: str
    server_version: str | None = None


# ---------------------------------------------------------------------------
# メタデータ
# ---------------------------------------------------------------------------


class TableInfo(BaseModel):
    schema_name: str
    name: str
    table_type: str  # TABLE / VIEW / MVIEW など
    comment: str | None = None
    num_rows: int | None = None  # 統計情報上の概算件数


class ColumnInfo(BaseModel):
    name: str
    comment: str | None = None  # 論理名として扱う
    data_type: str
    nullable: bool = True
    is_pk: bool = False
    position: int
    # 自動判定で「マスキング対象」となった場合の推奨規則（要確認の場合は None）
    suggested_mask: MaskRule | None = None
    # 自動判定の結果（対象外なら None）
    suggestion: Suggestion | None = None


class Suggestion(BaseModel):
    """列名・論理名・値の特徴による自動判定の結果。"""

    category: str
    label: str
    score: float
    level: Literal["auto", "review"]
    rule: MaskRule
    reasons: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# マスキング・エクスポート
# ---------------------------------------------------------------------------


class MaskRule(BaseModel):
    """列に適用するマスキング規則。type の一覧は masking.RULE_DEFINITIONS 参照。"""

    type: str = "none"
    params: dict[str, Any] = Field(default_factory=dict)


ColumnInfo.model_rebuild()
Suggestion.model_rebuild()


class ColumnSpec(BaseModel):
    name: str
    mask: MaskRule | None = None
    # 出力時の見出しを任意に上書きする場合に指定
    header: str | None = None


class TableExportSpec(BaseModel):
    schema_name: str
    table: str
    columns: list[ColumnSpec] = Field(..., min_length=1)
    where: str | None = None
    order_by: str | None = None
    max_rows: int | None = Field(default=None, ge=1)
    sheet_name: str | None = None


HeaderMode = Literal["physical", "logical", "both"]


ExportFormat = Literal["xlsx", "sql_insert", "sql_update"]


class ExportOptions(BaseModel):
    # 出力形式: xlsx=Excel / sql_insert=マスク済みデータの INSERT 文 / sql_update=テスト環境をマスクする UPDATE 文
    format: ExportFormat = "xlsx"
    # 見出し: physical=物理名 / logical=論理名(コメント) / both=2行（論理名＋物理名）
    header_mode: HeaderMode = "logical"
    font_name: str = "游ゴシック"
    font_size: float = 11
    # 「エクスポート情報」シートを付与するか（監査用）
    include_info_sheet: bool = True
    # 件数を事前に COUNT(*) して進捗率を表示するか
    count_rows: bool = True
    # ハッシュ化マスクのソルト（同じソルトなら同じ値は同じハッシュ）
    hash_salt: str = ""
    # 日付の表示書式
    date_format: str = "yyyy/mm/dd"
    datetime_format: str = "yyyy/mm/dd hh:mm:ss"
    # ---- SQL 出力（sql_insert / sql_update）----
    # 出力する SQL の表名に付けるスキーマ名（空欄=元のスキーマ名、sql_qualify_schema=False なら付けない）
    sql_target_schema: str = ""
    sql_qualify_schema: bool = True
    # INSERT 文: 何件ごとに COMMIT するか（0=最後に 1 回）
    sql_commit_every: int = Field(default=1000, ge=0)
    # INSERT 文: 先頭に既存データを削除する DELETE 文を付けるか
    sql_delete_before_insert: bool = False
    # 文字コード（SQL*Plus を Shift_JIS 環境で使う場合は cp932）
    sql_encoding: Literal["utf-8", "cp932"] = "utf-8"


class ExportRequest(BaseModel):
    connection_id: str
    tables: list[TableExportSpec] = Field(..., min_length=1)
    file_name: str | None = None
    options: ExportOptions = Field(default_factory=ExportOptions)


class PreviewRequest(BaseModel):
    connection_id: str
    table: TableExportSpec
    limit: int = Field(default=50, ge=1, le=500)
    options: ExportOptions = Field(default_factory=ExportOptions)


class PreviewResult(BaseModel):
    columns: list[str]
    rows: list[list[Any]]


class MaskTestRequest(BaseModel):
    rule: MaskRule
    value: str | None
    hash_salt: str = ""


class TableProgress(BaseModel):
    schema_name: str
    table: str
    rows_written: int = 0
    total_rows: int | None = None
    status: Literal["pending", "running", "done", "error"] = "pending"


class ExportJobStatus(BaseModel):
    job_id: str
    status: Literal["pending", "running", "done", "error", "cancelled"]
    message: str | None = None
    file_name: str
    tables: list[TableProgress]
    started_at: str | None = None
    finished_at: str | None = None


# ---------------------------------------------------------------------------
# 判定結果（マスキング対象一覧・要確認一覧）
# ---------------------------------------------------------------------------


class Finding(BaseModel):
    """自動判定で見つかったマスキング対象（または要確認）の 1 件。"""

    id: str
    source: Literal["db", "doc"]
    # column=列全体 / text=文章中の語句
    target: Literal["column", "text"]
    level: Literal["auto", "review"]
    category: str
    category_label: str
    score: float
    reasons: list[str] = Field(default_factory=list)
    rule: MaskRule
    # 場所（DB: file="スキーマ.表"、ドキュメント: file=ファイル名 / location=シート・行など）
    file: str
    location: str | None = None
    column: str | None = None
    column_comment: str | None = None
    data_type: str | None = None
    is_pk: bool = False
    # 要確認の文中語句（target=text の場合）
    text: str | None = None
    occurrences: int = 1
    # 画面で人が判断するための元の値（ファイル・一覧には出力しない）
    samples: list[str] = Field(default_factory=list)
    # マスク後の例（一覧の出力にも使う）
    masked_samples: list[str] = Field(default_factory=list)


class Decision(BaseModel):
    """人の判断。mask=False なら「マスクしない」。"""

    mask: bool = True
    rule: MaskRule | None = None


class DbScanRequest(BaseModel):
    schema_name: str
    # 対象の表（省略時はスキーマ内の全表・ビュー）
    tables: list[str] | None = None
    sample_rows: int = Field(default=200, ge=10, le=5000)


class ScannedTable(BaseModel):
    schema_name: str
    table: str
    table_type: str = "TABLE"
    comment: str | None = None
    columns: list[ColumnInfo] = Field(default_factory=list)
    sampled_rows: int = 0
    error: str | None = None


class DbScanStatus(BaseModel):
    job_id: str
    status: Literal["pending", "running", "done", "error", "cancelled"]
    message: str | None = None
    schema_name: str
    total_tables: int = 0
    done_tables: int = 0
    current_table: str | None = None
    tables: list[ScannedTable] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)


class DocFileInfo(BaseModel):
    name: str
    kind: str
    size: int
    blocks: int = 0
    tables: int = 0
    lines: int = 0
    error: str | None = None


class DocScanResult(BaseModel):
    scan_id: str
    files: list[DocFileInfo]
    findings: list[Finding]


class DocExportRequest(BaseModel):
    decisions: dict[str, Decision] = Field(default_factory=dict)
    hash_salt: str = ""


class ReportRequest(BaseModel):
    title: str = "マスキング判定結果"
    source_label: str | None = None
    findings: list[Finding]
    decisions: dict[str, Decision] = Field(default_factory=dict)
