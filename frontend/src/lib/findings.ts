// 自動判定の結果（Finding）と人の判断（Decision）の扱い
import type { Decision, Decisions, Finding, MaskRule } from './types'

/** 人の判断を反映した規則。null ならマスクしない（判断が無い場合は推奨規則でマスクする） */
export function effectiveRule(f: Finding, decisions: Decisions): MaskRule | null {
  const d = decisions[f.id]
  if (!d) return f.rule
  if (!d.mask) return null
  return d.rule ?? f.rule
}

/** 要確認のうち、まだ人が判断していないもの */
export function isUndecided(f: Finding, decisions: Decisions): boolean {
  return f.level === 'review' && !decisions[f.id]
}

export function sameRule(a: MaskRule | null | undefined, b: MaskRule | null | undefined): boolean {
  if (!a || !b) return a === b
  return a.type === b.type && JSON.stringify(a.params ?? {}) === JSON.stringify(b.params ?? {})
}

export interface FindingSummary {
  auto: number
  review: number
  undecided: number
  keep: number
}

export function summarize(findings: Finding[], decisions: Decisions): FindingSummary {
  let auto = 0
  let review = 0
  let undecided = 0
  let keep = 0
  for (const f of findings) {
    if (f.level === 'auto') auto++
    else review++
    if (isUndecided(f, decisions)) undecided++
    else if (effectiveRule(f, decisions) === null) keep++
  }
  return { auto, review, undecided, keep }
}

/** 複数の Finding に同じ判断を設定する */
export function decideAll(decisions: Decisions, targets: Finding[], decision: (f: Finding) => Decision): Decisions {
  const next = { ...decisions }
  for (const f of targets) next[f.id] = decision(f)
  return next
}

/** 前回の判断のうち、今回の結果にも存在するものだけを残す（再スキャン時に判断を引き継ぐ） */
export function carryOver(decisions: Decisions, findings: Finding[]): Decisions {
  const ids = new Set(findings.map((f) => f.id))
  return Object.fromEntries(Object.entries(decisions).filter(([id]) => ids.has(id)))
}
