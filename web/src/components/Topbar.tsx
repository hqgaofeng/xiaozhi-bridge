import { Sun, Moon, Circle } from 'lucide-react'
import { useUIStore } from '@/lib/store'
import { cn } from '@/lib/utils'

/**
 * Top bar — shows current page title and global actions.
 */
export function Topbar() {
  const { theme, setTheme, page } = useUIStore()
  const titles: Record<string, string> = {
    dashboard: '总览',
    devices: '设备管理',
    conversations: '对话历史',
    iot: 'IoT 设备',
    settings: '设置',
    logs: '实时日志',
  }

  return (
    <header className="h-14 border-b border-border bg-card/50 backdrop-blur flex items-center justify-between px-6">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-medium">{titles[page] || '小智 Bridge'}</h1>
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Circle className="h-2 w-2 fill-emerald-500 text-emerald-500" />
          <span>已连接</span>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <button
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          className={cn(
            'h-8 w-8 flex items-center justify-center rounded-md',
            'hover:bg-accent transition-colors',
          )}
          title="切换主题"
        >
          {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>
      </div>
    </header>
  )
}
