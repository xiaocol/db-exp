// ドキュメントモードの画面
//   左: ファイルの読み込み / 中央: マスキング対象一覧・要確認一覧 / 右: Markdown 出力
import { useRef, useState, type DragEvent } from 'react'
import { toast } from 'sonner'
import {
  FileArchiveIcon,
  FileSpreadsheetIcon,
  FileTextIcon,
  FileUpIcon,
  FolderUpIcon,
  Loader2Icon,
  RefreshCwIcon,
  Trash2Icon,
  UploadIcon,
  XIcon,
} from 'lucide-react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { FindingsView } from '@/components/FindingsView'
import { api, errorMessage } from '@/lib/api'
import { carryOver, summarize } from '@/lib/findings'
import type { Decisions, DocScanResult, MaskRuleDef } from '@/lib/types'
import { cn } from '@/lib/utils'

const EXTENSIONS = ['.xlsx', '.xlsm', '.csv', '.tsv', '.txt', '.md', '.markdown', '.log']

interface PickedFile {
  /** フォルダから読み込んだ場合はフォルダ名付きのパス */
  name: string
  file: File
}

const extOf = (name: string) => {
  const i = name.lastIndexOf('.')
  return i >= 0 ? name.slice(i).toLowerCase() : ''
}

const sizeLabel = (n: number) => (n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`)

/** ドロップされたフォルダの中のファイルを再帰的に集める */
async function collectEntries(entry: FileSystemEntry, prefix = ''): Promise<PickedFile[]> {
  if (entry.isFile) {
    const file = await new Promise<File>((resolve, reject) => (entry as FileSystemFileEntry).file(resolve, reject))
    return [{ name: prefix + file.name, file }]
  }
  const reader = (entry as FileSystemDirectoryEntry).createReader()
  const all: FileSystemEntry[] = []
  // readEntries は一度に全件を返さないため、空になるまで繰り返す
  for (;;) {
    const batch = await new Promise<FileSystemEntry[]>((resolve, reject) => reader.readEntries(resolve, reject))
    if (batch.length === 0) break
    all.push(...batch)
  }
  const nested = await Promise.all(all.map((e) => collectEntries(e, `${prefix}${entry.name}/`)))
  return nested.flat()
}

function FileIcon({ kind }: { kind: string }) {
  if (kind === 'excel' || kind === 'csv') return <FileSpreadsheetIcon className="size-4 shrink-0 text-emerald-600" />
  return <FileTextIcon className="size-4 shrink-0 text-sky-600" />
}

interface Props {
  rules: MaskRuleDef[]
}

export function DocWorkspace({ rules }: Props) {
  const [files, setFiles] = useState<PickedFile[]>([])
  const [result, setResult] = useState<DocScanResult | null>(null)
  const [decisions, setDecisions] = useState<Decisions>({})
  const [scanning, setScanning] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [salt, setSalt] = useState('')
  const [dragging, setDragging] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const folderInput = useRef<HTMLInputElement>(null)

  /** ファイル一覧全体をスキャンし直す（同じファイル・同じ場所の判断は引き継ぐ） */
  const rescan = async (next: PickedFile[]) => {
    setFiles(next)
    const previous = result
    if (next.length === 0) {
      setResult(null)
      setDecisions({})
      if (previous) void api.deleteDocuments(previous.scan_id).catch(() => undefined)
      return
    }
    setScanning(true)
    try {
      const res = await api.scanDocuments(next)
      setResult(res)
      setDecisions((d) => carryOver(d, res.findings))
      if (previous) void api.deleteDocuments(previous.scan_id).catch(() => undefined)
      const errors = res.files.filter((f) => f.error).length
      const s = summarize(res.findings, {})
      toast.success(`${res.files.length} ファイルをスキャンしました。`, {
        description: `マスキング対象 ${s.auto} 件、要確認 ${s.review} 件${errors ? `、読み込めないファイル ${errors} 件` : ''}`,
      })
    } catch (e) {
      toast.error('スキャンに失敗しました', { description: errorMessage(e) })
    } finally {
      setScanning(false)
    }
  }

  const addFiles = (picked: PickedFile[]) => {
    const supported = picked.filter((p) => EXTENSIONS.includes(extOf(p.name)))
    const skipped = picked.length - supported.length
    if (skipped > 0) toast.info(`対応していない形式のファイル ${skipped} 件を除外しました。`, { description: '対応形式: Excel（.xlsx）・CSV・テキスト・Markdown' })
    if (supported.length === 0) return
    // 同じ名前のファイルは新しいもので置き換える
    const names = new Set(supported.map((p) => p.name))
    void rescan([...files.filter((f) => !names.has(f.name)), ...supported])
  }

  const handleDrop = async (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const items = Array.from(e.dataTransfer.items)
    const entries = items.map((i) => i.webkitGetAsEntry?.()).filter((x): x is FileSystemEntry => !!x)
    if (entries.length > 0) {
      const nested = await Promise.all(entries.map((en) => collectEntries(en)))
      addFiles(nested.flat())
    } else {
      addFiles(Array.from(e.dataTransfer.files).map((f) => ({ name: f.name, file: f })))
    }
  }

  const handleExport = async () => {
    if (!result) return
    setExporting(true)
    try {
      await api.exportDocuments(result.scan_id, decisions, salt)
      toast.success('マスク済みの Markdown を出力しました。', { description: 'ZIP にファイルごとの .md と「マスキング結果一覧.md」が入っています。' })
    } catch (e) {
      toast.error('出力に失敗しました', { description: errorMessage(e) })
    } finally {
      setExporting(false)
    }
  }

  const handleReport = () => {
    if (!result) return
    api
      .downloadReport(result.findings, decisions, '判定結果一覧', `ドキュメント ${result.files.length} ファイル`)
      .catch((e) => toast.error('判定結果一覧を出力できません', { description: errorMessage(e) }))
  }

  const summary = result ? summarize(result.findings, decisions) : null
  const infoByName = new Map(result?.files.map((f) => [f.name, f]) ?? [])

  return (
    <div className="flex min-h-0 min-w-0 flex-1">
      {/* 左ペイン: ファイルの読み込み */}
      <aside className="flex w-80 shrink-0 flex-col gap-3 border-r p-3">
        <h2 className="text-sm font-semibold">ドキュメントの読み込み</h2>
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => void handleDrop(e)}
          className={cn(
            'flex flex-col items-center gap-2 rounded-md border-2 border-dashed p-4 text-center text-xs text-muted-foreground transition-colors',
            dragging && 'border-primary bg-primary/5',
          )}
        >
          <UploadIcon className="size-6" />
          <p>
            ファイルまたはフォルダをここにドロップ
            <br />
            （Excel・CSV・テキスト・Markdown）
          </p>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => fileInput.current?.click()} disabled={scanning}>
              <FileUpIcon />
              ファイル選択
            </Button>
            <Button size="sm" variant="outline" onClick={() => folderInput.current?.click()} disabled={scanning}>
              <FolderUpIcon />
              フォルダ選択
            </Button>
          </div>
          <input
            ref={fileInput}
            type="file"
            multiple
            accept={EXTENSIONS.join(',')}
            className="hidden"
            onChange={(e) => {
              addFiles(Array.from(e.target.files ?? []).map((f) => ({ name: f.name, file: f })))
              e.target.value = ''
            }}
          />
          <input
            ref={folderInput}
            type="file"
            multiple
            className="hidden"
            {...({ webkitdirectory: '' } as Record<string, string>)}
            onChange={(e) => {
              addFiles(Array.from(e.target.files ?? []).map((f) => ({ name: f.webkitRelativePath || f.name, file: f })))
              e.target.value = ''
            }}
          />
        </div>

        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">
            {scanning ? 'スキャン中…' : `${files.length} ファイル`}
          </span>
          <div className="flex gap-1">
            <Button size="xs" variant="ghost" disabled={scanning || files.length === 0} onClick={() => void rescan(files)} title="もう一度スキャンします（判断は引き継ぎます）">
              <RefreshCwIcon />
              再スキャン
            </Button>
            <Button size="xs" variant="ghost" disabled={scanning || files.length === 0} onClick={() => void rescan([])}>
              <Trash2Icon />
              クリア
            </Button>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-auto rounded-md border">
          {files.length === 0 ? (
            <p className="p-4 text-center text-xs text-muted-foreground">読み込んだファイルがここに表示されます。</p>
          ) : (
            <ul className="divide-y">
              {files.map((f) => {
                const info = infoByName.get(f.name)
                return (
                  <li key={f.name} className="flex items-start gap-2 p-2">
                    <FileIcon kind={info?.kind ?? (['.xlsx', '.xlsm', '.csv', '.tsv'].includes(extOf(f.name)) ? 'excel' : 'text')} />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-xs font-medium" title={f.name}>
                        {f.name}
                      </div>
                      <div className={cn('text-[11px]', info?.error ? 'text-destructive' : 'text-muted-foreground')}>
                        {info?.error ?? (info ? `${sizeLabel(info.size)} ／ 表 ${info.tables} ／ ${info.lines.toLocaleString()} 行` : sizeLabel(f.file.size))}
                      </div>
                    </div>
                    <Button
                      size="icon-xs"
                      variant="ghost"
                      disabled={scanning}
                      onClick={() => void rescan(files.filter((x) => x.name !== f.name))}
                      title="一覧から外す"
                    >
                      <XIcon />
                    </Button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </aside>

      {/* 中央ペイン: 判定結果 */}
      <main className="flex min-w-0 flex-1 flex-col gap-3 p-4">
        {scanning && !result ? (
          <div className="flex flex-1 items-center justify-center">
            <Loader2Icon className="size-6 animate-spin text-muted-foreground" />
          </div>
        ) : result ? (
          <>
            <div>
              <h2 className="font-semibold">判定結果</h2>
              <p className="text-xs text-muted-foreground">
                表になっている部分は列ごとに、それ以外の文章は文中の語句ごとに判定しています。自動判定のものは確認のうえ規則を変更でき、要確認のものは人が判断してください。
              </p>
            </div>
            <FindingsView
              findings={result.findings}
              decisions={decisions}
              onDecisionsChange={setDecisions}
              rules={rules}
              hashSalt={salt}
              groupLabel="ファイル"
            />
          </>
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 text-muted-foreground">
            <FileUpIcon className="size-8" />
            <p className="text-sm">左からドキュメント（Excel・CSV・テキスト・Markdown）を読み込むと、マスキングが必要な箇所を自動で判定します。</p>
          </div>
        )}
      </main>

      {/* 右ペイン: 出力 */}
      <aside className="flex w-80 shrink-0 flex-col gap-3 border-l p-3">
        <h2 className="text-sm font-semibold">出力（Markdown）</h2>
        {summary ? (
          <div className="grid grid-cols-3 gap-2 text-center">
            <div className="rounded-md border p-2">
              <div className="text-lg font-semibold tabular-nums">{summary.auto}</div>
              <div className="text-[11px] text-muted-foreground">マスキング対象</div>
            </div>
            <div className="rounded-md border p-2">
              <div className="text-lg font-semibold tabular-nums">{summary.review}</div>
              <div className="text-[11px] text-muted-foreground">要確認</div>
            </div>
            <div className={cn('rounded-md border p-2', summary.undecided > 0 && 'border-amber-400 bg-amber-50 dark:bg-amber-950/30')}>
              <div className="text-lg font-semibold tabular-nums">{summary.undecided}</div>
              <div className="text-[11px] text-muted-foreground">未判断</div>
            </div>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">ファイルを読み込むと出力できます。</p>
        )}
        <Separator />
        <div className="grid gap-1">
          <Label className="text-xs">ハッシュ用ソルト（ハッシュ化・ダミー氏名で使用）</Label>
          <Input type="password" autoComplete="off" value={salt} placeholder="空欄可" onChange={(e) => setSalt(e.target.value)} />
        </div>
        <ul className="list-disc space-y-1 pl-4 text-[11px] text-muted-foreground">
          <li>元のファイルごとにマスク済みの Markdown（.md）を作成し、ZIP にまとめます。フォルダ構成は保ちます。</li>
          <li>Excel はシートごとに見出しを付け、表は Markdown の表にします。</li>
          <li>「マスキング結果一覧.md」に、マスクした箇所・判断の結果・件数を記録します（元の値は記載しません）。</li>
        </ul>
        {summary && summary.undecided > 0 && (
          <Alert className="py-2">
            <AlertDescription className="text-xs">要確認の未判断が {summary.undecided} 件あります。すべて判断すると出力できます。</AlertDescription>
          </Alert>
        )}
        <div className="mt-auto grid gap-2">
          <Button variant="outline" onClick={handleReport} disabled={!result}>
            <FileSpreadsheetIcon />
            判定結果一覧（Excel）
          </Button>
          <Button size="lg" onClick={() => void handleExport()} disabled={!result || exporting || scanning || (summary?.undecided ?? 0) > 0}>
            {exporting ? <Loader2Icon className="animate-spin" /> : <FileArchiveIcon />}
            Markdown で出力（ZIP）
          </Button>
        </div>
      </aside>
    </div>
  )
}
