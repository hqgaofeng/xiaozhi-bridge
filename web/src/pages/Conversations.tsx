import { Card, CardContent } from '@/components/ui/card'
import { MessageCircle } from 'lucide-react'

export function Conversations() {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold">对话历史</h2>
        <p className="text-sm text-muted-foreground">
          查看、搜索、回放历史对话
        </p>
      </div>

      <Card>
        <CardContent className="py-12 text-center text-muted-foreground">
          <MessageCircle className="h-12 w-12 mx-auto mb-3 opacity-30" />
          <p>还没有对话记录</p>
          <p className="text-xs mt-1">V2 阶段会接入 SQLite 存储</p>
        </CardContent>
      </Card>
    </div>
  )
}
