import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type PageId = 'dashboard' | 'devices' | 'conversations' | 'iot' | 'settings' | 'logs'

interface UIState {
  page: PageId
  setPage: (page: PageId) => void
  theme: 'light' | 'dark' | 'system'
  setTheme: (theme: 'light' | 'dark' | 'system') => void
  sidebarCollapsed: boolean
  toggleSidebar: () => void
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      page: 'dashboard',
      setPage: (page) => set({ page }),
      theme: 'dark',
      setTheme: (theme) => set({ theme }),
      sidebarCollapsed: false,
      toggleSidebar: () =>
        set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
    }),
    { name: 'xiaozhi-ui' },
  ),
)
