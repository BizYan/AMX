'use client'

import { useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import {
  LayoutDashboard,
  FolderKanban,
  BrainCircuit,
  Download,
  UserCog,
  Settings,
  ChevronLeft,
  ChevronRight,
  Network,
  FileUp,
  Activity,
  AlertTriangle,
  ClipboardCheck,
  Bell,
  Bot,
  Gauge,
  History,
  ServerCog,
  Workflow,
} from 'lucide-react'

interface NavItem {
  href: string
  labelKey: string
  icon: React.ReactNode
}

const mainNav: NavItem[] = [
  { href: '/dashboard', labelKey: 'dashboard', icon: <LayoutDashboard className="h-5 w-5" /> },
  { href: '/delivery', labelKey: 'deliveryPortfolio', icon: <FolderKanban className="h-5 w-5" /> },
  { href: '/projects', labelKey: 'projects', icon: <FolderKanban className="h-5 w-5" /> },
  { href: '/knowledge/graph', labelKey: 'knowledgeGraph', icon: <Network className="h-5 w-5" /> },
  { href: '/agents', labelKey: 'agents', icon: <BrainCircuit className="h-5 w-5" /> },
  { href: '/agent-ops', labelKey: 'agentOps', icon: <Bot className="h-5 w-5" /> },
  { href: '/workflows', labelKey: 'workflows', icon: <Workflow className="h-5 w-5" /> },
  { href: '/templates', labelKey: 'templates', icon: <FileUp className="h-5 w-5" /> },
  { href: '/documents/contradictions', labelKey: 'traceability', icon: <AlertTriangle className="h-5 w-5" /> },
  { href: '/exports', labelKey: 'exports', icon: <Download className="h-5 w-5" /> },
  { href: '/collaboration', labelKey: 'collaboration', icon: <ClipboardCheck className="h-5 w-5" /> },
  { href: '/team', labelKey: 'team', icon: <UserCog className="h-5 w-5" /> },
  { href: '/notifications', labelKey: 'notifications', icon: <Bell className="h-5 w-5" /> },
  { href: '/system-health', labelKey: 'health', icon: <Activity className="h-5 w-5" /> },
  { href: '/providers', labelKey: 'providers', icon: <ServerCog className="h-5 w-5" /> },
  { href: '/quotas', labelKey: 'quotas', icon: <Gauge className="h-5 w-5" /> },
  { href: '/audit', labelKey: 'audit', icon: <History className="h-5 w-5" /> },
]

const bottomNav: NavItem[] = [
  { href: '/settings', labelKey: 'settings', icon: <Settings className="h-5 w-5" /> },
]

interface SidebarNavProps {
  user?: {
    email: string
    name?: string
  } | null
}

export function SidebarNav({ user }: SidebarNavProps) {
  const pathname = usePathname()
  const t = useTranslations('nav')
  const [collapsed, setCollapsed] = useState(false)

  const NavItem = ({ item }: { item: NavItem }) => {
    const isActive = pathname === item.href
    const label = t(item.labelKey)
    const content = (
      <Link
        href={item.href}
        className={cn(
          'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
          isActive
            ? 'bg-indigo-100 text-indigo-900 dark:bg-indigo-900 dark:text-indigo-100'
            : 'text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800',
          collapsed && 'justify-center px-2',
          'max-md:justify-center max-md:px-2'
        )}
      >
        {item.icon}
        {!collapsed && <span className="hidden md:inline">{label}</span>}
      </Link>
    )

    if (collapsed) {
      return (
        <Tooltip delayDuration={0}>
          <TooltipTrigger asChild>{content}</TooltipTrigger>
          <TooltipContent side="right">{label}</TooltipContent>
        </Tooltip>
      )
    }

    return content
  }

  return (
    <div className={cn(
      'flex h-full flex-col border-r border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 transition-all duration-300',
      collapsed ? 'w-16' : 'w-16 md:w-64'
    )}>
      {/* Logo */}
      <div className="flex h-16 items-center justify-center border-b border-slate-200 px-4 dark:border-slate-700 md:justify-between">
        {!collapsed && (
          <span className="hidden text-lg font-semibold text-slate-900 dark:text-white md:inline">
            Avenir Matrix
          </span>
        )}
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setCollapsed(!collapsed)}
          className="h-8 w-8 p-0"
        >
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </Button>
      </div>

      {/* Main Navigation */}
      <nav className="flex-1 space-y-1 overflow-y-auto p-2">
        {mainNav.map((item) => (
          <NavItem key={item.href} item={item} />
        ))}
      </nav>

      {/* Bottom Navigation */}
      <div className="border-t border-slate-200 dark:border-slate-700 p-2">
        {bottomNav.map((item) => (
          <NavItem key={item.href} item={item} />
        ))}
      </div>
    </div>
  )
}
