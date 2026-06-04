import { useState, useEffect } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Cpu, Wifi, WifiOff, RefreshCw, ChevronLeft, X, Save, Trash2, MessageSquare } from 'lucide-react'
import { toast } from 'sonner'

import { api, APIError, type Device } from '@/lib/api'
import { useApi } from '@/lib/useApi'
import { formatDate, formatRelative } from '@/lib/utils'

import { Conversations } from './Conversations'

/**
 * Devices — V2 #5 wired to /api/*; V2 #6 added device metadata
 * editing + delete.
 *
 * Clicking a device opens a detail modal (instead of jumping
 * straight to conversations as in V2 #5). The modal exposes
 * name/notes/room editing, a delete button, and a "view
 * conversation history" link that navigates to the per-device
 * conversation view. The "unknown" synthetic bucket is
 * protected from edits and deletes (matches the backend
 * 400 on /api/devices/unknown DELETE).
 */
export function Devices() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detailId, setDetailId] = useState<string | null>(null)
  const { data, error, loading, refresh } = useApi<Device[]>(api.listDevices)

  if (selectedId !== null) {
    return (
      <div className="space-y-4">
        <button
          onClick={() => setSelectedId(null)}
          className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ChevronLeft className="h-4 w-4" />
          返回设备列表
        </button>
        <Conversations deviceId={selectedId} />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">设备列表</h2>
          <p className="text-sm text-muted-foreground">
            管理已连接到 xiaozhi-bridge 的 ESP32 设备
          </p>
        </div>
        <button
          onClick={() => {
            refresh()
            toast.info('已刷新设备列表')
          }}
          className="p-2 rounded-md hover:bg-muted"
          title="刷新"
        >
          <RefreshCw className="h-4 w-4" />
        </button>
      </div>

      {error && <ErrorBlock message={error} onRetry={refresh} />}
      {loading && <SkeletonList />}

      {!loading && !error && (data?.length ?? 0) === 0 && (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            <Cpu className="h-12 w-12 mx-auto mb-3 opacity-30" />
            <p>还没有设备连接</p>
            <p className="text-xs mt-1">
              配置 ESP32 固件指向本后端即可。匿名连接会落到 “unknown” 设备桶。
            </p>
          </CardContent>
        </Card>
      )}

      {!loading && !error && (data?.length ?? 0) > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {(data ?? []).map((d) => (
            <DeviceCard
              key={d.id}
              device={d}
              onOpenDetail={() => setDetailId(d.id)}
            />
          ))}
        </div>
      )}

      {detailId !== null && (
        <DeviceDetailModal
          deviceId={detailId}
          onClose={() => setDetailId(null)}
          onDeleted={() => {
            setDetailId(null)
            refresh()
          }}
          onViewConversations={() => {
            const id = detailId
            setDetailId(null)
            setSelectedId(id)
          }}
        />
      )}
    </div>
  )
}

function DeviceCard({ device, onOpenDetail }: { device: Device; onOpenDetail: () => void }) {
  const online = device.state !== 'offline' && !!device.sessionId
  return (
    <Card
      className="cursor-pointer hover:border-primary/40 transition-colors"
      onClick={onOpenDetail}
    >
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Cpu className="h-5 w-5" />
          {device.name}
          {device.id === 'unknown' && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-500 font-normal">
              匿名
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">状态</span>
            <span className="flex items-center gap-1.5">
              {online ? (
                <>
                  <Wifi className="h-3 w-3 text-emerald-500" />
                  <span className="text-emerald-500">在线 · {device.state}</span>
                </>
              ) : (
                <>
                  <WifiOff className="h-3 w-3 text-gray-500" />
                  <span className="text-gray-500">离线</span>
                </>
              )}
            </span>
          </div>
          {device.room && (
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">房间</span>
              <span>{device.room}</span>
            </div>
          )}
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">ID</span>
            <span className="font-mono text-xs">{device.id}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">最近活动</span>
            <span
              className="text-xs text-muted-foreground"
              title={formatDate(device.lastSeen)}
            >
              {formatRelative(device.lastSeen)}
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

/**
 * DeviceDetailModal — V2 #6.
 *
 * Fetches the latest record on open (so name/notes/room changes
 * from another tab show up), then submits a partial PATCH on
 * Save. Delete is gated by window.confirm and disabled for the
 * synthetic 'unknown' bucket (matches the backend 400).
 */
function DeviceDetailModal({
  deviceId,
  onClose,
  onDeleted,
  onViewConversations,
}: {
  deviceId: string
  onClose: () => void
  onDeleted: () => void
  onViewConversations: () => void
}) {
  // Local form state — kept separate from the server record so
  // the user can edit without committing on every keystroke.
  const [record, setRecord] = useState<Device | null>(null)
  const [name, setName] = useState('')
  const [notes, setNotes] = useState('')
  const [room, setRoom] = useState('')
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // Fetch latest record on open (re-fetches even if the list
  // already has it, in case the device updated in the last few
  // seconds).
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .getDevice(deviceId)
      .then((d) => {
        if (cancelled) return
        setRecord(d)
        setName(d.name === d.id ? '' : d.name) // pre-fill only user-set name
        setNotes(d.notes ?? '')
        setRoom(d.room ?? '')
      })
      .catch((e: unknown) => {
        if (cancelled) return
        setError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [deviceId])

  // The 'unknown' synthetic bucket is a fallback for firmware
  // that forgot the Device-Id header. Editing it would silently
  // rename every orphan row's display label, which is misleading.
  // The backend also rejects DELETE on 'unknown' with a 400.
  const isProtected = deviceId === 'unknown'

  // Disable Save when nothing changed (so the button click feels
  // meaningful) or when the form is mid-submit.
  const dirty =
    record !== null &&
    (name !== (record.name === record.id ? '' : record.name) ||
      notes !== (record.notes ?? '') ||
      room !== (record.room ?? ''))

  async function handleSave() {
    if (!record) return
    if (!dirty) return
    setSaving(true)
    setError(null)
    try {
      const patch: { name?: string; notes?: string; room?: string } = {}
      const originalName = record.name === record.id ? '' : record.name
      if (name !== originalName) patch.name = name
      if (notes !== (record.notes ?? '')) patch.notes = notes
      if (room !== (record.room ?? '')) patch.room = room
      const updated = await api.patchDevice(deviceId, patch)
      setRecord(updated)
      toast.success('已保存')
      onClose()
    } catch (e: unknown) {
      const msg = e instanceof APIError ? e.message : e instanceof Error ? e.message : String(e)
      setError(msg)
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (isProtected) return
    const ok = window.confirm(
      `确定要删除设备 “${record?.name ?? deviceId}” 吗？\n\n` +
        `此设备的对话记录会保留，但会被归到 “unknown” 桶。`,
    )
    if (!ok) return
    setDeleting(true)
    setError(null)
    try {
      await api.deleteDevice(deviceId)
      toast.success('已删除')
      onDeleted()
    } catch (e: unknown) {
      const msg = e instanceof APIError ? e.message : e instanceof Error ? e.message : String(e)
      setError(msg)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <Card
        className="w-full max-w-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <CardHeader>
          <CardTitle className="flex items-center justify-between text-base">
            <span>设备详情</span>
            <button
              onClick={onClose}
              className="p-1 rounded hover:bg-muted"
              title="关闭"
            >
              <X className="h-4 w-4" />
            </button>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading && (
            <div className="py-8 text-center text-muted-foreground text-sm">
              加载中...
            </div>
          )}
          {!loading && error && (
            <div className="py-4 text-sm text-destructive">{error}</div>
          )}
          {!loading && record && (
            <div className="space-y-4">
              {/* readonly meta block */}
              <div className="space-y-1.5 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">ID</span>
                  <span className="font-mono text-xs">{record.id}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">最近活动</span>
                  <span
                    className="text-xs text-muted-foreground"
                    title={formatDate(record.lastSeen)}
                  >
                    {formatRelative(record.lastSeen)}
                  </span>
                </div>
              </div>

              {/* editable fields */}
              <div className="space-y-3">
                <FormField
                  label="名称"
                  value={name}
                  onChange={setName}
                  placeholder={record.id}
                  disabled={isProtected}
                />
                <FormField
                  label="房间"
                  value={room}
                  onChange={setRoom}
                  placeholder="例如：客厅"
                  disabled={isProtected}
                />
                <FormField
                  label="备注"
                  value={notes}
                  onChange={setNotes}
                  placeholder="例如：主控"
                  disabled={isProtected}
                  multiline
                />
              </div>

              {isProtected && (
                <p className="text-xs text-amber-500">
                  匿名设备桶为系统保留，不能编辑或删除。
                </p>
              )}

              {error && (
                <p className="text-sm text-destructive">{error}</p>
              )}

              {/* actions */}
              <div className="flex flex-wrap items-center gap-2 pt-2 border-t">
                <button
                  onClick={onViewConversations}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm hover:bg-muted"
                  title="查看此设备的对话记录"
                >
                  <MessageSquare className="h-4 w-4" />
                  对话记录
                </button>
                <div className="flex-1" />
                <button
                  onClick={handleDelete}
                  disabled={isProtected || deleting}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm text-destructive hover:bg-destructive/10 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Trash2 className="h-4 w-4" />
                  {deleting ? '删除中...' : '删除'}
                </button>
                <button
                  onClick={handleSave}
                  disabled={!dirty || saving || isProtected}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Save className="h-4 w-4" />
                  {saving ? '保存中...' : '保存'}
                </button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function FormField({
  label,
  value,
  onChange,
  placeholder,
  disabled,
  multiline,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  disabled?: boolean
  multiline?: boolean
}) {
  return (
    <label className="block space-y-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      {multiline ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          disabled={disabled}
          rows={3}
          className="w-full px-3 py-1.5 rounded-md border bg-background text-sm placeholder:text-muted-foreground/50 disabled:opacity-50 disabled:cursor-not-allowed resize-none"
        />
      ) : (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          disabled={disabled}
          className="w-full px-3 py-1.5 rounded-md border bg-background text-sm placeholder:text-muted-foreground/50 disabled:opacity-50 disabled:cursor-not-allowed"
        />
      )}
    </label>
  )
}

function ErrorBlock({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <Card className="border-destructive/50">
      <CardContent className="py-6 text-center space-y-2">
        <p className="text-destructive text-sm">加载失败：{message}</p>
        <button
          onClick={onRetry}
          className="text-xs text-muted-foreground hover:text-foreground underline"
        >
          重试
        </button>
      </CardContent>
    </Card>
  )
}

function SkeletonList() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {[0, 1].map((i) => (
        <Card key={i}>
          <CardContent className="py-4 space-y-2">
            <div className="h-5 w-32 bg-muted animate-pulse rounded" />
            <div className="h-3 w-full bg-muted animate-pulse rounded" />
            <div className="h-3 w-2/3 bg-muted animate-pulse rounded" />
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
