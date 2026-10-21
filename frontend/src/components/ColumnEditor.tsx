// 選択した表の列設定（出力対象・マスキング・見出し）と抽出条件の編集
import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { EyeIcon, KeyRoundIcon, ListPlusIcon, Loader2Icon, SaveIcon, ShieldCheckIcon, ShieldOffIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { MaskRuleEditor } from '@/components/MaskRuleEditor'
import { PreviewDialog } from '@/components/PreviewDialog'
import { api, errorMessage } from '@/lib/api'
import type { EditableColumn, ExportOptions, MaskRule, MaskRuleDef, PreviewResult, TableExportSpec, TableInfo } from '@/lib/types'

export interface TableOptions {
  where: string
  order_by: string
  max_rows: string
  sheet_name: string
}

export const EMPTY_TABLE_OPTIONS: TableOptions = { where: '', order_by: '', max_rows: '', sheet_name: '' }

const NONE: MaskRule = { type: 'none', params: {} }

interface Props {
  connectionId: string
  table: TableInfo
  columns: EditableColumn[]
  onColumnsChange: (cols: EditableColumn[]) => void
  options: TableOptions
  onOptionsChange: (opts: TableOptions) => void
  rules: MaskRuleDef[]
  exportOptions: ExportOptions
  /** エクスポートリスト内の項目を編集中の場合 true */
  editingQueueItem: boolean
  onAddToQueue: (spec: TableExportSpec) => void
}

/** 画面の編集状態から API 用のエクスポート定義を組み立てる */
export function buildSpec(table: TableInfo, columns: EditableColumn[], opts: TableOptions): TableExportSpec {
  return {
    schema_name: table.schema_name,
    table: table.name,
    columns: columns
      .filter((c) => c.include)
      .map((c) => ({
        name: c.name,
        mask: c.mask.type === 'none' ? null : c.mask,
        header: c.header.trim() || null,
      })),
    where: opts.where.trim() || null,
    order_by: opts.order_by.trim() || null,
    max_rows: opts.max_rows ? Number(opts.max_rows) : null,
    sheet_name: opts.sheet_name.trim() || null,
  }
}

export function ColumnEditor({
  connectionId,
  table,
  columns,
  onColumnsChange,
  options,
  onOptionsChange,
  rules,
  exportOptions,
  editingQueueItem,
  onAddToQueue,
}: Props) {
  const [previewing, setPreviewing] = useState(false)
  const [preview, setPreview] = useState<PreviewResult | null>(null)
  const [previewOpen, setPreviewOpen] = useState(false)

  const includedCount = columns.filter((c) => c.include).length
  const maskedCount = columns.filter((c) => c.include && c.mask.type !== 'none').length
  const suggestedCount = columns.filter((c) => c.suggested_mask).length
  const allChecked = includedCount === columns.length ? true : includedCount === 0 ? false : 'indeterminate'

  const maskedNames = useMemo(
    () => new Set(columns.filter((c) => c.include && c.mask.type !== 'none').map((c) => c.name)),
    [columns],
  )

  const update = (name: string, patch: Partial<EditableColumn>) =>
    onColumnsChange(columns.map((c) => (c.name === name ? { ...c, ...patch } : c)))

  const setOpt = (key: keyof TableOptions, value: string) => onOptionsChange({ ...options, [key]: value })

  const applySuggested = () => {
    onColumnsChange(columns.map((c) => (c.suggested_mask ? { ...c, mask: c.suggested_mask } : c)))
    toast.info(`${suggestedCount} 列に推奨マスキングを適用しました。`)
  }

  const validate = (): TableExportSpec | null => {
    if (includedCount === 0) {
      toast.error('出力する列を1つ以上選択してください。')
      return null
    }
    return buildSpec(table, columns, options)
  }

  const handlePreview = async () => {
    const spec = validate()
    if (!spec) return
    setPreviewing(true)
    try {
      setPreview(await api.preview(connectionId, spec, exportOptions, 50))
      setPreviewOpen(true)
    } catch (e) {
      toast.error('プレビューに失敗しました', { description: errorMessage(e) })
    } finally {
      setPreviewing(false)
    }
  }

  const handleAdd = () => {
    const spec = validate()
    if (spec) onAddToQueue(spec)
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      {/* 表の情報とアクション */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 className="truncate font-mono text-base font-semibold">
              {table.schema_name}.{table.name}
            </h2>
            <Badge variant="secondary">{table.table_type}</Badge>
          </div>
          <p className="truncate text-xs text-muted-foreground">
            {table.comment || '（コメントなし）'} ／ 出力 {includedCount} / {columns.length} 列 ／ マスキング {maskedCount} 列
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={applySuggested} disabled={suggestedCount === 0} title="列名・論理名・先頭の値から個人情報と判定した列に、推奨のマスキングを設定します">
          <ShieldCheckIcon />
          推奨マスキング適用（{suggestedCount}）
        </Button>
        <Button size="sm" variant="outline" onClick={() => onColumnsChange(columns.map((c) => ({ ...c, mask: NONE })))}>
          <ShieldOffIcon />
          マスキング全解除
        </Button>
      </div>

      {/* 列一覧 */}
      <div className="min-h-0 flex-1 overflow-auto rounded-md border">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 z-10 bg-muted">
            <tr className="text-left text-xs text-muted-foreground">
              <th className="w-8 px-2 py-2">
                <Checkbox
                  checked={allChecked}
                  onCheckedChange={(v) => onColumnsChange(columns.map((c) => ({ ...c, include: v === true })))}
                  aria-label="すべて選択"
                />
              </th>
              <th className="px-2 py-2 font-medium">物理名</th>
              <th className="min-w-28 px-2 py-2 font-medium">論理名（コメント）</th>
              <th className="px-2 py-2 font-medium">データ型</th>
              <th className="w-64 min-w-56 px-2 py-2 font-medium">マスキング</th>
              <th className="w-40 min-w-32 px-2 py-2 font-medium">見出し（任意）</th>
            </tr>
          </thead>
          <tbody>
            {columns.map((c) => (
              <tr key={c.name} className={'border-t align-top ' + (c.include ? '' : 'bg-muted/40 text-muted-foreground')}>
                <td className="px-2 py-2">
                  <Checkbox checked={c.include} onCheckedChange={(v) => update(c.name, { include: v === true })} />
                </td>
                <td className="px-2 py-2 font-mono text-xs">
                  <div className="flex items-center gap-1">
                    {c.is_pk && <KeyRoundIcon className="size-3 text-amber-600" aria-label="主キー" />}
                    <span className="whitespace-nowrap">{c.name}</span>
                  </div>
                </td>
                <td className="px-2 py-2 text-xs">
                  {c.comment || <span className="text-muted-foreground/60">—</span>}
                  {c.suggestion && (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Badge
                          variant="outline"
                          className={
                            'ml-1 h-4 cursor-help px-1 text-[10px] ' +
                            (c.suggestion.level === 'review'
                              ? 'border-amber-400 bg-amber-50 text-amber-800 dark:bg-amber-950/30'
                              : c.mask.type === 'none'
                                ? 'border-orange-400 text-orange-700'
                                : 'border-orange-200 text-orange-600')
                          }
                        >
                          {c.suggestion.level === 'review' ? `要確認: ${c.suggestion.label}` : c.suggestion.label}
                        </Badge>
                      </TooltipTrigger>
                      <TooltipContent side="bottom" className="block">
                        <p className="font-medium">
                          {c.suggestion.level === 'review' ? '要確認（人が判断してください）' : '自動判定: マスキング対象'}（確からしさ {Math.round(c.suggestion.score * 100)}%）
                        </p>
                        <ul className="mt-1 list-disc pl-4">
                          {c.suggestion.reasons.map((r, i) => (
                            <li key={i}>{r}</li>
                          ))}
                        </ul>
                      </TooltipContent>
                    </Tooltip>
                  )}
                </td>
                <td className="px-2 py-2 font-mono text-xs whitespace-nowrap text-muted-foreground">{c.data_type}</td>
                <td className="px-2 py-1.5">
                  <MaskRuleEditor rules={rules} value={c.mask} disabled={!c.include} onChange={(mask) => update(c.name, { mask })} />
                </td>
                <td className="px-2 py-1.5">
                  <Input
                    className="h-7 text-xs"
                    placeholder={c.comment || c.name}
                    value={c.header}
                    disabled={!c.include}
                    onChange={(e) => update(c.name, { header: e.target.value })}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 抽出条件 */}
      <div className="grid grid-cols-1 gap-3 rounded-md border p-3 md:grid-cols-6">
        <div className="grid gap-1 md:col-span-3">
          <Label className="text-xs">抽出条件（WHERE句、"WHERE"は不要）</Label>
          <Textarea
            className="min-h-14 font-mono text-xs"
            placeholder={`例: DEL_FLG = '0' AND UPD_DATE >= DATE '2024-04-01'`}
            value={options.where}
            onChange={(e) => setOpt('where', e.target.value)}
          />
        </div>
        <div className="grid content-start gap-1 md:col-span-3">
          <Label className="text-xs">並び順（ORDER BY句）</Label>
          <Input className="font-mono text-xs" placeholder="例: CUST_ID" value={options.order_by} onChange={(e) => setOpt('order_by', e.target.value)} />
          <div className="grid grid-cols-2 gap-2">
            <div className="grid gap-1">
              <Label className="text-xs">最大件数（空欄=全件）</Label>
              <Input type="number" min={1} className="text-xs" value={options.max_rows} onChange={(e) => setOpt('max_rows', e.target.value)} />
            </div>
            <div className="grid gap-1">
              <Label className="text-xs">シート名（空欄=表名）</Label>
              <Input className="text-xs" placeholder={table.name} value={options.sheet_name} onChange={(e) => setOpt('sheet_name', e.target.value)} />
            </div>
          </div>
        </div>
      </div>

      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={handlePreview} disabled={previewing}>
          {previewing ? <Loader2Icon className="animate-spin" /> : <EyeIcon />}
          プレビュー
        </Button>
        <Button onClick={handleAdd}>
          {editingQueueItem ? <SaveIcon /> : <ListPlusIcon />}
          {editingQueueItem ? 'エクスポートリストを更新' : 'エクスポートリストに追加'}
        </Button>
      </div>

      <PreviewDialog
        open={previewOpen}
        onOpenChange={setPreviewOpen}
        title={`${table.schema_name}.${table.name}`}
        data={preview}
        maskedColumns={maskedNames}
      />
    </div>
  )
}
