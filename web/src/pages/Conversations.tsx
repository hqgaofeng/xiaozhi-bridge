import { useMemo, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { MessageCircle, Search, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'

import { api, type Conversation, type Device } from '@/lib/api'
import { useApi } from '@/lib/useApi'
import { cn, formatDate, formatRelative } from '@/lib/utils'

/**
 * Conversations — V2 #5: real data from /api/conversations.
 *
 * Supports filtering by deviceId (?deviceId=... query), which is
 * what the Devices page links to when you click a single device.
 * The device filter is kept client-side too (search box) so users
 * can quickly narrow without going back to /api.
 */
export function Conversations({ deviceId }: { deviceId?: string } = {}) {
  // The api.listConversations method returns the right shape whether
  // deviceId is set or not, so the hook signature is uniform.
  const fetcher = useMemo(
    () => () => api.listConversations({ deviceId, limit: 100 }),
    [deviceId],
  )
  const { data, error, loading, refresh } = useApi<Conversation[]>(fetcher)

  // Pull the device list too so we can show a friendly "esp32-001"
  // → name mapping next to the filter. Tolerates a devices error:
  // we just won't show friendly names if /api/devices is down.
  const devicesResult = useApi<Device[]>(api.listDevices)
  const deviceNameById = useMemo(() => {
    const m = new Map<string, string>()
    for (const d of devicesResult.data ?? []) m.set(d.id, d.name || d.id)
    return m
  }, [devicesResult.data])

  const [query, setQuery] = useState('')

  // Filter by user-typed text. Matches anywhere in the conversation
  // text — the per-turn search is what users expect from chat UIs.
  const filtered = useMemo(() => {
    if (!data) return []
    const q = query.trim().toLowerCase()
    if (!q) return data
    return data.filter((c) =>
      c.turns.some((t) => t.text.toLowerCase().includes(q)),
    )
  }, [data, query])

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-xl font-semibold">对话历史</h2>
          <p className="text-sm text-muted-foreground">
            {deviceId
              ? `筛选设备：${deviceNameById.get(deviceId) ?? deviceId}`
              : '所有设备的对话记录'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="h-4 w-4 absolute left-2.5 top-2.5 text-muted-foreground" />
            <Input
              placeholder="搜索对话内容…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="pl-8 w-64"
            />
          </div>
          <button
            onClick={() => {
              refresh()
              toast.info('已刷新对话列表')
            }}
            className="p-2 rounded-md hover:bg-muted"
            title="刷新"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>
      </div>

      {error && <ErrorBlock message={error} onRetry={refresh} />}
      {loading && <SkeletonList />}

      {!loading && !error && filtered.length === 0 && (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            <MessageCircle className="h-12 w-12 mx-auto mb-3 opacity-30" />
            <p>
              {query
                ? `没有匹配 “${query}” 的对话`
                : '还没有对话记录'}
            </p>
            <p className="text-xs mt-1">
              设备发一条语音后会自动出现在这里
            </p>
          </CardContent>
        </Card>
      )}

      {!loading && !error && filtered.length > 0 && (
        <div className="space-y-3">
          {filtered.map((c) => (
            <ConversationRow
              key={c.id}
              conv={c}
              deviceName={
                c.deviceId
                  ? deviceNameById.get(c.deviceId) ?? c.deviceId
                  : '未指定设备'
              }
            />
          ))}
        </div>
      )}
    </div>
  )
}

function ConversationRow({
  conv,
  deviceName,
}: {
  conv: Conversation
  deviceName: string
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between text-sm font-medium">
          <span className="flex items-center gap-2">
            <MessageCircle className="h-4 w-4 text-muted-foreground" />
            {deviceName}
            <span className="text-xs text-muted-foreground font-mono">
              · {conv.sessionId || 'no-session'}
            </span>
          </span>
          <span className="text-xs text-muted-foreground" title={formatDate(conv.startedAt)}>
            {formatRelative(conv.startedAt)}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {conv.turns.map((turn, i) => (
            <div
              key={i}
              className={cn(
                'rounded-md p-2 text-sm',
                turn.role === 'user'
                  ? 'bg-muted/50'
                  : 'bg-primary/5 border border-primary/20',
              )}
            >
              <div className="text-xs text-muted-foreground mb-0.5">
                {turn.role === 'user' ? '用户' : '助手'}
              </div>
              <div className="whitespace-pre-wrap break-words">{turn.text}</div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
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
    <div className="space-y-3">
      {[0, 1, 2].map((i) => (
        <Card key={i}>
          <CardContent className="py-4 space-y-2">
            <div className="h-4 w-40 bg-muted animate-pulse rounded" />
            <div className="h-3 w-full bg-muted animate-pulse rounded" />
            <div className="h-3 w-3/4 bg-muted animate-pulse rounded" />
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
