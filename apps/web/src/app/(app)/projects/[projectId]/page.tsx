'use client'

import { use } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { projectsApi, Project, ProjectDeliveryNextAction, ProjectDeliveryRisk } from '@/lib/api-client'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from '@/components/ui/tabs'
import {
  FolderKanban,
  FileText,
  BrainCircuit,
  Network,
  GitBranch,
  Users,
  Settings,
  ArrowLeft,
  Plus,
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  ShieldAlert,
  RefreshCw,
  CalendarRange,
} from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { formatDistanceToNow } from '@/lib/utils'
import { getDocumentStatusLabel, getDocumentTypeLabel } from '@/lib/document-labels'
import { useToast } from '@/components/ui/toast'

interface ProjectPageProps {
  params: Promise<{ projectId: string }>
}

function getRiskBadgeClass(severity: string) {
  switch (severity) {
    case 'high':
      return 'border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-200'
    case 'medium':
      return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200'
    default:
      return 'border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200'
  }
}

function getActionBadgeClass(priority: string) {
  switch (priority) {
    case 'high':
      return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100'
    case 'medium':
      return 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-100'
    default:
      return 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-100'
  }
}

function getStatusBadgeClass(status: string) {
  switch (status) {
    case 'published':
    case 'approved':
      return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-100'
    case 'review':
    case 'in_review':
    case 'pending_review':
      return 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-100'
    case 'missing':
    case 'draft':
      return 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-100'
    case 'rejected':
    case 'revision_required':
      return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100'
    default:
      return 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-100'
  }
}

function getRiskIcon(risk: ProjectDeliveryRisk) {
  if (risk.severity === 'high') return <ShieldAlert className="h-4 w-4" />
  return <AlertTriangle className="h-4 w-4" />
}

function getActionLabel(action: ProjectDeliveryNextAction) {
  return action.priority === 'high' ? '高优先级' : action.priority === 'medium' ? '中优先级' : '低优先级'
}

function getSourceFileStatusLabel(status: string) {
  const labels: Record<string, string> = {
    ready: '已就绪',
    parsed: '已解析',
    processing: '处理中',
    failed: '失败',
    pending: '待处理',
  }
  return labels[status] || status
}

function getChangeStatusLabel(status: string) {
  const labels: Record<string, string> = {
    draft: '草稿',
    open: '待处理',
    approved: '已批准',
    rejected: '已拒绝',
    synced: '已同步',
    closed: '已关闭',
  }
  return labels[status] || status
}

function getLaunchBlueprintLabel(blueprintKey: string) {
  const labels: Record<string, string> = {
    'consulting-discovery': '咨询调研与需求澄清',
    'product-delivery': '产品需求到交付',
    'system-modernization': '系统升级与迁移',
  }
  return labels[blueprintKey] || blueprintKey
}

export default function ProjectDetailPage({ params }: ProjectPageProps) {
  const { projectId } = use(params)
  const router = useRouter()
  const queryClient = useQueryClient()
  const { addToast } = useToast()

  const { data: project, isLoading: projectLoading } = useQuery<Project>({
    queryKey: ['project', projectId],
    queryFn: () => projectsApi.get(projectId),
  })

  const { data: deliveryWorkbench, isLoading: workbenchLoading } = useQuery({
    queryKey: ['project-delivery-workbench', projectId],
    queryFn: () => projectsApi.getDeliveryWorkbench(projectId),
    enabled: Boolean(projectId),
  })

  const { data: launchResult } = useQuery({
    queryKey: ['project-launch-plan', projectId],
    queryFn: () => projectsApi.getLaunchPlan(projectId),
    enabled: Boolean(projectId),
    retry: false,
  })

  const retryLaunchMutation = useMutation({
    mutationFn: () => projectsApi.retryLaunch(projectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project-launch-plan', projectId] })
      queryClient.invalidateQueries({ queryKey: ['project-delivery-workbench', projectId] })
      addToast({ title: '启动计划已重新检查', description: '缺失的启动资产已按蓝图补齐。' })
    },
    onError: (retryError: Error) => {
      addToast({ title: '启动计划重试失败', description: retryError.message, variant: 'destructive' })
    },
  })

  if (projectLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-slate-500 dark:text-slate-400">正在加载项目...</div>
      </div>
    )
  }

  if (!project) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <div className="text-red-500">未找到项目</div>
        <Button variant="outline" onClick={() => router.push('/projects')}>
          <ArrowLeft className="mr-2 h-4 w-4" />
          返回项目
        </Button>
      </div>
    )
  }

  const totals = deliveryWorkbench?.totals
  const traceability = deliveryWorkbench?.traceability
  const deliveryChain = deliveryWorkbench?.delivery_chain || []
  const reviewQueue = deliveryWorkbench?.review_queue || []
  const risks = deliveryWorkbench?.risks || []
  const nextActions = deliveryWorkbench?.next_actions || []
  const recentDocuments = deliveryWorkbench?.recent_documents || []
  const readySourceFiles = deliveryWorkbench?.source_file_status_counts.ready || 0
  const failedSourceFiles = deliveryWorkbench?.source_file_status_counts.failed || 0
  const documentStatusEntries = Object.entries(deliveryWorkbench?.document_status_counts || {})
  const sourceFileStatusEntries = Object.entries(deliveryWorkbench?.source_file_status_counts || {})
  const changeStatusEntries = Object.entries(deliveryWorkbench?.change_status_counts || {})
  const completedDeliverySteps = deliveryChain.filter((item) =>
    !item.missing && ['published', 'approved'].includes(item.status)
  ).length
  const deliveryProgress = deliveryChain.length > 0
    ? Math.round((completedDeliverySteps / deliveryChain.length) * 100)
    : 0

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="sm" onClick={() => router.push('/projects')}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-indigo-100 p-2 dark:bg-indigo-900">
              <FolderKanban className="h-6 w-6 text-indigo-600 dark:text-indigo-400" />
            </div>
            <div>
              <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">{project.name}</h1>
              <p className="text-sm text-slate-500 dark:text-slate-400">{project.description || '暂无描述'}</p>
            </div>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" asChild>
            <Link href={`/projects/${projectId}/plan`}>
              <CalendarRange className="mr-2 h-4 w-4" />
              交付计划
            </Link>
          </Button>
          <Button variant="outline" asChild>
            <Link href={`/projects/${projectId}/acceptance`}>
              <CheckCircle2 className="mr-2 h-4 w-4" />
              客户验收
            </Link>
          </Button>
          <Button variant="outline" asChild>
            <Link href={`/projects/${projectId}/settings`}>
              <Settings className="mr-2 h-4 w-4" />
              项目设置
            </Link>
          </Button>
        </div>
      </div>

      {launchResult && (
        <Card data-testid="project-launch-status">
          <CardHeader>
            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div>
                <CardTitle>项目启动状态</CardTitle>
                <CardDescription>
                  {getLaunchBlueprintLabel(launchResult.plan.blueprint_key)}
                  {' · '}
                  第 {launchResult.plan.attempt_count} 次检查
                </CardDescription>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant={launchResult.plan.status === 'ready' ? 'default' : 'secondary'}>
                  {launchResult.plan.status === 'ready' ? '已就绪' : launchResult.plan.status === 'failed' ? '启动失败' : '需要关注'}
                </Badge>
                <Button
                  data-testid="retry-project-launch"
                  variant="outline"
                  size="sm"
                  disabled={retryLaunchMutation.isPending}
                  onClick={() => retryLaunchMutation.mutate()}
                >
                  <RefreshCw className={`mr-2 h-4 w-4 ${retryLaunchMutation.isPending ? 'animate-spin' : ''}`} />
                  重新检查
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div data-testid="project-launch-checks" className="grid gap-2 md:grid-cols-3">
              {launchResult.plan.checks_json.map((check) => (
                <div key={check.key} className="flex items-center gap-2 rounded-md border p-3 text-sm">
                  {check.status === 'passed'
                    ? <CheckCircle2 className="h-4 w-4 text-green-600" />
                    : <AlertTriangle className="h-4 w-4 text-amber-600" />}
                  <span>{check.label}</span>
                </div>
              ))}
            </div>
            {launchResult.plan.error_message && (
              <p className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                {launchResult.plan.error_message}
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              {(launchResult.plan.results_json?.next_actions || []).map((action: string) => (
                <Badge key={action} variant="outline">{action}</Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Quick Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center gap-3">
              <FileText className="h-5 w-5 text-slate-400" />
              <div>
                <p className="text-2xl font-bold">{totals?.documents ?? project.documentCount ?? 0}</p>
                <p className="text-xs text-slate-500">文档</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center gap-3">
              <Users className="h-5 w-5 text-slate-400" />
              <div>
                <p className="text-2xl font-bold">{totals?.members ?? '-'}</p>
                <p className="text-xs text-slate-500">成员</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center gap-3">
              <BrainCircuit className="h-5 w-5 text-slate-400" />
              <div>
                <p className="text-2xl font-bold">{totals?.knowledge_entries ?? '-'}</p>
                <p className="text-xs text-slate-500">知识节点</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center gap-3">
              <GitBranch className="h-5 w-5 text-slate-400" />
              <div>
                <p className="text-2xl font-bold">{totals?.change_requests ?? '-'}</p>
                <p className="text-xs text-slate-500">变更请求</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Navigation Tabs */}
      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList>
          <TabsTrigger value="overview">概览</TabsTrigger>
          <TabsTrigger value="documents">
            <FileText className="mr-2 h-4 w-4" />
            文档
          </TabsTrigger>
          <TabsTrigger value="files">
            <FolderKanban className="mr-2 h-4 w-4" />
            文件
          </TabsTrigger>
          <TabsTrigger value="knowledge">
            <BrainCircuit className="mr-2 h-4 w-4" />
            知识
          </TabsTrigger>
          <TabsTrigger value="traceability">
            <Network className="mr-2 h-4 w-4" />
            可追溯性
          </TabsTrigger>
          <TabsTrigger value="changes">
            <GitBranch className="mr-2 h-4 w-4" />
            变更
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-4">
          <Card data-testid="project-delivery-cockpit">
            <CardHeader>
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div>
                  <CardTitle>项目交付驾驶舱</CardTitle>
                  <CardDescription>
                    汇总交付文档、资料、知识、评审、追溯和变更状态，直接给出下一步动作。
                  </CardDescription>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button variant="outline" size="sm" asChild>
                    <Link href={`/projects/${projectId}/documents/generate`}>
                      <Plus className="mr-2 h-4 w-4" />
                      生成文档
                    </Link>
                  </Button>
                  <Button variant="outline" size="sm" asChild>
                    <Link href={`/projects/${projectId}/traceability`}>
                      <Network className="mr-2 h-4 w-4" />
                      追溯分析
                    </Link>
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-5">
              {workbenchLoading ? (
                <div className="rounded-md border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-slate-700">
                  正在加载交付驾驶舱...
                </div>
              ) : (
                <>
                  <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
                    <div className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
                      <div data-testid="delivery-kpi-documents" className="text-xl font-semibold text-slate-900 dark:text-white">
                        {totals?.documents ?? 0}
                      </div>
                      <p className="mt-1 text-xs text-slate-500">项目文档</p>
                    </div>
                    <div className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
                      <div className="text-xl font-semibold text-slate-900 dark:text-white">{totals?.source_files ?? 0}</div>
                      <p className="mt-1 text-xs text-slate-500">项目资料</p>
                    </div>
                    <div className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
                      <div data-testid="delivery-kpi-knowledge" className="text-xl font-semibold text-slate-900 dark:text-white">
                        {totals?.knowledge_entries ?? 0}
                      </div>
                      <p className="mt-1 text-xs text-slate-500">知识节点</p>
                    </div>
                    <div className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
                      <div className="text-xl font-semibold text-slate-900 dark:text-white">{traceability?.active_references ?? 0}</div>
                      <p className="mt-1 text-xs text-slate-500">正式引用</p>
                    </div>
                    <div className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
                      <div data-testid="delivery-kpi-pending-sync" className="text-xl font-semibold text-slate-900 dark:text-white">
                        {traceability?.pending_sync_proposals ?? 0}
                      </div>
                      <p className="mt-1 text-xs text-slate-500">待同步</p>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.2fr_0.8fr]">
                    <div
                      data-testid="delivery-status-matrix"
                      className="rounded-md border border-slate-200 p-4 dark:border-slate-700"
                    >
                      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                        <div>
                          <h2 className="text-sm font-semibold text-slate-900 dark:text-white">交付状态矩阵</h2>
                          <p className="mt-1 text-xs text-slate-500">
                            文档、资料和变更的状态集中在同一处，便于定位交付阻塞。
                          </p>
                        </div>
                        <Badge variant="outline">交付闭环 {deliveryProgress}%</Badge>
                      </div>
                      <div className="mt-4 grid gap-3 md:grid-cols-3">
                        <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
                          <p className="text-xs font-medium text-slate-500">文档状态</p>
                          <div className="mt-2 space-y-2">
                            {documentStatusEntries.length === 0 ? (
                              <p className="text-sm text-slate-500">暂无文档</p>
                            ) : (
                              documentStatusEntries.map(([status, count]) => (
                                <div
                                  key={status}
                                  data-testid={`delivery-status-${status}`}
                                  className="flex items-center justify-between gap-2 text-sm"
                                >
                                  <span className="text-slate-700 dark:text-slate-200">{getDocumentStatusLabel(status)}</span>
                                  <span className="font-semibold text-slate-900 dark:text-white">{count}</span>
                                </div>
                              ))
                            )}
                          </div>
                        </div>
                        <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
                          <p className="text-xs font-medium text-slate-500">资料状态</p>
                          <div className="mt-2 space-y-2">
                            {sourceFileStatusEntries.length === 0 ? (
                              <p className="text-sm text-slate-500">暂无资料</p>
                            ) : (
                              sourceFileStatusEntries.map(([status, count]) => (
                                <div
                                  key={status}
                                  data-testid={`delivery-source-${status}`}
                                  className="flex items-center justify-between gap-2 text-sm"
                                >
                                  <span className="text-slate-700 dark:text-slate-200">{getSourceFileStatusLabel(status)}</span>
                                  <span className="font-semibold text-slate-900 dark:text-white">{count}</span>
                                </div>
                              ))
                            )}
                          </div>
                        </div>
                        <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
                          <p className="text-xs font-medium text-slate-500">变更状态</p>
                          <div className="mt-2 space-y-2">
                            {changeStatusEntries.length === 0 ? (
                              <p className="text-sm text-slate-500">暂无变更</p>
                            ) : (
                              changeStatusEntries.map(([status, count]) => (
                                <div key={status} className="flex items-center justify-between gap-2 text-sm">
                                  <span className="text-slate-700 dark:text-slate-200">{getChangeStatusLabel(status)}</span>
                                  <span className="font-semibold text-slate-900 dark:text-white">{count}</span>
                                </div>
                              ))
                            )}
                          </div>
                        </div>
                      </div>
                    </div>

                    <div className="rounded-md border border-slate-200 p-4 dark:border-slate-700">
                      <h2 className="text-sm font-semibold text-slate-900 dark:text-white">追溯健康度</h2>
                      <div data-testid="delivery-traceability-health" className="mt-4 grid gap-2 text-sm">
                        <div className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2 dark:bg-slate-900">
                          <span className="text-slate-600 dark:text-slate-300">正式引用</span>
                          <span className="font-semibold text-slate-900 dark:text-white">{traceability?.active_references ?? 0}</span>
                        </div>
                        <div className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2 dark:bg-slate-900">
                          <span className="text-slate-600 dark:text-slate-300">影响分析</span>
                          <span className="font-semibold text-slate-900 dark:text-white">{traceability?.open_impact_analyses ?? 0}</span>
                        </div>
                        <div className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2 dark:bg-slate-900">
                          <span className="text-slate-600 dark:text-slate-300">待同步 {traceability?.pending_sync_proposals ?? 0}</span>
                          <Button variant="ghost" size="sm" asChild>
                            <Link href={`/projects/${projectId}/traceability`}>处理</Link>
                          </Button>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.25fr_0.75fr]">
                    <div className="space-y-5">
                      <section>
                        <div className="mb-3 flex items-center justify-between">
                          <h2 className="text-sm font-semibold text-slate-900 dark:text-white">交付链路</h2>
                          <Badge variant="outline">资料就绪 {readySourceFiles} · 失败 {failedSourceFiles}</Badge>
                        </div>
                        <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                          {deliveryChain.map((item) => (
                            <Link
                              key={item.doc_type}
                              data-testid={`delivery-chain-${item.doc_type}`}
                              href={item.document_id ? `/projects/${projectId}/documents/${item.document_id}` : `/projects/${projectId}/documents/generate`}
                              className="flex items-center justify-between gap-3 rounded-md border border-slate-200 p-3 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
                            >
                              <div className="flex min-w-0 items-center gap-3">
                                {item.missing ? (
                                  <CircleDashed className="h-4 w-4 shrink-0 text-slate-400" />
                                ) : (
                                  <CheckCircle2 className="h-4 w-4 shrink-0 text-green-500" />
                                )}
                                <div className="min-w-0">
                                  <p className="truncate text-sm font-medium text-slate-900 dark:text-white">{item.label}</p>
                                  <p className="truncate text-xs text-slate-500">
                                    {item.title || '尚未生成'}{item.version ? ` · v${item.version}` : ''}
                                  </p>
                                </div>
                              </div>
                              <Badge className={`shrink-0 text-xs ${getStatusBadgeClass(item.status)}`}>
                                {item.missing ? '待生成' : getDocumentStatusLabel(item.status)}
                              </Badge>
                              <Badge data-testid={`delivery-stage-${item.doc_type}`} variant="outline" className="shrink-0 text-xs">
                                {item.missing ? '缺口' : '已纳入交付链路'}
                              </Badge>
                            </Link>
                          ))}
                        </div>
                      </section>

                      <section>
                        <div className="mb-3 flex items-center justify-between">
                          <h2 className="text-sm font-semibold text-slate-900 dark:text-white">最近文档</h2>
                          <Button variant="ghost" size="sm" asChild>
                            <Link href={`/projects/${projectId}/documents`}>查看全部</Link>
                          </Button>
                        </div>
                        {recentDocuments.length === 0 ? (
                          <div className="rounded-md border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-slate-700">
                            暂无文档，先生成 URS 或 BRD 建立交付主线。
                          </div>
                        ) : (
                          <div className="space-y-2">
                            {recentDocuments.slice(0, 5).map((doc) => (
                              <Link
                                key={doc.id}
                                href={`/projects/${projectId}/documents/${doc.id}`}
                                className="flex items-center justify-between gap-3 rounded-md border border-slate-200 p-3 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
                              >
                                <div className="min-w-0">
                                  <p className="truncate text-sm font-medium text-slate-900 dark:text-white">{doc.title}</p>
                                  <p className="text-xs text-slate-500">
                                    {getDocumentTypeLabel(doc.doc_type)} · 更新于 {formatDistanceToNow(doc.updated_at)}
                                  </p>
                                </div>
                                <Badge className={`shrink-0 text-xs ${getStatusBadgeClass(doc.status)}`}>
                                  {getDocumentStatusLabel(doc.status)}
                                </Badge>
                              </Link>
                            ))}
                          </div>
                        )}
                      </section>
                    </div>

                    <div className="space-y-5">
                      <section>
                        <h2 className="mb-3 text-sm font-semibold text-slate-900 dark:text-white">下一步动作</h2>
                        <div data-testid="delivery-action-plan" className="space-y-2">
                          {nextActions.map((action) => (
                            <Link
                              key={action.code}
                              data-testid={`next-action-${action.code}`}
                              href={action.href}
                              className="block rounded-md border border-slate-200 p-3 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
                            >
                              <div className="flex items-center justify-between gap-3">
                                <p className="text-sm font-medium text-slate-900 dark:text-white">{action.label}</p>
                                <Badge className={`text-xs ${getActionBadgeClass(action.priority)}`}>{getActionLabel(action)}</Badge>
                              </div>
                              <p className="mt-2 text-xs text-slate-500">{action.description}</p>
                            </Link>
                          ))}
                        </div>
                      </section>

                      <section>
                        <h2 className="mb-3 text-sm font-semibold text-slate-900 dark:text-white">评审队列</h2>
                        <div data-testid="review-queue-list" className="space-y-2">
                          {reviewQueue.length === 0 ? (
                            <div className="rounded-md border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-slate-700">
                              当前没有待评审文档
                            </div>
                          ) : (
                            reviewQueue.map((doc) => (
                              <Link
                                key={doc.id}
                                href={`/projects/${projectId}/documents/${doc.id}`}
                                className="flex items-center justify-between gap-3 rounded-md border border-slate-200 p-3 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
                              >
                                <div className="min-w-0">
                                  <p className="truncate text-sm font-medium text-slate-900 dark:text-white">{doc.title}</p>
                                  <p className="text-xs text-slate-500">{getDocumentTypeLabel(doc.doc_type)}</p>
                                </div>
                                <Badge className={`shrink-0 text-xs ${getStatusBadgeClass(doc.status)}`}>
                                  {getDocumentStatusLabel(doc.status)}
                                </Badge>
                              </Link>
                            ))
                          )}
                        </div>
                      </section>

                      <section>
                        <h2 className="mb-3 text-sm font-semibold text-slate-900 dark:text-white">风险提示</h2>
                        <div data-testid="delivery-risk-list" className="space-y-2">
                          {risks.length === 0 ? (
                            <div className="rounded-md border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-slate-700">
                              当前未识别到阻塞风险
                            </div>
                          ) : (
                            risks.map((risk) => (
                              <Link
                                key={risk.code}
                                href={risk.target_href}
                                className={`flex gap-3 rounded-md border p-3 ${getRiskBadgeClass(risk.severity)}`}
                              >
                                <div className="mt-0.5 shrink-0">{getRiskIcon(risk)}</div>
                                <div>
                                  <p className="text-sm font-medium">{risk.title}</p>
                                  <p className="mt-1 text-xs opacity-80">{risk.description}</p>
                                </div>
                              </Link>
                            ))
                          )}
                        </div>
                      </section>
                    </div>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle>团队协作</CardTitle>
                <Button variant="ghost" size="sm" asChild>
                  <Link href={`/projects/${projectId}/members`}>管理</Link>
                </Button>
              </CardHeader>
              <CardContent>
                <div className="flex items-center justify-between rounded-md border border-slate-200 p-4 dark:border-slate-700">
                  <div>
                    <p className="text-sm font-medium text-slate-900 dark:text-white">{totals?.members ?? 0} 位成员</p>
                    <p className="mt-1 text-xs text-slate-500">维护顾问、评审和项目成员权限。</p>
                  </div>
                  <Users className="h-5 w-5 text-slate-400" />
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>快捷入口</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-2">
                  <Button variant="outline" className="justify-start" asChild>
                    <Link href={`/projects/${projectId}/documents/generate`}>
                      <Plus className="mr-2 h-4 w-4" />
                      生成文档
                    </Link>
                  </Button>
                  <Button variant="outline" className="justify-start" asChild>
                    <Link href={`/projects/${projectId}/files`}>
                      <FolderKanban className="mr-2 h-4 w-4" />
                      上传资料
                    </Link>
                  </Button>
                  <Button variant="outline" className="justify-start" asChild>
                    <Link href={`/projects/${projectId}/traceability`}>
                      <Network className="mr-2 h-4 w-4" />
                      追溯分析
                    </Link>
                  </Button>
                  <Button variant="outline" className="justify-start" asChild>
                    <Link href={`/projects/${projectId}/changes`}>
                      <GitBranch className="mr-2 h-4 w-4" />
                      变更处理
                    </Link>
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="documents">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <div>
                <CardTitle>文档</CardTitle>
                <CardDescription>管理项目文档</CardDescription>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" asChild>
                  <Link href={`/projects/${projectId}/documents/generate`}>
                    <Plus className="mr-2 h-4 w-4" />
                    生成文档
                  </Link>
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-center py-12 text-slate-500">
                <FileText className="mx-auto h-12 w-12 text-slate-300" />
                <p className="mt-4 text-lg font-medium">项目文档</p>
                <p className="mt-2 text-sm">查看当前项目的全部文档</p>
                <Button className="mt-4" asChild>
                  <Link href={`/projects/${projectId}/documents`}>查看文档</Link>
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="files">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <div>
                <CardTitle>文件</CardTitle>
                <CardDescription>管理项目文件</CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-center py-12 text-slate-500">
                <FolderKanban className="mx-auto h-12 w-12 text-slate-300" />
                <p className="mt-4 text-lg font-medium">文件管理</p>
                <p className="mt-2 text-sm">上传和管理项目资料</p>
                <Button className="mt-4" asChild>
                  <Link href={`/projects/${projectId}/files`}>管理文件</Link>
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="knowledge">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <div>
                <CardTitle>知识库</CardTitle>
                <CardDescription>项目知识和关联关系</CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-center py-12 text-slate-500">
                <BrainCircuit className="mx-auto h-12 w-12 text-slate-300" />
                <p className="mt-4 text-lg font-medium">知识图谱</p>
                <p className="mt-2 text-sm">探索项目知识关联</p>
                <Button className="mt-4" asChild>
                  <Link href={`/projects/${projectId}/knowledge`}>打开知识图谱</Link>
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="traceability">
          <Card>
            <CardHeader>
              <CardTitle>可追溯矩阵</CardTitle>
              <CardDescription>跟踪文档之间的关系</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="text-center py-12 text-slate-500">
                <Network className="mx-auto h-12 w-12 text-slate-300" />
                <p className="mt-4 text-lg font-medium">可追溯矩阵</p>
                <p className="mt-2 text-sm">查看文档链路</p>
                <Button className="mt-4" asChild>
                  <Link href={`/projects/${projectId}/traceability`}>查看矩阵</Link>
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="changes">
          <Card>
            <CardHeader>
              <CardTitle>变更请求</CardTitle>
              <CardDescription>跟踪和管理变更</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="text-center py-12 text-slate-500">
                <GitBranch className="mx-auto h-12 w-12 text-slate-300" />
                <p className="mt-4 text-lg font-medium">变更请求</p>
                <p className="mt-2 text-sm">管理项目变更</p>
                <Button className="mt-4" asChild>
                  <Link href={`/projects/${projectId}/changes`}>查看变更</Link>
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
