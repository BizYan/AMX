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
  FileUp,
  Activity,
  AlertTriangle,
  ClipboardCheck,
  History,
} from 'lucide-react'

interface NavItem {
  href: string
  labelKey: string
  icon: React.ReactNode
  activePrefixes?: string[]
}

interface NavSection {
  labelKey: string
  items: NavItem[]
}

const navSections: NavSection[] = [
  {
    labelKey: 'sectionOverview',
    items: [
      { href: '/dashboard', labelKey: 'dashboard', icon: <LayoutDashboard className="h-5 w-5" /> },
      { href: '/delivery', labelKey: 'deliveryPortfolio', icon: <FolderKanban className="h-5 w-5" /> },
    ],
  },
  {
    labelKey: 'sectionDelivery',
    items: [
      {
        href: '/projects',
        labelKey: 'projects',
        icon: <FolderKanban className="h-5 w-5" />,
        activePrefixes: ['/projects', '/knowledge/graph'],
      },
      { href: '/collaboration', labelKey: 'collaboration', icon: <ClipboardCheck className="h-5 w-5" /> },
      { href: '/documents/contradictions', labelKey: 'traceability', icon: <AlertTriangle className="h-5 w-5" /> },
      { href: '/exports', labelKey: 'exports', icon: <Download className="h-5 w-5" /> },
    ],
  },
  {
    labelKey: 'sectionIntelligence',
    items: [
      {
        href: '/agents',
        labelKey: 'agents',
        icon: <BrainCircuit className="h-5 w-5" />,
        activePrefixes: ['/agents', '/agent-ops', '/workflows'],
      },
      { href: '/templates', labelKey: 'templates', icon: <FileUp className="h-5 w-5" /> },
    ],
  },
  {
    labelKey: 'sectionGovernance',
    items: [
      { href: '/team', labelKey: 'team', icon: <UserCog className="h-5 w-5" /> },
      {
        href: '/system-health',
        labelKey: 'health',
        icon: <Activity className="h-5 w-5" />,
        activePrefixes: ['/system-health', '/health', '/providers', '/quotas'],
      },
      { href: '/audit', labelKey: 'audit', icon: <History className="h-5 w-5" /> },
      { href: '/settings', labelKey: 'settings', icon: <Settings className="h-5 w-5" /> },
    ],
  },
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
    const isActive = (item.activePrefixes ?? [item.href]).some(
      (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)
    )
    const label = t(item.labelKey)
    const content = (
      <Link
        href={item.href}
        aria-current={isActive ? 'page' : undefined}
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
    <div
      data-testid="primary-sidebar"
      className={cn(
        'flex h-full shrink-0 flex-col border-r border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 transition-all duration-300',
        collapsed ? 'w-16' : 'w-16 md:w-[200px]'
      )}
    >
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
        {navSections.map((section, index) => (
          <section
            key={section.labelKey}
            data-testid={`sidebar-section-${section.labelKey}`}
            className={cn(index > 0 && 'border-t border-slate-200 pt-3 dark:border-slate-800')}
          >
            {!collapsed && (
              <p className="mb-1 hidden px-3 text-xs font-semibold text-slate-400 md:block">
                {t(section.labelKey)}
              </p>
            )}
            <div className="space-y-1">
              {section.items.map((item) => (
                <NavItem key={item.href} item={item} />
              ))}
            </div>
          </section>
        ))}
      </nav>
    </div>
  )
}
