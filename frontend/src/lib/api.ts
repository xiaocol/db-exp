// FastAPI との通信処理
import type {
  ColumnInfo,
  ConnectionInput,
  ConnectionProfile,
  ConnectResult,
  DbScanStatus,
  Decisions,
  DocScanResult,
  ExportJobStatus,
  Finding,
  ExportOptions,
  MaskRule,
  MaskRuleDef,
  PreviewResult,
  TableExportSpec,
  TableInfo,
} from './types'

/** API エラー（サーバーから返された日本語メッセージを保持） */
export class ApiError extends Error {}

async function send(method: string, url: string, body?: unknown): Promise<Response> {
  const form = body instanceof FormData
  const res = await fetch(url, {
    method,
    headers: {
      // FormData の場合は境界文字列付きの Content-Type をブラウザに設定させる
      ...(form ? {} : { 'Content-Type': 'application/json' }),
      // CSRF 対策用ヘッダー（サーバー側で必須チェックしている）
      'X-DBEXP': '1',
    },
    body: body === undefined ? undefined : form ? body : JSON.stringify(body),
  })
  if (!res.ok) {
    let message = `通信エラーが発生しました（${res.status}）`
    try {
      const data = await res.json()
      if (typeof data.detail === 'string') {
        message = data.detail
      } else if (Array.isArray(data.detail)) {
        // Pydantic の入力チェックエラー
        message = '入力内容に誤りがあります: ' + data.detail.map((d: { msg: string }) => d.msg).join(' / ')
      }
    } catch {
      // JSON 以外の応答はそのまま既定メッセージを使う
    }
    throw new ApiError(message)
  }
  return res
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const res = await send(method, url, body)
  return (await res.json()) as T
}

/** Content-Disposition からファイル名を取り出す（RFC 5987 の日本語名に対応） */
function fileNameOf(res: Response, fallback: string): string {
  const cd = res.headers.get('content-disposition') ?? ''
  const star = /filename\*=(?:UTF-8|utf-8)''([^;]+)/.exec(cd)
  if (star) return decodeURIComponent(star[1])
  const plain = /filename="?([^";]+)"?/.exec(cd)
  return plain ? plain[1] : fallback
}

/** POST の応答（ファイル）をダウンロードさせる */
async function downloadPost(url: string, body: unknown, fallback: string): Promise<void> {
  const res = await send('POST', url, body)
  const blob = await res.blob()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = fileNameOf(res, fallback)
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(a.href), 10_000)
}

const q = (params: Record<string, string>) => new URLSearchParams(params).toString()

export const api = {
  // ---- 接続 ----
  listConnections: () => request<ConnectionProfile[]>('GET', '/api/connections'),
  saveConnection: (inp: ConnectionInput) => request<ConnectionProfile>('POST', '/api/connections', inp),
  deleteConnection: (id: string) => request<{ ok: boolean }>('DELETE', `/api/connections/${id}`),
  testConnection: (inp: ConnectionInput) => request<ConnectResult>('POST', '/api/connections/test', inp),
  connect: (id: string, password?: string) =>
    request<ConnectResult>('POST', `/api/connections/${id}/connect`, { password: password || null }),
  disconnect: (id: string) => request<{ ok: boolean }>('POST', `/api/connections/${id}/disconnect`),

  // ---- メタデータ ----
  listSchemas: (id: string) =>
    request<{ schemas: string[]; default: string }>('GET', `/api/connections/${id}/schemas`),
  listTables: (id: string, schema: string) =>
    request<TableInfo[]>('GET', `/api/connections/${id}/tables?${q({ schema })}`),
  /** sample > 0 なら先頭 sample 件の値も使って自動判定する */
  listColumns: (id: string, schema: string, table: string, sample = 0) =>
    request<ColumnInfo[]>('GET', `/api/connections/${id}/columns?${q({ schema, table, sample: String(sample) })}`),

  // ---- 自動判定（DB の一括スキャン） ----
  startScan: (id: string, schema_name: string, tables: string[] | null, sample_rows = 200) =>
    request<DbScanStatus>('POST', `/api/connections/${id}/scan`, { schema_name, tables, sample_rows }),
  scanStatus: (jobId: string) => request<DbScanStatus>('GET', `/api/scan/${jobId}`),
  cancelScan: (jobId: string) => request<DbScanStatus>('POST', `/api/scan/${jobId}/cancel`),

  // ---- 自動判定（ドキュメント） ----
  scanDocuments: (files: { file: File; name: string }[]) => {
    const form = new FormData()
    files.forEach((f) => form.append('files', f.file, f.name))
    return request<DocScanResult>('POST', '/api/documents/scan', form)
  },
  exportDocuments: (scanId: string, decisions: Decisions, hash_salt: string) =>
    downloadPost(`/api/documents/${scanId}/export`, { decisions, hash_salt }, 'マスキング済み.zip'),
  deleteDocuments: (scanId: string) => request<{ ok: boolean }>('DELETE', `/api/documents/${scanId}`),

  // ---- 判定結果一覧（Excel） ----
  downloadReport: (findings: Finding[], decisions: Decisions, title: string, source_label: string) =>
    downloadPost('/api/report', { findings, decisions, title, source_label }, `${title}.xlsx`),

  // ---- マスキング ----
  maskingRules: () => request<MaskRuleDef[]>('GET', '/api/masking/rules'),
  maskingTest: (rule: MaskRule, value: string, hash_salt: string) =>
    request<{ result: unknown }>('POST', '/api/masking/test', { rule, value, hash_salt }),

  // ---- プレビュー・エクスポート ----
  preview: (connection_id: string, table: TableExportSpec, options: ExportOptions, limit = 50) =>
    request<PreviewResult>('POST', '/api/preview', { connection_id, table, options, limit }),
  startExport: (connection_id: string, tables: TableExportSpec[], file_name: string, options: ExportOptions) =>
    request<ExportJobStatus>('POST', '/api/export', {
      connection_id,
      tables,
      file_name: file_name || null,
      options,
    }),
  exportStatus: (jobId: string) => request<ExportJobStatus>('GET', `/api/export/${jobId}`),
  cancelExport: (jobId: string) => request<ExportJobStatus>('POST', `/api/export/${jobId}/cancel`),
  downloadUrl: (jobId: string) => `/api/export/${jobId}/download`,
}

/** エラーオブジェクトから表示用メッセージを取り出す */
export function errorMessage(e: unknown): string {
  if (e instanceof Error) return e.message
  return String(e)
}
