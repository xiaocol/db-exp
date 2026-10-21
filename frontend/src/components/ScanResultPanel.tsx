// DB の一括スキャンの進捗と結果（マスキング対象一覧・要確認一覧）
import { useState } from 'react'
import { AlertTriangleIcon, FileSpreadsheetIcon, ListPlusIcon, Loader2Icon, SquareIcon } from 'lucide-react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Progress } from '@/components/ui/progress'
import { FindingsView } from '@/components/FindingsView'
import { summarize } from '@/lib/findings'
import type { DbScanStatus, Decisions, MaskRuleDef } from '@/lib/types'

interface Props {
  job: DbScanStatus
  decisions: Decisions
  onDecisionsChange: (d: Decisions) => void
  rules: MaskRuleDef[]
  hashSalt: string
  onCancel: () => void
  onApplyToQueue: (includeTablesWithoutMask: boolean) => void
  onDownloadReport: () => void
}

export function ScanResultPanel({ job, decisions, onDecisionsChange, rules, hashSalt, onCancel, onApplyToQueue, onDownloadReport }: Props) {
  const [includeAll, setIncludeAll] = useState(false)
  const running = job.status === 'pending' || job.status === 'running'

  if (running) {
    const pct = job.total_tables > 0 ? (job.done_tables / job.total_tables) * 100 : 0
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3">
        <Loader2Icon className="size-6 animate-spin text-muted-foreground" />
        <p className="text-sm">
          スキーマ <span className="font-mono">{job.schema_name}</span> をスキャンしています…（{job.done_tables} / {job.total_tables || '?'} 表）
        </p>
        <Progress value={pct} className="w-80" />
        {job.current_table && <p className="font-mono text-xs text-muted-foreground">{job.current_table}</p>}
        <Button size="sm" variant="outline" onClick={onCancel}>
          <SquareIcon />
          中止
        </Button>
      </div>
    )
  }

  if (job.status !== 'done') {
    return (
      <Alert variant={job.status === 'error' ? 'destructive' : 'default'} className="m-4">
        <AlertDescription>{job.message}</AlertDescription>
      </Alert>
    )
  }

  const summary = summarize(job.findings, decisions)
  const errors = job.tables.filter((t) => t.error)
  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-0 flex-1">
          <h2 className="font-semibold">
            一括スキャン結果 <span className="font-mono text-sm">{job.schema_name}</span>
          </h2>
          <p className="text-xs text-muted-foreground">{job.message}</p>
        </div>
        <Button size="sm" variant="outline" onClick={onDownloadReport} title="判定結果（元の値は含まない）を Excel で保存します">
          <FileSpreadsheetIcon />
          判定結果一覧（Excel）
        </Button>
      </div>

      {errors.length > 0 && (
        <Alert className="py-2">
          <AlertTriangleIcon />
          <AlertDescription className="text-xs">
            読み取れなかった表: {errors.map((t) => `${t.table}（${t.error?.split('\n')[0]}）`).join('、')}
          </AlertDescription>
        </Alert>
      )}

      <FindingsView
        findings={job.findings}
        decisions={decisions}
        onDecisionsChange={onDecisionsChange}
        rules={rules}
        hashSalt={hashSalt}
        groupLabel="表"
      />

      <div className="flex flex-wrap items-center justify-end gap-3">
        {summary.undecided > 0 && (
          <span className="text-xs text-amber-700">要確認の未判断が {summary.undecided} 件あります。すべて判断するとエクスポートリストに反映できます。</span>
        )}
        <label className="flex items-center gap-1.5 text-xs">
          <Checkbox checked={includeAll} onCheckedChange={(v) => setIncludeAll(v === true)} />
          マスク対象の列がない表も含める
        </label>
        <Button onClick={() => onApplyToQueue(includeAll)} disabled={summary.undecided > 0}>
          <ListPlusIcon />
          判定結果をエクスポートリストに反映
        </Button>
      </div>
    </div>
  )
}
