// 接続情報の新規作成・編集ダイアログ
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Loader2Icon, PlugZapIcon } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { api, errorMessage } from '@/lib/api'
import type { ConnectionInput, ConnectionProfile, DbType } from '@/lib/types'

const EMPTY: ConnectionInput = {
  name: '',
  db_type: 'oracle',
  host: 'localhost',
  port: 1521,
  database: '',
  oracle_connect_type: 'service_name',
  dsn: '',
  username: '',
  password: '',
  save_password: false,
}

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** 編集対象（新規作成時は null） */
  editing: ConnectionProfile | null
  onSaved: (profile: ConnectionProfile) => void
}

export function ConnectionDialog({ open, onOpenChange, editing, onSaved }: Props) {
  const [form, setForm] = useState<ConnectionInput>(EMPTY)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (open) {
      setForm(editing ? { ...editing, password: '' } : EMPTY)
    }
  }, [open, editing])

  const set = <K extends keyof ConnectionInput>(key: K, value: ConnectionInput[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  const changeDbType = (dbType: DbType) => {
    // DB 種別に応じて既定ポートを切り替える
    setForm((f) => ({ ...f, db_type: dbType, port: dbType === 'oracle' ? 1521 : 5432 }))
  }

  const isOracle = form.db_type === 'oracle'
  const useDsn = isOracle && form.oracle_connect_type === 'dsn'

  const handleTest = async () => {
    setTesting(true)
    try {
      const res = await api.testConnection(form)
      toast.success(res.message, { description: res.server_version ?? undefined })
    } catch (e) {
      toast.error('接続に失敗しました', { description: errorMessage(e) })
    } finally {
      setTesting(false)
    }
  }

  const handleSave = async () => {
    if (!form.name.trim()) {
      toast.error('接続名を入力してください。')
      return
    }
    setSaving(true)
    try {
      const saved = await api.saveConnection(form)
      toast.success('接続情報を保存しました。')
      onSaved(saved)
      onOpenChange(false)
    } catch (e) {
      toast.error('保存に失敗しました', { description: errorMessage(e) })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? '接続情報の編集' : '新しい接続'}</DialogTitle>
          <DialogDescription>
            接続はすべて読み取り専用で行われます。データの更新は行いません。
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4">
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2 grid gap-1.5">
              <Label htmlFor="conn-name">接続名</Label>
              <Input
                id="conn-name"
                placeholder="例: 本番DB（参照用）"
                value={form.name}
                onChange={(e) => set('name', e.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label>DB種別</Label>
              <Select value={form.db_type} onValueChange={(v) => changeDbType(v as DbType)}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="oracle">Oracle</SelectItem>
                  <SelectItem value="postgresql">PostgreSQL</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {isOracle && (
            <RadioGroup
              className="flex gap-4"
              value={form.oracle_connect_type}
              onValueChange={(v) => set('oracle_connect_type', v as ConnectionInput['oracle_connect_type'])}
            >
              {[
                ['service_name', 'サービス名'],
                ['sid', 'SID'],
                ['dsn', 'TNS名 / 接続文字列'],
              ].map(([value, label]) => (
                <div key={value} className="flex items-center gap-1.5">
                  <RadioGroupItem value={value} id={`ct-${value}`} />
                  <Label htmlFor={`ct-${value}`} className="font-normal">
                    {label}
                  </Label>
                </div>
              ))}
            </RadioGroup>
          )}

          {useDsn ? (
            <div className="grid gap-1.5">
              <Label htmlFor="conn-dsn">接続文字列</Label>
              <Input
                id="conn-dsn"
                placeholder="例: dbhost:1521/ORCLPDB1 または (DESCRIPTION=...)"
                value={form.dsn}
                onChange={(e) => set('dsn', e.target.value)}
              />
            </div>
          ) : (
            <div className="grid grid-cols-4 gap-3">
              <div className="col-span-3 grid gap-1.5">
                <Label htmlFor="conn-host">ホスト名</Label>
                <Input id="conn-host" value={form.host} onChange={(e) => set('host', e.target.value)} />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="conn-port">ポート</Label>
                <Input
                  id="conn-port"
                  type="number"
                  value={form.port ?? ''}
                  onChange={(e) => set('port', e.target.value ? Number(e.target.value) : null)}
                />
              </div>
              <div className="col-span-4 grid gap-1.5">
                <Label htmlFor="conn-db">
                  {isOracle ? (form.oracle_connect_type === 'sid' ? 'SID' : 'サービス名') : 'データベース名'}
                </Label>
                <Input
                  id="conn-db"
                  placeholder={isOracle ? '例: ORCLPDB1' : '例: postgres'}
                  value={form.database}
                  onChange={(e) => set('database', e.target.value)}
                />
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="conn-user">ユーザー名</Label>
              <Input
                id="conn-user"
                autoComplete="off"
                value={form.username}
                onChange={(e) => set('username', e.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="conn-pw">パスワード</Label>
              <Input
                id="conn-pw"
                type="password"
                autoComplete="new-password"
                placeholder={editing?.has_saved_password ? '（保存済み・変更時のみ入力）' : ''}
                value={form.password ?? ''}
                onChange={(e) => set('password', e.target.value)}
              />
            </div>
          </div>

          <div className="flex items-start gap-2">
            <Checkbox
              id="conn-save-pw"
              checked={form.save_password}
              onCheckedChange={(v) => set('save_password', v === true)}
            />
            <div className="grid gap-0.5">
              <Label htmlFor="conn-save-pw" className="font-normal">
                パスワードを保存する
              </Label>
              <p className="text-xs text-muted-foreground">
                ユーザーフォルダ内に簡易的な難読化のみで保存されます。共用PCでは保存しないでください。
              </p>
            </div>
          </div>
        </div>

        <DialogFooter className="gap-2 sm:justify-between">
          <Button variant="outline" onClick={handleTest} disabled={testing}>
            {testing ? <Loader2Icon className="animate-spin" /> : <PlugZapIcon />}
            接続テスト
          </Button>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              キャンセル
            </Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving && <Loader2Icon className="animate-spin" />}
              保存
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
