'use client'

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Download,
  FileText,
  Fingerprint,
  GitBranch,
  KeyRound,
  PackageCheck,
  RefreshCw,
  Search,
  ShieldCheck,
  User,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import type { BadgeProps } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectOption } from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useToast } from '@/components/ui/toast'
import { auditApi, changeApi, type AuditLog, type ChangeAuditCommandCenter } from '@/lib/api-client'
import { formatDistanceToNow } from '@/lib/utils'

type NormalizedAuditLog = AuditLog & {
  actionLabel: string
  resourceLabel: string
  severity: 'critical' | 'high' | 'medium' | 'low'
  actorLabel: string
  summary: string
}

const actionOptions = [
  { value: 'all', label: '全部动作' },
  { value: 'create', label: '创建' },
  { value: 'update', label: '更新' },
  { value: 'delete', label: '删除' },
  { value: 'approve', label: '审批' },
  { value: 'reject', label: '拒绝' },
  { value: 'execute', label: '执行' },
  { value: 'role', label: '角色权限' },
  { value: 'export', label: '导出' },
]

const resourceOptions = [
  { value: 'all', label: '全部实体' },
  { value: 'document', label: '文档' },
  { value: 'project', label: '项目' },
  { value: 'role', label: '角色' },
  { value: 'user', label: '用户' },
  { value: 'export', label: '导出' },
  { value: 'workflow', label: '工作流' },
]

const dateRangeOptions = [
  { value: '24h', label: '最近 24 小时' },
  { value: '7d', label: '最近 7 天' },
  { value: '30d', label: '最近 30 天' },
  { value: '90d', label: '最近 90 天' },
]

const resourceLabels: Record<string, string> = {
  document: '文档',
  project: '项目',
  role: '角色',
  user: '用户',
  export: '导出',
  workflow: '工作流',
  provider: '提供商',
  integration: '集成',
}

function actionLabel(action: string) {
  const normalized = action.toLowerCase()
  if (normalized.includes('create')) return '创建'
  if (normalized.includes('update')) return '更新'
  if (normalized.includes('delete')) return '删除'
  if (normalized.includes('approve')) return '审批通过'
  if (normalized.includes('reject')) return '审批拒绝'
  if (normalized.includes('execute')) return '执行'
  if (normalized.includes('assign')) return '分配'
  if (normalized.includes('login')) return '登录'
  return action
}

function severityFor(log: AuditLog): NormalizedAuditLog['severity'] {
  const action = log.action.toLowerCase()
  const resource = (log.resource_type || '').toLowerCase()
  if (action.includes('delete') || action.includes('reject')) return 'critical'
  if (resource === 'role' || action.includes('assign') || action.includes('permission')) return 'high'
  if (resource === 'export' || resource === 'workflow' || action.includes('execute')) return 'medium'
  return 'low'
}

function severityBadge(severity: NormalizedAuditLog['severity']): BadgeProps['variant'] {
  if (severity === 'critical' || severity === 'high') return 'destructive'
  if (severity === 'medium') return 'outline'
  return 'secondary'
}

function severityLabel(severity: NormalizedAuditLog['severity']) {
  return {
    critical: '关键',
    high: '高',
    medium: '中',
    low: '低',
  }[severity]
}

function resourceIcon(resourceType: string | null) {
  const resource = (resourceType || '').toLowerCase()
  if (resource === 'document') return <FileText className="h-4 w-4" />
  if (resource === 'role' || resource === 'user') return <KeyRound className="h-4 w-4" />
  if (resource === 'export') return <PackageCheck className="h-4 w-4" />
  if (resource === 'workflow') return <GitBranch className="h-4 w-4" />
  return <Activity className="h-4 w-4" />
}

function dateWindow(range: string) {
  const endDate = new Date()
  const startDate = new Date(endDate)
  if (range === '24h') startDate.setHours(endDate.getHours() - 24)
  if (range === '7d') startDate.setDate(endDate.getDate() - 7)
  if (range === '30d') startDate.setDate(endDate.getDate() - 30)
  if (range === '90d') startDate.setDate(endDate.getDate() - 90)
  return { startDate: startDate.toISOString(), endDate: endDate.toISOString() }
}

function normalizeLog(log: AuditLog): NormalizedAuditLog {
  const resourceType = log.resource_type || 'system'
  const extra = log.extra_data || {}
  const actor =
    extra.user_name ||
    extra.actor ||
    extra.email ||
    (log.user_id ? `用户 ${String(log.user_id).slice(0, 8)}` : '系统')
  const resourceLabel = resourceLabels[resourceType] || resourceType
  const label = actionLabel(log.action)
  return {
    ...log,
    actionLabel: label,
    resourceLabel,
    severity: severityFor(log),
    actorLabel: String(actor),
    summary: String(extra.summary || extra.reason || extra.title || `${resourceLabel}发生${label}事件`),
  }
}

function StatCard({ title, value, detail }: { title: string; value: string | number; detail: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{title}</CardDescription>
        <CardTitle className="text-3xl">{value}</CardTitle>
      </CardHeader>
      <CardContent className="text-sm text-slate-500">{detail}</CardContent>
    </Card>
  )
}

function gateBadgeVariant(status: string): BadgeProps['variant'] {
  if (status === 'blocked') return 'destructive'
  if (status === 'attention') return 'outline'
  return 'secondary'
}

function riskBadgeVariant(severity: string): BadgeProps['variant'] {
  if (severity === 'critical' || severity === 'high') return 'destructive'
  if (severity === 'medium') return 'outline'
  return 'secondary'
}

function ChangeAuditCommandCenterPanel({
  commandCenter,
  isLoading,
  isError,
  onRetry,
}: {
  commandCenter?: ChangeAuditCommandCenter
  isLoading: boolean
  isError: boolean
  onRetry: () => void
}) {
  if (isLoading) {
    return (
      <Card data-testid="change-audit-command-center">
        <CardContent className="flex items-center gap-2 py-6 text-sm text-slate-500">
          <RefreshCw className="h-4 w-4 animate-spin" />
          正在加载变更追溯指挥台...
        </CardContent>
      </Card>
    )
  }

  if (isError || !commandCenter) {
    return (
      <Card data-testid="change-audit-command-center" className="border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/20">
        <CardContent className="flex flex-col gap-3 py-5 text-amber-900 dark:text-amber-100 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="font-semibold">变更追溯指挥台暂不可用</p>
            <p className="text-sm">审计日志仍可使用，但发布前需要重新拉取变更门禁证据。</p>
          </div>
          <Button variant="outline" size="sm" onClick={onRetry}>重试</Button>
        </CardContent>
      </Card>
    )
  }

  const { summary, release_gate: gate } = commandCenter
  const metrics = [
    { label: '打开变更', value: summary.open_changes, detail: `高优先级 ${summary.critical_or_high_open_changes}` },
    { label: '待审补丁', value: summary.pending_field_patches, detail: '字段级回写' },
    { label: '影响分析', value: summary.open_impact_analyses, detail: `高影响 ${summary.critical_or_high_open_impacts}` },
    { label: '同步建议', value: summary.pending_sync_proposals, detail: '待接受或拒绝' },
  ]

  return (
    <Card data-testid="change-audit-command-center" className="border-slate-300 dark:border-slate-700">
      <CardHeader>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <GitBranch className="h-5 w-5" />
              变更追溯指挥台
            </CardTitle>
            <CardDescription>汇总变更、字段补丁、影响分析和同步建议，作为发布前审计门禁。</CardDescription>
          </div>
          <Badge data-testid="change-audit-release-gate" variant={gateBadgeVariant(gate.status)} className="w-fit">
            {gate.label}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-900/40">
          <p className="font-semibold text-slate-900 dark:text-white">{gate.summary}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {[...gate.blockers, ...gate.warnings].slice(0, 5).map((item) => (
              <Badge key={item} variant={gate.blockers.includes(item) ? 'destructive' : 'outline'}>{item}</Badge>
            ))}
            {gate.blockers.length === 0 && gate.warnings.length === 0 ? <Badge variant="secondary">无阻断项</Badge> : null}
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {metrics.map((metric) => (
            <div key={metric.label} className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950/20">
              <p className="text-sm text-slate-500">{metric.label}</p>
              <p className="mt-1 text-2xl font-semibold text-slate-900 dark:text-white">{metric.value}</p>
              <p className="mt-1 text-xs text-slate-500">{metric.detail}</p>
            </div>
          ))}
        </div>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="space-y-3">
            <p className="text-sm font-semibold text-slate-900 dark:text-white">关键风险</p>
            {commandCenter.risk_items.length === 0 ? (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
                没有未关闭的变更追溯风险。
              </div>
            ) : (
              commandCenter.risk_items.slice(0, 4).map((item) => (
                <a key={item.code} href={item.href} className="block rounded-lg border border-slate-200 bg-white p-4 transition hover:border-slate-400 dark:border-slate-800 dark:bg-slate-950/20">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-semibold text-slate-900 dark:text-white">{item.title}</p>
                    <Badge variant={riskBadgeVariant(item.severity)}>{item.count} 项</Badge>
                  </div>
                  <p className="mt-1 text-sm text-slate-500">{item.detail}</p>
                </a>
              ))
            )}
          </div>
          <div className="space-y-3">
            <p className="text-sm font-semibold text-slate-900 dark:text-white">优先动作</p>
            {commandCenter.priority_actions.map((action) => (
              <a key={action.code} href={action.href} className="block rounded-lg border border-slate-200 bg-white p-4 transition hover:border-slate-400 dark:border-slate-800 dark:bg-slate-950/20">
                <div className="flex items-center justify-between gap-2">
                  <p className="font-semibold text-slate-900 dark:text-white">{action.title}</p>
                  <Badge variant={riskBadgeVariant(action.priority)}>{action.priority}</Badge>
                </div>
                <p className="mt-1 text-sm text-slate-500">{action.description}</p>
              </a>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function exportCsv(logs: NormalizedAuditLog[]) {
  const rows = [
    ['时间', '风险', '动作', '实体类型', '实体 ID', '操作者', 'IP', '摘要'],
    ...logs.map((log) => [
      new Date(log.created_at).toLocaleString('zh-CN'),
      severityLabel(log.severity),
      log.action,
      log.resourceLabel,
      log.resource_id || '',
      log.actorLabel,
      log.ip_address || '',
      log.summary,
    ]),
  ]
  return rows.map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(',')).join('\n')
}

export default function AuditPage() {
  const { addToast } = useToast()
  const [query, setQuery] = useState('')
  const [actionFilter, setActionFilter] = useState('all')
  const [resourceFilter, setResourceFilter] = useState('all')
  const [dateRange, setDateRange] = useState('7d')
  const dateParams = useMemo(() => dateWindow(dateRange), [dateRange])

  const logsQuery = useQuery({
    queryKey: ['audit-evidence-center', actionFilter, resourceFilter, dateRange],
    queryFn: () =>
      auditApi.listLogs({
        pageSize: 100,
        action: actionFilter === 'all' ? undefined : actionFilter,
        resourceType: resourceFilter === 'all' ? undefined : resourceFilter,
        startDate: dateParams.startDate,
        endDate: dateParams.endDate,
      }),
  })

  const commandCenterQuery = useQuery({
    queryKey: ['change-audit-command-center'],
    queryFn: () => changeApi.getAuditCommandCenter(),
  })

  const logs = useMemo(() => (logsQuery.data?.items || []).map(normalizeLog), [logsQuery.data?.items])

  const filteredLogs = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()
    return logs.filter((log) => {
      if (!normalizedQuery) return true
      return [
        log.action,
        log.actionLabel,
        log.resourceLabel,
        log.resource_id || '',
        log.actorLabel,
        log.summary,
        log.ip_address || '',
      ]
        .join(' ')
        .toLowerCase()
        .includes(normalizedQuery)
    })
  }, [logs, query])

  const criticalLogs = filteredLogs.filter((log) => log.severity === 'critical' || log.severity === 'high')
  const resourceGroups = useMemo(() => {
    const counts = new Map<string, { label: string; count: number; high: number }>()
    for (const log of filteredLogs) {
      const key = log.resource_type || 'system'
      const current = counts.get(key) || { label: log.resourceLabel, count: 0, high: 0 }
      current.count += 1
      if (log.severity === 'critical' || log.severity === 'high') current.high += 1
      counts.set(key, current)
    }
    return Array.from(counts.entries())
      .map(([key, value]) => ({ key, ...value }))
      .sort((a, b) => b.count - a.count)
  }, [filteredLogs])

  const exportLogs = () => {
    const csv = exportCsv(filteredLogs)
    const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = window.document.createElement('a')
    link.href = url
    link.download = `audit-evidence-${new Date().toISOString().slice(0, 10)}.csv`
    link.click()
    URL.revokeObjectURL(url)
    addToast({ title: '审计证据已导出', description: `${filteredLogs.length} 条记录已写入 CSV。` })
  }

  if (logsQuery.isLoading) {
    return (
      <div className="flex h-64 items-center justify-center text-slate-500">
        <RefreshCw className="mr-2 h-5 w-5 animate-spin" />
        正在加载审计证据...
      </div>
    )
  }

  if (logsQuery.isError) {
    return (
      <div className="rounded-lg border border-rose-200 bg-rose-50 p-6 text-rose-900">
        <div className="flex items-center gap-2 font-semibold">
          <AlertTriangle className="h-5 w-5" />
          审计证据加载失败
        </div>
        <p className="mt-2 text-sm">{logsQuery.error instanceof Error ? logsQuery.error.message : '审计接口暂不可用。'}</p>
        <Button className="mt-4" variant="outline" onClick={() => logsQuery.refetch()}>
          重试
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">审计证据中心</h1>
          <p className="mt-1 text-sm text-slate-500">集中追踪权限、文档、导出、工作流和系统操作证据, 支持风险筛选与 CSV 导出。</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => logsQuery.refetch()}>
            <RefreshCw className="mr-2 h-4 w-4" />
            刷新
          </Button>
          <Button onClick={exportLogs} disabled={filteredLogs.length === 0}>
            <Download className="mr-2 h-4 w-4" />
            导出证据
          </Button>
        </div>
      </div>

      <ChangeAuditCommandCenterPanel
        commandCenter={commandCenterQuery.data}
        isLoading={commandCenterQuery.isLoading}
        isError={commandCenterQuery.isError}
        onRetry={() => commandCenterQuery.refetch()}
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard title="审计事件" value={filteredLogs.length} detail={`${dateRangeOptions.find((item) => item.value === dateRange)?.label || '当前范围'}内记录`} />
        <StatCard title="高风险事件" value={criticalLogs.length} detail="删除、拒绝、权限分配等需重点复核" />
        <StatCard title="涉及实体" value={resourceGroups.length} detail="按资源类型聚合追踪" />
        <StatCard title="最新事件" value={filteredLogs[0] ? formatDistanceToNow(filteredLogs[0].created_at) : '暂无'} detail={filteredLogs[0]?.summary || '没有可展示事件'} />
      </div>

      <Card>
        <CardContent className="py-4">
          <div className="grid gap-3 lg:grid-cols-[minmax(220px,1fr)_170px_170px_150px]">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索动作、用户、实体、IP 或摘要"
                className="pl-10"
                data-testid="audit-search"
              />
            </div>
            <Select value={actionFilter} onValueChange={setActionFilter}>
              {actionOptions.map((option) => (
                <SelectOption key={option.value} value={option.value}>
                  {option.label}
                </SelectOption>
              ))}
            </Select>
            <Select value={resourceFilter} onValueChange={setResourceFilter}>
              {resourceOptions.map((option) => (
                <SelectOption key={option.value} value={option.value}>
                  {option.label}
                </SelectOption>
              ))}
            </Select>
            <Select value={dateRange} onValueChange={setDateRange}>
              {dateRangeOptions.map((option) => (
                <SelectOption key={option.value} value={option.value}>
                  {option.label}
                </SelectOption>
              ))}
            </Select>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5" />
              风险事件队列
            </CardTitle>
            <CardDescription>优先展示权限、删除、拒绝和执行类事件。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {criticalLogs.length === 0 ? (
              <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
                <CheckCircle2 className="h-4 w-4" />
                当前筛选范围内没有高风险审计事件。
              </div>
            ) : (
              criticalLogs.slice(0, 6).map((log) => (
                <div key={log.id} className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950/20">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant={severityBadge(log.severity)}>{severityLabel(log.severity)}</Badge>
                        <p className="font-semibold text-slate-900 dark:text-white">{log.actionLabel}</p>
                      </div>
                      <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{log.summary}</p>
                    </div>
                    <div className="text-right text-xs text-slate-500">
                      <p>{new Date(log.created_at).toLocaleString('zh-CN')}</p>
                      <p>{log.ip_address || '无 IP'}</p>
                    </div>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>实体影响聚合</CardTitle>
            <CardDescription>按实体类型统计事件量和高风险量。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {resourceGroups.length === 0 ? (
              <div className="rounded-lg border border-slate-200 p-4 text-sm text-slate-500 dark:border-slate-800">暂无实体聚合。</div>
            ) : (
              resourceGroups.map((group) => (
                <div key={group.key} className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950/20">
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      {resourceIcon(group.key)}
                      <span className="font-semibold text-slate-900 dark:text-white">{group.label}</span>
                    </div>
                    <Badge variant={group.high ? 'destructive' : 'secondary'}>{group.count} 条</Badge>
                  </div>
                  <p className="mt-2 text-sm text-slate-500">高风险 {group.high} 条</p>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>审计时间线</CardTitle>
          <CardDescription>按发生时间倒序展示可追溯证据。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {filteredLogs.length === 0 ? (
            <div className="py-12 text-center text-slate-500">
              <FileText className="mx-auto h-12 w-12 text-slate-300" />
              <p className="mt-3 text-sm">没有匹配的审计事件。</p>
            </div>
          ) : (
            filteredLogs.slice(0, 12).map((log) => (
              <div key={log.id} data-testid="audit-entry" className="grid gap-3 rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950/20 lg:grid-cols-[190px_minmax(0,1fr)_220px]">
                <div className="flex items-center gap-2 text-sm text-slate-500">
                  <Clock className="h-4 w-4" />
                  <div>
                    <p>{new Date(log.created_at).toLocaleString('zh-CN')}</p>
                    <p className="text-xs">{formatDistanceToNow(log.created_at)}</p>
                  </div>
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={severityBadge(log.severity)}>{severityLabel(log.severity)}</Badge>
                    <Badge variant="outline">{log.resourceLabel}</Badge>
                    <p className="font-semibold text-slate-900 dark:text-white">{log.actionLabel}</p>
                  </div>
                  <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{log.summary}</p>
                  <p className="mt-1 truncate text-xs text-slate-500">实体 ID: {log.resource_id || '-'}</p>
                </div>
                <div className="flex flex-col gap-2 text-sm text-slate-500">
                  <span className="flex items-center gap-2">
                    <User className="h-4 w-4" />
                    {log.actorLabel}
                  </span>
                  <span className="flex items-center gap-2">
                    <Fingerprint className="h-4 w-4" />
                    {log.ip_address || '无 IP'}
                  </span>
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>明细表</CardTitle>
          <CardDescription>用于审计复核和导出前检查。</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <Table data-testid="audit-table">
            <TableHeader>
              <TableRow className="bg-slate-50 dark:bg-slate-800">
                <TableHead>时间</TableHead>
                <TableHead>风险</TableHead>
                <TableHead>动作</TableHead>
                <TableHead>实体</TableHead>
                <TableHead>操作者</TableHead>
                <TableHead>IP</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredLogs.map((log) => (
                <TableRow key={log.id}>
                  <TableCell>{new Date(log.created_at).toLocaleString('zh-CN')}</TableCell>
                  <TableCell>
                    <Badge variant={severityBadge(log.severity)}>{severityLabel(log.severity)}</Badge>
                  </TableCell>
                  <TableCell>{log.action}</TableCell>
                  <TableCell>
                    <div>
                      <p className="font-medium text-slate-900 dark:text-white">{log.resourceLabel}</p>
                      <p className="text-xs text-slate-500">{log.resource_id || '-'}</p>
                    </div>
                  </TableCell>
                  <TableCell>{log.actorLabel}</TableCell>
                  <TableCell>{log.ip_address || '-'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
