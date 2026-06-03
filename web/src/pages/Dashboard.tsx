import { Cpu, MessagesSquare, Lightbulb, Activity } from 'lucide-react'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'

/**
 * Dashboard — overview page.
 *
 * Shows key metrics: device count, active sessions, conversation count, IoT devices.
 * For V1, data is mocked; for V2 we'll fetch from the bridge HTTP API.
 */
export function Dashboard() {
  // V1: hardcoded stats
  const stats = [
    { label: '在线设备', value: 1, icon: Cpu, color: 'text-emerald-500' },
    { label: '今日对话', value: 12, icon: MessagesSquare, color: 'text-blue-500' },
    { label: 'IoT 设备', value: 0, icon: Lightbulb, color: 'text-amber-500' },
    { label: 'API 状态', value: '正常', icon: Activity, color: 'text-emerald-500' },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold">欢迎回来 👋</h2>
        <p className="text-muted-foreground text-sm mt-1">
          xiaozhi-bridge V1 — 一个轻量级的 ESP32 智能音箱后端
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((s) => (
          <Card key={s.label}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {s.label}
              </CardTitle>
              <s.icon className={`h-4 w-4 ${s.color}`} />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-semibold">{s.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>最近对话</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-sm text-muted-foreground">
              还没有对话记录。等硬件连上后会自动显示。
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>系统状态</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">桥接服务</span>
                <span className="text-emerald-500 font-medium">运行中</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">OpenClaw</span>
                <span className="text-emerald-500 font-medium">已连接</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">LLM 模型</span>
                <span className="font-mono text-xs">MiniMax-M3</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">ASR</span>
                <span>Mock</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">TTS</span>
                <span>Mock</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
