// バックエンド（FastAPI）の入出力モデルに対応する型定義

export type DbType = 'oracle' | 'postgresql'
export type OracleConnectType = 'service_name' | 'sid' | 'dsn'

export interface ConnectionProfile {
  id: string
  name: string
  db_type: DbType
  host: string
  port: number | null
  database: string
  oracle_connect_type: OracleConnectType
  dsn: string
  username: string
  save_password: boolean
  has_saved_password: boolean
  connected: boolean
}

export interface ConnectionInput extends Omit<ConnectionProfile, 'id' | 'has_saved_password' | 'connected'> {
  id?: string | null
  password?: string | null
}

export interface ConnectResult {
  ok: boolean
  message: string
  server_version?: string | null
}

export interface TableInfo {
  schema_name: string
  name: string
  table_type: string
  comment: string | null
  num_rows: number | null
}

export interface MaskRule {
  type: string
  params: Record<string, unknown>
}

export interface ColumnInfo {
  name: string
  comment: string | null
  data_type: string
  nullable: boolean
  is_pk: boolean
  position: number
  suggested_mask: MaskRule | null
}

export interface MaskParamDef {
  key: string
  label: string
  kind: 'text' | 'number' | 'select'
  default: string | number
  options?: { value: string; label: string }[]
}

export interface MaskRuleDef {
  type: string
  label: string
  example: string
  params: MaskParamDef[]
}

export interface ColumnSpec {
  name: string
  mask: MaskRule | null
  header?: string | null
}

export interface TableExportSpec {
  schema_name: string
  table: string
  columns: ColumnSpec[]
  where?: string | null
  order_by?: string | null
  max_rows?: number | null
  sheet_name?: string | null
}

export type HeaderMode = 'physical' | 'logical' | 'both'

export interface ExportOptions {
  header_mode: HeaderMode
  font_name: string
  font_size: number
  include_info_sheet: boolean
  count_rows: boolean
  hash_salt: string
  date_format: string
  datetime_format: string
}

export interface PreviewResult {
  columns: string[]
  rows: unknown[][]
}

export interface TableProgress {
  schema_name: string
  table: string
  rows_written: number
  total_rows: number | null
  status: 'pending' | 'running' | 'done' | 'error'
}

export interface ExportJobStatus {
  job_id: string
  status: 'pending' | 'running' | 'done' | 'error' | 'cancelled'
  message: string | null
  file_name: string
  tables: TableProgress[]
  started_at: string | null
  finished_at: string | null
}

/** 画面上で編集中の列（出力対象チェック・マスキング設定を含む） */
export interface EditableColumn extends ColumnInfo {
  include: boolean
  mask: MaskRule
  header: string
}

/** エクスポート対象リストの 1 件 */
export interface QueueItem {
  id: string
  spec: TableExportSpec
  tableComment: string | null
}

/** 設定ファイル（JSON）として保存・読込する内容 */
export interface SavedSettings {
  version: 1
  db_type: DbType
  file_name: string
  options: ExportOptions
  tables: TableExportSpec[]
}
