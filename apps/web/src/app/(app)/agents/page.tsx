'use client'

import Link from 'next/link'
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  CircleOff,
  Clock3,
  FlaskConical,
  Loader2,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Workflow,
} from 'lucide-react'
import {
  agentApi,
  type AgentProfile,
  type AgentRun,
  type SkillCatalogEntry,
  type SkillCatalogTestResult,
  type WorkflowDefinition,
} from '@/lib/api-client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectOption } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useToast } from '@/components/ui/toast'

const DOC_TYPE_LABELS: Record<string, string> = {
  urs: 'URS',
  brd: 'BRD',
  prd: 'PRD',
  user_story: '用户故事',
  test_case: '测试用例',
  change: '变更',
}

const STATUS_LABELS: Record<string, string> = {
  active: '启用',
  draft: '草稿',
  disabled: '停用',
  published: '已发布',
  pending: '待执行',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

const GOVERNANCE_LABELS: Record<string, string> = {
  system: '系统级',
  platform: '平台级',
  tenant: '租户级',
  project: '项目级',
  personal: '个人级',
}

function permissionLabel(skill: SkillCatalogEntry | null | undefined) {
  if (!skill) return '未绑定权限'
  if (skill.is_locked) return skill.locked_reason || '系统锁定，只读使用'
  if (skill.can_edit || skill.can_publish || skill.can_disable) return '租户可治理'
  return '只读使用'
}

function agentRunDisabledReason(agent: AgentProfile) {
  if (agent.status !== 'active') return `${STATUS_LABELS[agent.status] || agent.status}状态不可运行`
  if (!agent.workflow_definition_id) return '未绑定工作流不可运行'
  if ((agent.skill_bindings || []).length === 0) return '未绑定 Skill 不可运行'
  return null
}

function labelDocTypes(types: string[] | null | undefined) {
  const values = types?.length ? types : ['未限定']
  return values.map((type) => DOC_TYPE_LABELS[type] || type).join(' / ')
}

function statusClass(status: string) {
  if (status === 'active' || status === 'published' || status === 'completed') {
    return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-100'
  }
  if (status === 'running' || status === 'pending') {
    return 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-100'
  }
  if (status === 'failed' || status === 'disabled') {
    return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100'
  }
  return 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200'
}

function skillName(skill: SkillCatalogEntry | null | undefined) {
  return skill?.effective_display_name || skill?.display_name || skill?.name || '未命名 Skill'
}

function workflowName(workflowMap: Map<string, WorkflowDefinition>, workflowId: string | null | undefined) {
  if (!workflowId) return '未绑定工作流'
  return workflowMap.get(workflowId)?.name || `工作流 ${workflowId.slice(0, 8)}`
}

function runAgentName(run: AgentRun, agentMap: Map<string, AgentProfile>) {
  const input = run.input_data || {}
  const profileId = String(input.agent_profile_id || run.agent_profile_id || '')
  return String(input.agent_name || run.agent_name || agentMap.get(profileId)?.name || '工作流运行')
}

function runWorkflowName(run: AgentRun, workflowMap: Map<string, WorkflowDefinition>) {
  const input = run.input_data || {}
  if (input.workflow_name) return String(input.workflow_name)
  return run.workflow_version_id ? `版本 ${run.workflow_version_id.slice(0, 8)}` : '未记录工作流'
}

function formatDate(value: string | null | undefined) {
  if (!value) return '未记录'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function stringifyJson(value: Record<string, any> | null | undefined) {
  return JSON.stringify(value || {}, null, 2)
}

function parseJsonObject(value: string, label: string) {
  try {
    const parsed = JSON.parse(value || '{}')
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error(`${label} 必须是 JSON 对象`)
    }
    return parsed
  } catch (error: any) {
    throw new Error(`${label} 格式错误：${error.message}`)
  }
}

function sampleInput(skill: SkillCatalogEntry) {
  const metadata = skill.metadata_json || {}
  if (metadata.sample_input && typeof metadata.sample_input === 'object') {
    return metadata.sample_input as Record<string, any>
  }
  return { content: `用于测试「${skillName(skill)}」的示例内容。` }
}

function sampleContext(skill: SkillCatalogEntry) {
  const metadata = skill.metadata_json || {}
  if (metadata.sample_context && typeof metadata.sample_context === 'object') {
    return metadata.sample_context as Record<string, any>
  }
  return { document_type: skill.supported_doc_types?.[0] || 'prd' }
}

function EmptyState({ title, description, testId }: { title: string; description: string; testId: string }) {
  return (
    <Card data-testid={testId}>
      <CardContent className="flex flex-col items-center justify-center py-10 text-center">
        <CircleOff className="h-10 w-10 text-slate-300" />
        <h3 className="mt-3 text-base font-semibold text-slate-900 dark:text-white">{title}</h3>
        <p className="mt-1 max-w-md text-sm text-slate-500">{description}</p>
      </CardContent>
    </Card>
  )
}

export default function AgentsPage() {
  const queryClient = useQueryClient()
  const { addToast } = useToast()
  const [activeTab, setActiveTab] = useState('overview')
  const [agentSearch, setAgentSearch] = useState('')
  const [agentStatus, setAgentStatus] = useState('all')
  const [skillSearch, setSkillSearch] = useState('')
  const [skillType, setSkillType] = useState('all')
  const [runSearch, setRunSearch] = useState('')
  const [runStatus, setRunStatus] = useState('all')
  const [skillDialogOpen, setSkillDialogOpen] = useState(false)
  const [selectedSkill, setSelectedSkill] = useState<SkillCatalogEntry | null>(null)
  const [skillInputJson, setSkillInputJson] = useState('{}')
  const [skillContextJson, setSkillContextJson] = useState('{}')
  const [skillTestResult, setSkillTestResult] = useState<SkillCatalogTestResult | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  const skillsQuery = useQuery({
    queryKey: ['agent-center-skills'],
    queryFn: () => agentApi.listSkillCatalog({ pageSize: 200 }),
  })
  const agentsQuery = useQuery({
    queryKey: ['agent-center-profiles'],
    queryFn: () => agentApi.listAgentProfiles({ pageSize: 200 }),
  })
  const workflowsQuery = useQuery({
    queryKey: ['agent-center-workflows'],
    queryFn: () => agentApi.listWorkflows({ pageSize: 100 }),
  })
  const runsQuery = useQuery({
    queryKey: ['agent-center-runs'],
    queryFn: () => agentApi.listRuns({ pageSize: 100 }),
  })

  const skills = useMemo(() => skillsQuery.data?.items || [], [skillsQuery.data])
  const agents = useMemo(() => agentsQuery.data?.items || [], [agentsQuery.data])
  const workflows = useMemo(() => workflowsQuery.data?.items || [], [workflowsQuery.data])
  const runs = useMemo(() => runsQuery.data?.items || [], [runsQuery.data])
  const isLoading = skillsQuery.isLoading || agentsQuery.isLoading || workflowsQuery.isLoading || runsQuery.isLoading
  const hasError = skillsQuery.isError || agentsQuery.isError || workflowsQuery.isError || runsQuery.isError
  const errorMessage =
    (skillsQuery.error as Error | undefined)?.message ||
    (agentsQuery.error as Error | undefined)?.message ||
    (workflowsQuery.error as Error | undefined)?.message ||
    (runsQuery.error as Error | undefined)?.message ||
    '加载智能编排中心失败'

  const workflowMap = useMemo(() => new Map(workflows.map((workflow) => [workflow.id, workflow])), [workflows])
  const agentMap = useMemo(() => new Map(agents.map((agent) => [agent.id, agent])), [agents])

  const filteredAgents = useMemo(() => {
    const query = agentSearch.trim().toLowerCase()
    return agents.filter((agent) => {
      const searchable = [
        agent.name,
        agent.description || '',
        agent.agent_type,
        workflowName(workflowMap, agent.workflow_definition_id),
        ...(agent.applicable_doc_types || []),
        ...(agent.skill_bindings || []).map((binding) => skillName(binding.skill)),
      ].join(' ').toLowerCase()
      return (agentStatus === 'all' || agent.status === agentStatus) && (!query || searchable.includes(query))
    })
  }, [agentSearch, agentStatus, agents, workflowMap])

  const filteredSkills = useMemo(() => {
    const query = skillSearch.trim().toLowerCase()
    return skills.filter((skill) => {
      const searchable = [
        skill.name,
        skill.display_name || '',
        skill.effective_display_name || '',
        skill.description || '',
        skill.category,
        skill.governance_scope,
        ...(skill.supported_doc_types || []),
      ].join(' ').toLowerCase()
      return (skillType === 'all' || skill.skill_type === skillType) && (!query || searchable.includes(query))
    })
  }, [skillSearch, skillType, skills])

  const filteredRuns = useMemo(() => {
    const query = runSearch.trim().toLowerCase()
    return runs.filter((run) => {
      const searchable = [
        runAgentName(run, agentMap),
        runWorkflowName(run, workflowMap),
        run.status,
        JSON.stringify(run.input_data || {}),
      ].join(' ').toLowerCase()
      return (runStatus === 'all' || run.status === runStatus) && (!query || searchable.includes(query))
    })
  }, [agentMap, runSearch, runStatus, runs, workflowMap])

  const summary = {
    activeAgents: agents.filter((agent) => agent.status === 'active').length,
    publishedSkills: skills.filter((skill) => skill.status === 'published').length,
    boundWorkflows: agents.filter((agent) => Boolean(agent.workflow_definition_id)).length,
    runningRuns: runs.filter((run) => run.status === 'running' || run.status === 'pending').length,
  }

  const refreshAll = async () => {
    setRefreshing(true)
    try {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['agent-center-skills'] }),
        queryClient.invalidateQueries({ queryKey: ['agent-center-profiles'] }),
        queryClient.invalidateQueries({ queryKey: ['agent-center-workflows'] }),
        queryClient.invalidateQueries({ queryKey: ['agent-center-runs'] }),
      ])
      addToast({ title: '智能编排数据已刷新', description: 'Agent、Skill、工作流和运行记录已重新拉取。' })
    } finally {
      setRefreshing(false)
    }
  }

  const bootstrapMutation = useMutation({
    mutationFn: () => agentApi.bootstrapOrchestration(),
    onSuccess: async (result) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['agent-center-skills'] }),
        queryClient.invalidateQueries({ queryKey: ['agent-center-profiles'] }),
        queryClient.invalidateQueries({ queryKey: ['agent-center-workflows'] }),
        queryClient.invalidateQueries({ queryKey: ['agent-center-runs'] }),
      ])
      const initialized = result.initialized || {}
      addToast({
        title: '智能编排已初始化',
        description: `已准备 ${initialized.active_agents ?? 0} 个 Agent、${initialized.published_skills ?? 0} 个 Skill、${initialized.executable_workflows ?? 0} 条可执行工作流。`,
      })
    },
    onError: (error: Error) => addToast({ title: '智能编排初始化失败', description: error.message, variant: 'destructive' }),
  })

  const openSkillTest = (skill: SkillCatalogEntry) => {
    setSelectedSkill(skill)
    setSkillInputJson(stringifyJson(sampleInput(skill)))
    setSkillContextJson(stringifyJson(sampleContext(skill)))
    setSkillTestResult(null)
    setSkillDialogOpen(true)
  }

  const testSkillMutation = useMutation({
    mutationFn: () => {
      if (!selectedSkill) throw new Error('请选择要测试的 Skill')
      return agentApi.testSkillCatalogEntry(selectedSkill.id, {
        input_data: parseJsonObject(skillInputJson, '测试输入'),
        context: parseJsonObject(skillContextJson, '上下文'),
      })
    },
    onSuccess: (result) => {
      setSkillTestResult(result)
      addToast({
        title: result.success ? 'Skill 测试通过' : 'Skill 测试未通过',
        description: result.error_message || '已返回可展示执行结果。',
      })
    },
    onError: (error: Error) => addToast({ title: 'Skill 测试失败', description: error.message, variant: 'destructive' }),
  })

  const runAgentMutation = useMutation({
    mutationFn: (agent: AgentProfile) =>
      agentApi.runAgentProfile(agent.id, {
        input_data: {
          source: 'agents_page',
          agent_profile_id: agent.id,
          agent_name: agent.name,
          document_type: agent.applicable_doc_types?.[0] || agent.agent_type,
          workflow_name: workflowName(workflowMap, agent.workflow_definition_id),
        },
      }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['agent-center-runs'] })
      addToast({ title: 'Agent 已开始运行', description: `运行记录 ${result.run_id} 已写入。` })
    },
    onError: (error: Error) => addToast({ title: 'Agent 运行失败', description: error.message, variant: 'destructive' }),
  })

  const renderSkillCard = (skill: SkillCatalogEntry) => {
    const lastResult = skill.last_test_result || skill.metadata_json?.last_test_result || 'unknown'
    return (
      <Card key={skill.id} data-testid={`skill-card-${skill.id}`} className="overflow-hidden">
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <CardTitle className="text-base">{skillName(skill)}</CardTitle>
              <CardDescription className="mt-1 line-clamp-2">{skill.description || skill.name}</CardDescription>
            </div>
            <Badge className={statusClass(skill.status)}>{STATUS_LABELS[skill.status] || skill.status}</Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-2 text-sm text-slate-600 dark:text-slate-300">
            <div className="flex items-center justify-between gap-3">
              <span>治理级别</span>
              <Badge variant="outline">{GOVERNANCE_LABELS[skill.governance_scope] || skill.governance_scope}</Badge>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span>适用文档</span>
              <span className="text-right">{labelDocTypes(skill.supported_doc_types)}</span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span>最近测试</span>
              <span className={lastResult === 'passed' ? 'text-green-700' : lastResult === 'failed' ? 'text-red-700' : 'text-slate-500'}>
                {lastResult === 'passed' ? '通过' : lastResult === 'failed' ? '失败' : '未记录'}
              </span>
            </div>
          </div>
          {skill.metadata_json?.last_test_summary && (
            <div className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-600 dark:bg-slate-900 dark:text-slate-300">
              {String(skill.metadata_json.last_test_summary)}
            </div>
          )}
          <Button data-testid={`skill-test-${skill.id}`} variant="outline" size="sm" className="w-full" onClick={() => openSkillTest(skill)}>
            <FlaskConical className="mr-2 h-4 w-4" />
            测试 Skill
          </Button>
        </CardContent>
      </Card>
    )
  }

  const renderAgentCard = (agent: AgentProfile) => {
    const latestRun = runs.find((run) => {
      const input = run.input_data || {}
      return input.agent_profile_id === agent.id || input.agent_name === agent.name
    })
    const disabledReason = agentRunDisabledReason(agent)
    const requiredSkill = (agent.skill_bindings || []).find((binding) => binding.is_required)?.skill || agent.skill_bindings?.[0]?.skill
    return (
      <Card key={agent.id} data-testid={`agent-card-${agent.id}`} className="overflow-hidden">
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <Bot className="h-4 w-4 text-indigo-600" />
                {agent.name}
              </CardTitle>
              <CardDescription className="mt-1 line-clamp-2">{agent.description || '未填写 Agent 说明'}</CardDescription>
            </div>
            <Badge className={statusClass(agent.status)}>{STATUS_LABELS[agent.status] || agent.status}</Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
              <p className="text-xs text-slate-500">适用文档</p>
              <p className="mt-1 font-medium text-slate-900 dark:text-white">{labelDocTypes(agent.applicable_doc_types)}</p>
            </div>
            <div className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
              <p className="text-xs text-slate-500">最近运行</p>
              <p className="mt-1 font-medium text-slate-900 dark:text-white">
                {latestRun ? STATUS_LABELS[latestRun.status] || latestRun.status : '未运行'}
              </p>
            </div>
          </div>
          <div>
            <p className="mb-2 text-xs font-medium text-slate-500">绑定 Skill</p>
            <div className="flex flex-wrap gap-1">
              {(agent.skill_bindings || []).length === 0 ? (
                <Badge variant="outline">未绑定</Badge>
              ) : (
                agent.skill_bindings.map((binding) => (
                  <Badge key={binding.id || binding.skill_id} variant="secondary">{skillName(binding.skill)}</Badge>
                ))
              )}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
              <p className="text-slate-500">治理状态</p>
              <p className="mt-1 font-medium text-slate-900 dark:text-white">
                {agent.human_review_required ? '需要人工复核' : '自动执行'}
              </p>
            </div>
            <div className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
              <p className="text-slate-500">权限状态</p>
              <p className="mt-1 font-medium text-slate-900 dark:text-white">{permissionLabel(requiredSkill)}</p>
            </div>
          </div>
          <div className="rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-600 dark:bg-slate-900 dark:text-slate-300">
            <div className="flex items-center gap-2">
              <Workflow className="h-4 w-4 text-slate-400" />
              <span>{workflowName(workflowMap, agent.workflow_definition_id)}</span>
            </div>
          </div>
          <div className="flex gap-2">
            <Button
              data-testid={`agent-run-${agent.id}`}
              size="sm"
              title={disabledReason || '触发 Agent 运行'}
              disabled={Boolean(disabledReason) || runAgentMutation.isPending}
              onClick={() => runAgentMutation.mutate(agent)}
            >
              {runAgentMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
              运行
            </Button>
            {disabledReason && <span className="self-center text-xs text-slate-500">{disabledReason}</span>}
            <Button variant="outline" size="sm" asChild>
              <Link href="/workflows">工作流</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    )
  }

  const renderRunRows = (rows: AgentRun[]) => {
    if (rows.length === 0) {
      return <EmptyState testId="run-empty-state" title="没有匹配的运行记录" description="调整搜索或状态筛选后重试，新的 Agent 运行会自动进入这里。" />
    }
    return (
      <Card>
        <CardContent className="p-0">
          <div className="divide-y divide-slate-100 dark:divide-slate-800">
            {rows.map((run) => (
              <div key={run.id} data-testid={`run-row-${run.id}`} className="grid gap-3 p-4 md:grid-cols-[150px_1fr_1fr_180px] md:items-center">
                <div className="flex items-center gap-2">
                  <Badge className={statusClass(run.status)}>{STATUS_LABELS[run.status] || run.status}</Badge>
                </div>
                <div>
                  <p className="font-medium text-slate-900 dark:text-white">{runAgentName(run, agentMap)}</p>
                  <p className="mt-1 text-xs text-slate-500">{run.id}</p>
                </div>
                <div className="text-sm text-slate-600 dark:text-slate-300">{runWorkflowName(run, workflowMap)}</div>
                <div className="text-sm text-slate-500">{formatDate(run.created_at || run.started_at)}</div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    )
  }

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center text-slate-500">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        正在加载智能编排中心...
      </div>
    )
  }

  if (hasError) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12 text-center">
          <AlertTriangle className="h-10 w-10 text-red-500" />
          <h1 className="mt-3 text-lg font-semibold text-slate-900 dark:text-white">智能编排中心加载失败</h1>
          <p className="mt-2 text-sm text-slate-500">{errorMessage}</p>
          <Button className="mt-4" onClick={() => {
            queryClient.invalidateQueries({ queryKey: ['agent-center-skills'] })
            queryClient.invalidateQueries({ queryKey: ['agent-center-profiles'] })
            queryClient.invalidateQueries({ queryKey: ['agent-center-workflows'] })
            queryClient.invalidateQueries({ queryKey: ['agent-center-runs'] })
          }}>
            重试
          </Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">智能编排中心</h1>
          <p className="mt-1 text-sm text-slate-500">配置 Agent、治理 Skill、绑定工作流，并追踪测试与运行闭环。</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" asChild>
            <Link href="/agent-ops">
              <Activity className="mr-2 h-4 w-4" />
              运行中心
            </Link>
          </Button>
          <Button data-testid="agent-center-refresh" variant="outline" onClick={refreshAll} disabled={refreshing}>
            <RefreshCw className={`mr-2 h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
            刷新
          </Button>
          <Button
            data-testid="agent-center-bootstrap"
            onClick={() => bootstrapMutation.mutate()}
            disabled={bootstrapMutation.isPending}
          >
            {bootstrapMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Sparkles className="mr-2 h-4 w-4" />}
            初始化编排
          </Button>
          <Button variant="outline" asChild>
            <Link href="/workflows">
              <Workflow className="mr-2 h-4 w-4" />
              工作流
            </Link>
          </Button>
        </div>
      </div>

      <div data-testid="agent-center-summary" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Card>
          <CardContent className="pt-4">
            <p className="text-2xl font-semibold text-slate-900 dark:text-white">{summary.activeAgents}</p>
            <p className="mt-1 text-xs text-slate-500">活跃 Agent</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-2xl font-semibold text-slate-900 dark:text-white">{summary.publishedSkills}</p>
            <p className="mt-1 text-xs text-slate-500">已发布 Skill</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-2xl font-semibold text-slate-900 dark:text-white">{summary.boundWorkflows}</p>
            <p className="mt-1 text-xs text-slate-500">绑定工作流</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-2xl font-semibold text-slate-900 dark:text-white">{summary.runningRuns}</p>
            <p className="mt-1 text-xs text-slate-500">运行中/待执行</p>
          </CardContent>
        </Card>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="flex-wrap justify-start">
          <TabsTrigger value="overview">
            <Sparkles className="mr-2 h-4 w-4" />
            总览
          </TabsTrigger>
          <TabsTrigger value="agents">Agent</TabsTrigger>
          <TabsTrigger value="skills">Skill 市场</TabsTrigger>
          <TabsTrigger value="workflows">工作流</TabsTrigger>
          <TabsTrigger value="runs">运行记录</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-6">
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold text-slate-900 dark:text-white">常用 Agent</h2>
              <Button variant="ghost" size="sm" onClick={() => setActiveTab('agents')}>查看全部</Button>
            </div>
            <div className="grid gap-4 lg:grid-cols-3">{filteredAgents.slice(0, 3).map(renderAgentCard)}</div>
          </section>
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold text-slate-900 dark:text-white">Skill 市场</h2>
              <Button variant="ghost" size="sm" onClick={() => setActiveTab('skills')}>管理 Skill</Button>
            </div>
            <div className="grid gap-4 lg:grid-cols-3">{filteredSkills.slice(0, 3).map(renderSkillCard)}</div>
          </section>
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold text-slate-900 dark:text-white">最近运行记录</h2>
              <Button variant="ghost" size="sm" onClick={() => setActiveTab('runs')}>查看记录</Button>
            </div>
            {renderRunRows(filteredRuns.slice(0, 5))}
          </section>
        </TabsContent>

        <TabsContent value="agents" className="space-y-4">
          <Card>
            <CardContent className="grid gap-3 py-4 md:grid-cols-[1fr_180px]">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <Input data-testid="agent-search-input" className="pl-10" placeholder="搜索 Agent、Skill、工作流或文档类型" value={agentSearch} onChange={(event) => setAgentSearch(event.target.value)} />
              </div>
              <Select value={agentStatus} onValueChange={setAgentStatus}>
                <SelectOption value="all">全部状态</SelectOption>
                <SelectOption value="active">启用</SelectOption>
                <SelectOption value="draft">草稿</SelectOption>
                <SelectOption value="disabled">停用</SelectOption>
              </Select>
            </CardContent>
          </Card>
          {filteredAgents.length === 0 ? (
            <EmptyState testId="agent-empty-state" title="没有匹配的 Agent" description="调整搜索或状态筛选后重试，或先在后端创建 Agent 配置。" />
          ) : (
            <div className="grid gap-4 lg:grid-cols-3">{filteredAgents.map(renderAgentCard)}</div>
          )}
        </TabsContent>

        <TabsContent value="skills" className="space-y-4">
          <Card>
            <CardContent className="grid gap-3 py-4 md:grid-cols-[1fr_180px]">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <Input data-testid="skill-search-input" className="pl-10" placeholder="搜索 Skill 名称、说明、治理级别或适用文档" value={skillSearch} onChange={(event) => setSkillSearch(event.target.value)} />
              </div>
              <Select value={skillType} onValueChange={setSkillType}>
                <SelectOption value="all">全部类型</SelectOption>
                <SelectOption value="quality">质量评审</SelectOption>
                <SelectOption value="clarification">需求澄清</SelectOption>
                <SelectOption value="analysis">分析</SelectOption>
                <SelectOption value="generation">生成</SelectOption>
                <SelectOption value="custom">自定义</SelectOption>
              </Select>
            </CardContent>
          </Card>
          {filteredSkills.length === 0 ? (
            <EmptyState testId="skill-empty-state" title="没有匹配的 Skill" description="调整搜索或类型筛选后重试。" />
          ) : (
            <div className="grid gap-4 lg:grid-cols-3">{filteredSkills.map(renderSkillCard)}</div>
          )}
        </TabsContent>

        <TabsContent value="workflows" className="space-y-4">
          <div className="flex flex-col gap-3 rounded-md border border-slate-200 p-4 dark:border-slate-800 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="font-medium text-slate-900 dark:text-white">工作流定义与执行入口</p>
              <p className="mt-1 text-sm text-slate-500">在智能编排中心查看绑定关系，并进入工作流工作台编辑、校验、发布和运行。</p>
            </div>
            <Button asChild>
              <Link href="/workflows">
                <Workflow className="mr-2 h-4 w-4" />
                打开工作流工作台
              </Link>
            </Button>
          </div>
          {workflows.length === 0 ? (
            <EmptyState testId="workflow-empty-state" title="还没有工作流" description="先初始化智能编排默认配置，或进入工作流工作台创建工作流。" />
          ) : (
            <div className="grid gap-4 lg:grid-cols-3">
              {workflows.map((workflow: WorkflowDefinition) => (
                <Card key={workflow.id} data-testid={`workflow-card-${workflow.id}`}>
                  <CardHeader>
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <CardTitle className="text-base">{workflow.name}</CardTitle>
                        <CardDescription className="mt-1 line-clamp-2">{workflow.description || '未填写工作流说明'}</CardDescription>
                      </div>
                      <Badge variant={workflow.is_active ? 'secondary' : 'outline'}>{workflow.is_active ? '启用' : '停用'}</Badge>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="grid grid-cols-2 gap-2 text-sm">
                      <div className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
                        <p className="text-xs text-slate-500">分类</p>
                        <p className="mt-1 font-medium">{workflow.category || '通用'}</p>
                      </div>
                      <div className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
                        <p className="text-xs text-slate-500">版本数</p>
                        <p className="mt-1 font-medium">{workflow.version_count ?? 0}</p>
                      </div>
                    </div>
                    <Button variant="outline" size="sm" className="w-full" asChild>
                      <Link href={`/workflows/${workflow.id}/editor`}>编辑工作流</Link>
                    </Button>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="runs" className="space-y-4">
          <Card>
            <CardContent className="grid gap-3 py-4 md:grid-cols-[1fr_180px]">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <Input data-testid="run-search-input" className="pl-10" placeholder="搜索 Agent、工作流、状态或输入上下文" value={runSearch} onChange={(event) => setRunSearch(event.target.value)} />
              </div>
              <Select data-testid="run-status-filter" value={runStatus} onValueChange={setRunStatus}>
                <SelectOption value="all">全部运行</SelectOption>
                <SelectOption value="pending">待执行</SelectOption>
                <SelectOption value="running">运行中</SelectOption>
                <SelectOption value="completed">已完成</SelectOption>
                <SelectOption value="failed">失败</SelectOption>
              </Select>
            </CardContent>
          </Card>
          {renderRunRows(filteredRuns)}
        </TabsContent>
      </Tabs>

      <Dialog open={skillDialogOpen} onOpenChange={setSkillDialogOpen}>
        <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>测试 Skill</DialogTitle>
            <DialogDescription>{selectedSkill ? `${skillName(selectedSkill)} 的输入契约、执行结果和治理可见性测试。` : '选择 Skill 后运行测试。'}</DialogDescription>
          </DialogHeader>
          {selectedSkill && (
            <div className="grid gap-4 py-4 md:grid-cols-2">
              <div className="rounded-md border border-slate-200 p-3 text-sm dark:border-slate-700 md:col-span-2">
                <div className="flex items-center gap-2 font-medium text-slate-900 dark:text-white">
                  <ShieldCheck className="h-4 w-4 text-indigo-600" />
                  测试场景
                </div>
                <p className="mt-1 text-slate-600 dark:text-slate-300">{String(selectedSkill.metadata_json?.test_scenario || '使用示例输入验证 Skill 契约。')}</p>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">测试输入 JSON</label>
                <textarea
                  data-testid="skill-test-input-json"
                  className="min-h-48 w-full rounded-md border border-slate-200 bg-white px-3 py-2 font-mono text-xs text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                  value={skillInputJson}
                  onChange={(event) => setSkillInputJson(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">上下文 JSON</label>
                <textarea
                  className="min-h-48 w-full rounded-md border border-slate-200 bg-white px-3 py-2 font-mono text-xs text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                  value={skillContextJson}
                  onChange={(event) => setSkillContextJson(event.target.value)}
                />
              </div>
              {skillTestResult && (
                <div className="space-y-2 md:col-span-2">
                  <div className="flex items-center gap-2">
                    {skillTestResult.success ? <CheckCircle2 className="h-4 w-4 text-green-600" /> : <AlertTriangle className="h-4 w-4 text-red-600" />}
                    <span className="text-sm text-slate-600 dark:text-slate-300">
                      {skillTestResult.success ? '通过' : '失败'} · {skillTestResult.mode} · {skillTestResult.execution_time_ms ?? 0}ms
                    </span>
                  </div>
                  <pre className="max-h-64 overflow-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">
                    {JSON.stringify(skillTestResult.output_data || { error: skillTestResult.error_message }, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setSkillDialogOpen(false)}>关闭</Button>
            <Button onClick={() => testSkillMutation.mutate()} disabled={!selectedSkill || testSkillMutation.isPending}>
              {testSkillMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Clock3 className="mr-2 h-4 w-4" />}
              运行测试
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
