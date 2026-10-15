// マスキング適用後データのプレビュー表示
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import type { PreviewResult } from '@/lib/types'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  data: PreviewResult | null
  /** マスキング対象の列名（強調表示用） */
  maskedColumns: Set<string>
}

export function PreviewDialog({ open, onOpenChange, title, data, maskedColumns }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[85vh] flex-col sm:max-w-[min(1200px,95vw)]">
        <DialogHeader>
          <DialogTitle>プレビュー: {title}</DialogTitle>
          <DialogDescription>
            マスキング適用後の先頭 {data?.rows.length ?? 0} 件です。
            <Badge variant="outline" className="ml-2 border-orange-400 bg-orange-50 text-orange-700 dark:bg-orange-950/30">
              マスキング列
            </Badge>
          </DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-auto rounded-md border">
          {data && (
            <table className="w-max min-w-full border-collapse text-xs">
              <thead className="sticky top-0 bg-muted">
                <tr>
                  <th className="border-b px-2 py-1.5 text-right font-medium text-muted-foreground">#</th>
                  {data.columns.map((c) => (
                    <th
                      key={c}
                      className={
                        'border-b px-2 py-1.5 text-left font-mono font-medium whitespace-nowrap ' +
                        (maskedColumns.has(c) ? 'bg-orange-100 dark:bg-orange-950/50' : '')
                      }
                    >
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row, i) => (
                  <tr key={i} className="odd:bg-muted/30">
                    <td className="px-2 py-1 text-right text-muted-foreground tabular-nums">{i + 1}</td>
                    {row.map((v, j) => (
                      <td
                        key={j}
                        className={
                          'max-w-80 truncate px-2 py-1 whitespace-nowrap ' +
                          (maskedColumns.has(data.columns[j]) ? 'bg-orange-50/70 dark:bg-orange-950/20' : '') +
                          (typeof v === 'number' ? ' text-right tabular-nums' : '')
                        }
                        title={v === null ? '' : String(v)}
                      >
                        {v === null ? <span className="text-muted-foreground/60">(NULL)</span> : String(v)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
