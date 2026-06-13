'use client'

import { use, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ClipboardList,
  Clock3,
  Database,
  Download,
  FileText,
  GitBranch,
  Layers3,
  MessageSquareText,
  PackageCheck,
  PackagePlus,
  Plus,
  Search,
  ShieldCheck,
  Users,
  Workflow,
  XCircle,
} from 'lucide-react'
import {
  documentsApi,
  exportsApi,
  projectsApi,
  type Document,
  type ProjectDeliveryChainItem,
  type ProjectDocumentQualityGate,
  type ProjectDocumentWorkflowLane,
} from '@/lib/api-client'
import { getDocumentStatusLabel, getDocumentTypeLabel } from '@/lib/document-labels'
import { formatDistanceToNow } from '@/lib/utils'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useToast } from '@/components/ui/toast'

interface DocumentsPageProps {
  params: Promise<{ projectId: string }>
}

const DELIVERY_TYPES = [
  'urs',
  'brd',
  'prd',
  'user_story',
  'detailed_design',
  'interface',
  'data_dictionary',
  'test_case',
]

const LANE_ICONS: Record<string, typeof Workflow> = {
  authoring: MessageSquareText,
  review: ShieldCheck,
  release: CheckCircle2,
  traceability: GitBranch,
  export: Download,
}

function chainTone(item: ProjectDeliveryChainItem) {
  if (item.missing) return 'border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100'
  if (item.status === 'published' || item.status === 'approved') {
    return 'border-emerald-300 bg-emerald-50 text-emerald-950 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-100'
  }
  return 'border-sky-300 bg-sky-50 text-sky-950 dark:border-sky-800 dark:bg-sky-950/40 dark:text-sky-100'
}

function gateTone(gate: ProjectDocumentQualityGate) {
  if (gate.status === 'blocked') return 'border-red-300 bg-red-50 text-red-950 dark:border-red-900 dark:bg-red-950/40 dark:text-red-100'
  if (gate.status === 'warning') return 'border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100'
  return 'border-emerald-300 bg-emerald-50 text-emerald-950 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-100'
}

function gateIcon(gate: ProjectDocumentQualityGate) {
  if (gate.status === 'blocked') return <XCircle className="h-4 w-4" />
  if (gate.status === 'warning') return <AlertTriangle className="h-4 w-4" />
  return <CheckCircle2 className="h-4 w-4" />
}

function riskTone(severity: string) {
  if (severity === 'high') return 'border-red-300 bg-red-50 text-red-950 dark:border-red-900 dark:bg-red-950/40 dark:text-red-100'
  if (severity === 'medium') return 'border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100'
  return 'border-slate-300 bg-slate-50 text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200'
}

function documentHref(projectId: string, item: ProjectDeliveryChainItem) {
  if (item.document_id) return `/projects/${projectId}/documents/${item.document_id}`
  return `/projects/${projectId}/documents/generate?docType=${item.doc_type}`
}

function progressPercent(value?: number) {
  return Math.max(0, Math.min(100, Math.round((value || 0) * 100)))
}

function workflowLaneDescription(lane: ProjectDocumentWorkflowLane) {
  if (lane.key === 'authoring') return `${lane.attention_count} 个对话会话可继续`
  if (lane.key === 'review') return `${lane.attention_count} 个评审或评论事项待处理`
  if (lane.key === 'release') return `${lane.attention_count} 类核心文档尚未发布`
  if (lane.key === 'traceability') return `${lane.attention_count} 个追溯影响需要确认`
  if (lane.key === 'export') return `${lane.attention_count} 个导出阻塞项`
  return `${lane.attention_count} 个待处理事项`
}

function controlStageTone(stage: string) {
  if (stage === 'published' || stage === 'release_ready') {
    return 'border-emerald-200 bg-emerald-50 text-emerald-950 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-100'
  }
  if (stage === 'review' || stage === 'authoring') {
    return 'border-sky-200 bg-sky-50 text-sky-950 dark:border-sky-900 dark:bg-sky-950/40 dark:text-sky-100'
  }
  if (stage === 'missing') {
    return 'border-amber-200 bg-amber-50 text-amber-950 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100'
  }
  return 'border-red-200 bg-red-50 text-red-950 dark:border-red-900 dark:bg-red-950/40 dark:text-red-100'
}

function coverageTone(status?: string) {
  if (status === 'ready') return 'border-emerald-200 bg-emerald-50 text-emerald-950 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-100'
  if (status === 'warning') return 'border-amber-200 bg-amber-50 text-amber-950 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100'
  return 'border-red-200 bg-red-50 text-red-950 dark:border-red-900 dark:bg-red-950/40 dark:text-red-100'
}

export default function DocumentsPage({ params }: DocumentsPageProps) {
  const { projectId } = use(params)
  const queryClient = useQueryClient()
  const { addToast } = useToast()
  const [selectedType, setSelectedType] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedPackageDocs, setSelectedPackageDocs] = useState<string[] | null>(null)

  const workbenchQuery = useQuery({
    queryKey: ['project-document-workbench', projectId],
    queryFn: () => projectsApi.getDocumentWorkbench(projectId),
  })

  const documentsQuery = useQuery({
    queryKey: ['project-documents', projectId, selectedType],
    queryFn: () => documentsApi.list({ projectId, docType: selectedType || undefined, includePlaceholders: true }),
  })

  const workbench = workbenchQuery.data
  const documents = documentsQuery.data?.items || []
  const readiness = workbench?.readiness
  const activeSessions = workbench?.active_sessions || []
  const qualityGates = workbench?.quality_gates || []
  const workflowLanes = workbench?.workflow_lanes || []
  const templateCoverage = workbench?.template_coverage || []
  const exportPackage = workbench?.export_package
  const collaborationSummary = workbench?.collaboration_summary
  const packageManifest = useMemo(() => workbench?.package_manifest ?? [], [workbench?.package_manifest])
  const traceabilityActions = useMemo(() => workbench?.traceability_actions ?? [], [workbench?.traceability_actions])
  const collaborationActions = useMemo(() => workbench?.collaboration_actions ?? [], [workbench?.collaboration_actions])
  const controlMatrix = useMemo(() => workbench?.control_matrix ?? [], [workbench?.control_matrix])
  const sourceCoverage = workbench?.source_coverage
  const reviewQueue = workbench?.review_queue || []
  const nextOperationalActions = useMemo(
    () => [...collaborationActions, ...(workbench?.next_actions || [])].slice(0, 5),
    [collaborationActions, workbench?.next_actions],
  )
  const packageReadyCount = packageManifest.filter((item) => item.release_ready).length
  const packageRequiredCount = exportPackage?.required_document_count || packageManifest.length || DELIVERY_TYPES.length
  const packageBlockedCount = packageManifest.filter((item) => item.required && !item.release_ready).length
  const reviewAttentionCount =
    (collaborationSummary?.review_queue_count || 0) + (collaborationSummary?.unresolved_comment_count || 0)

  const chain = useMemo(() => {
    const byType = new Map((workbench?.delivery_chain || []).map((item) => [item.doc_type, item]))
    return DELIVERY_TYPES.map((docType) => byType.get(docType)).filter(Boolean) as ProjectDeliveryChainItem[]
  }, [workbench])

  const completion = chain.length
    ? Math.round((chain.reduce((sum, item) => sum + (item.completion_ratio || 0), 0) / chain.length) * 100)
    : 0

  const filteredDocuments = documents.filter((doc: Document) => {
    if (!searchQuery) return true
    const term = searchQuery.toLowerCase()
    return doc.name.toLowerCase().includes(term) || (doc.content || '').toLowerCase().includes(term)
  })

  const defaultPackageDocumentIds = useMemo(
    () => packageManifest
      .filter((item) => item.document_id && item.included)
      .map((item) => item.document_id as string),
    [packageManifest],
  )

  const effectivePackageDocumentIds = selectedPackageDocs ?? defaultPackageDocumentIds

  const packageMutation = useMutation({
    mutationFn: () => exportsApi.createProjectPackage({
      project_id: projectId,
      document_ids: effectivePackageDocumentIds,
      title: `项目文档交付包 - ${new Date().toLocaleDateString('zh-CN')}`,
      include_drafts: false,
      include_manifest: true,
      variables: {
        source: 'project_documents_final_workbench',
      },
    }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['project-document-workbench', projectId] })
      addToast({
        title: '交付包任务已创建',
        description: `任务 ${result.job_id} 当前状态：${result.status}`,
      })
    },
    onError: (error: Error) => {
      addToast({ title: '交付包创建失败', description: error.message, variant: 'destructive' })
    },
  })

  const togglePackageDocument = (documentId: string) => {
    const current = selectedPackageDocs ?? defaultPackageDocumentIds
    setSelectedPackageDocs(
      current.includes(documentId)
        ? current.filter((id) => id !== documentId)
        : [...current, documentId],
    )
  }

  if (workbenchQuery.isLoading || documentsQuery.isLoading) {
    return <div className="py-16 text-center text-sm text-slate-500">正在加载项目文档工作台...</div>
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 data-testid="project-document-workbench-heading" className="text-2xl font-semibold text-slate-900 dark:text-white">
            项目文档工作台
          </h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            从资料、模板、对话式编写、评审、追溯到导出包，统一管理项目交付文档。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild>
            <Link href={`/projects/${projectId}/documents/generate`}>
              <MessageSquareText className="mr-2 h-4 w-4" />
              对话式编写
            </Link>
          </Button>
          <Button variant="outline" asChild>
            <Link href={`/projects/${projectId}/traceability`}>
              <GitBranch className="mr-2 h-4 w-4" />
              追溯矩阵
            </Link>
          </Button>
          <Button variant="outline" asChild>
            <Link href="/exports">
              <Download className="mr-2 h-4 w-4" />
              导出中心
            </Link>
          </Button>
          <Button variant="outline" asChild>
            <Link href="/collaboration">
              <Users className="mr-2 h-4 w-4" />
              协同评审
            </Link>
          </Button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>交付完整度</CardDescription>
            <CardTitle className="text-3xl">{completion}%</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-slate-500">8 类核心交付物平均完成度</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>文档总数</CardDescription>
            <CardTitle className="text-3xl">{workbench?.totals.documents || 0}</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-slate-500">当前项目已生成文档</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>协同事项</CardDescription>
            <CardTitle className="text-3xl">
              {(collaborationSummary?.review_queue_count || 0) + (collaborationSummary?.unresolved_comment_count || 0)}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-slate-500">评审队列与未解决评论</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>导出包准备</CardDescription>
            <CardTitle className="flex items-center gap-2 text-xl">
              {exportPackage?.ready ? <CheckCircle2 className="h-5 w-5 text-emerald-500" /> : <AlertTriangle className="h-5 w-5 text-amber-500" />}
              {exportPackage?.ready ? '可打包' : '有阻塞'}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-slate-500">{exportPackage?.blockers?.[0] || readiness?.blockers?.[0] || '暂无阻塞项'}</CardContent>
        </Card>
      </div>

      <Card data-testid="document-workflow-lanes">
        <CardHeader>
          <CardTitle>文档工作流分区</CardTitle>
          <CardDescription>把编写、评审、发布、追溯和导出放在同一个可执行视图里。</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            {workflowLanes.map((lane) => {
              const Icon = LANE_ICONS[lane.key] || Workflow
              return (
                <Link
                  key={lane.key}
                  href={lane.href}
                  className="rounded-lg border border-slate-200 p-4 transition hover:border-indigo-300 hover:shadow-sm dark:border-slate-800 dark:hover:border-indigo-700"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <Icon className="h-4 w-4 text-indigo-500" />
                      <p className="font-medium text-slate-900 dark:text-white">{lane.label}</p>
                    </div>
                    <Badge variant={lane.attention_count ? 'destructive' : 'secondary'}>{lane.attention_count}</Badge>
                  </div>
                  <p className="mt-3 text-2xl font-semibold text-slate-900 dark:text-white">{lane.count}</p>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{workflowLaneDescription(lane)}</p>
                </Link>
              )
            })}
          </div>
        </CardContent>
      </Card>

      <Card data-testid="document-quality-gates">
        <CardHeader>
          <CardTitle>质量门禁</CardTitle>
          <CardDescription>发布和导出前需要同时满足资料、交付链、评审、追溯和导出门禁。</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            {qualityGates.map((gate) => (
              <Link key={gate.key} href={gate.target_href} className={`rounded-lg border p-4 ${gateTone(gate)}`}>
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2 font-medium">
                    {gateIcon(gate)}
                    {gate.label}
                  </div>
                  <Badge variant="outline">{gate.score}%</Badge>
                </div>
                <p className="mt-3 text-sm opacity-85">{gate.message}</p>
              </Link>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card data-testid="document-collaboration-review-export-linkage">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Workflow className="h-5 w-5 text-indigo-500" />
            协同评审与交付包联动
          </CardTitle>
          <CardDescription>
            对生成文档同步展示评审状态、责任人/评审人、交付包准备度和下一步动作，避免编写完成后断在评审或导出前。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-4">
            <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-medium text-slate-900 dark:text-white">评审状态</p>
                <Badge variant={reviewAttentionCount ? 'destructive' : 'secondary'}>{reviewAttentionCount}</Badge>
              </div>
              <p className="mt-2 text-xs text-slate-500">
                {reviewQueue.length} 份文档在评审队列，{collaborationSummary?.unresolved_comment_count || 0} 条评论未关闭
              </p>
            </div>
            <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-medium text-slate-900 dark:text-white">责任人/评审人</p>
                <Badge variant="outline">{collaborationSummary?.member_count || workbench?.totals.members || 0} 人</Badge>
              </div>
              <p className="mt-2 text-xs text-slate-500">
                协同评审中心承接评审分派、评论关闭和变更责任归口
              </p>
            </div>
            <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-medium text-slate-900 dark:text-white">交付包准备度</p>
                <Badge variant={exportPackage?.ready ? 'secondary' : 'destructive'}>
                  {packageReadyCount}/{packageRequiredCount}
                </Badge>
              </div>
              <p className="mt-2 text-xs text-slate-500">
                {packageBlockedCount ? `${packageBlockedCount} 类交付文档仍需处理` : '核心交付文档已满足打包条件'}
              </p>
            </div>
            <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-medium text-slate-900 dark:text-white">下一步动作</p>
                <Badge variant="outline">{nextOperationalActions.length}</Badge>
              </div>
              <p className="mt-2 text-xs text-slate-500">
                优先处理高优先级评审、追溯同步和缺失交付物
              </p>
            </div>
          </div>

          <div className="grid gap-3 lg:grid-cols-[1fr_1fr]">
            <div className="space-y-2">
              <p className="text-xs font-medium uppercase text-slate-500">待评审/待归口文档</p>
              {reviewQueue.length === 0 ? (
                <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-100">
                  当前没有待评审文档
                </div>
              ) : (
                reviewQueue.slice(0, 3).map((item) => (
                  <Link
                    key={item.id}
                    href={`/projects/${projectId}/documents/${item.id}`}
                    className="flex items-center justify-between gap-3 rounded-md border border-slate-200 p-3 text-sm hover:border-indigo-300 dark:border-slate-800 dark:hover:border-indigo-700"
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-medium text-slate-900 dark:text-white">{item.title}</span>
                      <span className="text-xs text-slate-500">{getDocumentTypeLabel(item.doc_type)} · {getDocumentStatusLabel(item.status)}</span>
                    </span>
                    <Badge variant="outline">v{item.version || 1}</Badge>
                  </Link>
                ))
              )}
            </div>

            <div className="space-y-2">
              <p className="text-xs font-medium uppercase text-slate-500">阻塞与动作闭环</p>
              {(exportPackage?.blockers || []).slice(0, 2).map((blocker) => (
                <div key={blocker} className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
                  {blocker}
                </div>
              ))}
              <div className="grid gap-2 sm:grid-cols-2">
                {nextOperationalActions.map((action) => (
                  <Button key={action.code} variant="outline" size="sm" className="justify-start" asChild>
                    <Link href={'href' in action ? action.href : action.action_href}>
                      <ArrowRight className="mr-2 h-4 w-4" />
                      {action.label}
                    </Link>
                  </Button>
                ))}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-[1.4fr_0.6fr]">
        <Card data-testid="document-control-matrix">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ClipboardList className="h-5 w-5 text-indigo-500" />
              交付控制矩阵
            </CardTitle>
            <CardDescription>逐项显示每类核心文档的阶段、阻塞、资料/模板/追溯状态和下一步动作。</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[860px] text-left text-sm">
                <thead className="text-xs text-slate-500">
                  <tr className="border-b border-slate-200 dark:border-slate-800">
                    <th className="py-2 pr-3 font-medium">文档</th>
                    <th className="py-2 pr-3 font-medium">阶段</th>
                    <th className="py-2 pr-3 font-medium">完成度</th>
                    <th className="py-2 pr-3 font-medium">门禁</th>
                    <th className="py-2 pr-3 font-medium">主要阻塞</th>
                    <th className="py-2 pr-3 font-medium">动作</th>
                  </tr>
                </thead>
                <tbody>
                  {controlMatrix.map((item) => (
                    <tr key={item.doc_type} className="border-b border-slate-100 align-top dark:border-slate-900">
                      <td className="py-3 pr-3">
                        <p className="font-medium text-slate-900 dark:text-white">{getDocumentTypeLabel(item.doc_type)}</p>
                        <p className="mt-1 max-w-[220px] truncate text-xs text-slate-500">{item.title || '尚未生成'}</p>
                      </td>
                      <td className="py-3 pr-3">
                        <Badge className={controlStageTone(item.stage)} variant="outline">{item.stage_label}</Badge>
                      </td>
                      <td className="py-3 pr-3">
                        <div className="w-28">
                          <div className="h-2 rounded-full bg-slate-100 dark:bg-slate-800">
                            <div className="h-2 rounded-full bg-indigo-500" style={{ width: `${progressPercent(item.completion_ratio)}%` }} />
                          </div>
                          <p className="mt-1 text-xs text-slate-500">{progressPercent(item.completion_ratio)}%</p>
                        </div>
                      </td>
                      <td className="py-3 pr-3">
                        <div className="flex flex-wrap gap-1">
                          <Badge variant={item.template_ready ? 'secondary' : 'outline'}>模板</Badge>
                          <Badge variant={item.source_ready ? 'secondary' : 'outline'}>资料</Badge>
                          <Badge variant={item.traceability_gap_count ? 'destructive' : 'secondary'}>追溯 {item.traceability_gap_count}</Badge>
                          <Badge variant={item.release_ready ? 'secondary' : 'outline'}>{item.release_ready ? '可发布' : '待发布'}</Badge>
                        </div>
                      </td>
                      <td className="py-3 pr-3">
                        {item.blockers.length ? (
                          <ul className="max-w-[260px] space-y-1 text-xs text-slate-600 dark:text-slate-300">
                            {item.blockers.slice(0, 2).map((blocker) => <li key={blocker}>{blocker}</li>)}
                          </ul>
                        ) : (
                          <span className="text-xs text-emerald-600 dark:text-emerald-300">无阻塞</span>
                        )}
                      </td>
                      <td className="py-3 pr-3">
                        <div className="flex flex-wrap gap-2">
                          <Button size="sm" asChild>
                            <Link href={item.primary_action.href}>{item.primary_action.label}</Link>
                          </Button>
                          {item.secondary_actions.slice(0, 2).map((action) => (
                            <Button key={action.code} size="sm" variant="outline" asChild>
                              <Link href={action.href}>{action.label}</Link>
                            </Button>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>

        <Card data-testid="document-source-coverage">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Database className="h-5 w-5 text-indigo-500" />
              资料覆盖
            </CardTitle>
            <CardDescription>生成与发布前的项目资料、解析和知识沉淀状态。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className={`rounded-lg border p-4 ${coverageTone(sourceCoverage?.status)}`}>
              <div className="flex items-center justify-between gap-3">
                <p className="font-medium">{sourceCoverage?.label || '缺少资料'}</p>
                <Badge variant="outline">{sourceCoverage?.knowledge_entry_count || 0} 条知识</Badge>
              </div>
              <div className="mt-4 grid grid-cols-3 gap-2 text-xs">
                <div>
                  <p className="opacity-70">资料</p>
                  <p className="text-lg font-semibold">{sourceCoverage?.source_file_total || 0}</p>
                </div>
                <div>
                  <p className="opacity-70">可用</p>
                  <p className="text-lg font-semibold">{sourceCoverage?.ready_source_file_count || 0}</p>
                </div>
                <div>
                  <p className="opacity-70">异常</p>
                  <p className="text-lg font-semibold">{sourceCoverage?.failed_source_file_count || 0}</p>
                </div>
              </div>
            </div>
            {(sourceCoverage?.blockers || []).length ? (
              <div className="space-y-2">
                {sourceCoverage?.blockers.map((blocker) => (
                  <div key={blocker} className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
                    {blocker}
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-100">
                项目资料已经可用于对话式生成、评审和交付追溯。
              </div>
            )}
            <Button variant="outline" className="w-full" asChild>
              <Link href={sourceCoverage?.action_href || `/projects/${projectId}/files`}>打开项目资料</Link>
            </Button>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>交付链路</CardTitle>
          <CardDescription>按上游到下游组织文档，每个节点都可进入对话式编写或正式文档。</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 lg:grid-cols-4">
            {chain.map((item, index) => (
              <div
                key={item.doc_type}
                data-testid={`delivery-chain-${item.doc_type}`}
                className={`rounded-lg border p-4 ${chainTone(item)}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold">{getDocumentTypeLabel(item.doc_type)}</p>
                    <p className="mt-1 text-xs opacity-80">{getDocumentStatusLabel(item.status)}</p>
                  </div>
                  {index < chain.length - 1 && <ArrowRight className="mt-1 hidden h-4 w-4 opacity-60 lg:block" />}
                </div>
                <div className="mt-4 h-2 rounded-full bg-white/60 dark:bg-black/20">
                  <div className="h-2 rounded-full bg-current" style={{ width: `${Math.max(4, progressPercent(item.completion_ratio))}%` }} />
                </div>
                <div className="mt-3 text-xs">
                  上游：{item.upstream_dependencies?.length ? item.upstream_dependencies.map(getDocumentTypeLabel).join('、') : '无'}
                </div>
                {item.blockers?.length ? <div className="mt-2 text-xs">阻塞：{item.blockers[0]}</div> : null}
                <Button size="sm" variant={item.missing ? 'default' : 'outline'} className="mt-4 w-full" asChild>
                  <Link href={documentHref(projectId, item)}>
                    {item.missing ? '开始编写' : '打开文档'}
                  </Link>
                </Button>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <Card>
          <CardHeader>
            <CardTitle>模板与 Skill 覆盖</CardTitle>
            <CardDescription>检查每类交付文档是否已有可复用模板、章节定义和 Skill 绑定。</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 md:grid-cols-2">
              {templateCoverage.map((item) => (
                <Link
                  key={item.doc_type}
                  href={item.action_href}
                  data-testid={`template-coverage-${item.doc_type}`}
                  className="rounded-lg border border-slate-200 p-4 transition hover:border-indigo-300 dark:border-slate-800 dark:hover:border-indigo-700"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-medium text-slate-900 dark:text-white">{getDocumentTypeLabel(item.doc_type)}</p>
                      <p className="mt-1 text-xs text-slate-500">章节 {item.section_count} · Skill {item.skill_binding_count}</p>
                    </div>
                    <Badge variant={item.template_available ? 'secondary' : 'outline'}>
                      {item.template_available ? '已配置' : '待配置'}
                    </Badge>
                  </div>
                </Link>
              ))}
            </div>
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card data-testid="document-export-package">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <PackageCheck className="h-5 w-5 text-indigo-500" />
                交付包
              </CardTitle>
              <CardDescription>汇总核心文档、评审状态、追溯同步和最近导出任务。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-3 gap-2 text-sm">
                <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
                  <p className="text-slate-500">已生成</p>
                  <p className="mt-1 font-semibold text-slate-900 dark:text-white">
                    {exportPackage?.completed_document_count || 0}/{exportPackage?.required_document_count || DELIVERY_TYPES.length}
                  </p>
                </div>
                <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
                  <p className="text-slate-500">已发布</p>
                  <p className="mt-1 font-semibold text-slate-900 dark:text-white">{exportPackage?.approved_or_published_count || 0}</p>
                </div>
                <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
                  <p className="text-slate-500">最近任务</p>
                  <p className="mt-1 font-semibold text-slate-900 dark:text-white">{exportPackage?.latest_job_status || '无'}</p>
                </div>
              </div>
              {(exportPackage?.blockers || []).length ? (
                <div className="space-y-2">
                  {exportPackage?.blockers.map((blocker) => (
                    <div key={blocker} className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
                      {blocker}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-100">
                  当前可以生成项目交付包
                </div>
              )}
              <div className="space-y-2" data-testid="package-manifest-list">
                {packageManifest.map((item) => (
                  <label
                    key={item.doc_type}
                    className="flex items-start gap-3 rounded-md border border-slate-200 p-3 text-sm dark:border-slate-800"
                  >
                    <input
                      type="checkbox"
                      className="mt-1 h-4 w-4"
                      checked={!!item.document_id && effectivePackageDocumentIds.includes(item.document_id)}
                      disabled={!item.document_id}
                      onChange={() => item.document_id && togglePackageDocument(item.document_id)}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block font-medium text-slate-900 dark:text-white">{getDocumentTypeLabel(item.doc_type)}</span>
                      <span className="block text-xs text-slate-500">
                        {item.title || '尚未生成'} · {getDocumentStatusLabel(item.status)}
                      </span>
                      {item.blockers.length > 0 && (
                        <span className="mt-1 block text-xs text-amber-700 dark:text-amber-300">{item.blockers[0]}</span>
                      )}
                    </span>
                    <Badge variant={item.release_ready ? 'secondary' : 'outline'}>
                      {item.release_ready ? '可交付' : '待处理'}
                    </Badge>
                  </label>
                ))}
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <Button
                  data-testid="create-project-package-action"
                  onClick={() => packageMutation.mutate()}
                  disabled={effectivePackageDocumentIds.length === 0 || packageMutation.isPending}
                >
                  <PackagePlus className="mr-2 h-4 w-4" />
                  {packageMutation.isPending ? '正在生成' : '生成交付包'}
                </Button>
                <Button variant="outline" asChild>
                  <Link href={exportPackage?.action_href || '/exports'}>打开导出中心</Link>
                </Button>
              </div>
              <p className="text-xs text-slate-500">
                已选择 {effectivePackageDocumentIds.length} 份文档。默认包含所有已生成的核心交付文档，导出任务会写入清单。
              </p>
            </CardContent>
          </Card>

          <Card data-testid="document-traceability-actions">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <GitBranch className="h-5 w-5 text-indigo-500" />
                追溯待办
              </CardTitle>
              <CardDescription>列出缺失引用和待确认同步，不再只给一个跳转入口。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {traceabilityActions.length === 0 ? (
                <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-100">
                  当前没有追溯待办
                </div>
              ) : (
                traceabilityActions.map((action) => (
                  <Link
                    key={action.code}
                    href={action.action_href}
                    className="block rounded-md border border-slate-200 p-3 text-sm hover:border-indigo-300 dark:border-slate-800 dark:hover:border-indigo-700"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-medium text-slate-900 dark:text-white">
                        {getDocumentTypeLabel(action.source_doc_type)} → {getDocumentTypeLabel(action.target_doc_type)}
                      </span>
                      <Badge variant={action.status === 'pending_sync' ? 'destructive' : 'outline'}>
                        {action.status === 'pending_sync' ? '待同步' : '缺引用'}
                      </Badge>
                    </div>
                    <p className="mt-1 text-xs text-slate-500">{action.reason}</p>
                  </Link>
                ))
              )}
            </CardContent>
          </Card>

          <Card data-testid="document-collaboration-actions">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Users className="h-5 w-5 text-indigo-500" />
                协同待办
              </CardTitle>
              <CardDescription>把会话续写、评审、评论和变更闭环拆成可执行动作。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {collaborationActions.map((action) => (
                <Link
                  key={action.code}
                  href={action.action_href}
                  className="block rounded-md border border-slate-200 p-3 text-sm hover:border-indigo-300 dark:border-slate-800 dark:hover:border-indigo-700"
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-medium text-slate-900 dark:text-white">{action.label}</span>
                    <Badge variant={action.priority === 'high' ? 'destructive' : 'outline'}>{action.count}</Badge>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">{action.description}</p>
                </Link>
              ))}
            </CardContent>
          </Card>

          <Card data-testid="document-collaboration-summary">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Users className="h-5 w-5 text-indigo-500" />
                协同状态
              </CardTitle>
              <CardDescription>把评审、评论、成员和变更事项合并为一个协同入口。</CardDescription>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-2 text-sm">
              <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">成员 {collaborationSummary?.member_count || 0}</div>
              <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">评论 {collaborationSummary?.unresolved_comment_count || 0}</div>
              <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">评审 {collaborationSummary?.review_queue_count || 0}</div>
              <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">变更 {collaborationSummary?.open_change_count || 0}</div>
              <Button className="col-span-2 mt-2" variant="outline" asChild>
                <Link href={collaborationSummary?.action_href || '/collaboration'}>打开协同评审</Link>
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
        <Card>
          <CardHeader>
            <CardTitle>活跃对话会话</CardTitle>
            <CardDescription>继续未完成的章节化文档编写。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3" data-testid="active-generation-sessions">
            {activeSessions.length === 0 ? (
              <div className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
                暂无活跃会话
              </div>
            ) : (
              activeSessions.map((session) => (
                <div key={session.id} className="flex items-center justify-between gap-4 rounded-lg border border-slate-200 p-4 dark:border-slate-800">
                  <div>
                    <p className="font-medium text-slate-900 dark:text-white">{session.title}</p>
                    <p className="mt-1 text-xs text-slate-500">
                      {getDocumentTypeLabel(session.doc_type)} · {session.confirmed_sections}/{session.section_count} 章节已确认
                    </p>
                  </div>
                  <Button size="sm" variant="outline" asChild>
                    <Link href={`/projects/${projectId}/documents/generate?sessionId=${session.id}`}>继续</Link>
                  </Button>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>阻塞与下一步</CardTitle>
            <CardDescription>发布、导出和协同评审前需要处理的事项。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {(workbench?.risks || []).slice(0, 4).map((risk) => (
              <Link key={risk.code} href={risk.target_href} className={`block rounded-lg border p-3 text-sm ${riskTone(risk.severity)}`}>
                <div className="flex items-center gap-2 font-medium">
                  <AlertTriangle className="h-4 w-4" />
                  {risk.title}
                </div>
                <p className="mt-1 text-xs opacity-80">{risk.description}</p>
              </Link>
            ))}
            {(workbench?.risks || []).length === 0 && (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-100">
                当前没有关键阻塞项
              </div>
            )}
            <div className="space-y-2 pt-2">
              {(workbench?.next_actions || []).slice(0, 4).map((action) => (
                <Button key={action.code} variant="outline" className="w-full justify-start" asChild>
                  <Link href={action.href}>
                    <ShieldCheck className="mr-2 h-4 w-4" />
                    {action.label}
                  </Link>
                </Button>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Layers3 className="h-5 w-5 text-indigo-500" />
            文档检索
          </CardTitle>
          <CardDescription>正式文档列表保留为底层清单，便于快速打开、评审和归档。</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="mb-4 grid gap-3 md:grid-cols-[1fr_220px]">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                className="h-10 w-full rounded-md border border-slate-200 bg-white pl-10 pr-4 text-sm text-slate-900 outline-none focus:ring-2 focus:ring-indigo-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                placeholder="搜索文档名称或内容"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
              />
            </div>
            <select
              className="h-10 rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-900 outline-none focus:ring-2 focus:ring-indigo-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
              value={selectedType}
              onChange={(event) => setSelectedType(event.target.value)}
            >
              <option value="">全部文档类型</option>
              {DELIVERY_TYPES.map((docType) => (
                <option key={docType} value={docType}>
                  {getDocumentTypeLabel(docType)}
                </option>
              ))}
            </select>
          </div>

          {filteredDocuments.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 py-10 text-center dark:border-slate-700">
              <FileText className="h-10 w-10 text-slate-300" />
              <p className="mt-3 text-sm text-slate-500">没有匹配的文档</p>
              <Button className="mt-4" asChild>
                <Link href={`/projects/${projectId}/documents/generate`}>
                  <Plus className="mr-2 h-4 w-4" />
                  开始对话式编写
                </Link>
              </Button>
            </div>
          ) : (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {filteredDocuments.map((doc) => (
                <Link
                  key={doc.id}
                  href={`/projects/${projectId}/documents/${doc.id}`}
                  className="rounded-lg border border-slate-200 p-4 transition hover:border-indigo-300 hover:shadow-sm dark:border-slate-800 dark:hover:border-indigo-700"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-medium text-slate-900 dark:text-white">{doc.name}</p>
                      <p className="mt-1 text-xs text-slate-500">{getDocumentTypeLabel(doc.type)}</p>
                    </div>
                    <Badge variant="secondary">{getDocumentStatusLabel(doc.metadata?.status || doc.status || 'draft')}</Badge>
                  </div>
                  <p className="mt-3 line-clamp-2 text-sm text-slate-500">{doc.content || '暂无内容预览'}</p>
                  <div className="mt-4 flex items-center gap-2 text-xs text-slate-400">
                    <Clock3 className="h-3 w-3" />
                    更新于 {formatDistanceToNow(doc.updatedAt)}
                  </div>
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
