// 画面全体のレイアウト
//   データベース: 接続した DB の表をマスクして Excel / INSERT 文 / UPDATE 文に出力
//   ドキュメント: Excel・CSV・テキスト・Markdown をマスクして Markdown に出力
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { DatabaseIcon, FileTextIcon, ShieldCheckIcon } from 'lucide-react'

import { DbWorkspace } from '@/components/DbWorkspace'
import { DocWorkspace } from '@/components/DocWorkspace'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { api, errorMessage } from '@/lib/api'
import type { ConnectionProfile, MaskRuleDef } from '@/lib/types'
import { cn } from '@/lib/utils'

type Mode = 'db' | 'doc'

export default function App() {
  const [mode, setMode] = useState<Mode>('db')
  const [rules, setRules] = useState<MaskRuleDef[]>([])
  const [active, setActive] = useState<ConnectionProfile | null>(null)

  useEffect(() => {
    api.maskingRules().then(setRules).catch((e) => toast.error(errorMessage(e)))
  }, [])

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b px-4">
        <ShieldCheckIcon className="size-5 text-primary" />
        <h1 className="font-semibold">マスキング出力ツール</h1>
        <Tabs value={mode} onValueChange={(v) => setMode(v as Mode)} className="ml-2">
          <TabsList>
            <TabsTrigger value="db" className="px-3">
              <DatabaseIcon />
              データベース
            </TabsTrigger>
            <TabsTrigger value="doc" className="px-3">
              <FileTextIcon />
              ドキュメント
            </TabsTrigger>
          </TabsList>
        </Tabs>
        <span className="hidden text-xs text-muted-foreground lg:inline">
          {mode === 'db' ? 'Oracle / PostgreSQL → Excel・INSERT 文・UPDATE 文' : 'Excel・CSV・テキスト・Markdown → Markdown'}
        </span>
        <div className="ml-auto text-xs text-muted-foreground">
          {mode === 'db' &&
            (active ? (
              <span>
                接続中: <span className="font-medium text-foreground">{active.name}</span>
              </span>
            ) : (
              '未接続'
            ))}
        </div>
      </header>

      {/* 切り替えても作業中の状態を保つよう、両方を描画して表示だけ切り替える */}
      <div className={cn('flex min-h-0 min-w-0 flex-1', mode !== 'db' && 'hidden')}>
        <DbWorkspace rules={rules} onActiveChange={setActive} />
      </div>
      <div className={cn('flex min-h-0 min-w-0 flex-1', mode !== 'doc' && 'hidden')}>
        <DocWorkspace rules={rules} />
      </div>
    </div>
  )
}
