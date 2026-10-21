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
  /** 自動判定で「マスキング対象」となった場合の推奨規則（要確認なら null） */
  suggested_mask: MaskRule | null
  suggestion?: Suggestion | null
}

/** 列名・論理名・値の特徴による自動判定の結果 */
export interface Suggestion {
  category: string
  label: string
  score: number
  level: FindingLevel
  rule: MaskRule
  reasons: string[]
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
export type ExportFormat = 'xlsx' | 'sql_insert' | 'sql_update'

export interface ExportOptions {
  format: ExportFormat
  header_mode: HeaderMode
  font_name: string
  font_size: number
  include_info_sheet: boolean
  count_rows: boolean
  hash_salt: string
  date_format: string
  datetime_format: string
  sql_target_schema: string
  sql_qualify_schema: boolean
  sql_commit_every: number
  sql_delete_before_insert: boolean
  sql_encoding: 'utf-8' | 'cp932'
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

// ---------------------------------------------------------------------------
// 自動判定（マスキング対象一覧・要確認一覧）
// ---------------------------------------------------------------------------

export type FindingLevel = 'auto' | 'review'

/** 自動判定で見つかったマスキング対象（または要確認）の 1 件 */
export interface Finding {
  id: string
  source: 'db' | 'doc'
  /** column=列全体 / text=文章中の語句 */
  target: 'column' | 'text'
  level: FindingLevel
  category: string
  category_label: string
  score: number
  reasons: string[]
  rule: MaskRule
  file: string
  location: string | null
  column: string | null
  column_comment: string | null
  data_type: string | null
  is_pk: boolean
  text: string | null
  occurrences: number
  samples: string[]
  masked_samples: string[]
}

/** 人の判断。mask=false なら「マスクしない」 */
export interface Decision {
  mask: boolean
  rule: MaskRule | null
}

export type Decisions = Record<string, Decision>

export interface ScannedTable {
  schema_name: string
  table: string
  table_type: string
  comment: string | null
  columns: ColumnInfo[]
  sampled_rows: number
  error: string | null
}

export interface DbScanStatus {
  job_id: string
  status: 'pending' | 'running' | 'done' | 'error' | 'cancelled'
  message: string | null
  schema_name: string
  total_tables: number
  done_tables: number
  current_table: string | null
  tables: ScannedTable[]
  findings: Finding[]
}

export interface DocFileInfo {
  name: string
  kind: string
  size: number
  blocks: number
  tables: number
  lines: number
  error: string | null
}

export interface DocScanResult {
  scan_id: string
  files: DocFileInfo[]
  findings: Finding[]
}
