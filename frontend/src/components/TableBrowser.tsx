// スキーマ選択と表・ビューの一覧（名前・コメントで検索可能）
import { useMemo, useState } from 'react'
import { Loader2Icon, SearchIcon, TableIcon, EyeIcon } from 'lucide-react'

import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { TableInfo } from '@/lib/types'
import { cn } from '@/lib/utils'

interface Props {
  schemas: string[]
  schema: string | null
  onSchemaChange: (schema: string) => void
  tables: TableInfo[]
  loading: boolean
  selected: string | null
  onSelect: (table: TableInfo) => void
}

export function TableBrowser({ schemas, schema, onSchemaChange, tables, loading, selected, onSelect }: Props) {
  const [keyword, setKeyword] = useState('')

  const filtered = useMemo(() => {
    // 全角・半角や大文字・小文字の違いを無視して検索する
    const k = keyword.normalize('NFKC').toLowerCase().trim()
    if (!k) return tables
    return tables.filter(
      (t) =>
        t.name.normalize('NFKC').toLowerCase().includes(k) ||
        (t.comment ?? '').normalize('NFKC').toLowerCase().includes(k),
    )
  }, [tables, keyword])

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <h2 className="text-sm font-semibold">テーブル選択</h2>
      <Select value={schema ?? undefined} onValueChange={onSchemaChange}>
        <SelectTrigger className="w-full">
          <SelectValue placeholder="スキーマを選択" />
        </SelectTrigger>
        <SelectContent>
          {schemas.map((s) => (
            <SelectItem key={s} value={s}>
              {s}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <div className="relative">
        <SearchIcon className="absolute top-1/2 left-2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          className="pl-8"
          placeholder="表名・論理名で検索"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
      </div>
      <div className="text-xs text-muted-foreground">
        {loading ? '読み込み中…' : `${filtered.length} / ${tables.length} 件`}
      </div>
      <ScrollArea className="min-h-0 flex-1 rounded-md border">
        {loading ? (
          <div className="flex items-center justify-center p-6">
            <Loader2Icon className="size-5 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <ul className="p-1">
            {filtered.map((t) => (
              <li key={t.name}>
                <button
                  type="button"
                  onClick={() => onSelect(t)}
                  className={cn(
                    'flex w-full items-start gap-2 rounded px-2 py-1.5 text-left hover:bg-muted',
                    selected === t.name && 'bg-primary/10 hover:bg-primary/10',
                  )}
                >
                  {t.table_type === 'VIEW' ? (
                    <EyeIcon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                  ) : (
                    <TableIcon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                  )}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-mono text-xs">{t.name}</span>
                    {t.comment && (
                      <span className="block truncate text-xs text-muted-foreground">{t.comment}</span>
                    )}
                  </span>
                  {t.num_rows !== null && (
                    <span className="shrink-0 text-[10px] text-muted-foreground tabular-nums">
                      {t.num_rows.toLocaleString()}
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </ScrollArea>
    </div>
  )
}
