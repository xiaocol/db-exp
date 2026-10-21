// 自動判定の結果一覧。「マスキング対象（自動判定）」と「要確認（人が判断）」の 2 つのタブで表示する
import { Fragment, useEffect, useMemo, useState } from 'react'
import { CheckIcon, FileTextIcon, KeyRoundIcon, SearchIcon, ShieldCheckIcon, ShieldOffIcon, TableIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { MaskRuleEditor } from '@/components/MaskRuleEditor'
import { api } from '@/lib/api'
import { decideAll, effectiveRule, isUndecided, sameRule, summarize } from '@/lib/findings'
import type { Decisions, Finding, FindingLevel, MaskRule, MaskRuleDef } from '@/lib/types'
import { cn } from '@/lib/utils'

interface Props {
  findings: Finding[]
  decisions: Decisions
  onDecisionsChange: (d: Decisions) => void
  rules: MaskRuleDef[]
  hashSalt?: string
  /** 一覧の見出し（DB: 表 / ドキュメント: ファイル） */
  groupLabel: string
}

/** 規則を変更した場合のマスク結果を、サーバーで計算して表示する */
function MaskedSample({ value, rule, fallback, salt }: { value: string; rule: MaskRule | null; fallback?: string; salt: string }) {
  const [result, setResult] = useState<string | null>(null)
  const needsFetch = rule !== null && fallback === undefined
  useEffect(() => {
    if (!needsFetch || !rule) return
    let alive = true
    const timer = window.setTimeout(() => {
      api
        .maskingTest(rule, value, salt)
        .then((r) => alive && setResult(r.result === null ? '(NULL)' : String(r.result)))
        .catch(() => alive && setResult('（プレビュー不可）'))
    }, 250)
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [needsFetch, rule, value, salt])
  if (rule === null) return <span className="text-muted-foreground">{value}</span>
  return <span className="font-medium text-orange-700 dark:text-orange-400">{fallback ?? result ?? '…'}</span>
}

function ScoreBar({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  return (
    <div className="flex items-center gap-1" title={`確からしさ ${pct}%`}>
      <div className="h-1.5 w-10 overflow-hidden rounded bg-muted">
        <div className={cn('h-full', score >= 0.7 ? 'bg-orange-500' : 'bg-amber-400')} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] tabular-nums text-muted-foreground">{pct}</span>
    </div>
  )
}

const normalize = (s: string | null | undefined) => (s ?? '').normalize('NFKC').toLowerCase()

export function FindingsView({ findings, decisions, onDecisionsChange, rules, hashSalt = '', groupLabel }: Props) {
  const summary = summarize(findings, decisions)
  const [tab, setTab] = useState<FindingLevel>(summary.auto === 0 && summary.review > 0 ? 'review' : 'auto')
  const [keyword, setKeyword] = useState('')
  const [onlyUndecided, setOnlyUndecided] = useState(false)

  const visible = useMemo(() => {
    const k = normalize(keyword).trim()
    return findings.filter((f) => {
      if (f.level !== tab) return false
      if (tab === 'review' && onlyUndecided && !isUndecided(f, decisions)) return false
      if (!k) return true
      return [f.file, f.location, f.column, f.column_comment, f.text, f.category_label].some((x) => normalize(x).includes(k))
    })
  }, [findings, tab, keyword, onlyUndecided, decisions])

  const setDecision = (f: Finding, mask: boolean, rule?: MaskRule) => {
    const r = rule ?? decisions[f.id]?.rule ?? f.rule
    // 「そのまま出力」を選んだ後に「マスクする」に戻した場合は推奨規則に戻す
    onDecisionsChange({ ...decisions, [f.id]: { mask, rule: mask && r.type === 'none' ? f.rule : r } })
  }

  const bulk = (mask: boolean) => {
    const targets = visible.filter((f) => tab === 'auto' || isUndecided(f, decisions))
    onDecisionsChange(decideAll(decisions, targets, (f) => ({ mask, rule: decisions[f.id]?.rule ?? f.rule })))
  }

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Tabs value={tab} onValueChange={(v) => setTab(v as FindingLevel)}>
          <TabsList>
            <TabsTrigger value="auto" className="px-3">
              <ShieldCheckIcon />
              マスキング対象（自動判定）
              <Badge variant="secondary" className="h-4 px-1.5 text-[10px]">
                {summary.auto}
              </Badge>
            </TabsTrigger>
            <TabsTrigger value="review" className="px-3">
              要確認（人が判断）
              <Badge variant={summary.undecided > 0 ? 'destructive' : 'secondary'} className="h-4 px-1.5 text-[10px]">
                {summary.undecided > 0 ? `未判断 ${summary.undecided} / ${summary.review}` : summary.review}
              </Badge>
            </TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="relative min-w-40 flex-1">
          <SearchIcon className="absolute top-1/2 left-2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="h-8 pl-8 text-xs" placeholder={`${groupLabel}・列名・語句で絞り込み`} value={keyword} onChange={(e) => setKeyword(e.target.value)} />
        </div>
        {tab === 'review' && (
          <label className="flex items-center gap-1.5 text-xs">
            <Checkbox checked={onlyUndecided} onCheckedChange={(v) => setOnlyUndecided(v === true)} />
            未判断のみ
          </label>
        )}
        <Button size="sm" variant="outline" onClick={() => bulk(true)} disabled={visible.length === 0}>
          <ShieldCheckIcon />
          {tab === 'review' ? '表示中の未判断をマスクする' : 'すべてマスクする'}
        </Button>
        <Button size="sm" variant="outline" onClick={() => bulk(false)} disabled={visible.length === 0}>
          <ShieldOffIcon />
          {tab === 'review' ? '表示中の未判断をマスクしない' : 'すべてマスクしない'}
        </Button>
      </div>

      {tab === 'review' && summary.review > 0 && (
        <p className="text-xs text-muted-foreground">
          判定の確度が低い、または業務上の判断が必要な項目です。値の例と判定理由を確認し、1 件ずつ「マスクする / しない」を選んでください。
        </p>
      )}

      <div className="min-h-0 flex-1 overflow-auto rounded-md border">
        {visible.length === 0 ? (
          <p className="p-6 text-center text-sm text-muted-foreground">
            {findings.length === 0 ? '個人情報と思われる項目は見つかりませんでした。' : '該当する項目はありません。'}
          </p>
        ) : (
          <table className="w-full border-collapse text-sm">
            <thead className="sticky top-0 z-10 bg-muted">
              <tr className="text-left text-xs text-muted-foreground">
                <th className="w-36 min-w-32 px-2 py-2 font-medium whitespace-nowrap">{tab === 'auto' ? 'マスク' : '判断'}</th>
                <th className="min-w-44 px-2 py-2 font-medium">対象</th>
                <th className="w-32 min-w-28 px-2 py-2 font-medium">種類</th>
                <th className="min-w-48 px-2 py-2 font-medium">値の例（元 → マスク後）</th>
                <th className="w-60 min-w-52 px-2 py-2 font-medium">マスキング規則</th>
                <th className="min-w-56 px-2 py-2 font-medium">判定理由</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((f, i) => {
                const newGroup = i === 0 || visible[i - 1].file !== f.file
                const rule = effectiveRule(f, decisions)
                const d = decisions[f.id]
                const undecided = isUndecided(f, decisions)
                const editedRule = d?.rule ?? f.rule
                return (
                  <Fragment key={f.id}>
                    {newGroup && (
                      <tr className="border-t bg-muted/40">
                        <td colSpan={6} className="px-2 py-1 text-xs font-medium">
                          <span className="inline-flex items-center gap-1.5">
                            {f.source === 'db' ? <TableIcon className="size-3.5" /> : <FileTextIcon className="size-3.5" />}
                            <span className="font-mono">{f.file}</span>
                          </span>
                        </td>
                      </tr>
                    )}
                    <tr className={cn('border-t align-top', rule === null && !undecided && 'bg-muted/30 text-muted-foreground', undecided && 'bg-amber-50/60 dark:bg-amber-950/20')}>
                      <td className="px-2 py-2">
                        {tab === 'auto' ? (
                          <label className="flex items-center gap-1.5 text-xs whitespace-nowrap">
                            <Checkbox checked={rule !== null} onCheckedChange={(v) => setDecision(f, v === true)} />
                            {rule !== null ? 'マスクする' : 'マスクしない'}
                          </label>
                        ) : (
                          <div className="flex flex-col gap-1">
                            <div className="flex">
                              <Button
                                size="xs"
                                variant={d?.mask === true ? 'default' : 'outline'}
                                className="rounded-r-none"
                                onClick={() => setDecision(f, true)}
                              >
                                {d?.mask === true && <CheckIcon />}
                                マスクする
                              </Button>
                              <Button
                                size="xs"
                                variant={d?.mask === false ? 'default' : 'outline'}
                                className="-ml-px rounded-l-none"
                                onClick={() => setDecision(f, false)}
                              >
                                {d?.mask === false && <CheckIcon />}
                                しない
                              </Button>
                            </div>
                            {undecided && <span className="text-[10px] font-medium text-amber-700">未判断</span>}
                          </div>
                        )}
                      </td>
                      <td className="px-2 py-2 text-xs">
                        {f.target === 'column' ? (
                          <div className="flex items-center gap-1">
                            {f.is_pk && <KeyRoundIcon className="size-3 shrink-0 text-amber-600" aria-label="主キー" />}
                            <span className="font-mono font-medium">{f.column}</span>
                          </div>
                        ) : (
                          <div>
                            文中{f.text ? <span className="font-medium">「{f.text}」</span> : 'の語句'}
                            <span className="ml-1 text-muted-foreground">{f.occurrences.toLocaleString()} 件</span>
                          </div>
                        )}
                        {f.column_comment && <div className="text-muted-foreground">{f.column_comment}</div>}
                        {(f.location || f.data_type) && (
                          <div className="text-[10px] text-muted-foreground">{[f.location, f.data_type].filter(Boolean).join(' ／ ')}</div>
                        )}
                      </td>
                      <td className="px-2 py-2 text-xs">
                        <div className="mb-1">{f.category_label}</div>
                        <ScoreBar score={f.score} />
                      </td>
                      <td className="px-2 py-2 text-xs">
                        {f.samples.length === 0 ? (
                          <span className="text-muted-foreground">（値なし）</span>
                        ) : (
                          <ul className="space-y-0.5">
                            {f.samples.map((s, si) => (
                              <li key={si} className="break-all">
                                <span className="text-muted-foreground">{s}</span>
                                <span className="mx-1 text-muted-foreground">→</span>
                                <MaskedSample
                                  value={s}
                                  rule={rule}
                                  salt={hashSalt}
                                  fallback={sameRule(rule, f.rule) && !hashSalt ? f.masked_samples[si] : undefined}
                                />
                              </li>
                            ))}
                          </ul>
                        )}
                      </td>
                      <td className="px-2 py-1.5">
                        <MaskRuleEditor
                          rules={rules}
                          value={editedRule}
                          disabled={d?.mask === false}
                          onChange={(r) => setDecision(f, r.type !== 'none', r)}
                        />
                      </td>
                      <td className="px-2 py-2 text-[11px] text-muted-foreground">
                        <ul className="list-disc space-y-0.5 pl-4">
                          {f.reasons.map((r, ri) => (
                            <li key={ri}>{r}</li>
                          ))}
                        </ul>
                      </td>
                    </tr>
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
