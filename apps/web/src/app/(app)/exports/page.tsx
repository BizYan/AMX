'use client'

import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, Archive, CheckCircle2, Download, FileText, Loader2, Package, Plus, RefreshCw, Search, ShieldCheck, Trash2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectOption } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useToast } from '@/components/ui/toast'
import { apiClient, documentsApi, exportsApi, projectsApi, type Document, type ExportJob, type ExportReleaseEvidence, type Project } from '@/lib/api-client'
import {
  hasTemplatePlaceholderBlocker,
  templatePlaceholderSummary,
} from '@/lib/document-template-placeholders'

const DOCUMENT_TYPE_LABELS: Record<string, string> = {
  urs: 'URS',
  brd: 'BRD',
  prd: 'PRD',
  implementation_plan: '实施方案',
  acceptance_report: '验收报告',
  detailed_design: '设计说明',
}

const DOCUMENT_STATUS_LABELS: Record<string, string> = {
  published: '已发布',
  approved: '已批准',
  draft: '待评审',
  review: '评审中',
  pending_review: '待评审',
  placeholder: '占位',
}

const EXPORT_STATUS_LABELS: Record<string, string> = {
  pending: '排队中',
  processing: '处理中',
  completed: '已完成',
  failed: '失败',
}

const FORMAT_LABELS: Record<string, string> = {
  word: 'Word',
  markdown: 'Markdown',
  pptx: 'PPTX',
  project_package: '交付包',
}

const READINESS_STATUS_LABELS: Record<string, string> = {
  ready: '已就绪',
  blocked: '有阻塞',
  missing: '缺失',
}

type ExportVariableRow = {
  id: string
  key: string
  value: string
}

interface CapabilityReadinessItem {
  key: string
  label: string
  status: string
  score: number
  summary: string
  evidence: Record<string, any>
  blockers?: string[]
  recommended_actions?: string[]
}

interface CapabilityReadinessResponse {
  capabilities: CapabilityReadinessItem[]
}

interface CapabilityCommissioningCheck {
  key: string
  capability_key: string
  label: string
  status: string
  summary: string
  evidence: Record<string, any>
  blockers: string[]
  can_run: boolean
  run_status?: string | null
}

interface CapabilityCommissioningResponse {
  checks: CapabilityCommissioningCheck[]
}

function documentTitle(document: Document) {
  return document.name || document.title || document.id
}

function documentTypeLabel(type?: string | null) {
  return DOCUMENT_TYPE_LABELS[(type || '').toLowerCase()] || type || '文档'
}

function documentStatusLabel(status?: string | null) {
  return DOCUMENT_STATUS_LABELS[(status || 'draft').toLowerCase()] || status || '待评审'
}

function isPlaceholder(document: Document) {
  return hasTemplatePlaceholderBlocker(document)
}

function isReviewBlocked(document: Document) {
  return isPlaceholder(document) || document.type === 'implementation_plan'
}

function isExportable(document: Document) {
  return !isPlaceholder(document) && (document.status === 'published' || document.type === 'implementation_plan')
}

function statusBadge(status: ExportJob['status'] | string) {
  if (status === 'completed') {
    return <Badge className="bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300">已完成</Badge>
  }
  if (status === 'failed') {
    return <Badge className="bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300">失败</Badge>
  }
  if (status === 'processing') {
    return (
      <Badge className="gap-1 bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300">
        <Loader2 className="h-3 w-3 animate-spin" />
        处理中
      </Badge>
    )
  }
  return <Badge variant="secondary">{EXPORT_STATUS_LABELS[status] || status}</Badge>
}

function jobTitle(job: ExportJob) {
  return job.title || FORMAT_LABELS[job.export_type] || '导出任务'
}

function artifactFormat(filename: string) {
  const extension = filename.split('.').pop()?.toLowerCase()
  if (extension === 'docx') return 'Word'
  if (extension === 'md') return 'Markdown'
  if (extension === 'pptx') return 'PPTX'
  return extension?.toUpperCase() || '文件'
}

function evidenceNumber(evidence: Record<string, any> | undefined, keys: string[], fallback = 0) {
  if (!evidence) return fallback
  for (const key of keys) {
    const value = Number(evidence[key])
    if (Number.isFinite(value)) return value
  }
  return fallback
}

function releaseGateBadgeVariant(status: string) {
  if (status === 'blocked') return 'destructive' as const
  if (status === 'attention') return 'outline' as const
  return 'secondary' as const
}

function releaseRiskBadgeVariant(severity: string) {
  if (severity === 'critical' || severity === 'high') return 'destructive' as const
  if (severity === 'medium') return 'outline' as const
  return 'secondary' as const
}

function ExportReleaseEvidenceCenter({
  evidence,
  isLoading,
  isError,
  onRetry,
}: {
  evidence?: ExportReleaseEvidence
  isLoading: boolean
  isError: boolean
  onRetry: () => void
}) {
  if (isLoading) {
    return (
      <Card data-testid="export-release-evidence-center">
        <CardContent className="flex items-center gap-2 py-6 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          正在加载发布包证据中心...
        </CardContent>
      </Card>
    )
  }

  if (isError || !evidence) {
    return (
      <Card data-testid="export-release-evidence-center" className="border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/20">
        <CardContent className="flex flex-col gap-3 py-5 text-amber-900 dark:text-amber-100 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="font-semibold">发布包证据中心暂不可用</p>
            <p className="text-sm">导出配置仍可使用，但发布前需要重新拉取后端证据汇总。</p>
          </div>
          <Button variant="outline" size="sm" onClick={onRetry}>重试</Button>
        </CardContent>
      </Card>
    )
  }

  const { summary, release_gate: gate } = evidence
  const metrics = [
    { label: '成功任务', value: summary.completed_jobs, detail: `失败 ${summary.failed_jobs}` },
    { label: '交付包', value: summary.production_package_jobs, detail: '项目级产物' },
    { label: '下载产物', value: summary.artifact_count, detail: '已保留文件' },
    { label: '格式覆盖', value: summary.covered_formats.length, detail: summary.covered_formats.join('、') || '未覆盖' },
  ]

  return (
    <Card data-testid="export-release-evidence-center" className="border-slate-300 dark:border-slate-700">
      <CardHeader>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Package className="h-5 w-5" />
              发布包证据中心
            </CardTitle>
            <CardDescription>由后端汇总核心文档就绪度、导出任务、下载产物、格式覆盖和发布动作。</CardDescription>
          </div>
          <Badge data-testid="export-release-gate" variant={releaseGateBadgeVariant(gate.status)}>{gate.label}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-900/40">
          <p className="font-semibold text-slate-900 dark:text-white">{gate.summary}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {[...gate.blockers, ...gate.warnings].slice(0, 6).map((item) => (
              <Badge key={item} variant={gate.blockers.includes(item) ? 'destructive' : 'outline'}>{item}</Badge>
            ))}
            {gate.blockers.length === 0 && gate.warnings.length === 0 ? <Badge variant="secondary">证据完整</Badge> : null}
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
            <p className="text-sm font-semibold text-slate-900 dark:text-white">发布风险</p>
            {evidence.risk_items.length === 0 ? (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
                没有发布包证据阻断。
              </div>
            ) : (
              evidence.risk_items.slice(0, 4).map((item) => (
                <a key={item.code} href={item.href} className="block rounded-lg border border-slate-200 bg-white p-4 transition hover:border-slate-400 dark:border-slate-800 dark:bg-slate-950/20">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-semibold text-slate-900 dark:text-white">{item.title}</p>
                    <Badge variant={releaseRiskBadgeVariant(item.severity)}>{item.count} 项</Badge>
                  </div>
                  <p className="mt-1 text-sm text-slate-500">{item.detail}</p>
                </a>
              ))
            )}
          </div>
          <div className="space-y-3">
            <p className="text-sm font-semibold text-slate-900 dark:text-white">优先动作</p>
            {evidence.priority_actions.map((action) => (
              <a key={action.code} href={action.href} className="block rounded-lg border border-slate-200 bg-white p-4 transition hover:border-slate-400 dark:border-slate-800 dark:bg-slate-950/20">
                <div className="flex items-center justify-between gap-2">
                  <p className="font-semibold text-slate-900 dark:text-white">{action.title}</p>
                  <Badge variant={releaseRiskBadgeVariant(action.priority)}>{action.priority}</Badge>
                </div>
                <p className="mt-1 text-sm text-slate-500">{action.description}</p>
              </a>
            ))}
          </div>
        </div>

        <div className="space-y-3">
          <p className="text-sm font-semibold text-slate-900 dark:text-white">最近产物</p>
          {evidence.recent_artifacts.length === 0 ? (
            <div className="rounded-lg border border-slate-200 p-4 text-sm text-slate-500 dark:border-slate-800">尚无可下载交付产物。</div>
          ) : (
            <div className="grid gap-2 md:grid-cols-3">
              {evidence.recent_artifacts.slice(0, 6).map((artifact) => (
                <Button key={artifact.id} variant="outline" size="sm" asChild>
                  <a href={exportsApi.downloadArtifact(artifact.id)} target="_blank" rel="noreferrer">
                    <Download className="mr-2 h-4 w-4" />
                    {artifact.filename}
                  </a>
                </Button>
              ))}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

export default function ExportsPage() {
  const queryClient = useQueryClient()
  const { addToast } = useToast()
  const [activeTab, setActiveTab] = useState('package')
  const [selectedProjectId, setSelectedProjectId] = useState('')
  const [packageTitle, setPackageTitle] = useState('')
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([])
  const [formats, setFormats] = useState({ word: true, markdown: true, pptx: false })
  const [variablesSummary, setVariablesSummary] = useState('项目名、版本号、发布日期')
  const [variableRows, setVariableRows] = useState<ExportVariableRow[]>([
    { id: 'client-name', key: '客户名称', value: '' },
    { id: 'release-date', key: '发布日期', value: '' },
    { id: 'project-manager', key: '项目经理', value: '' },
  ])
  const [watermark, setWatermark] = useState('客户评审版')
  const [includeAudit, setIncludeAudit] = useState(false)

  const { data: projectsData, isLoading: projectsLoading } = useQuery({
    queryKey: ['projects-for-export-release-room'],
    queryFn: () => projectsApi.list({ pageSize: 100 }),
  })
  const projects: Project[] = useMemo(() => projectsData?.items || [], [projectsData?.items])

  useEffect(() => {
    if (!selectedProjectId && projects.length > 0) {
      setSelectedProjectId(projects[0].id)
      setPackageTitle(`${projects[0].name} 交付包`)
    }
  }, [projects, selectedProjectId])

  const selectedProject = projects.find((project) => project.id === selectedProjectId)

  const { data: documentsData, isLoading: documentsLoading } = useQuery({
    queryKey: ['release-room-documents', selectedProjectId],
    queryFn: () => documentsApi.list({ projectId: selectedProjectId, pageSize: 100, includePlaceholders: true }),
    enabled: Boolean(selectedProjectId),
  })
  const documents = useMemo(() => documentsData?.items || [], [documentsData?.items])

  const { data: readinessData, isLoading: readinessLoading } = useQuery({
    queryKey: ['export-readiness', selectedProjectId],
    queryFn: () => exportsApi.getReadiness(selectedProjectId),
    enabled: Boolean(selectedProjectId),
  })

  const releaseEvidenceQuery = useQuery({
    queryKey: ['export-release-evidence', selectedProjectId],
    queryFn: () => exportsApi.getReleaseEvidence(selectedProjectId),
    enabled: Boolean(selectedProjectId),
  })

  const { data: jobsData, isLoading: jobsLoading, refetch: refetchJobs } = useQuery({
    queryKey: ['export-jobs'],
    queryFn: () => exportsApi.list(),
  })
  const exportJobs = jobsData || []

  const readinessQuery = useQuery({
    queryKey: ['export-production-readiness'],
    queryFn: () => apiClient.get<CapabilityReadinessResponse>('/ops/capabilities/readiness'),
  })

  const commissioningQuery = useQuery({
    queryKey: ['export-production-commissioning'],
    queryFn: () => apiClient.get<CapabilityCommissioningResponse>('/ops/capabilities/commissioning'),
  })

  const exportableDocuments = useMemo(() => documents.filter(isExportable), [documents])
  const blockers = useMemo(() => documents.filter(isReviewBlocked), [documents])
  const readinessScore = readinessData?.readiness_score ?? 0
  const productionExportableCount = readinessData?.exportable_documents ?? exportableDocuments.length
  const productionBlockedCount = readinessData?.blocked_documents ?? blockers.length
  const displayedBlockers = readinessData?.blockers ?? blockers.map((document) => {
    const unresolvedTemplateSummary = templatePlaceholderSummary(document)
    return {
      document_id: document.id,
      title: documentTitle(document),
      doc_type: document.type || 'document',
      status: document.status || 'draft',
      reason: unresolvedTemplateSummary ? `未填模板变量：${unresolvedTemplateSummary}` : (isPlaceholder(document) ? '仍包含占位内容' : '处于待评审状态'),
      recommended_action: unresolvedTemplateSummary ? '补齐模板变量后再发布或导出。' : (isPlaceholder(document) ? '补齐占位内容后再发布。' : '完成评审或发布流程后再用于正式交付。'),
    }
  })

  useEffect(() => {
    setSelectedDocumentIds(exportableDocuments.map((document) => document.id))
  }, [exportableDocuments])

  const filteredDocuments = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()
    return documents
      .filter((document) => statusFilter === 'all' || document.status === statusFilter)
      .filter((document) => {
        if (!normalizedQuery) return true
        return `${documentTitle(document)} ${document.type} ${documentStatusLabel(document.status)} ${templatePlaceholderSummary(document)}`.toLowerCase().includes(normalizedQuery)
      })
  }, [documents, query, statusFilter])

  const selectedFormats = Object.entries(formats)
    .filter(([, selected]) => selected)
    .map(([format]) => format as 'word' | 'markdown' | 'pptx')
  const exportVariables = useMemo(() => {
    const variables: Record<string, string> = {}
    const summary = variablesSummary.trim()
    if (summary) {
      variables.summary = summary
    }
    variableRows.forEach((row) => {
      const key = row.key.trim()
      const value = row.value.trim()
      if (key && value) {
        variables[key] = value
      }
    })
    return variables
  }, [variableRows, variablesSummary])
  const configuredVariableCount = Object.keys(exportVariables).length
  const emptyVariableKeys = variableRows
    .map((row) => ({ key: row.key.trim(), value: row.value.trim() }))
    .filter((row) => row.key && !row.value)
    .map((row) => row.key)
  const recentJob = exportJobs[0]
  const canCreate = Boolean(selectedProjectId) && selectedDocumentIds.length > 0 && selectedFormats.length > 0
  const completedJobs = exportJobs.filter((job) => job.status === 'completed')
  const failedJobs = exportJobs.filter((job) => job.status === 'failed')
  const artifactCount = exportJobs.reduce((total, job) => total + (job.artifacts?.length ?? 0), 0)
  const deliveredFormats = new Set(
    exportJobs
      .flatMap((job) => job.artifacts ?? [])
      .map((artifact) => artifactFormat(artifact.filename))
      .filter((format) => ['Word', 'Markdown', 'PPTX'].includes(format))
  )
  const exportCapability = readinessQuery.data?.capabilities.find((capability) => capability.key === 'export_release')
  const exportCommissioningCheck = commissioningQuery.data?.checks.find((check) => check.key === 'export_validation')
  const exportEvidence = exportCapability?.evidence
  const exportEvidenceItems = [
    {
      key: 'export_job_count',
      label: '导出任务',
      value: evidenceNumber(exportEvidence, ['export_job_count', 'export_jobs'], exportJobs.length),
    },
    {
      key: 'completed_export_count',
      label: '成功导出',
      value: evidenceNumber(exportEvidence, ['completed_export_count', 'completed_exports'], completedJobs.length),
    },
    {
      key: 'exportable_document_count',
      label: '可导出文档',
      value: evidenceNumber(exportCommissioningCheck?.evidence, ['exportable_document_count'], productionExportableCount),
    },
    {
      key: 'artifact_count',
      label: '可下载产物',
      value: artifactCount,
    },
    {
      key: 'failed_export_count',
      label: '失败任务',
      value: failedJobs.length,
    },
  ]

  const createPackageExport = useMutation({
    mutationFn: () =>
      exportsApi.createProjectPackage({
        project_id: selectedProjectId,
        document_ids: selectedDocumentIds,
        title: packageTitle.trim() || `${selectedProject?.name || '项目'} 交付包`,
        formats: selectedFormats,
        include_drafts: true,
        include_manifest: true,
        include_audit: includeAudit,
        watermark: watermark.trim(),
        variables: exportVariables,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['export-jobs'] })
      queryClient.invalidateQueries({ queryKey: ['export-release-evidence', selectedProjectId] })
      addToast({ title: '导出任务已创建', description: '交付包任务已进入历史，可查看产物或失败原因。' })
      setActiveTab('history')
    },
    onError: (error: Error) => {
      addToast({ title: '导出任务创建失败', description: error.message, variant: 'destructive' })
    },
  })

  const runCommissioningMutation = useMutation({
    mutationFn: () => apiClient.post<CapabilityCommissioningResponse>('/ops/capabilities/commissioning/run', {
      checks: ['export_validation'],
    }),
    onSuccess: async () => {
      await Promise.all([commissioningQuery.refetch(), readinessQuery.refetch(), refetchJobs()])
      addToast({ title: '导出发布校准已完成', description: '成功导出记录、可导出文档和交付产物证据已重新检查。' })
    },
    onError: (error) => {
      addToast({
        title: '导出发布校准失败',
        description: error instanceof Error ? error.message : '生产校准未能完成。',
        variant: 'destructive',
      })
    },
  })

  const toggleDocument = (documentId: string) => {
    setSelectedDocumentIds((current) =>
      current.includes(documentId) ? current.filter((id) => id !== documentId) : [...current, documentId]
    )
  }

  const toggleFormat = (format: keyof typeof formats) => {
    setFormats((current) => ({ ...current, [format]: !current[format] }))
  }

  const updateVariableRow = (id: string, field: 'key' | 'value', value: string) => {
    setVariableRows((current) => current.map((row) => (row.id === id ? { ...row, [field]: value } : row)))
  }

  const addVariableRow = () => {
    setVariableRows((current) => [...current, { id: `variable-${Date.now()}`, key: '', value: '' }])
  }

  const removeVariableRow = (id: string) => {
    setVariableRows((current) => current.filter((row) => row.id !== id))
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">交付导出发布室</h1>
          <p className="mt-1 text-sm text-slate-500">选择项目、组织交付包、检查发布阻塞，并跟踪导出产物与失败原因。</p>
        </div>
        {activeTab === 'history' && (
          <Button variant="outline" size="sm" onClick={() => refetchJobs()} className="gap-2">
            <RefreshCw className="h-4 w-4" />
            刷新
          </Button>
        )}
      </div>

      <div className="grid gap-4 md:grid-cols-3" data-testid="export-readiness">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>生产准备度</CardDescription>
            <CardTitle className="text-2xl">{readinessLoading ? '检查中' : `${readinessScore}%`}</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-slate-500">
            可正式导出 {productionExportableCount}，阻塞 {productionBlockedCount}。后端按核心文档类型、状态和占位内容校验。
          </CardContent>
        </Card>
        <Card data-testid="recent-export-summary">
          <CardHeader className="pb-2">
            <CardDescription>最近导出任务</CardDescription>
            <CardTitle className="text-lg">{recentJob ? jobTitle(recentJob) : '暂无任务'}</CardTitle>
          </CardHeader>
          <CardContent className="flex items-center gap-2 text-sm text-slate-500">
            {recentJob ? statusBadge(recentJob.status) : <Badge variant="secondary">未创建</Badge>}
          </CardContent>
        </Card>
        <Card data-testid="export-format-summary">
          <CardHeader className="pb-2">
            <CardDescription>产物格式</CardDescription>
            <CardTitle className="text-lg">Word / Markdown / PPTX</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-slate-500">支持多格式交付包，历史中保留下载入口。</CardContent>
        </Card>
      </div>

      {readinessData ? (
        <Card data-testid="export-production-readiness">
          <CardHeader>
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <CardTitle>核心交付清单</CardTitle>
                <CardDescription>由后端校验 URS、BRD、PRD、设计说明和测试用例是否具备正式交付条件。</CardDescription>
              </div>
              <Badge variant={readinessData.can_export_production ? 'secondary' : 'destructive'}>
                {readinessData.can_export_production ? '可正式发布' : '仍有阻塞'}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 md:grid-cols-5">
              {readinessData.required_types.map((item) => (
                <div key={item.doc_type} className="rounded-md border border-slate-200 p-3 text-sm dark:border-slate-800">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-slate-900 dark:text-white">{item.label}</span>
                    <Badge variant={item.status === 'ready' ? 'secondary' : item.status === 'blocked' ? 'destructive' : 'outline'}>
                      {READINESS_STATUS_LABELS[item.status] ?? item.status}
                    </Badge>
                  </div>
                  <p className="mt-2 text-xs text-slate-500">就绪 {item.ready_count}，阻塞 {item.blocked_count}</p>
                </div>
              ))}
            </div>
            <div className="rounded-md bg-slate-50 p-3 text-sm text-slate-600 dark:bg-slate-900 dark:text-slate-300">
              {(readinessData.recommended_actions.length ? readinessData.recommended_actions : ['当前没有额外建议。']).map((action) => (
                <p key={action}>{action}</p>
              ))}
            </div>
          </CardContent>
        </Card>
      ) : null}

      <ExportReleaseEvidenceCenter
        evidence={releaseEvidenceQuery.data}
        isLoading={releaseEvidenceQuery.isLoading}
        isError={releaseEvidenceQuery.isError}
        onRetry={() => releaseEvidenceQuery.refetch()}
      />

      <Card data-testid="export-production-loop">
        <CardHeader>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <CardTitle>导出发布生产闭环</CardTitle>
              <CardDescription>汇总正式导出证据、格式覆盖、失败处置和投产校准状态。</CardDescription>
            </div>
            <Badge variant={exportCapability?.status === 'ready' ? 'secondary' : exportCapability?.status === 'blocked' ? 'destructive' : 'outline'}>
              {readinessQuery.isLoading ? '检查中' : exportCapability?.status === 'ready' ? '已就绪' : exportCapability?.status === 'degraded' ? '需补证据' : exportCapability?.status === 'blocked' ? '阻塞' : '未校准'}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="space-y-4">
            <div>
              <p className="font-semibold text-slate-900 dark:text-white">{exportCapability?.label || '导出与交付发布'}</p>
              <p className="mt-1 text-sm text-slate-500">{exportCapability?.summary || '正在读取导出发布生产准备度。'}</p>
            </div>
            <div data-testid="export-production-evidence-grid" className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
              {exportEvidenceItems.map((item) => (
                <div key={item.key} data-testid={`export-production-evidence-${item.key}`} className="rounded-md border border-slate-200 px-3 py-2 dark:border-slate-800">
                  <p className="text-xs text-slate-500">{item.label}</p>
                  <p className="mt-1 text-lg font-semibold text-slate-900 dark:text-white">{item.value}</p>
                </div>
              ))}
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              {(['Word', 'Markdown', 'PPTX'] as const).map((format) => (
                <div key={format} data-testid={`export-format-coverage-${format.toLowerCase()}`} className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2 text-sm dark:bg-slate-900">
                  <span>{format}</span>
                  <Badge variant={deliveredFormats.has(format) ? 'secondary' : 'outline'}>{deliveredFormats.has(format) ? '已有产物' : '待覆盖'}</Badge>
                </div>
              ))}
            </div>
            {failedJobs.length > 0 ? (
              <div data-testid="export-failure-triage" className="rounded-md bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
                <p className="font-medium">失败处置</p>
                <p className="mt-1">最近失败：{failedJobs[0].error_message || '请查看任务错误详情'}。补齐变量、占位内容或评审状态后重新生成交付包。</p>
              </div>
            ) : null}
          </div>
          <div className="space-y-3 rounded-lg border border-slate-200 p-4 dark:border-slate-800">
            <div>
              <p className="font-semibold text-slate-900 dark:text-white">{exportCommissioningCheck?.label || '交付导出校准'}</p>
              <p className="mt-1 text-sm text-slate-500">{exportCommissioningCheck?.summary || '按成功导出记录和可导出文档检查投产可用性。'}</p>
            </div>
            {exportCommissioningCheck?.blockers?.length ? (
              <p className="text-sm text-amber-700 dark:text-amber-200">{exportCommissioningCheck.blockers[0]}</p>
            ) : null}
            <Button
              data-testid="export-production-commissioning-run"
              className="w-full"
              disabled={!exportCommissioningCheck?.can_run || runCommissioningMutation.isPending}
              onClick={() => runCommissioningMutation.mutate()}
            >
              {runCommissioningMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <ShieldCheck className="mr-2 h-4 w-4" />}
              {runCommissioningMutation.isPending ? '校准中...' : '运行导出发布校准'}
            </Button>
            <Button data-testid="export-production-history-link" variant="outline" className="w-full" onClick={() => setActiveTab('history')}>
              查看任务历史
            </Button>
          </div>
        </CardContent>
      </Card>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="mb-4">
          <TabsTrigger value="package" className="gap-2">
            <Package className="h-4 w-4" />
            交付包配置
          </TabsTrigger>
          <TabsTrigger value="history" className="gap-2">
            <Archive className="h-4 w-4" />
            任务历史
          </TabsTrigger>
        </TabsList>

        <TabsContent value="package">
          <div className="grid gap-4 lg:grid-cols-[360px_minmax(0,1fr)]">
            <Card>
              <CardHeader>
                <CardTitle>发布设置</CardTitle>
                <CardDescription>配置包名称、项目、格式、变量、水印和审计选项。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="project-select">项目</Label>
                  <Select
                    id="project-select"
                    value={selectedProjectId}
                    onValueChange={(value) => {
                      setSelectedProjectId(value)
                      const project = projects.find((item) => item.id === value)
                      setPackageTitle(project ? `${project.name} 交付包` : '交付包')
                    }}
                    disabled={projectsLoading || projects.length === 0}
                  >
                    {projects.map((project) => (
                      <SelectOption key={project.id} value={project.id}>
                        {project.name}
                      </SelectOption>
                    ))}
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="package-title">包名称</Label>
                  <Input id="package-title" value={packageTitle} onChange={(event) => setPackageTitle(event.target.value)} />
                </div>

                <div className="space-y-2">
                  <Label>导出格式</Label>
                  <div className="grid grid-cols-3 gap-2">
                    {(['word', 'markdown', 'pptx'] as const).map((format) => (
                      <label key={format} className="flex items-center gap-2 rounded-md border border-slate-200 px-3 py-2 text-sm dark:border-slate-800">
                        <input type="checkbox" checked={formats[format]} onChange={() => toggleFormat(format)} />
                        {FORMAT_LABELS[format]}
                      </label>
                    ))}
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="variables-summary">变量摘要</Label>
                  <Input id="variables-summary" value={variablesSummary} onChange={(event) => setVariablesSummary(event.target.value)} />
                </div>

                <div className="space-y-3 rounded-md border border-slate-200 p-3 dark:border-slate-800" data-testid="export-variable-panel">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-slate-900 dark:text-white">模板变量映射</p>
                      <p className="text-xs text-slate-500">用于填充 Word、Markdown、PPTX 中的 {`{{变量名}}`} 占位符。</p>
                    </div>
                    <Button type="button" variant="outline" size="sm" className="gap-2" onClick={addVariableRow} data-testid="add-export-variable">
                      <Plus className="h-4 w-4" />
                      添加
                    </Button>
                  </div>

                  <div className="space-y-2">
                    {variableRows.map((row, index) => (
                      <div key={row.id} className="grid gap-2 md:grid-cols-[1fr_1fr_auto]">
                        <Input
                          aria-label={`export-variable-key-${index + 1}`}
                          data-testid={`export-variable-key-${index + 1}`}
                          value={row.key}
                          onChange={(event) => updateVariableRow(row.id, 'key', event.target.value)}
                          placeholder="例如：客户名称"
                        />
                        <Input
                          aria-label={`export-variable-value-${index + 1}`}
                          data-testid={`export-variable-value-${index + 1}`}
                          value={row.value}
                          onChange={(event) => updateVariableRow(row.id, 'value', event.target.value)}
                          placeholder="例如：远大客户"
                        />
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          aria-label={`remove-export-variable-${index + 1}`}
                          onClick={() => removeVariableRow(row.id)}
                          disabled={variableRows.length <= 1}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    ))}
                  </div>

                  <div className="rounded-md bg-slate-50 p-2 text-xs text-slate-600 dark:bg-slate-900 dark:text-slate-300" data-testid="export-variable-evidence">
                    已配置 {configuredVariableCount} 个变量
                    {emptyVariableKeys.length > 0 ? `；待补值：${emptyVariableKeys.join('、')}` : '；没有待补变量'}
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="watermark">水印</Label>
                  <Input id="watermark" value={watermark} onChange={(event) => setWatermark(event.target.value)} />
                </div>

                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={includeAudit} onChange={(event) => setIncludeAudit(event.target.checked)} />
                  生成审计清单
                </label>

                <div className="rounded-md bg-slate-50 p-3 text-sm text-slate-600 dark:bg-slate-900 dark:text-slate-300" data-testid="package-selection-summary">
                  已选择 {selectedDocumentIds.length} 份文档；格式 {selectedFormats.map((format) => FORMAT_LABELS[format]).join('、') || '未选择'}。
                </div>

                <Button className="w-full gap-2" disabled={!canCreate || createPackageExport.isPending} onClick={() => createPackageExport.mutate()}>
                  {createPackageExport.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Package className="h-4 w-4" />}
                  创建导出任务
                </Button>
              </CardContent>
            </Card>

            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle>文档可发布性</CardTitle>
                  <CardDescription>筛选文档并选择要纳入交付包的发布范围。</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid gap-3 md:grid-cols-[1fr_180px]">
                    <div className="space-y-2">
                      <Label htmlFor="document-search">搜索文档</Label>
                      <div className="relative">
                        <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
                        <Input id="document-search" className="pl-9" value={query} onChange={(event) => setQuery(event.target.value)} />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="status-filter">状态筛选</Label>
                      <Select id="status-filter" value={statusFilter} onValueChange={setStatusFilter}>
                        <SelectOption value="all">全部</SelectOption>
                        <SelectOption value="published">已发布</SelectOption>
                        <SelectOption value="draft">待评审</SelectOption>
                        <SelectOption value="placeholder">占位</SelectOption>
                      </Select>
                    </div>
                  </div>

                  {documentsLoading ? (
                    <div className="flex h-40 items-center justify-center gap-2 text-sm text-slate-500">
                      <Loader2 className="h-5 w-5 animate-spin" />
                      正在加载文档...
                    </div>
                  ) : (
                    <div className="space-y-3" data-testid="export-document-list">
                      {filteredDocuments.map((document) => {
                        const disabled = isPlaceholder(document)
                        return (
                          <label key={document.id} className="flex items-start gap-3 rounded-md border border-slate-200 p-4 dark:border-slate-800">
                            <input
                              aria-label={`选择 ${documentTitle(document)}`}
                              type="checkbox"
                              checked={selectedDocumentIds.includes(document.id)}
                              disabled={disabled}
                              onChange={() => toggleDocument(document.id)}
                              className="mt-1 h-4 w-4 rounded border-slate-300"
                            />
                            <span className="min-w-0 flex-1">
                              <span className="block font-medium text-slate-900 dark:text-white">{documentTitle(document)}</span>
                              <span className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                                <Badge variant="outline">{documentTypeLabel(document.type)}</Badge>
                                <Badge variant={disabled ? 'destructive' : 'secondary'}>{documentStatusLabel(document.status)}</Badge>
                                {isReviewBlocked(document) && <span className="text-amber-700">发布前需处理</span>}
                              </span>
                            </span>
                          </label>
                        )
                      })}
                    </div>
                  )}
                </CardContent>
              </Card>

              <Card data-testid="export-blockers">
                <CardHeader>
                  <CardTitle>发布阻塞</CardTitle>
                  <CardDescription>待评审和占位文档会影响交付包发布。</CardDescription>
                </CardHeader>
                <CardContent className="space-y-2">
                  {displayedBlockers.length === 0 ? (
                    <div className="flex items-center gap-2 text-sm text-emerald-700">
                      <CheckCircle2 className="h-4 w-4" />
                      当前没有发布阻塞。
                    </div>
                  ) : (
                    displayedBlockers.map((blocker) => (
                      <div key={blocker.document_id} className="flex items-start gap-2 rounded-md bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-900/20 dark:text-amber-200">
                        <AlertCircle className="mt-0.5 h-4 w-4" />
                        <span>
                          <span className="font-medium">{blocker.title}</span>
                          <span className="ml-2">{blocker.reason}</span>
                          <span className="mt-1 block text-xs">{blocker.recommended_action}</span>
                        </span>
                      </div>
                    ))
                  )}
                </CardContent>
              </Card>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="history">
          <Card>
            <CardHeader>
              <CardTitle>导出任务历史</CardTitle>
              <CardDescription>查看交付包、单文档导出任务、下载入口和失败原因。</CardDescription>
            </CardHeader>
            <CardContent data-testid="export-history">
              {jobsLoading ? (
                <div className="flex h-40 items-center justify-center gap-2 text-sm text-slate-500">
                  <Loader2 className="h-5 w-5 animate-spin" />
                  正在加载任务历史...
                </div>
              ) : exportJobs.length === 0 ? (
                <div className="flex h-40 flex-col items-center justify-center gap-2 text-sm text-slate-500">
                  <Archive className="h-8 w-8 text-slate-400" />
                  暂无导出任务。
                </div>
              ) : (
                <div className="space-y-3">
                  {exportJobs.map((job) => (
                    <div key={job.id} className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <p className="font-medium text-slate-900 dark:text-white">{jobTitle(job)}</p>
                            <Badge variant="outline">{FORMAT_LABELS[job.export_type] || job.export_type}</Badge>
                            {statusBadge(job.status)}
                          </div>
                          <p className="mt-1 text-xs text-slate-500">
                            创建：{new Date(job.created_at).toLocaleString('zh-CN')}
                            {job.completed_at ? ` · 完成：${new Date(job.completed_at).toLocaleString('zh-CN')}` : ''}
                          </p>
                          {job.error_message && <p className="mt-2 text-sm text-red-600">失败原因：{job.error_message}</p>}
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {job.artifacts?.map((artifact) => (
                            <Button key={artifact.id} variant="outline" size="sm" asChild>
                              <a href={exportsApi.downloadArtifact(artifact.id)} target="_blank" rel="noreferrer">
                                <Download className="mr-2 h-4 w-4" />
                                {artifactFormat(artifact.filename)} {artifact.filename}
                              </a>
                            </Button>
                          ))}
                          {job.status === 'completed' && (!job.artifacts || job.artifacts.length === 0) && (
                            <Badge className="gap-1 bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300">
                              <CheckCircle2 className="h-3 w-3" />
                              已生成
                            </Badge>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
