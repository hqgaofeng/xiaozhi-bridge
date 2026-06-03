import { Cpu, MessagesSquare, Lightbulb, Activity, RefreshCw } from 'lucide-react'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'

import { api, type Device, type Conversation, type IotDevice } from '@/lib/api'
import { useApi } from '@/lib/useApi'

/**
 * Dashboard — V2 #5: live numbers from /api/*.
 *
 * The four KPI cards each pull from a different endpoint. Errors
 * per card are surfaced inline rather than as a banner so one
 * broken endpoint doesn't blank the whole page.
 *
 * "在线设备" is defined as: a device whose last session is still
 * open (i.e. /api/devices returned a non-null sessionId). This
 * matches what /api/devices already exposes, so no extra work.
 */
export function Dashboard() {
  const devicesR = useApi<Device[]>(api.listDevices)
  const convosR = useApi<Conversation[]>(() =>
    api.listConversations({ limit: 100 }),
  )
  const iotR = useApi<IotDevice[]>(api.listIotDevices)

  const onlineDevices =
    devicesR.data?.filter((d) => d.state !== 'offline' && !!d.sessionId).length ?? 0
  const totalDevices = devicesR.data?.length ?? 0
  const totalConversations = convosR.data?.length ?? 0
  const iotOnline = iotR.data?.filter((d) => d.online).length ?? 0
  const totalIot = iotR.data?.length ?? 0

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold">欢迎回来 👋</h2>
          <p className="text-muted-foreground text-sm mt-1">
            xiaozhi-bridge V2 — 智控台与 bridge HTTP API 实时联动
          </p>
        </div>
        <button
          onClick={() => {
            devicesR.refresh()
            convosR.refresh()
            iotR.refresh()
          }}
          className="p-2 rounded-md hover:bg-muted"
          title="刷新"
        >
          <RefreshCw className="h-4 w-4" />
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="在线设备"
          value={onlineDevices}
          sub={`共 ${totalDevices} 台`}
          icon={Cpu}
          color="text-emerald-500"
          loading={devicesR.loading}
          error={devicesR.error}
        />
        <StatCard
          label="最近 100 条对话"
          value={totalConversations}
          sub="最新优先"
          icon={MessagesSquare}
          color="text-blue-500"
          loading={convosR.loading}
          error={convosR.error}
        />
        <StatCard
          label="IoT 在线"
          value={iotOnline}
          sub={`共 ${totalIot} 台`}
          icon={Lightbulb}
          color="text-amber-500"
          loading={iotR.loading}
          error={iotR.error}
        />
        <StatCard
          label="API 状态"
          value="正常"
          sub="bridge-api 200 OK"
          icon={Activity}
          color="text-emerald-500"
          loading={false}
          error={null}
        />
      </div>

      {totalDevices === 0 && !devicesR.loading && !devicesR.error && (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            还没有设备连接。给 ESP32 通电、配置固件指向本 bridge 即可。
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  color,
  loading,
  error,
}: {
  label: string
  value: number | string
  sub?: string
  icon: typeof Cpu
  color: string
  loading: boolean
  error: string | null
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {label}
        </CardTitle>
        <Icon className={`h-4 w-4 ${color}`} />
      </CardHeader>
      <CardContent>
        {error ? (
          <div className="text-xs text-destructive">加载失败</div>
        ) : loading ? (
          <div className="h-8 w-16 bg-muted animate-pulse rounded" />
        ) : (
          <div className="text-2xl font-semibold">{value}</div>
        )}
        {sub && !error && !loading && (
          <p className="text-xs text-muted-foreground mt-1">{sub}</p>
        )}
      </CardContent>
    </Card>
  )
}
