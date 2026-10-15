// 画面全体のレイアウトと状態管理
//   左: 接続先・テーブル選択 / 中央: 列とマスキングの設定 / 右: エクスポートリストと出力
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { DatabaseZapIcon, Loader2Icon, MousePointerClickIcon } from 'lucide-react'

import { ColumnEditor, EMPTY_TABLE_OPTIONS, type TableOptions } from '@/components/ColumnEditor'
import { ConnectionPanel } from '@/components/ConnectionPanel'
import { ExportPanel } from '@/components/ExportPanel'
import { TableBrowser } from '@/components/TableBrowser'
import { Separator } from '@/components/ui/separator'
import { api, errorMessage } from '@/lib/api'
import type {
  ConnectionProfile,
  EditableColumn,
  ExportOptions,
  MaskRuleDef,
  QueueItem,
  SavedSettings,
  TableExportSpec,
  TableInfo,
} from '@/lib/types'

const DEFAULT_OPTIONS: ExportOptions = {
  header_mode: 'logical',
  font_name: '游ゴシック',
  font_size: 11,
  include_info_sheet: true,
  count_rows: true,
  hash_salt: '',
  date_format: 'yyyy/mm/dd',
  datetime_format: 'yyyy/mm/dd hh:mm:ss',
}

const newId = () => Math.random().toString(36).slice(2, 10)

export default function App() {
  // ---- 接続 ----
  const [connections, setConnections] = useState<ConnectionProfile[]>([])
  const [active, setActive] = useState<ConnectionProfile | null>(null)
  const [rules, setRules] = useState<MaskRuleDef[]>([])

  // ---- スキーマ・テーブル ----
  const [schemas, setSchemas] = useState<string[]>([])
  const [schema, setSchema] = useState<string | null>(null)
  const [tables, setTables] = useState<TableInfo[]>([])
  const [tablesLoading, setTablesLoading] = useState(false)

  // ---- 列設定（中央） ----
  const [table, setTable] = useState<TableInfo | null>(null)
  const [columns, setColumns] = useState<EditableColumn[]>([])
  const [columnsLoading, setColumnsLoading] = useState(false)
  const [tableOptions, setTableOptions] = useState<TableOptions>(EMPTY_TABLE_OPTIONS)
  const [editingId, setEditingId] = useState<string | null>(null)

  // ---- エクスポート（右） ----
  const [queue, setQueue] = useState<QueueItem[]>([])
  const [options, setOptions] = useState<ExportOptions>(DEFAULT_OPTIONS)
  const [fileName, setFileName] = useState('')

  const reloadConnections = useCallback(async () => {
    try {
      setConnections(await api.listConnections())
    } catch (e) {
      toast.error('接続一覧を取得できません', { description: errorMessage(e) })
    }
  }, [])

  useEffect(() => {
    void reloadConnections()
    api.maskingRules().then(setRules).catch((e) => toast.error(errorMessage(e)))
  }, [reloadConnections])

  const loadTables = async (connId: string, s: string) => {
    setSchema(s)
    setTablesLoading(true)
    try {
      setTables(await api.listTables(connId, s))
    } catch (e) {
      setTables([])
      toast.error('テーブル一覧を取得できません', { description: errorMessage(e) })
    } finally {
      setTablesLoading(false)
    }
  }

  const resetWorkspace = () => {
    setSchemas([])
    setSchema(null)
    setTables([])
    setTable(null)
    setColumns([])
    setEditingId(null)
    setQueue([])
  }

  const handleConnected = async (profile: ConnectionProfile) => {
    // 接続先を切り替えた場合、エクスポートリストは別DBのものになるためクリアする
    resetWorkspace()
    setActive(profile)
    try {
      const res = await api.listSchemas(profile.id)
      setSchemas(res.schemas.includes(res.default) ? res.schemas : [res.default, ...res.schemas])
      await loadTables(profile.id, res.default)
    } catch (e) {
      toast.error('スキーマ一覧を取得できません', { description: errorMessage(e) })
    }
  }

  const handleDisconnected = () => {
    resetWorkspace()
    setActive(null)
  }

  /** 表の列情報を読み込み、編集状態を作る。spec 指定時はその設定を反映する */
  const openTable = async (t: TableInfo, spec?: TableExportSpec, queueId?: string) => {
    if (!active) return
    setTable(t)
    setColumnsLoading(true)
    try {
      const cols = await api.listColumns(active.id, t.schema_name, t.name)
      if (spec) {
        const byName = new Map(spec.columns.map((c) => [c.name, c]))
        setColumns(
          cols.map((c) => {
            const s = byName.get(c.name)
            return {
              ...c,
              include: !!s,
              mask: s?.mask ?? { type: 'none', params: {} },
              header: s?.header ?? '',
            }
          }),
        )
        setTableOptions({
          where: spec.where ?? '',
          order_by: spec.order_by ?? '',
          max_rows: spec.max_rows ? String(spec.max_rows) : '',
          sheet_name: spec.sheet_name ?? '',
        })
        setEditingId(queueId ?? null)
      } else {
        // 安全側に倒すため、個人情報と推定される列には初期状態でマスキングを設定する
        const suggested = cols.filter((c) => c.suggested_mask).length
        setColumns(
          cols.map((c) => ({
            ...c,
            include: true,
            mask: c.suggested_mask ?? { type: 'none', params: {} },
            header: '',
          })),
        )
        setTableOptions(EMPTY_TABLE_OPTIONS)
        setEditingId(null)
        if (suggested > 0) {
          toast.info(`個人情報の可能性がある ${suggested} 列にマスキングを自動設定しました。`, {
            description: '内容を確認し、必要に応じて変更してください。',
          })
        }
      }
    } catch (e) {
      setTable(null)
      setColumns([])
      toast.error('列情報を取得できません', { description: errorMessage(e) })
    } finally {
      setColumnsLoading(false)
    }
  }

  const handleAddToQueue = (spec: TableExportSpec) => {
    if (editingId) {
      setQueue((q) => q.map((item) => (item.id === editingId ? { ...item, spec } : item)))
      setEditingId(null)
      toast.success('エクスポートリストを更新しました。')
    } else {
      setQueue((q) => [...q, { id: newId(), spec, tableComment: table?.comment ?? null }])
      toast.success(`${spec.table} をエクスポートリストに追加しました。`)
    }
  }

  const handleEditQueueItem = (item: QueueItem) => {
    const t: TableInfo = tables.find((x) => x.schema_name === item.spec.schema_name && x.name === item.spec.table) ?? {
      schema_name: item.spec.schema_name,
      name: item.spec.table,
      table_type: 'TABLE',
      comment: item.tableComment,
      num_rows: null,
    }
    void openTable(t, item.spec, item.id)
  }

  const handleLoadSettings = (data: SavedSettings) => {
    if (active && data.db_type !== active.db_type) {
      toast.warning('設定ファイルのDB種別が現在の接続と異なります。', { description: '列名等が一致しない場合はエクスポート時にエラーになります。' })
    }
    setQueue(data.tables.map((spec) => ({ id: newId(), spec, tableComment: null })))
    setOptions({ ...DEFAULT_OPTIONS, ...data.options })
    setFileName(data.file_name ?? '')
    setEditingId(null)
    toast.success(`設定を読み込みました（${data.tables.length} テーブル）。`)
  }

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b px-4">
        <DatabaseZapIcon className="size-5 text-primary" />
        <h1 className="font-semibold">DBエクスポートツール</h1>
        <span className="text-xs text-muted-foreground">Oracle / PostgreSQL → Excel（マスキング対応）</span>
        <div className="ml-auto text-xs text-muted-foreground">
          {active ? (
            <span>
              接続中: <span className="font-medium text-foreground">{active.name}</span>
            </span>
          ) : (
            '未接続'
          )}
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* 左ペイン: 接続とテーブル選択 */}
        <aside className="flex w-72 shrink-0 flex-col gap-3 border-r p-3">
          <ConnectionPanel
            connections={connections}
            activeId={active?.id ?? null}
            onReload={reloadConnections}
            onConnected={handleConnected}
            onDisconnected={handleDisconnected}
          />
          <Separator />
          {active ? (
            <TableBrowser
              schemas={schemas}
              schema={schema}
              onSchemaChange={(s) => void loadTables(active.id, s)}
              tables={tables}
              loading={tablesLoading}
              selected={table?.name ?? null}
              onSelect={(t) => void openTable(t)}
            />
          ) : (
            <p className="text-xs text-muted-foreground">接続するとテーブル一覧が表示されます。</p>
          )}
        </aside>

        {/* 中央ペイン: 列設定 */}
        <main className="flex min-w-0 flex-1 flex-col p-4">
          {columnsLoading ? (
            <div className="flex flex-1 items-center justify-center">
              <Loader2Icon className="size-6 animate-spin text-muted-foreground" />
            </div>
          ) : active && table && columns.length > 0 ? (
            <ColumnEditor
              key={`${table.schema_name}.${table.name}.${editingId ?? ''}`}
              connectionId={active.id}
              table={table}
              columns={columns}
              onColumnsChange={setColumns}
              options={tableOptions}
              onOptionsChange={setTableOptions}
              rules={rules}
              exportOptions={options}
              editingQueueItem={editingId !== null}
              onAddToQueue={handleAddToQueue}
            />
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 text-muted-foreground">
              <MousePointerClickIcon className="size-8" />
              <p className="text-sm">
                {active ? '左の一覧からテーブルを選択してください。' : '左の「接続先」からデータベースに接続してください。'}
              </p>
            </div>
          )}
        </main>

        {/* 右ペイン: エクスポート */}
        <aside className="flex w-96 shrink-0 flex-col border-l p-3">
          <ExportPanel
            connectionId={active?.id ?? null}
            dbType={active?.db_type ?? null}
            queue={queue}
            onQueueChange={setQueue}
            editingId={editingId}
            onEdit={handleEditQueueItem}
            options={options}
            onOptionsChange={setOptions}
            fileName={fileName}
            onFileNameChange={setFileName}
            onLoadSettings={handleLoadSettings}
          />
        </aside>
      </div>
    </div>
  )
}
