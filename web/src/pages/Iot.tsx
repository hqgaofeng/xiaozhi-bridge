import { Card, CardContent } from '@/components/ui/card'
import { Lightbulb, Plus } from 'lucide-react'

export function Iot() {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">IoT 设备</h2>
          <p className="text-sm text-muted-foreground">
            智能家居设备管理（灯、开关、风扇、空调等）
          </p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 rounded-md bg-primary text-primary-foreground hover:opacity-90">
          <Plus className="h-4 w-4" />
          添加设备
        </button>
      </div>

      <Card>
        <CardContent className="py-12 text-center text-muted-foreground">
          <Lightbulb className="h-12 w-12 mx-auto mb-3 opacity-30" />
          <p>还没有 IoT 设备</p>
          <p className="text-xs mt-1">
            V2 阶段会接入米家 / Home Assistant / 自定义设备
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
