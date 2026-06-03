import {
  LayoutDashboard,
  Cpu,
  MessagesSquare,
  Lightbulb,
  Settings as SettingsIcon,
  ScrollText,
  PanelLeftClose,
  PanelLeftOpen,
  Bot,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useUIStore, type PageId } from '@/lib/store'

interface NavItem {
  id: PageId
  label: string
  icon: React.ComponentType<{ className?: string }>
}

const items: NavItem[] = [
  { id: 'dashboard', label: '总览', icon: LayoutDashboard },
  { id: 'devices', label: '设备', icon: Cpu },
  { id: 'conversations', label: '对话', icon: MessagesSquare },
  { id: 'iot', label: 'IoT', icon: Lightbulb },
  { id: 'logs', label: '日志', icon: ScrollText },
  { id: 'settings', label: '设置', icon: SettingsIcon },
]

export function Sidebar() {
  const { page, setPage, sidebarCollapsed, toggleSidebar } = useUIStore()

  return (
    <aside
      className={cn(
        'border-r border-border bg-card flex flex-col transition-all',
        sidebarCollapsed ? 'w-16' : 'w-56',
      )}
    >
      <div className="h-14 flex items-center gap-2 px-4 border-b border-border">
        <Bot className="h-6 w-6 text-primary flex-shrink-0" />
        {!sidebarCollapsed && (
          <span className="font-semibold text-base">小智 Bridge</span>
        )}
      </div>
      <nav className="flex-1 p-2 space-y-1">
        {items.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setPage(id)}
            className={cn(
              'w-full flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors',
              'hover:bg-accent hover:text-accent-foreground',
              page === id && 'bg-accent text-accent-foreground font-medium',
            )}
            title={label}
          >
            <Icon className="h-4 w-4 flex-shrink-0" />
            {!sidebarCollapsed && <span>{label}</span>}
          </button>
        ))}
      </nav>
      <div className="p-2 border-t border-border">
        <button
          onClick={toggleSidebar}
          className="w-full flex items-center gap-3 px-3 py-2 rounded-md text-sm hover:bg-accent"
        >
          {sidebarCollapsed ? (
            <PanelLeftOpen className="h-4 w-4" />
          ) : (
            <>
              <PanelLeftClose className="h-4 w-4" />
              <span>收起</span>
            </>
          )}
        </button>
      </div>
    </aside>
  )
}
