// 列ごとのマスキング規則選択と、規則固有パラメータの入力
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { MaskRule, MaskRuleDef } from '@/lib/types'

interface Props {
  rules: MaskRuleDef[]
  value: MaskRule
  onChange: (rule: MaskRule) => void
  disabled?: boolean
}

/** 規則の既定パラメータを生成する */
export function defaultParams(def: MaskRuleDef | undefined): Record<string, unknown> {
  const params: Record<string, unknown> = {}
  def?.params.forEach((p) => {
    params[p.key] = p.default
  })
  return params
}

export function MaskRuleEditor({ rules, value, onChange, disabled }: Props) {
  const def = rules.find((r) => r.type === value.type)

  const changeType = (type: string) => {
    const nextDef = rules.find((r) => r.type === type)
    onChange({ type, params: defaultParams(nextDef) })
  }

  const setParam = (key: string, v: unknown) => onChange({ ...value, params: { ...value.params, [key]: v } })

  return (
    <div className="flex flex-col gap-1">
      <Select value={value.type} onValueChange={changeType} disabled={disabled}>
        <SelectTrigger size="sm" className={value.type !== 'none' ? 'w-full border-orange-400 bg-orange-50 dark:bg-orange-950/30' : 'w-full'}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {rules.map((r) => (
            <SelectItem key={r.type} value={r.type} title={r.example}>
              {r.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {def && def.example && <span className="text-[10px] text-muted-foreground">例: {def.example}</span>}
      {def && def.params.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {def.params.map((p) =>
            p.kind === 'select' ? (
              <Select
                key={p.key}
                value={String(value.params[p.key] ?? p.default)}
                onValueChange={(v) => setParam(p.key, v)}
                disabled={disabled}
              >
                <SelectTrigger size="sm" className="h-6 text-xs" title={p.label}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {p.options?.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <label key={p.key} className="flex items-center gap-1 text-[10px] text-muted-foreground">
                {p.label}
                <Input
                  className="h-6 w-16 px-1 text-xs"
                  type={p.kind === 'number' ? 'number' : 'text'}
                  value={String(value.params[p.key] ?? '')}
                  disabled={disabled}
                  onChange={(e) =>
                    setParam(p.key, p.kind === 'number' ? (e.target.value === '' ? '' : Number(e.target.value)) : e.target.value)
                  }
                />
              </label>
            ),
          )}
        </div>
      )}
    </div>
  )
}
