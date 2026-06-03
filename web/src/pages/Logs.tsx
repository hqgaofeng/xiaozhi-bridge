import { useEffect, useRef, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Pause, Play, Trash2 } from 'lucide-react'

interface LogLine {
  ts: string
  level: string
  msg: string
}

export function Logs() {
  const [lines, setLines] = useState<LogLine[]>([])
  const [paused, setPaused] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    // V1: mocked stream of fake logs
    // V2: real SSE from /api/logs/stream
    if (paused) return
    const interval = setInterval(() => {
      const sample: LogLine = {
        ts: new Date().toISOString(),
        level: 'INFO',
        msg: 'session.state_transition session_id=xiaozhi-abc from=idle to=listening',
      }
      setLines((prev) => [...prev.slice(-200), sample])
    }, 2000)
    return () => clearInterval(interval)
  }, [paused])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [lines])

  return (
    <div className="space-y-4 h-full flex flex-col">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">实时日志</h2>
          <p className="text-sm text-muted-foreground">
            来自桥接服务的结构化日志
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => setPaused(!paused)}>
            {paused ? <Play className="h-4 w-4" /> : <Pause className="h-4 w-4" />}
          </Button>
          <Button variant="outline" size="sm" onClick={() => setLines([])}>
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <Card className="flex-1 flex flex-col">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">终端输出</CardTitle>
        </CardHeader>
        <CardContent className="flex-1 p-0">
          <div
            ref={scrollRef}
            className="h-[500px] overflow-auto bg-zinc-950 text-zinc-100 font-mono text-xs p-4 space-y-1"
          >
            {lines.map((line, i) => (
              <div key={i} className="flex gap-3">
                <span className="text-zinc-500">{line.ts}</span>
                <span className="text-blue-400">{line.level}</span>
                <span className="flex-1">{line.msg}</span>
              </div>
            ))}
            {lines.length === 0 && (
              <div className="text-zinc-600">等待日志...</div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
