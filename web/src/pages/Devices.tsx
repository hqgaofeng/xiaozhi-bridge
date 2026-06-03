import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Cpu, Wifi, WifiOff, RefreshCw, ChevronLeft } from 'lucide-react'
import { toast } from 'sonner'

import { api, type Device } from '@/lib/api'
import { useApi } from '@/lib/useApi'
import { formatDate, formatRelative } from '@/lib/utils'

import { Conversations } from './Conversations'

/**
 * Devices — V2 #5: real /api/devices + per-device drill-down.
 *
 * Clicking a device flips to a per-device conversation view, which
 * is fetched via the new V2 #4 /api/devices/{id}/conversations route.
 * The "back" button restores the device list. We avoid React Router
 * to keep the routing model the same as the rest of the app (Zustand
 * page state in App.tsx).
 */
export function Devices() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
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
              onClick={() => setSelectedId(d.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function DeviceCard({ device, onClick }: { device: Device; onClick: () => void }) {
  const online = device.state !== 'offline' && !!device.sessionId
  return (
    <Card
      className="cursor-pointer hover:border-primary/40 transition-colors"
      onClick={onClick}
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
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">ID</span>
            <span className="font-mono text-xs">{device.id}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">MAC</span>
            <span className="font-mono text-xs">{device.mac}</span>
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
          {device.sessionId && (
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Session</span>
              <span className="font-mono text-xs truncate max-w-[180px]">
                {device.sessionId}
              </span>
            </div>
          )}
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
