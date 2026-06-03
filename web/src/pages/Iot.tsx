import { useState } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Lightbulb, Plus, RefreshCw, Power, Wifi, WifiOff } from 'lucide-react'
import { toast } from 'sonner'

import { api, type IotDevice } from '@/lib/api'
import { useApi } from '@/lib/useApi'

/**
 * Iot — V2 #5: real /api/iot list + /api/iot/{id}/control POST.
 *
 * The bridge-api demo seeds two devices (light-1, switch-1) on
 * first start. POST /api/iot/{id}/control with {"action":"on"|"off"}
 * flips the device state. The page reads /api/iot fresh after each
 * control call so the state-change round-trip is visible.
 */
export function Iot() {
  const { data, error, loading, refresh } = useApi<IotDevice[]>(api.listIotDevices)
  const [busyId, setBusyId] = useState<string | null>(null)

  async function control(id: string, action: 'on' | 'off') {
    setBusyId(id)
    try {
      const updated = await api.controlIot(id, { action })
      toast.success(`${updated.name} 已${action === 'on' ? '开启' : '关闭'}`)
      refresh()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      toast.error(`控制失败：${msg}`)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">IoT 设备</h2>
          <p className="text-sm text-muted-foreground">
            智能家居设备管理（灯、开关、风扇、空调等）
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => {
              refresh()
              toast.info('已刷新')
            }}
            className="p-2 rounded-md hover:bg-muted"
            title="刷新"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
          <button
            onClick={() => toast.info('V2 #6 起对接米家 / Home Assistant')}
            className="flex items-center gap-2 px-4 py-2 rounded-md bg-primary text-primary-foreground hover:opacity-90"
          >
            <Plus className="h-4 w-4" />
            添加设备
          </button>
        </div>
      </div>

      {error && <ErrorBlock message={error} onRetry={refresh} />}
      {loading && <SkeletonList />}

      {!loading && !error && (data?.length ?? 0) === 0 && (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            <Lightbulb className="h-12 w-12 mx-auto mb-3 opacity-30" />
            <p>还没有 IoT 设备</p>
            <p className="text-xs mt-1">
              V2 #6 阶段会接入米家 / Home Assistant / 自定义设备
            </p>
          </CardContent>
        </Card>
      )}

      {!loading && !error && (data?.length ?? 0) > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {(data ?? []).map((d) => {
            const on = Boolean(d.state?.on)
            return (
              <Card key={d.id}>
                <CardContent className="py-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Lightbulb
                        className={`h-5 w-5 ${on ? 'text-amber-500' : 'text-gray-500'}`}
                      />
                      <div>
                        <div className="font-medium">{d.name}</div>
                        <div className="text-xs text-muted-foreground font-mono">
                          {d.id}
                        </div>
                      </div>
                    </div>
                    <span className="flex items-center gap-1 text-xs text-muted-foreground">
                      {d.online ? (
                        <>
                          <Wifi className="h-3 w-3 text-emerald-500" /> 在线
                        </>
                      ) : (
                        <>
                          <WifiOff className="h-3 w-3" /> 离线
                        </>
                      )}
                    </span>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">状态</span>
                    <span
                      className={
                        on
                          ? 'text-emerald-500 font-medium'
                          : 'text-muted-foreground'
                      }
                    >
                      {on ? '已开启' : '已关闭'}
                    </span>
                  </div>
                  <div className="flex gap-2 pt-1">
                    <button
                      onClick={() => control(d.id, 'on')}
                      disabled={busyId === d.id || on}
                      className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md bg-primary text-primary-foreground text-sm hover:opacity-90 disabled:opacity-50"
                    >
                      <Power className="h-3.5 w-3.5" /> 开启
                    </button>
                    <button
                      onClick={() => control(d.id, 'off')}
                      disabled={busyId === d.id || !on}
                      className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md bg-muted text-foreground text-sm hover:bg-muted/70 disabled:opacity-50"
                    >
                      <Power className="h-3.5 w-3.5" /> 关闭
                    </button>
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
    </div>
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
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {[0, 1].map((i) => (
        <Card key={i}>
          <CardContent className="py-4 space-y-2">
            <div className="h-5 w-24 bg-muted animate-pulse rounded" />
            <div className="h-3 w-full bg-muted animate-pulse rounded" />
            <div className="h-8 w-full bg-muted animate-pulse rounded" />
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
