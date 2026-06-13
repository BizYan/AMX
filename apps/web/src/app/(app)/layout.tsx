'use client'

import { ReactNode } from 'react'
import { useAuth, useCurrentUser } from '@/lib/auth'
import { AppShell } from '@/components/layout/app-shell'
import { SidebarNav } from '@/components/layout/sidebar-nav'

export default function AppLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const { isAuthenticated, isLoading } = useAuth()
  const { data: user } = useCurrentUser()

  if (isLoading) {
    return null
  }

  if (!isAuthenticated) {
    return null
  }

  return (
    <AppShell
      sidebar={<SidebarNav user={user} />}
      user={user}
    >
      {children}
    </AppShell>
  )
}
