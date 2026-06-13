'use client'

import { ReactNode } from 'react'
import { Header } from './header'

interface AppShellProps {
  children: ReactNode
  sidebar: ReactNode
  user?: {
    email: string
    name?: string
  } | null
}

export function AppShell({ children, sidebar, user }: AppShellProps) {
  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      {sidebar}

      {/* Main Content */}
      <div className="flex flex-1 flex-col overflow-hidden">
        <Header user={user} />
        <main className="flex-1 overflow-auto bg-slate-50 p-4 dark:bg-slate-900 md:p-6">
          {children}
        </main>
      </div>
    </div>
  )
}
