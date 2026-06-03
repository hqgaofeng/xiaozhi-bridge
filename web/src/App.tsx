import { Toaster } from 'sonner'
import { Sidebar } from '@/components/Sidebar'
import { Topbar } from '@/components/Topbar'
import { Dashboard } from '@/pages/Dashboard'
import { Devices } from '@/pages/Devices'
import { Conversations } from '@/pages/Conversations'
import { Iot } from '@/pages/Iot'
import { Settings } from '@/pages/Settings'
import { Logs } from '@/pages/Logs'
import { useUIStore } from '@/lib/store'

/**
 * App root — single-page layout with sidebar navigation.
 *
 * The page state is in a Zustand store, persisted to localStorage so
 * the route survives page reloads.
 */
export function App() {
  const page = useUIStore((s) => s.page)

  return (
    <div className="flex h-screen bg-background text-foreground">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <Topbar />
        <main className="flex-1 overflow-auto p-6">
          {page === 'dashboard' && <Dashboard />}
          {page === 'devices' && <Devices />}
          {page === 'conversations' && <Conversations />}
          {page === 'iot' && <Iot />}
          {page === 'settings' && <Settings />}
          {page === 'logs' && <Logs />}
        </main>
      </div>
      <Toaster position="top-right" richColors />
    </div>
  )
}
