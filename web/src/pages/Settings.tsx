import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export function Settings() {
  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h2 className="text-xl font-semibold">设置</h2>
        <p className="text-sm text-muted-foreground">配置 xiaozhi-bridge 各项参数</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>OpenClaw</CardTitle>
          <CardDescription>LLM 推理服务</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label>Base URL</Label>
            <Input defaultValue="http://127.0.0.1:18789" />
          </div>
          <div className="space-y-1.5">
            <Label>模型</Label>
            <Input defaultValue="minimax/MiniMax-M3" />
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
            <Input defaultValue="mock" />
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
            <Input defaultValue="mock" />
          </div>
          <div className="space-y-1.5">
            <Label>语音</Label>
            <Input defaultValue="zh-CN-XiaoxiaoNeural" />
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
