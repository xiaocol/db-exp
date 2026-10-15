// FastAPI との通信処理
import type {
  ColumnInfo,
  ConnectionInput,
  ConnectionProfile,
  ConnectResult,
  ExportJobStatus,
  ExportOptions,
  MaskRule,
  MaskRuleDef,
  PreviewResult,
  TableExportSpec,
  TableInfo,
} from './types'

/** API エラー（サーバーから返された日本語メッセージを保持） */
export class ApiError extends Error {}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: {
      'Content-Type': 'application/json',
      // CSRF 対策用ヘッダー（サーバー側で必須チェックしている）
      'X-DBEXP': '1',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
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
  return (await res.json()) as T
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
  listColumns: (id: string, schema: string, table: string) =>
    request<ColumnInfo[]>('GET', `/api/connections/${id}/columns?${q({ schema, table })}`),

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
