import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User } from './api-client'

interface AppState {
  // User state
  user: User | null
  setUser: (user: User | null) => void

  // Current project/tenant
  currentProjectId: string | null
  currentTenantId: string | null
  setCurrentProject: (projectId: string | null) => void
  setCurrentTenant: (tenantId: string | null) => void

  // UI preferences
  sidebarCollapsed: boolean
  toggleSidebar: () => void
  setSidebarCollapsed: (collapsed: boolean) => void

  // Theme
  theme: 'light' | 'dark' | 'system'
  setTheme: (theme: 'light' | 'dark' | 'system') => void
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      // User state
      user: null,
      setUser: (user) => set({ user }),

      // Current project/tenant
      currentProjectId: null,
      currentTenantId: null,
      setCurrentProject: (projectId) => set({ currentProjectId: projectId }),
      setCurrentTenant: (tenantId) => set({ currentTenantId: tenantId }),

      // UI preferences
      sidebarCollapsed: false,
      toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
      setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),

      // Theme
      theme: 'system',
      setTheme: (theme) => set({ theme }),
    }),
    {
      name: 'app-storage',
      partialize: (state) => ({
        sidebarCollapsed: state.sidebarCollapsed,
        theme: state.theme,
        currentProjectId: state.currentProjectId,
        currentTenantId: state.currentTenantId,
      }),
    }
  )
)