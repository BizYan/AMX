'use client'

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  FileText,
  GitBranch,
  GitFork,
  Layers3,
  Loader2,
  Play,
  Plus,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Users,
  Workflow,
} from 'lucide-react'
import {
  agentApi,
  projectsApi,
  type AgentRun,
  type OrchestrationDashboard,
  type WorkflowDefinition,
  type WorkflowProductionPreflight,
  type WorkflowTemplate,
  type WorkflowVersion,
} from '@/lib/api-client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectOption } from '@/components/ui/select'
import { useToast } from '@/components/ui/toast'

interface WorkflowView {
  id: string
  name: string
  description: string
  category: string
  status: 'draft' | 'published' | 'disabled'
  nodeCount: number
  edgeCount: number
  activeVersionId?: string
  activeVersionNumber?: number
  createdAt: string
  updatedAt?: string
  nodes: any[]
  skills: string[]
  version?: WorkflowVersion
  definition: WorkflowDefinition
}

const STATUS_LABELS: Record<WorkflowView['status'], string> = {
  draft: '草稿',
  published: '已发布',
  disabled: '已停用',
}

const CATEGORY_LABELS: Record<string, string> = {
  document_generation: '文档生成',
  requirement_analysis: '需求分析',
  quality_assessment: '质量评审',
  export_orchestration: '交付导出',
  custom: '自定义',
}

const HEALTH_LABELS: Record<string, string> = {
  critical: '严重',
  high: '高',
  medium: '中',
  info: '提示',
}

const RUN_STATUS_LABELS: Record<string, string> = {
  pending: '等待执行',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

const PREFLIGHT_STATUS_LABELS: Record<string, string> = {
  passed: '通过',
  warning: '关注',
  failed: '阻断',
}

function getNodeLabel(node: any): string {
  return String(node?.data?.label || node?.label || node?.type || node?.id || '未命名节点')
}

function getNodeSkill(node: any): string | null {
  const skill = node?.data?.skill || node?.config?.skill || node?.skill || node?.skill_name || null
  return skill ? String(skill) : null
}

function countEdges(nodes: any[]) {
  return nodes.reduce((total, node) => total + (Array.isArray(node.depends_on) ? node.depends_on.length : 0), 0)
}

function statusClass(status: WorkflowView['status']) {
  if (status === 'published') return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-100'
  if (status === 'disabled') return 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200'
  return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-100'
}

function healthClass(severity: string) {
  if (severity === 'critical' || severity === 'high') return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100'
  if (severity === 'medium') return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-100'
  return 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-100'
}

function runStatusClass(status: string) {
  if (status === 'completed') return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-100'
  if (status === 'failed') return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100'
  if (status === 'running' || status === 'pending') return 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-100'
  return 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200'
}

function preflightStatusClass(status: string) {
  if (status === 'passed') return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-100'
  if (status === 'warning') return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-100'
  if (status === 'failed') return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100'
  return 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200'
}

function releaseGateClass(status: string) {
  if (status === 'passed') return 'border-green-200 bg-green-50 text-green-900 dark:border-green-900 dark:bg-green-950 dark:text-green-100'
  if (status === 'attention') return 'border-yellow-200 bg-yellow-50 text-yellow-900 dark:border-yellow-900 dark:bg-yellow-950 dark:text-yellow-100'
  return 'border-red-200 bg-red-50 text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-100'
}

function runTitle(run: AgentRun) {
  return String(run.input_data?.workflow_name || run.workflow?.workflow_name || run.workflow_version_id || run.id)
}

function formatDate(value?: string | null) {
  if (!value) return '未记录'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function buildWorkflowView(workflow: WorkflowDefinition, versions: WorkflowVersion[]): WorkflowView {
  const activeVersion = versions.find((version) => version.is_active) || versions[0]
  const nodes = activeVersion?.dag_json?.nodes || workflow.graph_data?.nodes || []
  const skills = Array.from(new Set<string>(
    nodes.map(getNodeSkill).filter((value: string | null): value is string => Boolean(value))
  ))
  const status: WorkflowView['status'] = workflow.is_active && activeVersion?.is_active
    ? 'published'
    : workflow.is_active
      ? 'draft'
      : 'disabled'

  return {
    id: workflow.id,
    name: workflow.name,
    description: workflow.description || '未填写说明',
    category: workflow.category || 'custom',
    status,
    nodeCount: nodes.length,
    edgeCount: countEdges(nodes),
    activeVersionId: activeVersion?.is_active ? activeVersion.id : undefined,
    activeVersionNumber: activeVersion?.version,
    createdAt: workflow.created_at,
    updatedAt: workflow.updated_at,
    nodes,
    skills,
    version: activeVersion,
    definition: workflow,
  }
}

function EmptyState({ search }: { search: string }) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center justify-center py-12 text-center">
        <GitBranch className="h-12 w-12 text-slate-300" />
        <h3 className="mt-4 text-lg font-semibold text-slate-900 dark:text-white">
          {search ? '没有匹配的工作流' : '还没有工作流'}
        </h3>
        <p className="mt-2 max-w-md text-sm text-slate-500">
          {search ? '调整搜索或筛选条件后重试。' : '可以从平台模板创建一条可发布、可运行、可观测的工作流。'}
        </p>
      </CardContent>
    </Card>
  )
}

function ReadinessBand({ dashboard }: { dashboard?: OrchestrationDashboard }) {
  const score = dashboard?.readiness_score ?? 0
  const kpis = dashboard?.kpis

  return (
    <section
      data-testid="orchestration-readiness-band"
      className="rounded-lg border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-950"
    >
      <div className="flex flex-col gap-5 xl:flex-row xl:items-center xl:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-indigo-600" />
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white">智能编排生产闭环</h2>
          </div>
          <p className="mt-1 text-sm text-slate-500">
            汇总 Skill、Agent、工作流模板、运行记录和可恢复异常，判断当前编排能力是否可用于项目交付。
          </p>
        </div>
        <div className="grid min-w-[280px] grid-cols-[96px_1fr] items-center gap-4">
          <div className="flex h-24 w-24 items-center justify-center rounded-full border-8 border-indigo-100 bg-indigo-50 text-2xl font-semibold text-indigo-700 dark:border-indigo-900 dark:bg-indigo-950 dark:text-indigo-200">
            {score}
          </div>
          <div>
            <p className="text-sm font-medium text-slate-900 dark:text-white">生产就绪度</p>
            <p className="mt-1 text-xs text-slate-500">80 分以上表示已具备配置、执行和观测闭环。</p>
          </div>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
          <p className="text-2xl font-semibold text-slate-900 dark:text-white">{kpis?.active_agents ?? 0}</p>
          <p className="mt-1 text-xs text-slate-500">启用 Agent</p>
        </div>
        <div className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
          <p className="text-2xl font-semibold text-slate-900 dark:text-white">{kpis?.published_skills ?? 0}</p>
          <p className="mt-1 text-xs text-slate-500">已发布 Skill</p>
        </div>
        <div className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
          <p className="text-2xl font-semibold text-slate-900 dark:text-white">{kpis?.executable_workflows ?? 0}</p>
          <p className="mt-1 text-xs text-slate-500">可执行工作流</p>
        </div>
        <div className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
          <p className="text-2xl font-semibold text-slate-900 dark:text-white">{kpis?.recoverable_runs ?? 0}</p>
          <p className="mt-1 text-xs text-slate-500">可恢复运行</p>
        </div>
      </div>

      {dashboard?.recommendations?.length ? (
        <div className="mt-5 grid gap-3 lg:grid-cols-2">
          {dashboard.recommendations.slice(0, 4).map((issue) => (
            <div key={issue.code} className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-medium text-slate-900 dark:text-white">{issue.title}</p>
                  <p className="mt-1 text-sm text-slate-500">{issue.detail}</p>
                </div>
                <Badge className={healthClass(issue.severity)}>{HEALTH_LABELS[issue.severity] || issue.severity}</Badge>
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  )
}

function WorkflowPreflightPanel({
  preflight,
  isLoading,
  isError,
}: {
  preflight?: WorkflowProductionPreflight
  isLoading: boolean
  isError: boolean
}) {
  if (isLoading) {
    return (
      <div data-testid="workflow-production-preflight" className="rounded-md border border-slate-200 p-3 text-sm text-slate-500 dark:border-slate-700">
        <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
        正在生成生产预检...
      </div>
    )
  }

  if (isError || !preflight) {
    return (
      <div data-testid="workflow-production-preflight" className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-100">
        生产预检加载失败，请刷新后重试。
      </div>
    )
  }

  return (
    <div data-testid="workflow-production-preflight" className="space-y-3">
      <div className={`rounded-md border p-3 ${releaseGateClass(preflight.release_gate.status)}`}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-sm font-semibold">生产预检：{preflight.release_gate.label}</p>
            <p className="mt-1 text-xs opacity-90">{preflight.release_gate.summary}</p>
          </div>
          <Badge variant="outline" data-testid="workflow-preflight-gate">{preflight.release_gate.status}</Badge>
        </div>
        <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
          <div>
            <p className="font-semibold">{preflight.preview.estimated_steps}</p>
            <p className="opacity-80">预计节点</p>
          </div>
          <div>
            <p className="font-semibold">{preflight.preview.approval_gates.length}</p>
            <p className="opacity-80">审批门禁</p>
          </div>
          <div>
            <p className="font-semibold">{preflight.recent_runs.length}</p>
            <p className="opacity-80">近期运行</p>
          </div>
        </div>
      </div>

      <div className="space-y-2">
        {preflight.checks.map((check) => (
          <div key={check.code} className="rounded-md border border-slate-200 p-3 text-sm dark:border-slate-700">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="font-medium text-slate-900 dark:text-white">{check.title}</p>
                <p className="mt-1 text-xs text-slate-500">{check.detail}</p>
              </div>
              <Badge className={preflightStatusClass(check.status)}>
                {PREFLIGHT_STATUS_LABELS[check.status] || check.status}
              </Badge>
            </div>
          </div>
        ))}
      </div>

      {preflight.next_actions.length > 0 ? (
        <div className="rounded-md bg-slate-50 p-3 text-xs text-slate-600 dark:bg-slate-900 dark:text-slate-300">
          <p className="font-medium text-slate-900 dark:text-white">下一步</p>
          <ul className="mt-2 space-y-1">
            {preflight.next_actions.map((action) => (
              <li key={action.code}>{action.action_label || action.title}：{action.detail}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}

export default function WorkflowsPage() {
  const router = useRouter()
  const queryClient = useQueryClient()
  const { addToast } = useToast()
  const [statusFilter, setStatusFilter] = useState('all')
  const [categoryFilter, setCategoryFilter] = useState('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedProjectId, setSelectedProjectId] = useState('')
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(null)

  const dashboardQuery = useQuery({
    queryKey: ['orchestration-dashboard'],
    queryFn: () => agentApi.getOrchestrationDashboard(),
  })

  const templatesQuery = useQuery({
    queryKey: ['workflow-templates'],
    queryFn: () => agentApi.listWorkflowTemplates(),
  })

  const workflowsQuery = useQuery({
    queryKey: ['workflows'],
    queryFn: async () => {
      const response = await agentApi.listWorkflows({ pageSize: 100 })
      const items = await Promise.all(response.items.map(async (workflow) => {
        const versions = await agentApi.listWorkflowVersions(workflow.id, { pageSize: 20 }).catch(() => ({ items: [] as WorkflowVersion[] }))
        return buildWorkflowView(workflow, versions.items)
      }))

      return items.sort((a, b) => {
        if (a.status !== b.status) return a.status === 'published' ? -1 : 1
        return b.nodeCount - a.nodeCount || a.name.localeCompare(b.name, 'zh-CN')
      })
    },
  })

  const projectsQuery = useQuery({
    queryKey: ['projects-for-workflow-run'],
    queryFn: () => projectsApi.list({ pageSize: 50 }),
  })

  const workflows = useMemo(() => workflowsQuery.data || [], [workflowsQuery.data])
  const templates = templatesQuery.data?.items || []
  const projects = projectsQuery.data?.items || []
  const selectedProject = selectedProjectId || projects[0]?.id || ''
  const categories = Array.from(new Set(workflows.map((workflow) => workflow.category))).sort()

  const filteredWorkflows = useMemo(() => {
    const query = searchQuery.trim().toLowerCase()
    return workflows.filter((workflow) => {
      const searchable = [
        workflow.name,
        workflow.description,
        workflow.category,
        CATEGORY_LABELS[workflow.category] || '',
        ...workflow.skills,
        ...workflow.nodes.map(getNodeLabel),
      ].join(' ').toLowerCase()

      return (
        (statusFilter === 'all' || workflow.status === statusFilter) &&
        (categoryFilter === 'all' || workflow.category === categoryFilter) &&
        (!query || searchable.includes(query))
      )
    })
  }, [categoryFilter, searchQuery, statusFilter, workflows])

  const selectedWorkflow =
    filteredWorkflows.find((workflow) => workflow.id === selectedWorkflowId) ||
    filteredWorkflows[0] ||
    null

  const selectedWorkflowPreflightQuery = useQuery({
    queryKey: ['workflow-production-preflight', selectedWorkflow?.id, selectedProject],
    queryFn: () => agentApi.getWorkflowProductionPreflight(
      selectedWorkflow!.id,
      selectedProject ? { projectId: selectedProject } : undefined
    ),
    enabled: Boolean(selectedWorkflow?.id),
  })

  const selectedWorkflowRunsQuery = useQuery({
    queryKey: ['workflow-agent-runs', selectedWorkflow?.id],
    queryFn: () => agentApi.listRuns({
      workflowDefinitionId: selectedWorkflow!.id,
      runType: 'workflow',
      pageSize: 5,
    }),
    enabled: Boolean(selectedWorkflow?.id),
  })

  const selectedWorkflowRuns = selectedWorkflowRunsQuery.data?.items || []

  const summary = {
    total: workflows.length,
    published: workflows.filter((workflow) => workflow.status === 'published').length,
    draft: workflows.filter((workflow) => workflow.status === 'draft').length,
    executable: workflows.filter((workflow) => workflow.activeVersionId).length,
  }

  const createFromTemplateMutation = useMutation({
    mutationFn: (template: WorkflowTemplate) => agentApi.createWorkflowFromTemplate({
      template_id: template.template_id,
      publish: true,
    }),
    onSuccess: async (workflow) => {
      setSelectedWorkflowId(workflow.id)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['workflows'] }),
        queryClient.invalidateQueries({ queryKey: ['orchestration-dashboard'] }),
      ])
      addToast({
        title: '已从模板创建工作流',
        description: `${workflow.name} 已创建并发布，可以直接进入项目运行。`,
      })
    },
    onError: (error: Error) => addToast({ title: '模板创建失败', description: error.message, variant: 'destructive' }),
  })

  const runWorkflowMutation = useMutation({
    mutationFn: (workflow: WorkflowView) => {
      if (!selectedProject) throw new Error('请先创建或选择一个项目。')
      if (!workflow.activeVersionId) throw new Error('当前工作流没有已发布版本，不能执行。')
      return agentApi.executeWorkflow({
        workflow_id: workflow.id,
        version_id: workflow.activeVersionId,
        project_id: selectedProject,
        input_data: {
          source: 'workflows_page',
          workflow_name: workflow.name,
          workflow_category: workflow.category,
        },
      })
    },
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ['orchestration-dashboard'] })
      addToast({
        title: '工作流已进入执行队列',
        description: `运行记录 ${response.run_id} 已写入智能编排运行中心。`,
      })
      router.push(`/agent-ops?runId=${response.run_id}`)
    },
    onError: (error: Error) => addToast({ title: '运行工作流失败', description: error.message, variant: 'destructive' }),
  })

  if (workflowsQuery.isLoading) {
    return (
      <div className="flex h-64 items-center justify-center text-slate-500">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        正在加载智能编排工作台...
      </div>
    )
  }

  if (workflowsQuery.isError) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12 text-center">
          <AlertTriangle className="h-10 w-10 text-red-500" />
          <h1 className="mt-3 text-lg font-semibold text-slate-900 dark:text-white">工作流加载失败</h1>
          <p className="mt-2 text-sm text-slate-500">{(workflowsQuery.error as Error).message}</p>
          <Button className="mt-4" onClick={() => workflowsQuery.refetch()}>重试</Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">智能编排工作台</h1>
          <p className="mt-1 text-sm text-slate-500">从模板创建工作流，绑定项目上下文运行，并在运行中心追踪执行结果。</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => router.push('/agent-ops')}>
            <Clock3 className="mr-2 h-4 w-4" />
            运行中心
          </Button>
          <Button onClick={() => router.push('/workflows/new/editor')}>
            <Plus className="mr-2 h-4 w-4" />
            新建工作流
          </Button>
        </div>
      </div>

      <ReadinessBand dashboard={dashboardQuery.data} />

      <section
        data-testid="orchestration-maturity-links"
        className="grid gap-3 lg:grid-cols-3"
      >
        <button
          type="button"
          className="rounded-lg border border-slate-200 bg-white p-4 text-left transition hover:border-indigo-300 hover:bg-indigo-50 dark:border-slate-800 dark:bg-slate-950 dark:hover:border-indigo-800 dark:hover:bg-indigo-950/40"
          onClick={() => router.push('/documents')}
        >
          <FileText className="h-5 w-5 text-indigo-600" />
          <p className="mt-3 font-medium text-slate-900 dark:text-white">项目文档联动</p>
          <p className="mt-1 text-sm text-slate-500">把 URS、BRD、PRD、测试和导出节点接入对话式文档工作台。</p>
        </button>
        <button
          type="button"
          className="rounded-lg border border-slate-200 bg-white p-4 text-left transition hover:border-indigo-300 hover:bg-indigo-50 dark:border-slate-800 dark:bg-slate-950 dark:hover:border-indigo-800 dark:hover:bg-indigo-950/40"
          onClick={() => router.push('/agents')}
        >
          <Users className="h-5 w-5 text-indigo-600" />
          <p className="mt-3 font-medium text-slate-900 dark:text-white">Agent 与 Skill 绑定</p>
          <p className="mt-1 text-sm text-slate-500">检查平台级 Skill、专用 Agent、权限和测试记录是否满足运行要求。</p>
        </button>
        <button
          type="button"
          className="rounded-lg border border-slate-200 bg-white p-4 text-left transition hover:border-indigo-300 hover:bg-indigo-50 dark:border-slate-800 dark:bg-slate-950 dark:hover:border-indigo-800 dark:hover:bg-indigo-950/40"
          onClick={() => router.push('/agent-ops')}
        >
          <GitFork className="h-5 w-5 text-indigo-600" />
          <p className="mt-3 font-medium text-slate-900 dark:text-white">运行观测与恢复</p>
          <p className="mt-1 text-sm text-slate-500">跟踪运行事件、失败任务、重试恢复和人工处理状态。</p>
        </button>
      </section>

      <div data-testid="workflow-ops-summary" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Card>
          <CardContent className="pt-4">
            <p className="text-2xl font-semibold text-slate-900 dark:text-white">{summary.total}</p>
            <p className="mt-1 text-xs text-slate-500">工作流总数</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-2xl font-semibold text-slate-900 dark:text-white">{summary.published}</p>
            <p className="mt-1 text-xs text-slate-500">已发布</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-2xl font-semibold text-slate-900 dark:text-white">{summary.draft}</p>
            <p className="mt-1 text-xs text-slate-500">草稿</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-2xl font-semibold text-slate-900 dark:text-white">{summary.executable}</p>
            <p className="mt-1 text-xs text-slate-500">可执行版本</p>
          </CardContent>
        </Card>
      </div>

      <Card data-testid="workflow-template-library">
        <CardHeader>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Sparkles className="h-5 w-5 text-indigo-600" />
                平台工作流模板
              </CardTitle>
              <CardDescription>模板内置 DAG、Skill 依赖和运行前检查，用于快速建立可执行编排。</CardDescription>
            </div>
            <Badge variant="outline">{templatesQuery.data?.total ?? 0} 个模板</Badge>
          </div>
        </CardHeader>
        <CardContent>
          {templatesQuery.isLoading ? (
            <div className="flex items-center text-sm text-slate-500">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              正在加载模板库...
            </div>
          ) : templates.length === 0 ? (
            <div className="rounded-md border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-slate-700">
              暂无可用模板。
            </div>
          ) : (
            <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-4">
              {templates.map((template) => (
                <div key={template.template_id} className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-medium text-slate-900 dark:text-white">{template.display_name}</p>
                      <p className="mt-1 line-clamp-2 text-sm text-slate-500">{template.description}</p>
                    </div>
                    <Badge variant="secondary">{template.node_count} 节点</Badge>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-1">
                    <Badge variant="outline">{CATEGORY_LABELS[template.category] || template.category}</Badge>
                    {template.recommended_doc_types.slice(0, 3).map((docType) => (
                      <Badge key={docType} variant="outline">{docType.toUpperCase()}</Badge>
                    ))}
                  </div>
                  <div className="mt-3 space-y-1">
                    {template.readiness_checks.slice(0, 3).map((check) => (
                      <div key={check} className="flex items-center gap-2 text-xs text-slate-500">
                        <CheckCircle2 className="h-3.5 w-3.5 text-green-600" />
                        <span>{check}</span>
                      </div>
                    ))}
                  </div>
                  <Button
                    className="mt-4 w-full"
                    size="sm"
                    data-testid={`workflow-template-create-${template.template_id}`}
                    disabled={createFromTemplateMutation.isPending}
                    onClick={() => createFromTemplateMutation.mutate(template)}
                  >
                    {createFromTemplateMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Plus className="mr-2 h-4 w-4" />}
                    从模板创建
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="grid gap-3 py-4 lg:grid-cols-[1fr_160px_180px_240px]">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <Input
              data-testid="workflow-search-input"
              className="pl-10"
              placeholder="搜索工作流、分类、节点或 Skill"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
            />
          </div>
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectOption value="all">全部状态</SelectOption>
            <SelectOption value="published">已发布</SelectOption>
            <SelectOption value="draft">草稿</SelectOption>
            <SelectOption value="disabled">已停用</SelectOption>
          </Select>
          <Select value={categoryFilter} onValueChange={setCategoryFilter}>
            <SelectOption value="all">全部分类</SelectOption>
            {categories.map((category) => (
              <SelectOption key={category} value={category}>{CATEGORY_LABELS[category] || category}</SelectOption>
            ))}
          </Select>
          <Select value={selectedProject} onValueChange={setSelectedProjectId}>
            {projects.length === 0 ? (
              <SelectOption value="">暂无项目</SelectOption>
            ) : (
              projects.map((project) => (
                <SelectOption key={project.id} value={project.id}>{project.name}</SelectOption>
              ))
            )}
          </Select>
        </CardContent>
      </Card>

      {filteredWorkflows.length === 0 ? (
        <EmptyState search={searchQuery} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[1fr_420px]">
          <div className="grid gap-4 xl:grid-cols-2">
            {filteredWorkflows.map((workflow) => (
              <Card
                key={workflow.id}
                data-testid={`workflow-card-${workflow.id}`}
                className={selectedWorkflow?.id === workflow.id ? 'border-indigo-500' : ''}
              >
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <CardTitle className="flex items-center gap-2 text-base">
                        <Workflow className="h-4 w-4 text-indigo-600" />
                        <span className="truncate">{workflow.name}</span>
                      </CardTitle>
                      <CardDescription className="mt-1 line-clamp-2">{workflow.description}</CardDescription>
                    </div>
                    <Badge className={statusClass(workflow.status)}>{STATUS_LABELS[workflow.status]}</Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid grid-cols-3 gap-2 text-sm">
                    <div className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
                      <p className="text-xs text-slate-500">节点</p>
                      <p className="mt-1 font-semibold text-slate-900 dark:text-white">{workflow.nodeCount}</p>
                    </div>
                    <div className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
                      <p className="text-xs text-slate-500">依赖</p>
                      <p className="mt-1 font-semibold text-slate-900 dark:text-white">{workflow.edgeCount}</p>
                    </div>
                    <div className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
                      <p className="text-xs text-slate-500">版本</p>
                      <p className="mt-1 font-semibold text-slate-900 dark:text-white">v{workflow.activeVersionNumber || '-'}</p>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    <Badge variant="outline">{CATEGORY_LABELS[workflow.category] || workflow.category}</Badge>
                    {workflow.skills.slice(0, 4).map((skill) => (
                      <Badge key={skill} variant="secondary">{skill}</Badge>
                    ))}
                    {workflow.skills.length === 0 && <Badge variant="outline">未绑定 Skill</Badge>}
                  </div>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => setSelectedWorkflowId(workflow.id)}>查看</Button>
                    <Button variant="outline" size="sm" onClick={() => router.push(`/workflows/${workflow.id}/editor`)}>
                      <Settings className="mr-1 h-4 w-4" />
                      编辑
                    </Button>
                    <Button
                      size="sm"
                      data-testid={`workflow-run-${workflow.id}`}
                      disabled={!workflow.activeVersionId || runWorkflowMutation.isPending}
                      onClick={() => runWorkflowMutation.mutate(workflow)}
                      title={!workflow.activeVersionId ? '请先发布工作流版本' : '运行工作流'}
                    >
                      {runWorkflowMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>

          <Card data-testid="workflow-ops-detail">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Layers3 className="h-5 w-5 text-indigo-600" />
                执行视图
              </CardTitle>
              <CardDescription>{selectedWorkflow?.name || '选择一个工作流查看版本、节点和执行条件。'}</CardDescription>
            </CardHeader>
            <CardContent>
              {!selectedWorkflow ? (
                <div className="rounded-md border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-slate-700">
                  暂无可展示工作流。
                </div>
              ) : (
                <div className="space-y-5">
                  <div className="rounded-md border border-slate-200 p-3 text-sm dark:border-slate-700">
                    <div className="flex items-center gap-2">
                      {selectedWorkflow.activeVersionId ? <CheckCircle2 className="h-4 w-4 text-green-600" /> : <AlertTriangle className="h-4 w-4 text-yellow-600" />}
                      <span className="font-medium text-slate-900 dark:text-white">
                        {selectedWorkflow.activeVersionId ? '已发布版本可执行' : '缺少已发布版本'}
                      </span>
                    </div>
                    <p className="mt-2 text-xs text-slate-500">
                      创建于 {formatDate(selectedWorkflow.createdAt)}，最近更新 {formatDate(selectedWorkflow.updatedAt)}。
                    </p>
                  </div>

                  <WorkflowPreflightPanel
                    preflight={selectedWorkflowPreflightQuery.data}
                    isLoading={selectedWorkflowPreflightQuery.isLoading}
                    isError={selectedWorkflowPreflightQuery.isError}
                  />

                  <div>
                    <h2 className="text-sm font-semibold text-slate-900 dark:text-white">DAG 节点</h2>
                    <div className="mt-3 space-y-2">
                      {selectedWorkflow.nodes.length === 0 ? (
                        <div className="rounded-md border border-dashed border-slate-300 p-3 text-sm text-slate-500 dark:border-slate-700">
                          还没有节点，请进入编辑器添加。
                        </div>
                      ) : (
                        selectedWorkflow.nodes.map((node: any, index: number) => (
                          <div key={node.id || index} className="rounded-md border border-slate-200 p-3 text-sm dark:border-slate-700">
                            <div className="flex items-center justify-between gap-3">
                              <div className="min-w-0">
                                <p className="truncate font-medium text-slate-900 dark:text-white">{getNodeLabel(node)}</p>
                                <p className="mt-1 text-xs text-slate-500">{node.id}</p>
                              </div>
                              <Badge variant="secondary">{getNodeSkill(node) || '未绑定 Skill'}</Badge>
                            </div>
                            {(node.depends_on || []).length > 0 && (
                              <p className="mt-2 text-xs text-slate-500">依赖：{node.depends_on.join('、')}</p>
                            )}
                          </div>
                        ))
                      )}
                    </div>
                  </div>

                  <div data-testid="workflow-recent-runs" className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
                    <div className="flex items-center justify-between gap-3">
                      <h2 className="text-sm font-semibold text-slate-900 dark:text-white">最近运行</h2>
                      <Button variant="ghost" size="sm" onClick={() => router.push(`/agent-ops?workflowDefinitionId=${selectedWorkflow.id}`)}>
                        <Clock3 className="mr-2 h-4 w-4" />
                        运行中心
                      </Button>
                    </div>
                    <div className="mt-3 space-y-2">
                      {selectedWorkflowRunsQuery.isLoading ? (
                        <p className="text-sm text-slate-500">正在加载运行记录...</p>
                      ) : selectedWorkflowRuns.length === 0 ? (
                        <p className="text-sm text-slate-500">当前工作流还没有运行记录。</p>
                      ) : (
                        selectedWorkflowRuns.map((run) => (
                          <button
                            key={run.id}
                            type="button"
                            data-testid={`workflow-recent-run-${run.id}`}
                            className="flex w-full items-center justify-between gap-3 rounded-md bg-slate-50 p-3 text-left text-sm transition hover:bg-slate-100 dark:bg-slate-900 dark:hover:bg-slate-800"
                            onClick={() => router.push(`/agent-ops?runId=${run.id}`)}
                          >
                            <span className="min-w-0">
                              <span className="block truncate font-medium text-slate-900 dark:text-white">{runTitle(run)}</span>
                              <span className="mt-1 block text-xs text-slate-500">{formatDate(run.created_at)}</span>
                            </span>
                            <Badge className={runStatusClass(run.status)}>{RUN_STATUS_LABELS[run.status] || run.status}</Badge>
                          </button>
                        ))
                      )}
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <Button variant="outline" onClick={() => router.push(`/workflows/${selectedWorkflow.id}/editor`)}>
                      <Settings className="mr-2 h-4 w-4" />
                      编辑版本
                    </Button>
                    <Button
                      disabled={!selectedWorkflow.activeVersionId || runWorkflowMutation.isPending}
                      onClick={() => runWorkflowMutation.mutate(selectedWorkflow)}
                    >
                      {runWorkflowMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
                      执行
                    </Button>
                  </div>

                  <div className="rounded-md bg-slate-50 p-3 text-xs text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                    <div className="flex items-center gap-2 font-medium text-slate-900 dark:text-white">
                      <ShieldCheck className="h-4 w-4 text-indigo-600" />
                      运行前置条件
                    </div>
                    <p className="mt-2">工作流需要至少一个节点、通过 DAG 校验、发布活动版本，并选择项目上下文后才能运行。</p>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
