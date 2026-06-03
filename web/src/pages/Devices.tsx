import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Cpu, Wifi, WifiOff } from 'lucide-react'

/**
 * Devices — list of connected xiaozhi devices.
 *
 * V1: mocked single-device view.
 * V2: real-time WebSocket-driven device list with status indicators.
 */
export function Devices() {
  const devices = [
    {
      id: 'esp32-001',
      name: '客厅小智',
      mac: 'AA:BB:CC:DD:EE:FF',
      state: 'idle' as const,
      lastSeen: new Date().toISOString(),
      sessionId: 'xiaozhi-abc123def456',
    },
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">设备列表</h2>
          <p className="text-sm text-muted-foreground">
            管理已连接到小智 Bridge 的 ESP32 设备
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {devices.map((d) => (
          <Card key={d.id}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Cpu className="h-5 w-5" />
                {d.name}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">状态</span>
                  <span className="flex items-center gap-1.5">
                    {d.state === 'idle' ? (
                      <>
                        <Wifi className="h-3 w-3 text-emerald-500" />
                        <span className="text-emerald-500">在线 · {d.state}</span>
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
                  <span className="text-muted-foreground">MAC</span>
                  <span className="font-mono text-xs">{d.mac}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Session</span>
                  <span className="font-mono text-xs">{d.sessionId}</span>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {devices.length === 0 && (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            还没有设备连接。配置 ESP32 固件指向本后端即可。
          </CardContent>
        </Card>
      )}
    </div>
  )
}
