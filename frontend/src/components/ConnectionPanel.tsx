// 保存済み接続の一覧と、接続・切断操作
import { useState } from 'react'
import { toast } from 'sonner'
import { DatabaseIcon, Loader2Icon, PencilIcon, PlusIcon, Trash2Icon, UnplugIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { ConnectionDialog } from '@/components/ConnectionDialog'
import { api, errorMessage } from '@/lib/api'
import type { ConnectionProfile } from '@/lib/types'
import { cn } from '@/lib/utils'

interface Props {
  connections: ConnectionProfile[]
  activeId: string | null
  onReload: () => Promise<void>
  onConnected: (profile: ConnectionProfile) => void
  onDisconnected: () => void
}

export function ConnectionPanel({ connections, activeId, onReload, onConnected, onDisconnected }: Props) {
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<ConnectionProfile | null>(null)
  const [pwTarget, setPwTarget] = useState<ConnectionProfile | null>(null)
  const [password, setPassword] = useState('')
  const [busyId, setBusyId] = useState<string | null>(null)

  const doConnect = async (profile: ConnectionProfile, pw?: string) => {
    setBusyId(profile.id)
    try {
      const res = await api.connect(profile.id, pw)
      toast.success(`${profile.name} に接続しました`, { description: res.server_version ?? undefined })
      setPwTarget(null)
      setPassword('')
      await onReload()
      onConnected(profile)
    } catch (e) {
      toast.error('接続に失敗しました', { description: errorMessage(e) })
    } finally {
      setBusyId(null)
    }
  }

  const handleConnect = (profile: ConnectionProfile) => {
    // パスワード未保存の場合は入力ダイアログを表示する
    if (profile.has_saved_password) {
      void doConnect(profile)
    } else {
      setPassword('')
      setPwTarget(profile)
    }
  }

  const handleDisconnect = async (profile: ConnectionProfile) => {
    await api.disconnect(profile.id)
    await onReload()
    onDisconnected()
  }

  const handleDelete = async (profile: ConnectionProfile) => {
    if (!window.confirm(`接続「${profile.name}」を削除しますか？`)) return
    try {
      await api.deleteConnection(profile.id)
      if (profile.id === activeId) onDisconnected()
      await onReload()
    } catch (e) {
      toast.error('削除に失敗しました', { description: errorMessage(e) })
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">接続先</h2>
        <Button
          size="sm"
          variant="outline"
          onClick={() => {
            setEditing(null)
            setDialogOpen(true)
          }}
        >
          <PlusIcon />
          新規
        </Button>
      </div>

      {connections.length === 0 && (
        <p className="rounded-md border border-dashed p-3 text-xs text-muted-foreground">
          接続情報がありません。「新規」から登録してください。
        </p>
      )}

      <ul className="flex flex-col gap-1">
        {connections.map((c) => {
          const active = c.id === activeId
          return (
            <li
              key={c.id}
              className={cn(
                'group flex items-center gap-2 rounded-md border px-2 py-1.5',
                active ? 'border-primary bg-primary/5' : 'hover:bg-muted/50',
              )}
            >
              <DatabaseIcon className="size-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium">{c.name}</div>
                <div className="flex items-center gap-1 text-xs text-muted-foreground">
                  <Badge variant="secondary" className="h-4 px-1 text-[10px]">
                    {c.db_type === 'oracle' ? 'Oracle' : 'PostgreSQL'}
                  </Badge>
                  <span className="truncate">{c.username}</span>
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-0.5">
                <Button
                  size="icon-xs"
                  variant="ghost"
                  title="編集"
                  onClick={() => {
                    setEditing(c)
                    setDialogOpen(true)
                  }}
                >
                  <PencilIcon />
                </Button>
                <Button size="icon-xs" variant="ghost" title="削除" onClick={() => handleDelete(c)}>
                  <Trash2Icon />
                </Button>
                {active ? (
                  <Button size="xs" variant="outline" onClick={() => handleDisconnect(c)}>
                    <UnplugIcon />
                    切断
                  </Button>
                ) : (
                  <Button size="xs" onClick={() => handleConnect(c)} disabled={busyId === c.id}>
                    {busyId === c.id && <Loader2Icon className="animate-spin" />}
                    接続
                  </Button>
                )}
              </div>
            </li>
          )
        })}
      </ul>

      <ConnectionDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        editing={editing}
        onSaved={async (saved) => {
          // 編集した接続が使用中だった場合はセッションが破棄されるため切断扱いにする
          if (saved.id === activeId) onDisconnected()
          await onReload()
        }}
      />

      <Dialog open={pwTarget !== null} onOpenChange={(o) => !o && setPwTarget(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>パスワード入力</DialogTitle>
            <DialogDescription>
              {pwTarget?.name}（{pwTarget?.username}）のパスワードを入力してください。
            </DialogDescription>
          </DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              if (pwTarget) void doConnect(pwTarget, password)
            }}
            className="grid gap-4"
          >
            <Input type="password" autoFocus value={password} onChange={(e) => setPassword(e.target.value)} />
            <DialogFooter>
              <Button type="submit" disabled={!password || busyId !== null}>
                {busyId && <Loader2Icon className="animate-spin" />}
                接続
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
