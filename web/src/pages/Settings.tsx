import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

/**
 * V1 Settings page: static (non-functional) form showing the V1
 * configuration values. The form does NOT submit anywhere — V1 has no
 * HTTP API to update config. V2 will wire this to PATCH /api/config.
 *
 * Defaults mirror the actual V1 wiring:
 *   - openclaw base_url = http://host.docker.internal:18789 (bridge is
 *     in docker, openclaw runs on the host)
 *   - model = "openclaw" (agent target, NOT a backend LLM id)
 *   - ASR / TTS = mock (V1 has no real providers)
 */
export function Settings() {
  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h2 className="text-xl font-semibold">设置</h2>
        <p className="text-sm text-muted-foreground">
          V1：只读展示当前配置。V2 会接 PATCH /api/config。
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>OpenClaw</CardTitle>
          <CardDescription>LLM/agent 运行时（宿主机上的 openclaw gateway）</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label>Base URL</Label>
            <Input
              defaultValue="http://host.docker.internal:18789"
              readOnly
            />
          </div>
          <div className="space-y-1.5">
            <Label>模型（agent target）</Label>
            <Input defaultValue="openclaw" readOnly />
            <p className="text-xs text-muted-foreground">
              固定为 "openclaw"；后端 LLM 由 openclaw 端 agents.defaults 决定。
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>ASR</CardTitle>
          <CardDescription>语音识别服务（V1 仅 mock）</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label>Provider</Label>
            <Input defaultValue="mock" readOnly />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>TTS</CardTitle>
          <CardDescription>语音合成服务（V1 仅 mock）</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label>Provider</Label>
            <Input defaultValue="mock" readOnly />
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
