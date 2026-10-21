// エクスポート対象リスト・出力オプション・実行と進捗表示
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import {
  ArrowDownIcon,
  ArrowUpIcon,
  DatabaseIcon,
  DownloadIcon,
  FileCodeIcon,
  FileDownIcon,
  FileSpreadsheetIcon,
  FolderOpenIcon,
  PencilIcon,
  ShieldIcon,
  SquareIcon,
  Trash2Icon,
  TriangleAlertIcon,
} from 'lucide-react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Switch } from '@/components/ui/switch'
import { api, errorMessage } from '@/lib/api'
import type { DbType, ExportFormat, ExportJobStatus, ExportOptions, HeaderMode, QueueItem, SavedSettings } from '@/lib/types'
import { cn } from '@/lib/utils'

// Windows の Excel で一般的に使われる日本語フォント
const FONTS = ['游ゴシック', 'Yu Gothic UI', 'メイリオ', 'Meiryo UI', 'ＭＳ Ｐゴシック', 'ＭＳ ゴシック', 'BIZ UDPゴシック']

const FORMATS: Record<ExportFormat, { label: string; button: string; description: string }> = {
  xlsx: { label: 'Excel（.xlsx）', button: 'Excelにエクスポート', description: '表ごとにシートを分けて出力します。' },
  sql_insert: {
    label: 'マスク済みダンプ（INSERT 文 .sql）',
    button: 'INSERT 文を出力',
    description: 'マスクしたデータを INSERT 文で出力します。テスト環境への投入に使えます。',
  },
  sql_update: {
    label: 'マスキング用 UPDATE 文（.sql）',
    button: 'UPDATE 文を出力',
    description: '本番データをコピーしたテスト環境で実行し、その場でマスクする SQL です（データは含みません）。',
  },
}

interface Props {
  connectionId: string | null
  dbType: DbType | null
  queue: QueueItem[]
  onQueueChange: (queue: QueueItem[]) => void
  editingId: string | null
  onEdit: (item: QueueItem) => void
  options: ExportOptions
  onOptionsChange: (opts: ExportOptions) => void
  fileName: string
  onFileNameChange: (name: string) => void
  onLoadSettings: (settings: SavedSettings) => void
}

export function ExportPanel({
  connectionId,
  dbType,
  queue,
  onQueueChange,
  editingId,
  onEdit,
  options,
  onOptionsChange,
  fileName,
  onFileNameChange,
  onLoadSettings,
}: Props) {
  const [job, setJob] = useState<ExportJobStatus | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const running = job?.status === 'running' || job?.status === 'pending'

  const setOpt = <K extends keyof ExportOptions>(key: K, value: ExportOptions[K]) =>
    onOptionsChange({ ...options, [key]: value })

  // 実行中は進捗をポーリングし、完了したら自動でダウンロードする
  useEffect(() => {
    if (!job || !running) return
    const timer = window.setInterval(async () => {
      try {
        const st = await api.exportStatus(job.job_id)
        setJob(st)
        if (st.status === 'done') {
          toast.success('エクスポートが完了しました', { description: st.message ?? undefined })
          download(st.job_id)
        } else if (st.status === 'error') {
          toast.error('エクスポートに失敗しました', { description: st.message ?? undefined, duration: 15000 })
        } else if (st.status === 'cancelled') {
          toast.info(st.message ?? '中止しました。')
        }
      } catch (e) {
        toast.error(errorMessage(e))
        setJob(null)
      }
    }, 500)
    return () => window.clearInterval(timer)
  }, [job, running])

  const download = (jobId: string) => {
    const a = document.createElement('a')
    a.href = api.downloadUrl(jobId)
    a.download = ''
    document.body.appendChild(a)
    a.click()
    a.remove()
  }

  const handleExport = async () => {
    if (!connectionId || queue.length === 0) return
    try {
      setJob(await api.startExport(connectionId, queue.map((q) => q.spec), fileName, options))
    } catch (e) {
      toast.error('エクスポートを開始できません', { description: errorMessage(e) })
    }
  }

  const move = (index: number, delta: number) => {
    const next = [...queue]
    const [item] = next.splice(index, 1)
    next.splice(index + delta, 0, item)
    onQueueChange(next)
  }

  // ---- 設定ファイル（JSON）の保存・読込 ----
  const handleSaveSettings = () => {
    if (!dbType) return
    const data: SavedSettings = { version: 1, db_type: dbType, file_name: fileName, options, tables: queue.map((q) => q.spec) }
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${fileName || 'エクスポート設定'}.json`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const handleLoadFile = async (file: File) => {
    try {
      const data = JSON.parse(await file.text()) as SavedSettings
      if (data.version !== 1 || !Array.isArray(data.tables)) throw new Error('設定ファイルの形式が正しくありません。')
      onLoadSettings(data)
    } catch (e) {
      toast.error('設定ファイルを読み込めません', { description: errorMessage(e) })
    }
  }

  const totalProgress = (() => {
    if (!job) return 0
    const total = job.tables.reduce((s, t) => s + (t.total_rows ?? 0), 0)
    const done = job.tables.reduce((s, t) => s + t.rows_written, 0)
    if (job.status === 'done') return 100
    return total > 0 ? Math.min(100, (done / total) * 100) : 0
  })()

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">エクスポートリスト（{queue.length}）</h2>
        <div className="flex gap-1">
          <Button size="xs" variant="ghost" onClick={() => fileInput.current?.click()} disabled={!connectionId} title="保存した設定（JSON）を読み込みます">
            <FolderOpenIcon />
            設定読込
          </Button>
          <Button size="xs" variant="ghost" onClick={handleSaveSettings} disabled={queue.length === 0} title="現在のリストと出力オプションをJSONで保存します">
            <FileDownIcon />
            設定保存
          </Button>
          <input
            ref={fileInput}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) void handleLoadFile(f)
              e.target.value = ''
            }}
          />
        </div>
      </div>

      <div className="min-h-24 flex-1 overflow-auto rounded-md border">
        {queue.length === 0 ? (
          <p className="p-4 text-center text-xs text-muted-foreground">
            テーブルを選択し、列とマスキングを設定して
            <br />
            「エクスポートリストに追加」を押してください。
            <br />
            「一括スキャン」の結果からまとめて追加することもできます。
          </p>
        ) : (
          <ul className="divide-y">
            {queue.map((item, i) => {
              const masked = item.spec.columns.filter((c) => c.mask).length
              const progress = job?.tables[i]
              return (
                <li key={item.id} className={cn('flex items-start gap-2 p-2', editingId === item.id && 'bg-primary/5')}>
                  {options.format === 'xlsx' ? (
                    <FileSpreadsheetIcon className="mt-0.5 size-4 shrink-0 text-emerald-600" />
                  ) : (
                    <DatabaseIcon className="mt-0.5 size-4 shrink-0 text-sky-600" />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-mono text-xs font-medium">
                      {item.spec.schema_name}.{item.spec.table}
                    </div>
                    <div className="truncate text-[11px] text-muted-foreground">
                      {item.tableComment && `${item.tableComment} ／ `}
                      {item.spec.columns.length} 列
                      {masked > 0 && (
                        <span className="ml-1 inline-flex items-center gap-0.5 text-orange-600">
                          <ShieldIcon className="size-3" />
                          {masked}
                        </span>
                      )}
                      {item.spec.where && ' ／ 条件あり'}
                      {item.spec.max_rows && ` ／ 最大${item.spec.max_rows.toLocaleString()}件`}
                    </div>
                    {progress && job && (
                      <div className="text-[11px] tabular-nums text-muted-foreground">
                        {progress.rows_written.toLocaleString()}
                        {progress.total_rows !== null && ` / ${progress.total_rows.toLocaleString()}`} 件
                        {progress.status === 'done' && ' ✓'}
                      </div>
                    )}
                  </div>
                  <div className="flex shrink-0">
                    <Button size="icon-xs" variant="ghost" disabled={i === 0 || running} onClick={() => move(i, -1)} title="上へ">
                      <ArrowUpIcon />
                    </Button>
                    <Button size="icon-xs" variant="ghost" disabled={i === queue.length - 1 || running} onClick={() => move(i, 1)} title="下へ">
                      <ArrowDownIcon />
                    </Button>
                    <Button size="icon-xs" variant="ghost" disabled={running} onClick={() => onEdit(item)} title="編集">
                      <PencilIcon />
                    </Button>
                    <Button
                      size="icon-xs"
                      variant="ghost"
                      disabled={running}
                      onClick={() => onQueueChange(queue.filter((q) => q.id !== item.id))}
                      title="削除"
                    >
                      <Trash2Icon />
                    </Button>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      <Separator />

      {/* 出力オプション */}
      <div className="grid gap-3 text-sm">
        <div className="grid gap-1">
          <Label className="text-xs">出力形式</Label>
          <Select value={options.format} onValueChange={(v) => setOpt('format', v as ExportFormat)}>
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(FORMATS) as ExportFormat[]).map((f) => (
                <SelectItem key={f} value={f}>
                  {FORMATS[f].label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="text-[11px] text-muted-foreground">{FORMATS[options.format].description}</span>
        </div>
        {options.format === 'sql_update' && (
          <Alert variant="destructive" className="py-2">
            <TriangleAlertIcon />
            <AlertDescription className="text-xs">
              本番環境では絶対に実行しないでください。表の全行を書き換えます（抽出条件・最大件数は適用されません）。「出力」のチェックを外した列は更新されません。
            </AlertDescription>
          </Alert>
        )}
        <div className="grid gap-1">
          <Label className="text-xs">ファイル名（空欄=表名_日時）</Label>
          <Input value={fileName} placeholder="例: 顧客データ_マスキング済" onChange={(e) => onFileNameChange(e.target.value)} />
        </div>
        {options.format === 'xlsx' ? (
        <div className="grid grid-cols-2 gap-2">
          <div className="grid gap-1">
            <Label className="text-xs">見出し行</Label>
            <Select value={options.header_mode} onValueChange={(v) => setOpt('header_mode', v as HeaderMode)}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="logical">論理名（コメント）</SelectItem>
                <SelectItem value="physical">物理名</SelectItem>
                <SelectItem value="both">論理名＋物理名（2行）</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-1">
            <Label className="text-xs">フォント</Label>
            <Select value={options.font_name} onValueChange={(v) => setOpt('font_name', v)}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {FONTS.map((f) => (
                  <SelectItem key={f} value={f}>
                    {f}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        ) : (
          <div className="grid gap-2">
            <div className="grid grid-cols-2 gap-2">
              <div className="grid gap-1">
                <Label className="text-xs">出力先スキーマ名</Label>
                <Input
                  className="text-xs"
                  value={options.sql_target_schema}
                  placeholder="空欄=元のスキーマ"
                  disabled={!options.sql_qualify_schema}
                  onChange={(e) => setOpt('sql_target_schema', e.target.value)}
                />
              </div>
              <div className="grid gap-1">
                <Label className="text-xs">文字コード</Label>
                <Select value={options.sql_encoding} onValueChange={(v) => setOpt('sql_encoding', v as ExportOptions['sql_encoding'])}>
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="utf-8">UTF-8</SelectItem>
                    <SelectItem value="cp932">Shift_JIS（CP932）</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="opt-qualify" className="text-xs font-normal">
                表名にスキーマ名を付ける
              </Label>
              <Switch id="opt-qualify" checked={options.sql_qualify_schema} onCheckedChange={(v) => setOpt('sql_qualify_schema', v)} />
            </div>
            {options.format === 'sql_insert' && (
              <>
                <div className="flex items-center justify-between gap-2">
                  <Label className="text-xs font-normal">COMMIT する間隔（件、0=最後に1回）</Label>
                  <Input
                    type="number"
                    min={0}
                    className="h-7 w-24 text-xs"
                    value={options.sql_commit_every}
                    onChange={(e) => setOpt('sql_commit_every', Math.max(0, Number(e.target.value) || 0))}
                  />
                </div>
                <div className="flex items-center justify-between">
                  <Label htmlFor="opt-delete" className="text-xs font-normal">
                    先頭に既存データを削除する DELETE 文を付ける
                  </Label>
                  <Switch id="opt-delete" checked={options.sql_delete_before_insert} onCheckedChange={(v) => setOpt('sql_delete_before_insert', v)} />
                </div>
              </>
            )}
          </div>
        )}
        <div className="grid gap-1">
          <Label className="text-xs">ハッシュ用ソルト（ハッシュ化・ダミー氏名で使用）</Label>
          <Input
            type="password"
            autoComplete="off"
            value={options.hash_salt}
            placeholder="空欄可。指定すると推測による復元が困難になります"
            onChange={(e) => setOpt('hash_salt', e.target.value)}
          />
        </div>
        {options.format === 'xlsx' && (
          <div className="flex items-center justify-between">
            <Label htmlFor="opt-info" className="text-xs font-normal">
              「エクスポート情報」シートを付ける（監査用）
            </Label>
            <Switch id="opt-info" checked={options.include_info_sheet} onCheckedChange={(v) => setOpt('include_info_sheet', v)} />
          </div>
        )}
        {options.format !== 'sql_update' && (
        <div className="flex items-center justify-between">
          <Label htmlFor="opt-count" className="text-xs font-normal">
            事前に件数を数えて進捗率を表示する
          </Label>
          <Switch id="opt-count" checked={options.count_rows} onCheckedChange={(v) => setOpt('count_rows', v)} />
        </div>
        )}
      </div>

      {job && (
        <div className="grid gap-1.5 rounded-md border p-2">
          <div className="flex items-center justify-between text-xs">
            <span className="truncate font-medium">{job.file_name}</span>
            <span className="tabular-nums text-muted-foreground">{Math.floor(totalProgress)}%</span>
          </div>
          <Progress value={totalProgress} />
          {job.status === 'error' && (
            <Alert variant="destructive" className="py-2">
              <AlertDescription className="text-xs whitespace-pre-wrap">{job.message}</AlertDescription>
            </Alert>
          )}
          {job.status === 'done' && (
            <Button size="sm" variant="outline" onClick={() => download(job.job_id)}>
              <DownloadIcon />
              再ダウンロード
            </Button>
          )}
        </div>
      )}

      {running ? (
        <Button variant="destructive" onClick={() => job && api.cancelExport(job.job_id)}>
          <SquareIcon />
          中止
        </Button>
      ) : (
        <Button size="lg" onClick={handleExport} disabled={!connectionId || queue.length === 0}>
          {options.format === 'xlsx' ? <FileSpreadsheetIcon /> : <FileCodeIcon />}
          {FORMATS[options.format].button}
        </Button>
      )}
    </div>
  )
}
