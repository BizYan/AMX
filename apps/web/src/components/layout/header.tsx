'use client'

import { useState } from 'react'
import { usePathname } from 'next/navigation'
import { logout } from '@/lib/auth'
import { useRouter } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell, CheckCheck, ChevronRight, ExternalLink, LogOut, Settings, User } from 'lucide-react'
import { notificationsApi, type UserNotification } from '@/lib/api-client'
import { formatDistanceToNow } from '@/lib/utils'

interface HeaderProps {
  user?: {
    email: string
    name?: string
  } | null
}

function Breadcrumb() {
  const pathname = usePathname()
  const tNav = useTranslations('nav')
  const tHeader = useTranslations('header')
  const segments = pathname.split('/').filter(Boolean)
  const labels: Record<string, string> = {
    dashboard: tNav('dashboard'),
    projects: tNav('projects'),
    documents: tNav('documents'),
    knowledge: tNav('knowledge'),
    graph: tNav('knowledgeGraph'),
    agents: tNav('agents'),
    templates: tNav('templates'),
    health: tNav('health'),
    'system-health': tNav('health'),
    contradictions: tNav('traceability'),
    exports: tNav('exports'),
    team: tNav('team'),
    collaboration: tNav('collaboration'),
    settings: tNav('settings'),
    providers: '供应商管理',
    quotas: '配额与监控',
    audit: '审计日志',
    'agent-ops': '智能体运行',
    workflows: '工作流',
    files: '文件',
    generate: '生成',
    members: '成员',
    changes: '变更',
    traceability: tNav('traceability'),
    notifications: tHeader('notifications'),
  }

  const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

  const breadcrumbs = segments.map((segment, index) => {
    const href = '/' + segments.slice(0, index + 1).join('/')
    const label = labels[segment] ?? (uuidPattern.test(segment) ? '项目' : segment.charAt(0).toUpperCase() + segment.slice(1).replace(/-/g, ' '))

    return (
      <span key={href} className="flex items-center">
        {index > 0 && <ChevronRight className="mx-2 h-4 w-4 text-slate-400" />}
        <span className={index === segments.length - 1 ? 'text-slate-900 dark:text-white font-medium' : 'text-slate-500'}>
          {label}
        </span>
      </span>
    )
  })

  if (breadcrumbs.length === 0) return null

  return (
    <div className="flex items-center text-sm">
      <span className="text-slate-500">{tHeader('home')}</span>
      {breadcrumbs}
    </div>
  )
}

export function Header({ user }: HeaderProps) {
  const router = useRouter()
  const tHeader = useTranslations('header')
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const [notificationMenuOpen, setNotificationMenuOpen] = useState(false)
  const queryClient = useQueryClient()
  const notificationSummary = useQuery({
    queryKey: ['notifications', 'summary'],
    queryFn: () => notificationsApi.summary(5),
    refetchInterval: 60_000,
  })
  const markReadMutation = useMutation({
    mutationFn: (notificationId: string) => notificationsApi.markRead(notificationId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['notifications'] }),
  })
  const markAllReadMutation = useMutation({
    mutationFn: notificationsApi.markAllRead,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['notifications'] }),
  })

  const handleLogout = async () => {
    setIsLoggingOut(true)
    try {
      await logout()
      router.push('/login')
    } finally {
      setIsLoggingOut(false)
    }
  }

  const initials = user?.name
    ? user.name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2)
    : user?.email?.[0]?.toUpperCase() || 'U'
  const unreadCount = notificationSummary.data?.unread_count || 0

  const openNotification = async (notification: UserNotification) => {
    if (!notification.read_at) {
      await markReadMutation.mutateAsync(notification.id)
    }
    if (notification.action_url) {
      setNotificationMenuOpen(false)
      router.push(notification.action_url)
    }
  }

  return (
    <header className="flex h-16 items-center justify-between border-b border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-6">
      <Breadcrumb />

      <div className="flex items-center gap-4">
        <DropdownMenu open={notificationMenuOpen} onOpenChange={setNotificationMenuOpen}>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className="relative"
              aria-label={tHeader('notifications')}
              data-testid="notification-trigger"
            >
              <Bell className="h-5 w-5" />
              {unreadCount > 0 && (
                <span
                  className="absolute -right-1 -top-1 flex min-h-4 min-w-4 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-medium text-white"
                  data-testid="notification-unread-count"
                >
                  {unreadCount > 99 ? '99+' : unreadCount}
                </span>
              )}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-96" data-testid="notification-dropdown">
            <DropdownMenuLabel className="flex items-center justify-between gap-3">
              <span>{tHeader('notifications')}</span>
              {unreadCount > 0 && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 gap-1 px-2 text-xs"
                  onClick={() => markAllReadMutation.mutate()}
                  disabled={markAllReadMutation.isPending}
                >
                  <CheckCheck className="h-3.5 w-3.5" />
                  全部已读
                </Button>
              )}
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            {notificationSummary.isLoading ? (
              <div className="px-3 py-6 text-center text-sm text-slate-500">正在加载通知...</div>
            ) : notificationSummary.isError ? (
              <div className="px-3 py-6 text-center text-sm text-red-600">通知暂时无法加载</div>
            ) : notificationSummary.data?.recent.length ? (
              <div className="max-h-96 overflow-y-auto">
                {notificationSummary.data.recent.map((notification) => (
                  <button
                    key={notification.id}
                    type="button"
                    onClick={() => openNotification(notification)}
                    className="flex w-full gap-3 border-b border-slate-100 px-3 py-3 text-left transition-colors hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-700/60"
                  >
                    <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${notification.read_at ? 'bg-slate-300' : 'bg-indigo-600'}`} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{notification.title}</span>
                      <span className="mt-1 line-clamp-2 block text-xs text-slate-500 dark:text-slate-400">{notification.body}</span>
                      <span className="mt-1 block text-xs text-slate-400">{formatDistanceToNow(notification.created_at)}</span>
                    </span>
                    {notification.action_url && <ExternalLink className="mt-1 h-3.5 w-3.5 shrink-0 text-slate-400" />}
                  </button>
                ))}
              </div>
            ) : (
              <div className="px-3 py-6 text-center text-sm text-slate-500 dark:text-slate-400">
                暂无新的系统通知
              </div>
            )}
            <DropdownMenuSeparator />
            <Button
              variant="ghost"
              className="w-full justify-center text-sm"
              onClick={() => {
                setNotificationMenuOpen(false)
                router.push('/notifications')
              }}
              data-testid="notification-view-all"
            >
              查看全部通知
            </Button>
          </DropdownMenuContent>
        </DropdownMenu>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" className="relative h-8 w-8 rounded-full">
              <Avatar className="h-8 w-8">
                <AvatarFallback className="bg-indigo-100 text-indigo-700 text-sm font-medium">
                  {initials}
                </AvatarFallback>
              </Avatar>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuLabel>
              <div className="flex flex-col space-y-1">
                <p className="text-sm font-medium">{user?.name || tHeader('user')}</p>
                <p className="text-xs text-slate-500">{user?.email}</p>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => router.push('/settings')}>
              <User className="mr-2 h-4 w-4" />
              {tHeader('profile')}
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => router.push('/settings')}>
              <Settings className="mr-2 h-4 w-4" />
              {tHeader('settings')}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={handleLogout} disabled={isLoggingOut}>
              <LogOut className="mr-2 h-4 w-4" />
              {isLoggingOut ? tHeader('signingOut') : tHeader('signOut')}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  )
}
