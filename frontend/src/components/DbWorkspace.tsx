// データベースモードの画面
//   左: 接続先・テーブル選択 / 中央: 列とマスキングの設定、または一括スキャン結果 / 右: エクスポートリストと出力
import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { Loader2Icon, MousePointerClickIcon, ScanSearchIcon, TableIcon } from 'lucide-react'

import { ColumnEditor, EMPTY_TABLE_OPTIONS, type TableOptions } from '@/components/ColumnEditor'
import { ConnectionPanel } from '@/components/ConnectionPanel'
import { ExportPanel } from '@/components/ExportPanel'
import { ScanResultPanel } from '@/components/ScanResultPanel'
import { TableBrowser } from '@/components/TableBrowser'
import { Separator } from '@/components/ui/separator'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { api, errorMessage } from '@/lib/api'
import { carryOver, effectiveRule } from '@/lib/findings'
import type {
  ConnectionProfile,
  DbScanStatus,
  Decisions,
  EditableColumn,
  ExportOptions,
  MaskRuleDef,
  QueueItem,
  SavedSettings,
  TableExportSpec,
  TableInfo,
} from '@/lib/types'

const DEFAULT_OPTIONS: ExportOptions = {
  format: 'xlsx',
  header_mode: 'logical',
  font_name: '游ゴシック',
  font_size: 11,
  include_info_sheet: true,
  count_rows: true,
  hash_salt: '',
  date_format: 'yyyy/mm/dd',
  datetime_format: 'yyyy/mm/dd hh:mm:ss',
  sql_target_schema: '',
  sql_qualify_schema: true,
  sql_commit_every: 1000,
  sql_delete_before_insert: false,
  sql_encoding: 'utf-8',
}

// 表を開いたときに自動判定に使うサンプル件数
const SAMPLE_ROWS = 200

const newId = () => Math.random().toString(36).slice(2, 10)

interface Props {
  rules: MaskRuleDef[]
  onActiveChange: (profile: ConnectionProfile | null) => void
}

export function DbWorkspace({ rules, onActiveChange }: Props) {
  // ---- 接続 ----
  const [connections, setConnections] = useState<ConnectionProfile[]>([])
  const [active, setActiveState] = useState<ConnectionProfile | null>(null)

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

  // ---- 一括スキャン（中央） ----
  const [scan, setScan] = useState<DbScanStatus | null>(null)
  const [scanDecisions, setScanDecisions] = useState<Decisions>({})
  const [view, setView] = useState<'table' | 'scan'>('table')
  const scanTimer = useRef<number | null>(null)

  // ---- エクスポート（右） ----
  const [queue, setQueue] = useState<QueueItem[]>([])
  const [options, setOptions] = useState<ExportOptions>(DEFAULT_OPTIONS)
  const [fileName, setFileName] = useState('')

  const setActive = (p: ConnectionProfile | null) => {
    setActiveState(p)
    onActiveChange(p)
  }

  const reloadConnections = useCallback(async () => {
    try {
      setConnections(await api.listConnections())
    } catch (e) {
      toast.error('接続一覧を取得できません', { description: errorMessage(e) })
    }
  }, [])

  useEffect(() => {
    void reloadConnections()
    return () => {
      if (scanTimer.current) window.clearInterval(scanTimer.current)
    }
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

  const stopPolling = () => {
    if (scanTimer.current) window.clearInterval(scanTimer.current)
    scanTimer.current = null
  }

  const resetWorkspace = () => {
    stopPolling()
    setSchemas([])
    setSchema(null)
    setTables([])
    setTable(null)
    setColumns([])
    setEditingId(null)
    setQueue([])
    setScan(null)
    setScanDecisions({})
    setView('table')
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
    setView('table')
    setTable(t)
    setColumnsLoading(true)
    try {
      const cols = await api.listColumns(active.id, t.schema_name, t.name, spec ? 0 : SAMPLE_ROWS)
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
        // 安全側に倒すため、自動判定でマスキング対象となった列には初期状態でマスキングを設定する
        const suggested = cols.filter((c) => c.suggested_mask).length
        const review = cols.filter((c) => c.suggestion?.level === 'review').length
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
        if (suggested > 0 || review > 0) {
          toast.info(`個人情報と判定した ${suggested} 列にマスキングを自動設定しました。`, {
            description: review > 0 ? `ほかに要確認の列が ${review} 列あります（「要確認」の印）。` : '内容を確認し、必要に応じて変更してください。',
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

  // ---- 一括スキャン ----
  const handleScan = async (targets: TableInfo[]) => {
    if (!active || !schema) return
    if (targets.length === 0) {
      toast.error('スキャンする表がありません。')
      return
    }
    stopPolling()
    try {
      const names = targets.length === tables.length ? null : targets.map((t) => t.name)
      let st = await api.startScan(active.id, schema, names, SAMPLE_ROWS)
      setScan(st)
      setView('scan')
      scanTimer.current = window.setInterval(async () => {
        try {
          st = await api.scanStatus(st.job_id)
          setScan(st)
          if (st.status === 'done') {
            stopPolling()
            // 同じ表を再スキャンした場合は、前回の判断を引き継ぐ
            setScanDecisions((d) => carryOver(d, st.findings))
            toast.success('スキャンが完了しました', { description: st.message ?? undefined })
          } else if (st.status !== 'running' && st.status !== 'pending') {
            stopPolling()
            if (st.status === 'error') toast.error('スキャンに失敗しました', { description: st.message ?? undefined })
          }
        } catch (e) {
          stopPolling()
          toast.error(errorMessage(e))
        }
      }, 700)
    } catch (e) {
      toast.error('スキャンを開始できません', { description: errorMessage(e) })
    }
  }

  const handleApplyScan = (includeTablesWithoutMask: boolean) => {
    if (!scan) return
    const byTable = new Map<string, typeof scan.findings>()
    for (const f of scan.findings) byTable.set(f.file, [...(byTable.get(f.file) ?? []), f])
    const specs: QueueItem[] = []
    for (const t of scan.tables) {
      if (t.error) continue
      const findings = byTable.get(`${t.schema_name}.${t.table}`) ?? []
      const masks = new Map(findings.map((f) => [f.column, effectiveRule(f, scanDecisions)]))
      const columns = t.columns.map((c) => ({ name: c.name, mask: masks.get(c.name) ?? null, header: null }))
      if (!includeTablesWithoutMask && !columns.some((c) => c.mask)) continue
      specs.push({ id: newId(), spec: { schema_name: t.schema_name, table: t.table, columns }, tableComment: t.comment })
    }
    if (specs.length === 0) {
      toast.info('反映する表がありません（マスク対象の列がある表はありません）。')
      return
    }
    // 既にリストにある同じ表は置き換える
    setQueue((q) => {
      const key = (s: TableExportSpec) => `${s.schema_name}.${s.table}`
      const replaced = new Map(specs.map((s) => [key(s.spec), s]))
      const kept = q.filter((item) => !replaced.has(key(item.spec)))
      return [...kept, ...specs]
    })
    setEditingId(null)
    toast.success(`${specs.length} 表をエクスポートリストに反映しました。`, { description: '右の「出力形式」で Excel / INSERT 文 / UPDATE 文を選べます。' })
  }

  const handleScanReport = () => {
    if (!scan || !active) return
    api
      .downloadReport(scan.findings, scanDecisions, '判定結果一覧', `${active.name} / スキーマ ${scan.schema_name}`)
      .catch((e) => toast.error('判定結果一覧を出力できません', { description: errorMessage(e) }))
  }

  const scanning = scan?.status === 'running' || scan?.status === 'pending'

  return (
    <div className="flex min-h-0 min-w-0 flex-1">
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
            selected={view === 'table' ? (table?.name ?? null) : null}
            onSelect={(t) => void openTable(t)}
            onScan={(targets) => void handleScan(targets)}
            scanning={scanning}
          />
        ) : (
          <p className="text-xs text-muted-foreground">接続するとテーブル一覧が表示されます。</p>
        )}
      </aside>

      {/* 中央ペイン: 列設定 / 一括スキャン結果 */}
      <main className="flex min-w-0 flex-1 flex-col gap-3 p-4">
        {scan && (
          <Tabs value={view} onValueChange={(v) => setView(v as 'table' | 'scan')}>
            <TabsList>
              <TabsTrigger value="table" className="px-3">
                <TableIcon />
                列の設定{table ? `（${table.name}）` : ''}
              </TabsTrigger>
              <TabsTrigger value="scan" className="px-3">
                {scanning ? <Loader2Icon className="animate-spin" /> : <ScanSearchIcon />}
                一括スキャン結果
              </TabsTrigger>
            </TabsList>
          </Tabs>
        )}
        {view === 'scan' && scan ? (
          <ScanResultPanel
            job={scan}
            decisions={scanDecisions}
            onDecisionsChange={setScanDecisions}
            rules={rules}
            hashSalt={options.hash_salt}
            onCancel={() => void api.cancelScan(scan.job_id).catch(() => undefined)}
            onApplyToQueue={handleApplyScan}
            onDownloadReport={handleScanReport}
          />
        ) : columnsLoading ? (
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
              {active ? '左の一覧からテーブルを選択するか、「一括スキャン」で個人情報の列をまとめて判定してください。' : '左の「接続先」からデータベースに接続してください。'}
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
  )
}
