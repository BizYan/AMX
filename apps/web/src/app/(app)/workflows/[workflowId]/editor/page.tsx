'use client'

import { use, useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import {
  ReactFlow,
  Background,
  Controls,
  MarkerType,
  Position,
  type Edge,
  type Node,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  CheckCircle2,
  Clock3,
  FileText,
  GitBranch,
  GitFork,
  Loader2,
  Play,
  Plus,
  Route,
  Save,
  ShieldCheck,
  Trash2,
  Users,
  Workflow,
} from 'lucide-react'
import {
  agentApi,
  projectsApi,
  type SkillCatalogEntry,
  type WorkflowDagPreview,
  type WorkflowDagValidation,
} from '@/lib/api-client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectOption } from '@/components/ui/select'
import { useToast } from '@/components/ui/toast'

interface WorkflowEditorPageProps {
  params: Promise<{ workflowId: string }>
}

type WorkflowNodeType = 'skill' | 'human_approval' | 'condition' | 'parallel_group' | 'delay'

interface WorkflowNode {
  id: string
  type: WorkflowNodeType
  skill?: string
  tool?: string
  depends_on: string[]
  position: { x: number; y: number }
  data: {
    label: string
    skill?: string
    description?: string
  }
  config: Record<string, any>
}

interface NodeTemplate {
  type: WorkflowNodeType
  key: string
  label: string
  description: string
  skill?: string
  icon: typeof FileText
  color: string
  config?: Record<string, any>
}

const NODE_TEMPLATES: NodeTemplate[] = [
  {
    type: 'skill',
    key: 'requirement_clarifier',
    label: '需求澄清',
    description: '识别缺口、追问关键信息并沉淀确认事实。',
    skill: 'RequirementClarifier',
    icon: FileText,
    color: 'bg-blue-600',
    config: { role: 'requirement_clarifier' },
  },
  {
    type: 'skill',
    key: 'issue_tree',
    label: '问题树分析',
    description: '拆解业务问题、根因假设和咨询分析路径。',
    skill: 'IssueTreeAnalyzer',
    icon: GitBranch,
    color: 'bg-amber-600',
    config: { role: 'analysis' },
  },
  {
    type: 'skill',
    key: 'document_reviewer',
    label: '文档质量评审',
    description: '检查结构、证据、验收标准和交付完整性。',
    skill: 'DocumentReviewer',
    icon: CheckCircle2,
    color: 'bg-purple-600',
    config: { role: 'quality_gate' },
  },
  {
    type: 'skill',
    key: 'traceability_mapper',
    label: '追溯映射',
    description: '建立 URS、BRD、PRD、测试用例之间的追溯关系。',
    skill: 'PRDTraceabilityMapper',
    icon: Workflow,
    color: 'bg-indigo-600',
    config: { role: 'traceability' },
  },
  {
    type: 'skill',
    key: 'export_orchestrator',
    label: '交付导出',
    description: '组织交付包、导出任务和发布前检查。',
    skill: 'ExportOrchestrator',
    icon: Bot,
    color: 'bg-emerald-600',
    config: { role: 'delivery_export' },
  },
  {
    type: 'human_approval',
    key: 'human_approval',
    label: '人工审批',
    description: '保留业务负责人、架构师或 QA 的人工确认关口。',
    icon: Users,
    color: 'bg-slate-700',
    config: { approver_role: '项目负责人', required: true, sla_hours: 24 },
  },
  {
    type: 'condition',
    key: 'condition',
    label: '条件分支',
    description: '根据风险、文档类型或质量分决定后续路径。',
    icon: GitFork,
    color: 'bg-rose-600',
    config: { expression: 'quality_score < 80', true_label: '需要返工', false_label: '继续交付' },
  },
  {
    type: 'parallel_group',
    key: 'parallel_group',
    label: '并行评审',
    description: '标记可并行处理的一组质量、追溯或导出任务。',
    icon: Route,
    color: 'bg-cyan-700',
    config: { parallel_mode: 'all', join_policy: 'wait_all' },
  },
  {
    type: 'delay',
    key: 'delay',
    label: '等待窗口',
    description: '为外部输入、评审 SLA 或批处理保留等待时间。',
    icon: Clock3,
    color: 'bg-orange-600',
    config: { delay_minutes: 60, resume_policy: 'auto' },
  },
]

const CATEGORY_LABELS: Record<string, string> = {
  document_generation: '文档生成',
  requirement_analysis: '需求分析',
  quality_assessment: '质量评审',
  export_orchestration: '交付导出',
  custom: '自定义',
}

const NODE_TYPE_LABELS: Record<WorkflowNodeType, string> = {
  skill: 'Skill',
  human_approval: '人工审批',
  condition: '条件分支',
  parallel_group: '并行组',
  delay: '等待',
}

function createNode(template: NodeTemplate, index: number, previousNodeId?: string): WorkflowNode {
  const nodeId = `${template.key}-${crypto.randomUUID()}`
  return {
    id: nodeId,
    type: template.type,
    skill: template.skill,
    depends_on: previousNodeId ? [previousNodeId] : [],
    position: { x: 80 + (index % 3) * 260, y: 80 + Math.floor(index / 3) * 170 },
    data: {
      label: template.label,
      skill: template.skill || '',
      description: template.description,
    },
    config: {
      ...(template.config || {}),
      skill: template.skill || undefined,
      template_key: template.key,
    },
  }
}

function normalizeNodeType(value: string | undefined): WorkflowNodeType {
  if (value === 'human_approval' || value === 'condition' || value === 'parallel_group' || value === 'delay') return value
  return 'skill'
}

function normalizeNodeFallbackId(node: any, type: WorkflowNodeType, skill: string, label: string) {
  const rawKey = [
    node.config?.template_key,
    type,
    skill,
    node.tool,
    node.config?.role,
    node.config?.expression,
    label,
    node.position?.x,
    node.position?.y,
  ].filter((value) => value !== undefined && value !== null && String(value).trim().length > 0).join(':')
  const slug = rawKey.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 96)
  return `node-${slug || type}`
}

function normalizeNodes(rawNodes: any[] | undefined): WorkflowNode[] {
  return (rawNodes || []).map((node, index) => {
    const rawType = String(node.type || node.config?.node_type || 'skill')
    const type = normalizeNodeType(rawType)
    const template = NODE_TEMPLATES.find((item) => item.key === node.config?.template_key || item.type === type && item.skill === node.skill)
    const skill = node?.skill || node?.data?.skill || node?.config?.skill || template?.skill || ''
    const label = String(node?.data?.label || node?.label || template?.label || type)
    return {
      id: String(node.id || normalizeNodeFallbackId(node, type, skill, label)),
      type,
      skill: skill || undefined,
      tool: node.tool,
      depends_on: Array.isArray(node.depends_on) ? node.depends_on.map(String) : [],
      position: node.position || { x: 80 + (index % 3) * 260, y: 80 + Math.floor(index / 3) * 170 },
      data: {
        label: String(node?.data?.label || node?.label || template?.label || NODE_TYPE_LABELS[type] || type),
        skill,
        description: node?.data?.description || template?.description || '',
      },
      config: node.config || {},
    }
  })
}

function buildDag(nodes: WorkflowNode[]) {
  return {
    nodes: nodes.map((node) => ({
      id: node.id,
      type: node.type,
      skill: node.type === 'skill' ? node.skill || node.data.skill || undefined : undefined,
      tool: node.tool || undefined,
      depends_on: node.depends_on || [],
      position: node.position,
      data: node.data,
      config: {
        ...node.config,
        node_type: node.type,
        skill: node.type === 'skill' ? node.skill || node.data.skill || undefined : undefined,
      },
    })),
  }
}

function skillLabel(skillName: string | undefined, skills: SkillCatalogEntry[]) {
  if (!skillName) return '未绑定 Skill'
  const skill = skills.find((item) => item.name === skillName)
  return skill?.effective_display_name || skill?.display_name || skillName
}

function validationMessage(result: WorkflowDagValidation | null) {
  if (!result) return '尚未校验'
  if (result.valid) return `校验通过，执行顺序：${result.execution_order.join(' -> ') || '无'}`
  return result.issues.map((issue) => issue.node_id ? `${issue.node_id}: ${issue.message}` : issue.message).join('；')
}

function nodeStatusClass(node: WorkflowNode) {
  if (node.type === 'skill') return 'border-blue-200 bg-blue-50 text-blue-950 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-100'
  if (node.type === 'human_approval') return 'border-slate-300 bg-slate-50 text-slate-950 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100'
  if (node.type === 'condition') return 'border-rose-200 bg-rose-50 text-rose-950 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-100'
  if (node.type === 'parallel_group') return 'border-cyan-200 bg-cyan-50 text-cyan-950 dark:border-cyan-900 dark:bg-cyan-950 dark:text-cyan-100'
  return 'border-orange-200 bg-orange-50 text-orange-950 dark:border-orange-900 dark:bg-orange-950 dark:text-orange-100'
}

export default function WorkflowEditorPage({ params }: WorkflowEditorPageProps) {
  const { workflowId } = use(params)
  const isNewWorkflow = workflowId === 'new'
  const router = useRouter()
  const queryClient = useQueryClient()
  const { addToast } = useToast()

  const [workflowName, setWorkflowName] = useState('')
  const [workflowDescription, setWorkflowDescription] = useState('')
  const [workflowCategory, setWorkflowCategory] = useState('custom')
  const [nodes, setNodes] = useState<WorkflowNode[]>([])
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [showSaveDialog, setShowSaveDialog] = useState(false)
  const [validationResult, setValidationResult] = useState<WorkflowDagValidation | null>(null)
  const [previewResult, setPreviewResult] = useState<WorkflowDagPreview | null>(null)

  const workflowQuery = useQuery({
    queryKey: ['workflow', workflowId],
    queryFn: () => agentApi.getWorkflow(workflowId),
    enabled: !isNewWorkflow,
  })

  const versionsQuery = useQuery({
    queryKey: ['workflow-versions', workflowId],
    queryFn: () => agentApi.listWorkflowVersions(workflowId, { pageSize: 20 }),
    enabled: !isNewWorkflow,
  })

  const skillsQuery = useQuery({
    queryKey: ['workflow-editor-skills'],
    queryFn: () => agentApi.listSkillCatalog({ pageSize: 200, status: 'published' }),
  })

  const projectsQuery = useQuery({
    queryKey: ['projects-for-editor-workflow-run'],
    queryFn: () => projectsApi.list({ pageSize: 1 }),
  })

  const skills = useMemo(() => skillsQuery.data?.items || [], [skillsQuery.data?.items])
  const activeVersion = versionsQuery.data?.items?.find((version) => version.is_active) || versionsQuery.data?.items?.[0]
  const selectedNode = nodes.find((node) => node.id === selectedNodeId) || null
  const selectedProjectId = projectsQuery.data?.items?.[0]?.id || ''

  const summary = useMemo(() => ({
    nodes: nodes.length,
    edges: nodes.reduce((total, node) => total + node.depends_on.length, 0),
    skills: nodes.filter((node) => node.type === 'skill').length,
    approvals: nodes.filter((node) => node.type === 'human_approval').length,
    conditions: nodes.filter((node) => node.type === 'condition').length,
    warnings: validationResult?.issues.filter((issue) => issue.severity === 'warning').length || 0,
  }), [nodes, validationResult])

  const flowNodes: Node[] = useMemo(() => nodes.map((node) => ({
    id: node.id,
    type: 'default',
    position: node.position,
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
    data: {
      label: (
        <div className="min-w-[180px]">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate text-sm font-semibold">{node.data.label}</span>
            <span className="rounded bg-white/70 px-1.5 py-0.5 text-[10px] dark:bg-black/20">{NODE_TYPE_LABELS[node.type]}</span>
          </div>
          <div className="mt-1 truncate text-xs opacity-75">
            {node.type === 'skill' ? skillLabel(node.skill || node.data.skill, skills) : node.config.expression || node.config.approver_role || node.config.parallel_mode || `${node.config.delay_minutes || 0} 分钟`}
          </div>
        </div>
      ),
    },
    className: nodeStatusClass(node),
  })), [nodes, skills])

  const flowEdges: Edge[] = useMemo(() => nodes.flatMap((node) => (
    node.depends_on.map((dependency) => ({
      id: `${dependency}->${node.id}`,
      source: dependency,
      target: node.id,
      animated: node.type === 'condition' || node.type === 'parallel_group',
      markerEnd: { type: MarkerType.ArrowClosed },
      style: { strokeWidth: 2 },
    }))
  )), [nodes])

  useEffect(() => {
    if (isNewWorkflow) {
      setWorkflowName('新工作流')
      setWorkflowDescription('用于项目文档生成、质量评审、审批和交付导出的智能编排流程。')
      setWorkflowCategory('custom')
      setNodes([])
      return
    }

    if (workflowQuery.data) {
      setWorkflowName(workflowQuery.data.name)
      setWorkflowDescription(workflowQuery.data.description || '')
      setWorkflowCategory(workflowQuery.data.category || 'custom')
      setNodes(normalizeNodes(activeVersion?.dag_json?.nodes || workflowQuery.data.graph_data?.nodes || []))
    }
  }, [activeVersion?.dag_json, isNewWorkflow, workflowQuery.data])

  const invalidatePlan = () => {
    setValidationResult(null)
    setPreviewResult(null)
  }

  const addNode = (template: NodeTemplate) => {
    setNodes((current) => [...current, createNode(template, current.length, current.at(-1)?.id)])
    invalidatePlan()
  }

  const updateNode = (nodeId: string, patch: Partial<WorkflowNode>) => {
    setNodes((current) => current.map((node) => node.id === nodeId ? { ...node, ...patch } : node))
    invalidatePlan()
  }

  const updateSelectedNodeConfig = (patch: Record<string, any>) => {
    if (!selectedNode) return
    updateNode(selectedNode.id, { config: { ...selectedNode.config, ...patch } })
  }

  const deleteNode = (nodeId: string) => {
    setNodes((current) => current
      .filter((node) => node.id !== nodeId)
      .map((node) => ({ ...node, depends_on: node.depends_on.filter((dependency) => dependency !== nodeId) }))
    )
    if (selectedNodeId === nodeId) setSelectedNodeId(null)
    invalidatePlan()
  }

  const connectToPrevious = () => {
    if (!selectedNode) return
    const index = nodes.findIndex((node) => node.id === selectedNode.id)
    if (index <= 0) return
    updateNode(selectedNode.id, { depends_on: [nodes[index - 1].id] })
  }

  const validateWorkflowMutation = useMutation({
    mutationFn: () => agentApi.validateWorkflowDag({ dag_json: buildDag(nodes) }),
    onSuccess: (result) => {
      setValidationResult(result)
      addToast({
        title: result.valid ? '工作流校验通过' : '工作流校验未通过',
        description: validationMessage(result),
        variant: result.valid ? undefined : 'destructive',
      })
    },
    onError: (error: Error) => addToast({ title: '工作流校验失败', description: error.message, variant: 'destructive' }),
  })

  const previewWorkflowMutation = useMutation({
    mutationFn: async () => {
      const dag = buildDag(nodes)
      return agentApi.previewWorkflowDag({ dag_json: dag, input_data: { source: 'workflow_editor_preview' } })
    },
    onSuccess: (result) => {
      setPreviewResult(result)
      addToast({
        title: result.blocking_issues.length > 0 ? '运行计划存在阻塞' : '运行计划已生成',
        description: `预计 ${result.estimated_steps} 步，${result.approval_gates.length} 个人工关口，${result.parallel_groups.length} 个并行组。`,
        variant: result.blocking_issues.length > 0 ? 'destructive' : undefined,
      })
    },
    onError: (error: Error) => addToast({ title: '运行计划生成失败', description: error.message, variant: 'destructive' }),
  })

  const saveWorkflowMutation = useMutation({
    mutationFn: async ({ publish }: { publish: boolean }) => {
      const name = workflowName.trim()
      if (!name) throw new Error('请输入工作流名称。')
      if (nodes.length === 0) throw new Error('请至少添加一个节点。')

      const dag = buildDag(nodes)
      const validation = await agentApi.validateWorkflowDag({ dag_json: dag })
      setValidationResult(validation)
      if (!validation.valid) {
        throw new Error(validation.issues.find((issue) => issue.severity === 'error')?.message || 'DAG 校验未通过。')
      }

      const workflowRecord = isNewWorkflow
        ? await agentApi.createWorkflow({
            name,
            description: workflowDescription || undefined,
            category: workflowCategory,
          })
        : await agentApi.updateWorkflow(workflowId, {
            name,
            description: workflowDescription || undefined,
            category: workflowCategory,
            is_active: publish ? true : undefined,
          })

      const version = await agentApi.createWorkflowVersion(workflowRecord.id, {
        dag_json: dag,
        skill_contracts: [],
        tool_contracts: [],
      })

      if (publish) {
        await agentApi.activateWorkflowVersion(workflowRecord.id, version.id)
        await agentApi.updateWorkflow(workflowRecord.id, { is_active: true })
      }

      return workflowRecord
    },
    onSuccess: (savedWorkflow, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workflows'] })
      queryClient.invalidateQueries({ queryKey: ['workflow', savedWorkflow.id] })
      queryClient.invalidateQueries({ queryKey: ['workflow-versions', savedWorkflow.id] })
      queryClient.invalidateQueries({ queryKey: ['orchestration-dashboard'] })
      setShowSaveDialog(false)
      addToast({
        title: variables.publish ? '工作流已发布' : '工作流已保存',
        description: '流程定义、DAG 节点和版本信息已写入后端。',
      })
      if (isNewWorkflow) router.replace(`/workflows/${savedWorkflow.id}/editor`)
    },
    onError: (error: Error) => addToast({ title: '保存工作流失败', description: error.message, variant: 'destructive' }),
  })

  const runWorkflowMutation = useMutation({
    mutationFn: () => {
      if (isNewWorkflow) throw new Error('请先保存并发布工作流。')
      if (!selectedProjectId) throw new Error('暂无可运行项目，请先创建项目。')
      if (!activeVersion?.id || !activeVersion.is_active) throw new Error('当前工作流没有已发布版本。')
      return agentApi.executeWorkflow({
        workflow_id: workflowId,
        version_id: activeVersion.id,
        project_id: selectedProjectId,
        input_data: {
          source: 'workflow_editor',
          workflow_name: workflowName,
          workflow_category: workflowCategory,
        },
      })
    },
    onSuccess: (response) => {
      addToast({ title: '工作流已开始运行', description: `运行记录 ${response.run_id} 已创建。` })
      router.push(`/agent-ops?runId=${response.run_id}`)
    },
    onError: (error: Error) => addToast({ title: '运行工作流失败', description: error.message, variant: 'destructive' }),
  })

  if (workflowQuery.isLoading) {
    return (
      <div className="flex h-64 items-center justify-center text-slate-500">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        正在加载工作流编辑器...
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 border-b border-slate-200 pb-4 dark:border-slate-800 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <Button variant="ghost" size="sm" onClick={() => router.push('/workflows')} aria-label="返回工作流列表">
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div className="min-w-0">
            <Input
              value={workflowName}
              onChange={(event) => setWorkflowName(event.target.value)}
              className="h-auto border-none bg-transparent p-0 text-xl font-semibold text-slate-900 shadow-none focus-visible:ring-0 dark:text-white"
              placeholder="工作流名称"
            />
            <p className="mt-1 text-sm text-slate-500">{isNewWorkflow ? '新建工作流' : `当前版本 v${activeVersion?.version || '-'}`}</p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => validateWorkflowMutation.mutate()} disabled={validateWorkflowMutation.isPending || nodes.length === 0}>
            {validateWorkflowMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <CheckCircle2 className="mr-2 h-4 w-4" />}
            校验
          </Button>
          <Button variant="outline" onClick={() => previewWorkflowMutation.mutate()} disabled={previewWorkflowMutation.isPending || nodes.length === 0}>
            {previewWorkflowMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Route className="mr-2 h-4 w-4" />}
            运行计划
          </Button>
          <Button variant="outline" onClick={() => setShowSaveDialog(true)} disabled={saveWorkflowMutation.isPending}>
            <Save className="mr-2 h-4 w-4" />
            保存
          </Button>
          <Button onClick={() => saveWorkflowMutation.mutate({ publish: true })} disabled={saveWorkflowMutation.isPending || nodes.length === 0}>
            {saveWorkflowMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <ShieldCheck className="mr-2 h-4 w-4" />}
            发布
          </Button>
          <Button variant="outline" onClick={() => runWorkflowMutation.mutate()} disabled={runWorkflowMutation.isPending || isNewWorkflow}>
            {runWorkflowMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
            执行
          </Button>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)_340px]">
        <Card className="h-fit">
          <CardHeader>
            <CardTitle className="text-base">节点组件</CardTitle>
            <CardDescription>组合 Skill、审批、条件、并行和等待节点，构建可运行 DAG。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {NODE_TEMPLATES.map((template) => {
              const Icon = template.icon
              return (
                <button
                  key={template.key}
                  type="button"
                  className="flex w-full items-center gap-3 rounded-md border border-slate-200 p-3 text-left transition hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
                  onClick={() => addNode(template)}
                >
                  <span className={`rounded-md p-2 ${template.color}`}>
                    <Icon className="h-4 w-4 text-white" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-sm font-medium text-slate-900 dark:text-white">{template.label}</span>
                    <span className="block truncate text-xs text-slate-500">{template.description}</span>
                  </span>
                  <Plus className="ml-auto h-4 w-4 text-slate-400" />
                </button>
              )
            })}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-3 xl:grid-cols-6">
            <Card><CardContent className="pt-4"><p className="text-xl font-semibold text-slate-900 dark:text-white">{summary.nodes}</p><p className="text-xs text-slate-500">节点</p></CardContent></Card>
            <Card><CardContent className="pt-4"><p className="text-xl font-semibold text-slate-900 dark:text-white">{summary.edges}</p><p className="text-xs text-slate-500">依赖</p></CardContent></Card>
            <Card><CardContent className="pt-4"><p className="text-xl font-semibold text-slate-900 dark:text-white">{summary.skills}</p><p className="text-xs text-slate-500">Skill</p></CardContent></Card>
            <Card><CardContent className="pt-4"><p className="text-xl font-semibold text-slate-900 dark:text-white">{summary.approvals}</p><p className="text-xs text-slate-500">审批</p></CardContent></Card>
            <Card><CardContent className="pt-4"><p className="text-xl font-semibold text-slate-900 dark:text-white">{summary.conditions}</p><p className="text-xs text-slate-500">分支</p></CardContent></Card>
            <Card><CardContent className="pt-4"><p className="text-xl font-semibold text-slate-900 dark:text-white">{summary.warnings}</p><p className="text-xs text-slate-500">警告</p></CardContent></Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">DAG 可视化画布</CardTitle>
              <CardDescription>{validationMessage(validationResult)}</CardDescription>
            </CardHeader>
            <CardContent>
              {nodes.length === 0 ? (
                <div className="flex min-h-[520px] flex-col items-center justify-center rounded-md border border-dashed border-slate-300 text-center dark:border-slate-700">
                  <Workflow className="h-14 w-14 text-slate-300" />
                  <p className="mt-4 text-base font-medium text-slate-900 dark:text-white">从左侧添加节点构建工作流</p>
                  <p className="mt-2 max-w-md text-sm text-slate-500">成熟编排支持 Skill、人工审批、条件分支、并行评审和等待窗口。</p>
                </div>
              ) : (
                <div data-testid="workflow-visual-canvas" className="h-[560px] overflow-hidden rounded-md border border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-950">
                  <ReactFlow
                    nodes={flowNodes}
                    edges={flowEdges}
                    fitView
                    onNodeClick={(_, node) => setSelectedNodeId(node.id)}
                    onNodeDragStop={(_, node) => updateNode(node.id, { position: node.position })}
                  >
                    <Background />
                    <Controls />
                  </ReactFlow>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">运行计划预览</CardTitle>
              <CardDescription>运行前确认执行顺序、审批关口、条件分支和阻塞项。</CardDescription>
            </CardHeader>
            <CardContent>
              {!previewResult ? (
                <div className="rounded-md border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-slate-700">
                  点击“运行计划”调用后端预检，生成执行顺序、控制关口和阻塞项。
                </div>
              ) : (
                <div className="grid gap-3 lg:grid-cols-2">
                  <div className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
                    <p className="text-sm font-medium text-slate-900 dark:text-white">执行顺序</p>
                    <p className="mt-2 text-xs text-slate-500">{previewResult.execution_order.join(' -> ') || '无'}</p>
                  </div>
                  <div className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
                    <p className="text-sm font-medium text-slate-900 dark:text-white">门禁摘要</p>
                    <p className="mt-2 text-xs text-slate-500">
                      {previewResult.approval_gates.length} 个审批，{previewResult.condition_paths.length} 个条件，{previewResult.parallel_groups.length} 个并行组。
                    </p>
                  </div>
                  {previewResult.blocking_issues.length > 0 && (
                    <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-100 lg:col-span-2">
                      {previewResult.blocking_issues.map((issue) => issue.message).join('；')}
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <Card className="h-fit">
          <CardHeader>
            <CardTitle className="text-base">属性面板</CardTitle>
            <CardDescription>{selectedNode ? '编辑当前节点、依赖和控制参数。' : '选择画布中的节点查看属性。'}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300">工作流说明</label>
              <textarea
                value={workflowDescription}
                onChange={(event) => setWorkflowDescription(event.target.value)}
                className="min-h-20 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                placeholder="说明这个工作流解决什么问题"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300">分类</label>
              <Select value={workflowCategory} onValueChange={setWorkflowCategory}>
                {Object.entries(CATEGORY_LABELS).map(([value, label]) => (
                  <SelectOption key={value} value={value}>{label}</SelectOption>
                ))}
              </Select>
            </div>

            {!selectedNode ? (
              <div className="rounded-md border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-slate-700">
                暂未选择节点。
              </div>
            ) : (
              <div className="space-y-4 border-t border-slate-200 pt-4 dark:border-slate-700">
                <div className="flex items-center justify-between gap-3">
                  <Badge variant="secondary">{NODE_TYPE_LABELS[selectedNode.type]}</Badge>
                  <Button variant="ghost" size="sm" onClick={() => deleteNode(selectedNode.id)}>
                    <Trash2 className="mr-1 h-4 w-4 text-red-500" />
                    删除
                  </Button>
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium text-slate-700 dark:text-slate-300">节点名称</label>
                  <Input
                    value={selectedNode.data.label}
                    onChange={(event) => updateNode(selectedNode.id, { data: { ...selectedNode.data, label: event.target.value } })}
                  />
                </div>
                {selectedNode.type === 'skill' && (
                  <div className="space-y-2">
                    <label className="text-sm font-medium text-slate-700 dark:text-slate-300">绑定 Skill</label>
                    <Select
                      value={selectedNode.skill || selectedNode.data.skill || ''}
                      onValueChange={(value) => updateNode(selectedNode.id, {
                        skill: value || undefined,
                        data: { ...selectedNode.data, skill: value },
                        config: { ...selectedNode.config, skill: value || undefined },
                      })}
                    >
                      <SelectOption value="">不绑定</SelectOption>
                      {skills.map((skill) => (
                        <SelectOption key={skill.id} value={skill.name}>{skill.effective_display_name || skill.display_name || skill.name}</SelectOption>
                      ))}
                    </Select>
                  </div>
                )}
                {selectedNode.type === 'human_approval' && (
                  <div className="grid gap-3">
                    <div className="space-y-2">
                      <label className="text-sm font-medium text-slate-700 dark:text-slate-300">审批角色</label>
                      <Input value={selectedNode.config.approver_role || ''} onChange={(event) => updateSelectedNodeConfig({ approver_role: event.target.value })} />
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-medium text-slate-700 dark:text-slate-300">SLA 小时</label>
                      <Input type="number" value={selectedNode.config.sla_hours || 24} onChange={(event) => updateSelectedNodeConfig({ sla_hours: Number(event.target.value) })} />
                    </div>
                  </div>
                )}
                {selectedNode.type === 'condition' && (
                  <div className="grid gap-3">
                    <div className="space-y-2">
                      <label className="text-sm font-medium text-slate-700 dark:text-slate-300">条件表达式</label>
                      <Input value={selectedNode.config.expression || ''} onChange={(event) => updateSelectedNodeConfig({ expression: event.target.value })} />
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <Input value={selectedNode.config.true_label || ''} onChange={(event) => updateSelectedNodeConfig({ true_label: event.target.value })} placeholder="满足条件标签" />
                      <Input value={selectedNode.config.false_label || ''} onChange={(event) => updateSelectedNodeConfig({ false_label: event.target.value })} placeholder="不满足条件标签" />
                    </div>
                  </div>
                )}
                {selectedNode.type === 'parallel_group' && (
                  <div className="grid gap-3">
                    <div className="space-y-2">
                      <label className="text-sm font-medium text-slate-700 dark:text-slate-300">汇合策略</label>
                      <Select value={selectedNode.config.join_policy || 'wait_all'} onValueChange={(value) => updateSelectedNodeConfig({ join_policy: value })}>
                        <SelectOption value="wait_all">等待全部完成</SelectOption>
                        <SelectOption value="first_success">任一成功即可继续</SelectOption>
                        <SelectOption value="manual_merge">人工汇总后继续</SelectOption>
                      </Select>
                    </div>
                  </div>
                )}
                {selectedNode.type === 'delay' && (
                  <div className="grid gap-3">
                    <div className="space-y-2">
                      <label className="text-sm font-medium text-slate-700 dark:text-slate-300">等待分钟</label>
                      <Input type="number" value={selectedNode.config.delay_minutes || 60} onChange={(event) => updateSelectedNodeConfig({ delay_minutes: Number(event.target.value) })} />
                    </div>
                  </div>
                )}
                <div className="space-y-2">
                  <label className="text-sm font-medium text-slate-700 dark:text-slate-300">依赖节点</label>
                  <Input
                    value={selectedNode.depends_on.join(',')}
                    onChange={(event) => updateNode(selectedNode.id, {
                      depends_on: event.target.value.split(',').map((item) => item.trim()).filter(Boolean),
                    })}
                    placeholder="用逗号分隔节点 ID"
                  />
                  <Button variant="outline" size="sm" onClick={connectToPrevious} disabled={!selectedNode || nodes.findIndex((node) => node.id === selectedNode.id) <= 0}>
                    连接到上一节点
                  </Button>
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium text-slate-700 dark:text-slate-300">节点说明</label>
                  <textarea
                    value={selectedNode.data.description || ''}
                    onChange={(event) => updateNode(selectedNode.id, { data: { ...selectedNode.data, description: event.target.value } })}
                    className="min-h-20 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                  />
                </div>
                <div className="rounded-md bg-slate-50 p-3 text-xs text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                  节点 ID：{selectedNode.id}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Dialog open={showSaveDialog} onOpenChange={setShowSaveDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>保存工作流</DialogTitle>
            <DialogDescription>保存会创建一个新版本；发布会把新版本设为活动版本。</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300">工作流名称</label>
              <Input value={workflowName} onChange={(event) => setWorkflowName(event.target.value)} />
            </div>
            <div className="rounded-md bg-slate-50 p-3 text-sm text-slate-600 dark:bg-slate-900 dark:text-slate-300">
              当前包含 {nodes.length} 个节点、{summary.edges} 条依赖、{summary.approvals} 个人工审批、{summary.conditions} 个条件分支。
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowSaveDialog(false)}>取消</Button>
            <Button variant="outline" onClick={() => saveWorkflowMutation.mutate({ publish: false })} disabled={saveWorkflowMutation.isPending}>
              {saveWorkflowMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
              保存草稿
            </Button>
            <Button onClick={() => saveWorkflowMutation.mutate({ publish: true })} disabled={saveWorkflowMutation.isPending}>
              发布版本
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
