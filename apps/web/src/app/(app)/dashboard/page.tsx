'use client'

import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import Link from 'next/link'
import {
  AlertTriangle,
  ArrowRight,
  BrainCircuit,
  CheckCircle2,
  ClipboardCheck,
  Download,
  FileText,
  FolderKanban,
  GitBranch,
  Layers3,
  Loader2,
  CalendarClock,
  Network,
  Plus,
  ShieldAlert,
  ShieldCheck,
  Users,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import type { BadgeProps } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  projectsApi,
  type SystemCompletionCapability,
  type SystemCompletionGap,
  type SystemDeliveryAction,
  type SystemDeliveryModuleHealth,
  type SystemDeliveryOperatingPlanItem,
  type SystemDeliveryMilestoneDigest,
  type SystemDeliveryOwnerLoad,
  type SystemDeliveryPhaseSummary,
  type SystemDeliveryProjectDigest,
  type SystemDeliveryReleaseGate,
  type SystemProductionGate,
} from '@/lib/api-client'

const priorityLabel: Record<string, string> = {
  critical: '紧急',
  high: '高',
  medium: '中',
  low: '低',
}

const moduleIcon: Record<string, ReactNode> = {
  sources: <FolderKanban className="h-4 w-4" />,
  knowledge: <Network className="h-4 w-4" />,
  documents: <FileText className="h-4 w-4" />,
  review: <Users className="h-4 w-4" />,
  changes: <GitBranch className="h-4 w-4" />,
  export: <Download className="h-4 w-4" />,
}

function scoreClass(score: number) {
  if (score >= 80) return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (score >= 50) return 'border-amber-200 bg-amber-50 text-amber-800'
  return 'border-rose-200 bg-rose-50 text-rose-800'
}

function statusBadge(status: string): BadgeProps['variant'] {
  if (status === 'healthy' || status === 'passed' || status === 'ready' || status === 'completed') return 'secondary'
  if (status === 'attention' || status === 'empty' || status === 'planned' || status === 'in_progress') return 'outline'
  return 'destructive'
}

function statusLabel(status: string) {
  return (
    {
      ready: '就绪',
      healthy: '健康',
      passed: '通过',
      attention: '关注',
      blocked: '阻塞',
      empty: '暂无',
      planned: '待开始',
      in_progress: '进行中',
      completed: '已完成',
    }[status] ?? status
  )
}

function systemDeliveryActionKey(action: SystemDeliveryAction) {
  return [
    action.project_id,
    action.code,
    action.href,
    action.label,
  ].join('::')
}

function severityLabel(severity: string) {
  return (
    {
      critical: '紧急',
      high: '高',
      medium: '中',
    }[severity] ?? severity
  )
}

function severityVariant(severity: string): BadgeProps['variant'] {
  return severity === 'critical' || severity === 'high' ? 'destructive' : 'outline'
}

function projectHref(project: SystemDeliveryProjectDigest) {
  return `/projects/${project.project_id}/documents`
}

function ProgressBar({ value }: { value: number }) {
  return (
    <div className="h-2 rounded-full bg-slate-100 dark:bg-slate-800">
      <div
        className="h-2 rounded-full bg-indigo-500 transition-all"
        style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
      />
    </div>
  )
}

function ModuleHealthRow({ module }: { module: SystemDeliveryModuleHealth }) {
  return (
    <Link
      href={module.action_href}
      className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white p-3 transition hover:border-indigo-300 hover:bg-indigo-50/50 dark:border-slate-800 dark:bg-slate-950/20 dark:hover:border-indigo-700"
    >
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
        {moduleIcon[module.key] ?? <ShieldCheck className="h-4 w-4" />}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-medium text-slate-900 dark:text-white">{module.label}</p>
          <Badge variant={statusBadge(module.status)}>{module.score}</Badge>
        </div>
        <p className="mt-1 truncate text-sm text-slate-500">{module.summary}</p>
      </div>
      <ArrowRight className="h-4 w-4 shrink-0 text-slate-400" />
    </Link>
  )
}

function CompletionCapabilityCard({ capability }: { capability: SystemCompletionCapability }) {
  return (
    <Link
      href={capability.action_href}
      className="block rounded-lg border border-slate-200 bg-white p-4 transition hover:border-indigo-300 hover:bg-indigo-50/50 dark:border-slate-800 dark:bg-slate-950/20 dark:hover:border-indigo-700"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-semibold text-slate-900 dark:text-white">{capability.label}</p>
            <Badge variant={statusBadge(capability.status)}>{statusLabel(capability.status)}</Badge>
          </div>
          <p className="mt-1 text-sm leading-5 text-slate-500">{capability.summary}</p>
        </div>
        <div className={`shrink-0 rounded-md border px-3 py-2 text-sm font-semibold ${scoreClass(capability.score)}`}>
          {capability.score}
        </div>
      </div>
      <div className="mt-4">
        <ProgressBar value={capability.score} />
      </div>
      {capability.blockers.length ? (
        <div className="mt-3 space-y-1 text-xs text-rose-700">
          {capability.blockers.slice(0, 2).map((blocker) => (
            <p key={blocker} className="truncate">
              {blocker}
            </p>
          ))}
        </div>
      ) : (
        <p className="mt-3 text-xs text-emerald-700">当前能力闭环无阻塞。</p>
      )}
      <div className="mt-4 flex items-center justify-between text-xs font-medium text-indigo-600">
        <span>{capability.action_label}</span>
        <ArrowRight className="h-4 w-4" />
      </div>
    </Link>
  )
}

function CompletionGapItem({ gap }: { gap: SystemCompletionGap }) {
  return (
    <Link
      href={gap.action_href}
      className="block rounded-lg border border-slate-200 bg-white p-4 transition hover:border-indigo-300 hover:bg-indigo-50/50 dark:border-slate-800 dark:bg-slate-950/20 dark:hover:border-indigo-700"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-semibold text-slate-900 dark:text-white">{gap.title}</p>
            <Badge variant={severityVariant(gap.severity)}>{severityLabel(gap.severity)}</Badge>
          </div>
          <p className="mt-1 text-sm leading-5 text-slate-600 dark:text-slate-300">{gap.detail}</p>
        </div>
        <ArrowRight className="h-4 w-4 shrink-0 text-slate-400" />
      </div>
      <p className="mt-3 text-xs font-medium text-indigo-600">{gap.action_label}</p>
    </Link>
  )
}

function ProductionGatePanel({ gate }: { gate: SystemProductionGate }) {
  return (
    <Card data-testid="production-gate">
      <CardHeader>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle>投产门禁</CardTitle>
            <CardDescription>统一检查交付、集成、协同、通知、权限和运维证据。</CardDescription>
          </div>
          <div className={`w-fit rounded-md border px-3 py-2 text-sm font-semibold ${scoreClass(gate.score)}`}>
            {statusLabel(gate.status)} {gate.score}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid gap-3 sm:grid-cols-4">
          <div className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
            <p className="text-xs text-slate-500">检查项</p>
            <p className="mt-1 text-xl font-semibold">{gate.total_count}</p>
          </div>
          <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-emerald-800">
            <p className="text-xs">已就绪</p>
            <p className="mt-1 text-xl font-semibold">{gate.ready_count}</p>
          </div>
          <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-amber-800">
            <p className="text-xs">需关注</p>
            <p className="mt-1 text-xl font-semibold">{gate.attention_count}</p>
          </div>
          <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-rose-800">
            <p className="text-xs">阻断投产</p>
            <p className="mt-1 text-xl font-semibold">{gate.blocking_count}</p>
          </div>
        </div>
        {gate.checks.length ? (
          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            {gate.checks.slice(0, 6).map((check) => (
              <Link
                key={check.capability_key}
                href={check.action_href}
                className="flex items-start justify-between gap-3 rounded-md border border-slate-200 p-3 transition hover:border-indigo-300 hover:bg-indigo-50/50 dark:border-slate-800"
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-medium text-slate-900 dark:text-white">{check.label}</p>
                    <Badge variant={statusBadge(check.status)}>{statusLabel(check.status)}</Badge>
                  </div>
                  <p className="mt-1 text-sm text-slate-500">{check.detail}</p>
                  <p className="mt-2 text-xs font-medium text-indigo-600">{check.action_label}</p>
                </div>
                <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-slate-400" />
              </Link>
            ))}
          </div>
        ) : (
          <div className="mt-4 flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
            <CheckCircle2 className="h-4 w-4" />
            所有投产检查项均已通过。
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function PhaseSummaryRow({ phase }: { phase: SystemDeliveryPhaseSummary }) {
  return (
    <Link
      href={phase.action_href}
      className="block rounded-lg border border-slate-200 bg-white p-4 transition hover:border-indigo-300 hover:bg-indigo-50/50 dark:border-slate-800 dark:bg-slate-950/20 dark:hover:border-indigo-700"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-semibold text-slate-900 dark:text-white">{phase.label}</p>
            <Badge variant={statusBadge(phase.status)}>{statusLabel(phase.status)}</Badge>
          </div>
          <p className="mt-1 text-sm text-slate-500">{phase.summary}</p>
        </div>
        <ArrowRight className="h-4 w-4 shrink-0 text-slate-400" />
      </div>
      <div className="mt-4 grid grid-cols-3 gap-2 text-xs text-slate-500">
        <span>项目 {phase.project_count}</span>
        <span>阻塞 {phase.blocked_project_count}</span>
        <span>就绪 {phase.ready_project_count}</span>
      </div>
      <div className="mt-3">
        <ProgressBar value={phase.score} />
      </div>
    </Link>
  )
}

function ReleaseGateRow({ gate }: { gate: SystemDeliveryReleaseGate }) {
  return (
    <Link
      href={gate.action_href}
      className="block rounded-lg border border-slate-200 bg-white p-4 transition hover:border-indigo-300 hover:bg-indigo-50/50 dark:border-slate-800 dark:bg-slate-950/20 dark:hover:border-indigo-700"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-semibold text-slate-900 dark:text-white">{gate.label}</p>
            <Badge variant={statusBadge(gate.status)}>{statusLabel(gate.status)}</Badge>
          </div>
          <p className="mt-1 text-sm text-slate-500">
            {gate.passed_count}/{gate.total_count} 个项目通过, 得分 {gate.score}
          </p>
        </div>
        <ArrowRight className="h-4 w-4 shrink-0 text-slate-400" />
      </div>
      {gate.blockers.length ? (
        <div className="mt-3 space-y-1 text-xs text-rose-700">
          {gate.blockers.slice(0, 2).map((blocker) => (
            <p key={blocker} className="truncate">
              {blocker}
            </p>
          ))}
        </div>
      ) : (
        <p className="mt-3 text-xs text-emerald-700">当前门禁无阻塞。</p>
      )}
    </Link>
  )
}

function OperatingPlanItem({ item }: { item: SystemDeliveryOperatingPlanItem }) {
  return (
    <Link
      href={item.action_href}
      className="block rounded-lg border border-slate-200 bg-white p-4 transition hover:border-indigo-300 hover:bg-indigo-50/50 dark:border-slate-800 dark:bg-slate-950/20 dark:hover:border-indigo-700"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm text-slate-500">{item.project_name}</p>
          <p className="mt-1 font-semibold text-slate-900 dark:text-white">{item.action_label}</p>
          <p className="mt-1 text-sm leading-5 text-slate-600 dark:text-slate-300">{item.action_description}</p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          <Badge variant={statusBadge(item.status)}>{statusLabel(item.status)}</Badge>
          <Badge variant={item.priority === 'high' || item.priority === 'critical' ? 'destructive' : 'outline'}>
            {priorityLabel[item.priority] ?? item.priority}
          </Badge>
        </div>
      </div>
      <div className="mt-3 flex items-center gap-2 text-xs text-slate-500">
        <Layers3 className="h-3.5 w-3.5" />
        {item.phase_label}
      </div>
    </Link>
  )
}

function MilestonePortfolioItem({ milestone }: { milestone: SystemDeliveryMilestoneDigest }) {
  return (
    <Link
      href={milestone.action_href}
      className="block rounded-lg border border-slate-200 bg-white p-4 transition hover:border-indigo-300 hover:bg-indigo-50/50 dark:border-slate-800 dark:bg-slate-950/20 dark:hover:border-indigo-700"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs text-slate-500">{milestone.project_name}</p>
          <p className="mt-1 font-semibold text-slate-900 dark:text-white">{milestone.title}</p>
          <p className="mt-2 text-xs text-slate-500">
            {milestone.owner_name}
            {milestone.due_at ? ` · 截止 ${new Date(milestone.due_at).toLocaleDateString('zh-CN')}` : ' · 未设置截止日期'}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          <Badge variant={statusBadge(milestone.status)}>{statusLabel(milestone.status)}</Badge>
          {milestone.is_overdue ? <Badge variant="destructive">已逾期</Badge> : null}
        </div>
      </div>
      {milestone.gate_blocker_count ? <p className="mt-3 text-xs text-rose-700">{milestone.gate_blocker_count} 个门禁阻塞</p> : null}
    </Link>
  )
}

function OwnerLoadItem({ owner }: { owner: SystemDeliveryOwnerLoad }) {
  return (
    <Link href={owner.action_href} className="block rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950/20">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-semibold text-slate-900 dark:text-white">{owner.owner_name}</p>
          <p className="mt-1 text-xs text-slate-500">覆盖 {owner.project_count} 个项目</p>
        </div>
        <Badge variant={owner.blocked_count || owner.overdue_count ? 'destructive' : 'secondary'}>{owner.active_count} 项进行中</Badge>
      </div>
      <div className="mt-3 flex gap-3 text-xs text-slate-500">
        <span>阻塞 {owner.blocked_count}</span>
        <span>逾期 {owner.overdue_count}</span>
      </div>
    </Link>
  )
}

function ActionItem({ action }: { action: SystemDeliveryAction }) {
  return (
    <Link
      href={action.href}
      className="block rounded-lg border border-slate-200 bg-white p-4 transition hover:border-indigo-300 hover:bg-indigo-50/50 dark:border-slate-800 dark:bg-slate-950/20 dark:hover:border-indigo-700"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm text-slate-500">{action.project_name}</p>
          <p className="mt-1 font-semibold text-slate-900 dark:text-white">{action.label}</p>
          <p className="mt-1 text-sm leading-5 text-slate-600 dark:text-slate-300">{action.description}</p>
        </div>
        <Badge variant={action.priority === 'high' || action.priority === 'critical' ? 'destructive' : 'outline'}>
          {priorityLabel[action.priority] ?? action.priority}
        </Badge>
      </div>
    </Link>
  )
}

function ProjectRow({ project }: { project: SystemDeliveryProjectDigest }) {
  return (
    <div className="grid gap-3 rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950/20 xl:grid-cols-[minmax(220px,1.2fr)_128px_minmax(260px,1fr)_170px] xl:items-center">
      <div className="min-w-0">
        <Link href={projectHref(project)} className="font-semibold text-slate-900 hover:text-indigo-600 dark:text-white">
          {project.name}
        </Link>
        <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
          <span>文档 {project.document_count}</span>
          <span>资料 {project.source_file_count}</span>
          <span>知识 {project.knowledge_entry_count}</span>
          <span>变更 {project.open_change_count}</span>
        </div>
      </div>
      <div className={`w-fit rounded-md border px-3 py-2 text-sm font-semibold ${scoreClass(project.readiness_score)}`}>
        {project.readiness_score} {project.readiness_label}
      </div>
      <div className="flex flex-wrap gap-2 text-sm">
        <Badge variant="outline">{project.delivery_phase_label}</Badge>
        <Badge variant={statusBadge(project.release_gate_status)}>门禁{statusLabel(project.release_gate_status)}</Badge>
        {project.blocker_count ? <Badge variant="destructive">{project.blocker_count} 个阻塞</Badge> : <Badge variant="secondary">无阻塞</Badge>}
        {project.review_queue_count ? <Badge variant="outline">{project.review_queue_count} 个评审</Badge> : null}
        {project.export_ready ? <Badge variant="secondary">可导出</Badge> : <Badge variant="outline">待导出准备</Badge>}
      </div>
      <Button asChild variant={project.next_action_priority === 'high' ? 'default' : 'outline'} size="sm">
        <Link href={project.next_action_href}>
          {project.next_action_label}
          <ArrowRight className="ml-2 h-4 w-4" />
        </Link>
      </Button>
    </div>
  )
}

export default function DashboardPage() {
  const overviewQuery = useQuery({
    queryKey: ['system-delivery-overview'],
    queryFn: () => projectsApi.getDeliveryOverview({ limit: 8 }),
  })

  const overview = overviewQuery.data
  const moduleHealth = overview?.module_health ?? []
  const phases = overview?.phase_summary ?? []
  const gates = overview?.release_gates ?? []
  const operatingPlan = overview?.operating_plan ?? []
  const projects = overview?.projects ?? []
  const criticalActions = overview?.critical_actions ?? []
  const completionCapabilities = overview?.completion_capabilities ?? []
  const completionGaps = overview?.completion_gaps ?? []
  const productionGate = overview?.production_gate
  const milestonePortfolio = overview?.milestone_portfolio

  if (overviewQuery.isLoading) {
    return (
      <div className="flex h-64 items-center justify-center text-slate-500">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        正在加载交付总控台...
      </div>
    )
  }

  if (overviewQuery.isError) {
    return (
      <div className="rounded-lg border border-rose-200 bg-rose-50 p-6 text-rose-900">
        <div className="flex items-center gap-2 font-semibold">
          <AlertTriangle className="h-5 w-5" />
          交付总控台加载失败
        </div>
        <p className="mt-2 text-sm">{overviewQuery.error instanceof Error ? overviewQuery.error.message : '系统概览接口暂不可用。'}</p>
        <Button className="mt-4" variant="outline" onClick={() => overviewQuery.refetch()}>
          重试
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">交付总控台</h1>
          <p className="mt-1 text-sm text-slate-500">
            汇总项目、资料、知识图谱、文档、评审、变更、导出和智能编排状态, 直接指向下一步交付动作。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline">
            <Link href="/workflows">
              <BrainCircuit className="mr-2 h-4 w-4" />
              智能编排
            </Link>
          </Button>
          <Button asChild>
            <Link href="/projects">
              <Plus className="mr-2 h-4 w-4" />
              新建或进入项目
            </Link>
          </Button>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
        <Card>
          <CardHeader>
            <CardTitle>系统就绪度</CardTitle>
            <CardDescription>按核心交付链路自动计算。</CardDescription>
          </CardHeader>
          <CardContent>
            <div className={`rounded-lg border p-5 ${scoreClass(overview?.readiness_score ?? 0)}`}>
              <p className="text-sm font-medium">总分</p>
              <p className="mt-2 text-4xl font-semibold">{overview?.readiness_score ?? 0}</p>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">项目 {overview?.totals.projects ?? 0}</div>
              <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">文档 {overview?.totals.documents ?? 0}</div>
              <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">资料 {overview?.totals.source_files ?? 0}</div>
              <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">知识 {overview?.totals.knowledge_entries ?? 0}</div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>核心模块健康</CardTitle>
            <CardDescription>每个模块都能直接跳转处理。</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {moduleHealth.map((module) => (
              <ModuleHealthRow key={module.key} module={module} />
            ))}
          </CardContent>
        </Card>
      </div>

      {productionGate ? <ProductionGatePanel gate={productionGate} /> : null}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.25fr)_420px]">
        <Card>
          <CardHeader>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <CardTitle>核心功能完整度</CardTitle>
                <CardDescription>按生产闭环衡量项目文档、知识、编排、模板、追溯、导出、供应商和权限。</CardDescription>
              </div>
              <div className={`w-fit rounded-md border px-3 py-2 text-sm font-semibold ${scoreClass(overview?.completion_score ?? 0)}`}>
                完整度 {overview?.completion_score ?? 0}
              </div>
            </div>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {completionCapabilities.map((capability) => (
              <CompletionCapabilityCard key={capability.key} capability={capability} />
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>系统缺口队列</CardTitle>
            <CardDescription>按严重度排序，直接指向需要补齐的能力入口。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {completionGaps.length === 0 ? (
              <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
                <CheckCircle2 className="h-4 w-4" />
                核心能力当前没有未闭环阻塞。
              </div>
            ) : (
              completionGaps.map((gap) => <CompletionGapItem key={gap.key} gap={gap} />)
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(360px,0.8fr)]">
        <Card>
          <CardHeader>
            <CardTitle>交付阶段作战图</CardTitle>
            <CardDescription>按资料导入、文档编写、评审追溯、导出发布组织项目推进。</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {phases.map((phase) => (
              <PhaseSummaryRow key={phase.key} phase={phase} />
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>发布门禁</CardTitle>
            <CardDescription>未全部通过前不建议进入正式交付。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {gates.map((gate) => (
              <ReleaseGateRow key={gate.key} gate={gate} />
            ))}
          </CardContent>
        </Card>
      </div>

      <div data-testid="milestone-portfolio" className="grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_420px]">
        <Card>
          <CardHeader>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <CardTitle>跨项目里程碑总控</CardTitle>
                <CardDescription>按逾期、截止时间和优先级集中推进项目交付节点。</CardDescription>
              </div>
              <div className="flex flex-wrap gap-2">
                <Badge variant="outline">总计 {milestonePortfolio?.totals.total ?? 0}</Badge>
                <Badge variant="destructive">阻塞 {milestonePortfolio?.totals.blocked ?? 0}</Badge>
                <Badge variant="destructive">逾期 {milestonePortfolio?.totals.overdue ?? 0}</Badge>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {milestonePortfolio?.upcoming.length ? (
              <div className="grid gap-3 md:grid-cols-2">
                {milestonePortfolio.upcoming.map((milestone) => (
                  <MilestonePortfolioItem key={milestone.milestone_id} milestone={milestone} />
                ))}
              </div>
            ) : (
              <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
                <CheckCircle2 className="h-4 w-4" />
                当前没有待推进里程碑。
              </div>
            )}
          </CardContent>
        </Card>

        <Card data-testid="milestone-owner-load">
          <CardHeader>
            <CardTitle>责任负载</CardTitle>
            <CardDescription>识别跨项目责任集中、阻塞和逾期风险。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {milestonePortfolio?.owner_load.length ? milestonePortfolio.owner_load.map((owner) => (
              <OwnerLoadItem key={owner.owner_id ?? 'unassigned'} owner={owner} />
            )) : (
              <div className="flex items-center gap-2 rounded-lg border border-slate-200 p-4 text-sm text-slate-500">
                <CalendarClock className="h-4 w-4" />
                暂无里程碑责任负载。
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_420px]">
        <Card>
          <CardHeader>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <CardTitle>项目交付队列</CardTitle>
                <CardDescription>优先显示 readiness 较低或有阻塞的项目。</CardDescription>
              </div>
              <Button asChild variant="outline" size="sm">
                <Link href="/projects">
                  查看全部
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Link>
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {projects.length === 0 ? (
              <div className="py-12 text-center text-slate-500">
                <FolderKanban className="mx-auto h-12 w-12 text-slate-300" />
                <p className="mt-3 text-sm">暂无项目。创建项目后, 总控台会自动形成交付队列。</p>
                <Button className="mt-4" asChild>
                  <Link href="/projects">创建项目</Link>
                </Button>
              </div>
            ) : (
              <div className="space-y-3">
                {projects.map((project) => (
                  <ProjectRow key={project.project_id} project={project} />
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>执行计划</CardTitle>
              <CardDescription>跨项目聚合后的当前批次优先动作。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {operatingPlan.length === 0 ? (
                <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
                  <CheckCircle2 className="h-4 w-4" />
                  当前没有待执行动作。
                </div>
              ) : (
                operatingPlan.map((item) => <OperatingPlanItem key={`${item.project_id}-${item.action_code}`} item={item} />)
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>关键动作</CardTitle>
              <CardDescription>来自项目工作台的高优先级事项。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {criticalActions.length === 0 ? (
                <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
                  <CheckCircle2 className="h-4 w-4" />
                  当前没有高优先级阻塞。
                </div>
              ) : (
                criticalActions.map((action) => <ActionItem key={systemDeliveryActionKey(action)} action={action} />)
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>核心入口</CardTitle>
              <CardDescription>按端到端交付顺序组织。</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-2">
              {[
                ['/projects', '项目资料', <FolderKanban key="projects" className="h-4 w-4" />],
                ['/documents', '项目文档', <FileText key="documents" className="h-4 w-4" />],
                ['/knowledge/graph', '知识图谱', <Network key="knowledge" className="h-4 w-4" />],
                ['/workflows', '智能编排', <BrainCircuit key="workflows" className="h-4 w-4" />],
                ['/collaboration', '协同评审', <Users key="collaboration" className="h-4 w-4" />],
                ['/exports', '导出中心', <Download key="exports" className="h-4 w-4" />],
              ].map(([href, label, icon]) => (
                <Button key={href as string} asChild variant="outline" className="justify-between">
                  <Link href={href as string}>
                    <span className="flex items-center gap-2">
                      {icon as ReactNode}
                      {label as string}
                    </span>
                    <ArrowRight className="h-4 w-4" />
                  </Link>
                </Button>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
