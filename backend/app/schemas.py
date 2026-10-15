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
    suggested_mask: MaskRule | None = None


# ---------------------------------------------------------------------------
# マスキング・エクスポート
# ---------------------------------------------------------------------------


class MaskRule(BaseModel):
    """列に適用するマスキング規則。type の一覧は masking.RULE_DEFINITIONS 参照。"""

    type: str = "none"
    params: dict[str, Any] = Field(default_factory=dict)


ColumnInfo.model_rebuild()


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


class ExportOptions(BaseModel):
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
