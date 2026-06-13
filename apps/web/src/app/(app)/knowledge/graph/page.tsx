'use client'

import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  Background,
  Controls,
  Edge,
  MarkerType,
  Node,
  ReactFlow,
  useEdgesState,
  useNodesState,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Download,
  FileSearch,
  GitBranch,
  Loader2,
  Network,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
} from 'lucide-react'

import { apiClient } from '@/lib/api-client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectOption } from '@/components/ui/select'
import { useToast } from '@/components/ui/toast'

type GraphStatus = 'ready' | 'gap' | 'conflict'

interface ProjectOption {
  id: string
  name: string
}

interface KnowledgeGraphNode {
  id: string
  type: string
  title: string
  summary: string
  project_id: string
  source_file_id?: string | null
  source_label: string
  status: GraphStatus | string
  confidence?: number | null
  metadata: Record<string, any>
  created_at: string
  updated_at?: string | null
}

interface KnowledgeGraphEdge {
  id: string
  source: string
  target: string
  type: string
  confidence?: number | null
  metadata: Record<string, any>
  created_at: string
}

interface KnowledgeGraphWorkbench {
  nodes: KnowledgeGraphNode[]
  edges: KnowledgeGraphEdge[]
  summary: {
    node_count: number
    edge_count: number
    source_count: number
    ready_count: number
    gap_count: number
    conflict_count: number
    isolated_count: number
  }
  gaps: KnowledgeGraphNode[]
  isolated_nodes: KnowledgeGraphNode[]
}

interface KnowledgeLineageRecord {
  id: string
  source_type: string
  source_id: string
  target_type: string
  target_id: string
  lineage_type: string
  metadata_json?: Record<string, any>
  created_at: string
}

interface KnowledgeProvenanceRecord {
  id: string
  provider_id: string
  provider_version_id?: string | null
  raw_artifact_id?: string | null
  confidence?: number | null
  normalization_notes?: string | null
  created_at: string
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

interface CapabilityActivationAction {
  key: string
  label: string
  capability_key: string
  action_type: string
  status: string
  can_execute: boolean
  requires_confirmation: boolean
  description: string
  evidence: Record<string, any>
}

interface CapabilityActivationResponse {
  actions: CapabilityActivationAction[]
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

const statusLabel: Record<string, string> = {
  ready: '可用',
  gap: '缺口',
  conflict: '冲突',
}

const statusClass: Record<string, string> = {
  ready: 'border-emerald-300 bg-emerald-50 text-emerald-800',
  gap: 'border-amber-300 bg-amber-50 text-amber-900',
  conflict: 'border-rose-300 bg-rose-50 text-rose-900',
}

const typeLabel: Record<string, string> = {
  text: '文本',
  table: '表格',
  image: '图片',
  code: '代码',
}

const linkTypeLabel: Record<string, string> = {
  cites: '引用',
  extends: '扩展',
  depends_on: '依赖',
  implements: '实现',
}

function compactText(value: string, max = 90) {
  const normalized = value.replace(/\s+/g, ' ').trim()
  return normalized.length > max ? `${normalized.slice(0, max)}...` : normalized
}

function evidenceNumber(evidence: Record<string, any> | undefined, keys: string[], fallback = 0) {
  if (!evidence) return fallback
  for (const key of keys) {
    const value = Number(evidence[key])
    if (Number.isFinite(value)) return value
  }
  return fallback
}

function buildFlowNodes(nodes: KnowledgeGraphNode[], selectedId: string | null): Node[] {
  const radius = Math.max(220, nodes.length * 36)
  return nodes.map((node, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(nodes.length, 1)
    const isSelected = node.id === selectedId
    return {
      id: node.id,
      position: {
        x: Math.cos(angle) * radius + radius + 80,
        y: Math.sin(angle) * radius + radius + 40,
      },
      data: {
        label: compactText(node.title, 34),
        sublabel: statusLabel[node.status] ?? node.status,
      },
      style: {
        width: 190,
        minHeight: 64,
        borderRadius: 8,
        border: isSelected ? '2px solid #4f46e5' : '1px solid #cbd5e1',
        background: node.status === 'conflict' ? '#fff1f2' : node.status === 'gap' ? '#fffbeb' : '#f8fafc',
        color: '#0f172a',
        fontSize: 12,
        padding: 10,
        boxShadow: isSelected ? '0 12px 28px rgba(79, 70, 229, 0.22)' : '0 8px 20px rgba(15, 23, 42, 0.08)',
      },
    }
  })
}

function buildFlowEdges(edges: KnowledgeGraphEdge[]): Edge[] {
  return edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    label: linkTypeLabel[edge.type] ?? edge.type,
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, color: '#6366f1' },
    style: { stroke: '#6366f1', strokeWidth: 2 },
    labelStyle: { fill: '#334155', fontSize: 11 },
    labelBgStyle: { fill: '#ffffff', fillOpacity: 0.9 },
  }))
}

export default function KnowledgeGraphPage() {
  const searchParams = useSearchParams()
  const { addToast } = useToast()
  const initialProjectId = searchParams.get('projectId') || ''
  const initialSourceFileId = searchParams.get('sourceFileId') || ''
  const initialSelectedNodeId = searchParams.get('selected') || null

  const [projectId, setProjectId] = useState(initialProjectId)
  const [sourceFileId] = useState(initialSourceFileId)
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [typeFilter, setTypeFilter] = useState('all')
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(initialSelectedNodeId)
  const [remoteResultIds, setRemoteResultIds] = useState<string[]>([])
  const [remoteSearchError, setRemoteSearchError] = useState<string | null>(null)
  const [newTitle, setNewTitle] = useState('')
  const [newContent, setNewContent] = useState('')
  const [newStatus, setNewStatus] = useState<GraphStatus>('ready')
  const [targetNodeId, setTargetNodeId] = useState('')
  const [linkType, setLinkType] = useState('cites')

  const [flowNodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [flowEdges, setEdges, onEdgesChange] = useEdgesState<Edge>([])

  const { data: projectsData } = useQuery({
    queryKey: ['knowledge-project-options'],
    queryFn: () => apiClient.get<{ items?: ProjectOption[]; projects?: ProjectOption[] }>('/projects', { page_size: 100 }),
  })

  const projects = projectsData?.items ?? projectsData?.projects ?? []

  const graphQuery = useQuery({
    queryKey: ['knowledge-graph-workbench', projectId, sourceFileId, typeFilter],
    queryFn: () =>
      apiClient.get<KnowledgeGraphWorkbench>('/knowledge/graph', {
        project_id: projectId || undefined,
        source_file_id: sourceFileId || undefined,
        entry_type: typeFilter === 'all' ? undefined : typeFilter,
        limit: 240,
      }),
  })

  const readinessQuery = useQuery({
    queryKey: ['knowledge-production-readiness'],
    queryFn: () => apiClient.get<CapabilityReadinessResponse>('/ops/capabilities/readiness'),
  })

  const commissioningQuery = useQuery({
    queryKey: ['knowledge-production-commissioning'],
    queryFn: () => apiClient.get<CapabilityCommissioningResponse>('/ops/capabilities/commissioning'),
  })

  const activationPlanQuery = useQuery({
    queryKey: ['knowledge-production-activation-plan'],
    queryFn: () => apiClient.get<CapabilityActivationResponse>('/ops/capabilities/activation-plan'),
  })

  const graph = graphQuery.data
  const nodes = useMemo(() => graph?.nodes ?? [], [graph?.nodes])
  const edges = useMemo(() => graph?.edges ?? [], [graph?.edges])
  const knowledgeCapability = readinessQuery.data?.capabilities.find((capability) => capability.key === 'knowledge_graph')
  const knowledgeCommissioningCheck = commissioningQuery.data?.checks.find((check) => check.key === 'knowledge_graph_evidence')
  const knowledgeActivationActions = (activationPlanQuery.data?.actions ?? []).filter(
    (action) => action.capability_key === 'knowledge_graph'
  )
  const knowledgeEvidence = knowledgeCapability?.evidence
  const knowledgeEvidenceItems = [
    {
      key: 'source_file_count',
      label: '来源资料',
      value: evidenceNumber(knowledgeEvidence, ['source_file_count', 'source_files'], graph?.summary.source_count ?? 0),
    },
    {
      key: 'knowledge_entry_count',
      label: '知识条目',
      value: evidenceNumber(knowledgeEvidence, ['knowledge_entry_count', 'knowledge_entries'], graph?.summary.node_count ?? 0),
    },
    {
      key: 'knowledge_link_count',
      label: '图谱关系',
      value: evidenceNumber(knowledgeEvidence, ['knowledge_link_count', 'knowledge_links'], graph?.summary.edge_count ?? 0),
    },
    {
      key: 'gap_count',
      label: '缺口',
      value: graph?.summary.gap_count ?? 0,
    },
    {
      key: 'isolated_count',
      label: '孤立节点',
      value: graph?.summary.isolated_count ?? 0,
    },
  ]

  const filteredNodes = useMemo(() => {
    const normalizedQuery = searchQuery.trim().toLowerCase()
    const remoteFilter = remoteResultIds.length ? new Set(remoteResultIds) : null
    return nodes.filter((node) => {
      const matchesStatus = statusFilter === 'all' || node.status === statusFilter
      const haystack = [node.title, node.summary, node.source_label, node.type, JSON.stringify(node.metadata)]
        .join(' ')
        .toLowerCase()
      const matchesQuery = !normalizedQuery || haystack.includes(normalizedQuery)
      const matchesRemote = !remoteFilter || remoteFilter.has(node.id)
      return matchesStatus && matchesQuery && matchesRemote
    })
  }, [nodes, remoteResultIds, searchQuery, statusFilter])

  const filteredNodeIds = useMemo(() => new Set(filteredNodes.map((node) => node.id)), [filteredNodes])
  const filteredEdges = useMemo(
    () => edges.filter((edge) => filteredNodeIds.has(edge.source) && filteredNodeIds.has(edge.target)),
    [edges, filteredNodeIds]
  )

  useEffect(() => {
    setNodes(buildFlowNodes(filteredNodes, selectedNodeId))
    setEdges(buildFlowEdges(filteredEdges))
  }, [filteredEdges, filteredNodes, selectedNodeId, setEdges, setNodes])

  useEffect(() => {
    if (!selectedNodeId && filteredNodes.length) {
      setSelectedNodeId(filteredNodes[0].id)
    }
    if (selectedNodeId && !filteredNodeIds.has(selectedNodeId)) {
      setSelectedNodeId(filteredNodes[0]?.id ?? null)
    }
  }, [filteredNodeIds, filteredNodes, selectedNodeId])

  const selectedNode = nodes.find((node) => node.id === selectedNodeId) ?? null
  const connectedEdges = selectedNode
    ? edges.filter((edge) => edge.source === selectedNode.id || edge.target === selectedNode.id)
    : []

  const lineageQuery = useQuery({
    queryKey: ['knowledge-node-lineage', selectedNodeId],
    queryFn: () => apiClient.get<KnowledgeLineageRecord[]>(`/knowledge/entries/${selectedNodeId}/lineage`),
    enabled: Boolean(selectedNodeId),
  })

  const provenanceQuery = useQuery({
    queryKey: ['knowledge-node-provenance', selectedNodeId],
    queryFn: () => apiClient.get<KnowledgeProvenanceRecord[]>(`/knowledge/provenance/${selectedNodeId}`),
    enabled: Boolean(selectedNodeId),
  })

  const createMutation = useMutation({
    mutationFn: () =>
      apiClient.post('/knowledge/entries', {
        project_id: projectId,
        entry_type: 'text',
        content: newContent,
        sharing_scope: 'project',
        generate_embedding: false,
        metadata: {
          title: newTitle,
          state: newStatus,
          source: '顾问手工补充',
          summary: compactText(newContent, 180),
        },
      }),
    onSuccess: async () => {
      setNewTitle('')
      setNewContent('')
      setNewStatus('ready')
      await graphQuery.refetch()
      addToast({ title: '知识条目已创建', description: '新条目已进入图谱，可继续补链或用于文档生成。' })
    },
    onError: (error) => {
      addToast({
        title: '创建失败',
        description: error instanceof Error ? error.message : '知识条目未能保存。',
        variant: 'destructive',
      })
    },
  })

  const linkMutation = useMutation({
    mutationFn: () =>
      apiClient.post(`/knowledge/entries/${selectedNodeId}/link`, {
        source_entry_id: selectedNodeId,
        target_entry_id: targetNodeId,
        link_type: linkType,
        confidence: 0.9,
        metadata: { source: 'knowledge-workbench' },
      }),
    onSuccess: async () => {
      setTargetNodeId('')
      await graphQuery.refetch()
      addToast({ title: '关联已建立', description: '图谱边已保存，后续检索和血缘审计会使用该关系。' })
    },
    onError: (error) => {
      addToast({
        title: '关联失败',
        description: error instanceof Error ? error.message : '知识关联未能保存。',
        variant: 'destructive',
      })
    },
  })

  const deleteLinkMutation = useMutation({
    mutationFn: (edgeId: string) => apiClient.delete(`/knowledge/links/${edgeId}`),
    onSuccess: async () => {
      await graphQuery.refetch()
      addToast({ title: '关系已删除', description: '错误或过期的图谱关系已从当前知识图谱中移除。' })
    },
    onError: (error) => {
      addToast({
        title: '删除失败',
        description: error instanceof Error ? error.message : '知识关系未能删除。',
        variant: 'destructive',
      })
    },
  })

  const runCommissioningMutation = useMutation({
    mutationFn: () => apiClient.post<CapabilityCommissioningResponse>('/ops/capabilities/commissioning/run', {
      checks: ['knowledge_graph_evidence'],
    }),
    onSuccess: async () => {
      await Promise.all([commissioningQuery.refetch(), readinessQuery.refetch()])
      addToast({ title: '知识图谱校准已完成', description: '来源、条目和关系证据已按投产标准重新检查。' })
    },
    onError: (error) => {
      addToast({
        title: '知识图谱校准失败',
        description: error instanceof Error ? error.message : '生产校准未能完成。',
        variant: 'destructive',
      })
    },
  })

  const runActivationMutation = useMutation({
    mutationFn: (actions: string[]) => apiClient.post<CapabilityActivationResponse>('/ops/capabilities/activation-run', {
      dry_run: false,
      confirm: true,
      actions,
    }),
    onSuccess: async () => {
      await Promise.all([
        graphQuery.refetch(),
        readinessQuery.refetch(),
        commissioningQuery.refetch(),
        activationPlanQuery.refetch(),
      ])
      addToast({ title: '知识图谱证据已初始化', description: '来源文件、知识条目和关系边已重新检查并写入生产证据。' })
    },
    onError: (error) => {
      addToast({
        title: '知识图谱初始化失败',
        description: error instanceof Error ? error.message : '安全初始化动作未能完成。',
        variant: 'destructive',
      })
    },
  })

  const exportGraph = () => {
    const payload = {
      exported_at: new Date().toISOString(),
      project_id: projectId || null,
      source_file_id: sourceFileId || null,
      summary: graph?.summary,
      nodes: filteredNodes,
      edges: filteredEdges,
    }
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `knowledge-graph-${projectId || 'all'}-${Date.now()}.json`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
    addToast({ title: '图谱已导出', description: '当前筛选范围内的节点和关系已导出为 JSON。' })
  }

  const runRemoteSearch = async () => {
    const query = searchQuery.trim()
    if (!query) {
      setRemoteResultIds([])
      setRemoteSearchError(null)
      return
    }

    try {
      const result = await apiClient.get<{ results: Array<{ entry?: { id: string }; node?: { id: string } }> }>('/knowledge/search', {
        q: query,
        type: 'fulltext',
        project_id: projectId || undefined,
        top_k: 30,
      })
      const ids = result.results.map((item) => item.entry?.id ?? item.node?.id).filter(Boolean) as string[]
      setRemoteResultIds(ids)
      setRemoteSearchError(null)
      addToast({ title: '检索完成', description: `已返回 ${ids.length} 条可定位知识。` })
    } catch (error) {
      setRemoteResultIds([])
      const detail = error instanceof Error ? error.message : '后端全文检索服务暂不可用。'
      setRemoteSearchError(`全文检索不可用：${detail} 当前仅显示原始图谱和手动筛选结果，请恢复检索索引后重试。`)
      addToast({
        title: '全文检索不可用',
        description: detail,
        variant: 'destructive',
      })
    }
  }

  const canCreate = Boolean(projectId && newTitle.trim() && newContent.trim())
  const canLink = Boolean(selectedNodeId && targetNodeId && targetNodeId !== selectedNodeId)

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">知识图谱</h1>
          <p className="mt-1 text-sm text-slate-500">
            汇总项目材料、知识条目、图谱关联、缺口冲突和可追溯证据，为文档生成提供可信上下文。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => void graphQuery.refetch()}>
            <RefreshCw className="mr-2 h-4 w-4" />
            刷新
          </Button>
          <Button variant="outline" disabled={!filteredNodes.length} onClick={exportGraph}>
            <Download className="mr-2 h-4 w-4" />
            导出图谱
          </Button>
          <Button asChild>
            <Link href={projectId ? `/projects/${projectId}/documents/generate` : '/projects'}>
              <Plus className="mr-2 h-4 w-4" />
              用知识生成文档
            </Link>
          </Button>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-7">
        {[
          ['知识条目', graph?.summary.node_count ?? 0],
          ['图谱关系', graph?.summary.edge_count ?? 0],
          ['来源材料', graph?.summary.source_count ?? 0],
          ['可用', graph?.summary.ready_count ?? 0],
          ['缺口', graph?.summary.gap_count ?? 0],
          ['冲突', graph?.summary.conflict_count ?? 0],
          ['孤立节点', graph?.summary.isolated_count ?? 0],
        ].map(([label, value]) => (
          <div key={label} className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900/40">
            <p className="text-sm text-slate-500">{label}</p>
            <p className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{value}</p>
          </div>
        ))}
      </div>

      <Card data-testid="knowledge-production-loop">
        <CardHeader>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <CardTitle>知识图谱生产闭环</CardTitle>
              <CardDescription>把来源资料、知识条目、图谱关系、缺口和投产校准放在同一个入口。</CardDescription>
            </div>
            <Badge variant={knowledgeCapability?.status === 'ready' ? 'secondary' : knowledgeCapability?.status === 'blocked' ? 'destructive' : 'outline'}>
              {readinessQuery.isLoading ? '检查中' : knowledgeCapability?.status === 'ready' ? '已就绪' : knowledgeCapability?.status === 'degraded' ? '需补关系' : knowledgeCapability?.status === 'blocked' ? '阻塞' : '未校准'}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="space-y-4">
            <div>
              <p className="font-semibold text-slate-900 dark:text-white">{knowledgeCapability?.label || '知识图谱与来源追溯'}</p>
              <p className="mt-1 text-sm text-slate-500">{knowledgeCapability?.summary || '正在读取知识图谱生产准备度。'}</p>
            </div>
            <div data-testid="knowledge-production-evidence-grid" className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
              {knowledgeEvidenceItems.map((item) => (
                <div key={item.key} data-testid={`knowledge-production-evidence-${item.key}`} className="rounded-md border border-slate-200 px-3 py-2 dark:border-slate-800">
                  <p className="text-xs text-slate-500">{item.label}</p>
                  <p className="mt-1 text-lg font-semibold text-slate-900 dark:text-white">{item.value}</p>
                </div>
              ))}
            </div>
            {knowledgeCapability?.blockers?.length ? (
              <div className="rounded-md bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
                {knowledgeCapability.blockers[0]}
              </div>
            ) : null}
          </div>
          <div className="space-y-3 rounded-lg border border-slate-200 p-4 dark:border-slate-800">
            <div>
              <p className="font-semibold text-slate-900 dark:text-white">{knowledgeCommissioningCheck?.label || '来源知识图谱校准'}</p>
              <p className="mt-1 text-sm text-slate-500">{knowledgeCommissioningCheck?.summary || '按来源、条目和关系证据检查投产可用性。'}</p>
            </div>
            {knowledgeCommissioningCheck?.blockers?.length ? (
              <p className="text-sm text-amber-700 dark:text-amber-200">{knowledgeCommissioningCheck.blockers[0]}</p>
            ) : null}
            {knowledgeActivationActions.length ? (
              <div className="space-y-2">
                {knowledgeActivationActions.map((action) => (
                  <Button
                    key={action.key}
                    data-testid={`knowledge-activation-action-${action.key}`}
                    variant="outline"
                    className="w-full justify-between"
                    disabled={action.action_type !== 'safe' || !action.can_execute || runActivationMutation.isPending}
                    onClick={() => runActivationMutation.mutate([action.key])}
                  >
                    <span>{runActivationMutation.isPending ? '初始化中...' : action.label}</span>
                    {runActivationMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
                  </Button>
                ))}
              </div>
            ) : (
              <p className="text-sm text-slate-500">当前没有可执行初始化动作。</p>
            )}
            <Button
              data-testid="knowledge-production-commissioning-run"
              className="w-full"
              disabled={!knowledgeCommissioningCheck?.can_run || runCommissioningMutation.isPending}
              onClick={() => runCommissioningMutation.mutate()}
            >
              {runCommissioningMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <ShieldCheck className="mr-2 h-4 w-4" />}
              {runCommissioningMutation.isPending ? '校准中...' : '运行知识图谱校准'}
            </Button>
            <Button data-testid="knowledge-production-source-link" variant="outline" className="w-full" asChild>
              <Link href={projectId ? `/projects/${projectId}/files` : '/projects'}>
                补齐来源资料
              </Link>
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="py-4">
          <div className="grid gap-3 xl:grid-cols-[minmax(220px,0.8fr)_minmax(280px,1.6fr)_160px_140px_auto]">
            <Select
              value={projectId || 'all'}
              onValueChange={(value) => {
                setProjectId(value === 'all' ? '' : value)
                setRemoteResultIds([])
                setRemoteSearchError(null)
              }}
            >
              <SelectOption value="all">全部项目</SelectOption>
              {projects.map((project) => (
                <SelectOption key={project.id} value={project.id}>
                  {project.name}
                </SelectOption>
              ))}
            </Select>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <Input
                className="pl-10"
                placeholder="搜索知识、来源、证据或结论"
                value={searchQuery}
                onChange={(event) => {
                  setSearchQuery(event.target.value)
                  if (!event.target.value.trim()) {
                    setRemoteResultIds([])
                    setRemoteSearchError(null)
                  }
                }}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') void runRemoteSearch()
                }}
              />
            </div>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectOption value="all">全部状态</SelectOption>
              <SelectOption value="ready">可用</SelectOption>
              <SelectOption value="gap">缺口</SelectOption>
              <SelectOption value="conflict">冲突</SelectOption>
            </Select>
            <Select value={typeFilter} onValueChange={setTypeFilter}>
              <SelectOption value="all">全部类型</SelectOption>
              <SelectOption value="text">文本</SelectOption>
              <SelectOption value="table">表格</SelectOption>
              <SelectOption value="image">图片</SelectOption>
              <SelectOption value="code">代码</SelectOption>
            </Select>
            <Button onClick={() => void runRemoteSearch()}>
              <FileSearch className="mr-2 h-4 w-4" />
              全文检索
            </Button>
          </div>
          {remoteSearchError && (
            <div
              data-testid="knowledge-search-error"
              className="mt-4 flex gap-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-100"
            >
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <div className="space-y-1">
                <p className="font-medium">全文检索不可用</p>
                <p>{remoteSearchError}</p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.4fr)_420px]">
        <Card className="min-h-[620px]">
          <CardHeader>
            <CardTitle>图谱画布</CardTitle>
            <CardDescription>
              当前显示 {filteredNodes.length} 个节点、{filteredEdges.length} 条关系。点击节点查看来源、证据和可执行动作。
            </CardDescription>
          </CardHeader>
          <CardContent className="h-[520px] p-0">
            {graphQuery.isLoading ? (
              <div className="flex h-full items-center justify-center text-slate-500">
                <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                正在加载知识图谱...
              </div>
            ) : filteredNodes.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center px-6 text-center text-slate-500">
                <Network className="h-14 w-14 text-slate-300" />
                <p className="mt-4 text-base font-medium text-slate-700 dark:text-slate-200">暂无匹配的知识节点</p>
                <p className="mt-2 text-sm">上传项目材料、创建知识条目或放宽筛选条件后即可查看图谱。</p>
              </div>
            ) : (
              <ReactFlow
                nodes={flowNodes}
                edges={flowEdges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onNodeClick={(_, node) => setSelectedNodeId(node.id)}
                fitView
                minZoom={0.35}
                className="bg-slate-50 dark:bg-slate-950"
              >
                <Controls />
                <Background color="#cbd5e1" gap={18} />
              </ReactFlow>
            )}
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>节点详情</CardTitle>
              <CardDescription>查看来源、可信度、上下游关系和写作动作。</CardDescription>
            </CardHeader>
            <CardContent>
              {!selectedNode ? (
                <div className="rounded-lg border border-slate-200 p-4 text-sm text-slate-500 dark:border-slate-800">
                  请选择一个知识节点。
                </div>
              ) : (
                <div className="space-y-4">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="text-lg font-semibold text-slate-900 dark:text-white">{selectedNode.title}</h2>
                      <Badge className={statusClass[selectedNode.status] ?? statusClass.ready}>
                        {statusLabel[selectedNode.status] ?? selectedNode.status}
                      </Badge>
                    </div>
                    <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{selectedNode.summary}</p>
                  </div>
                  <div className="grid gap-3 text-sm sm:grid-cols-2">
                    <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                      <p className="text-slate-500">来源</p>
                      <p className="mt-1 font-medium text-slate-900 dark:text-white">{selectedNode.source_label}</p>
                    </div>
                    <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                      <p className="text-slate-500">类型/可信度</p>
                      <p className="mt-1 font-medium text-slate-900 dark:text-white">
                        {typeLabel[selectedNode.type] ?? selectedNode.type}
                        {selectedNode.confidence ? ` · ${Math.round(selectedNode.confidence * 100)}%` : ''}
                      </p>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <p className="text-sm font-medium text-slate-700 dark:text-slate-200">关系</p>
                    {connectedEdges.length === 0 ? (
                      <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                        当前节点还没有关系，建议补充上游来源或下游影响。
                      </p>
                    ) : (
                      connectedEdges.map((edge) => {
                        const otherId = edge.source === selectedNode.id ? edge.target : edge.source
                        const otherNode = nodes.find((node) => node.id === otherId)
                        return (
                          <div key={edge.id} className="rounded-lg border border-slate-200 p-3 text-sm dark:border-slate-800">
                            <div className="flex items-start justify-between gap-3">
                              <div>
                                <p className="font-medium text-slate-900 dark:text-white">
                                  {edge.source === selectedNode.id ? '指向' : '来自'}：{otherNode?.title ?? otherId}
                                </p>
                                <p className="mt-1 text-slate-500">
                                  {linkTypeLabel[edge.type] ?? edge.type}
                                  {edge.confidence ? ` · ${Math.round(edge.confidence * 100)}%` : ''}
                                </p>
                              </div>
                              <Button
                                variant="ghost"
                                size="sm"
                                aria-label={`删除关系 ${edge.id}`}
                                disabled={deleteLinkMutation.isPending}
                                onClick={() => deleteLinkMutation.mutate(edge.id)}
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            </div>
                          </div>
                        )
                      })
                    )}
                  </div>
                  <div className="grid gap-3 text-sm">
                    <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                      <p className="font-medium text-slate-700 dark:text-slate-200">来源证据</p>
                      {provenanceQuery.isLoading ? (
                        <p className="mt-2 text-slate-500">正在加载来源证据...</p>
                      ) : (provenanceQuery.data ?? []).length === 0 ? (
                        <p className="mt-2 text-slate-500">暂无来源证据记录。</p>
                      ) : (
                        <div className="mt-2 space-y-2">
                          {provenanceQuery.data!.map((item) => (
                            <div key={item.id} className="rounded border border-slate-100 p-2 dark:border-slate-800">
                              <p className="font-medium text-slate-900 dark:text-white">{item.provider_id}</p>
                              <p className="mt-1 text-slate-500">
                                {item.raw_artifact_id ? `原始材料：${item.raw_artifact_id}` : '未记录原始材料'}
                                {item.confidence ? ` · ${Math.round(item.confidence * 100)}%` : ''}
                              </p>
                              {item.normalization_notes ? <p className="mt-1 text-slate-500">{item.normalization_notes}</p> : null}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                    <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                      <p className="font-medium text-slate-700 dark:text-slate-200">血缘记录</p>
                      {lineageQuery.isLoading ? (
                        <p className="mt-2 text-slate-500">正在加载血缘记录...</p>
                      ) : (lineageQuery.data ?? []).length === 0 ? (
                        <p className="mt-2 text-slate-500">暂无血缘记录。</p>
                      ) : (
                        <div className="mt-2 space-y-2">
                          {lineageQuery.data!.map((item) => (
                            <div key={item.id} className="rounded border border-slate-100 p-2 dark:border-slate-800">
                              <p className="font-medium text-slate-900 dark:text-white">{item.lineage_type}</p>
                              <p className="mt-1 text-slate-500">
                                {item.source_type}:{item.source_id} → {item.target_type}:{item.target_id}
                              </p>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button asChild size="sm">
                      <Link href={`/projects/${selectedNode.project_id}/documents/generate?knowledgeEntryId=${selectedNode.id}`}>
                        <Plus className="mr-2 h-4 w-4" />
                        加入生成上下文
                      </Link>
                    </Button>
                    <Button asChild variant="outline" size="sm">
                      <Link href={`/projects/${selectedNode.project_id}/knowledge`}>
                        <GitBranch className="mr-2 h-4 w-4" />
                        项目知识
                      </Link>
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>补充关系</CardTitle>
              <CardDescription>为选中节点建立引用、依赖、扩展或实现关系。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <Select value={targetNodeId || 'none'} onValueChange={(value) => setTargetNodeId(value === 'none' ? '' : value)}>
                <SelectOption value="none">选择目标节点</SelectOption>
                {nodes
                  .filter((node) => node.id !== selectedNodeId)
                  .map((node) => (
                    <SelectOption key={node.id} value={node.id}>
                      {compactText(node.title, 26)}
                    </SelectOption>
                  ))}
              </Select>
              <Select value={linkType} onValueChange={setLinkType}>
                <SelectOption value="cites">引用</SelectOption>
                <SelectOption value="extends">扩展</SelectOption>
                <SelectOption value="depends_on">依赖</SelectOption>
                <SelectOption value="implements">实现</SelectOption>
              </Select>
              <Button className="w-full" disabled={!canLink || linkMutation.isPending} onClick={() => linkMutation.mutate()}>
                {linkMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Network className="mr-2 h-4 w-4" />}
                保存关系
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
        <Card>
          <CardHeader>
            <CardTitle>缺口与冲突</CardTitle>
            <CardDescription>生成文档前需要补证、确认或人工裁决的知识项。</CardDescription>
          </CardHeader>
          <CardContent>
            {(graph?.gaps ?? []).length === 0 ? (
              <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
                <CheckCircle2 className="h-4 w-4" />
                当前没有阻塞性缺口或冲突。
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-2">
                {graph!.gaps.map((node) => (
                  <button
                    key={node.id}
                    type="button"
                    onClick={() => setSelectedNodeId(node.id)}
                    className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-left text-sm text-amber-950 transition hover:border-amber-400"
                  >
                    <div className="flex items-start gap-2">
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                      <div>
                        <p className="font-semibold">{node.title}</p>
                        <p className="mt-1">{node.metadata.gap || node.metadata.conflict || node.summary}</p>
                        <p className="mt-2 text-xs">来源：{node.source_label}</p>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>新建知识条目</CardTitle>
            <CardDescription>把顾问确认后的事实、规则或风险写回项目知识图谱。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Input placeholder="条目标题" value={newTitle} onChange={(event) => setNewTitle(event.target.value)} />
            <textarea
              className="min-h-[120px] w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-indigo-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
              placeholder="输入已确认的知识、证据、约束或待补充说明"
              value={newContent}
              onChange={(event) => setNewContent(event.target.value)}
            />
            <Select value={newStatus} onValueChange={(value) => setNewStatus(value as GraphStatus)}>
              <SelectOption value="ready">可用知识</SelectOption>
              <SelectOption value="gap">待补充缺口</SelectOption>
              <SelectOption value="conflict">待裁决冲突</SelectOption>
            </Select>
            <Button className="w-full" disabled={!canCreate || createMutation.isPending} onClick={() => createMutation.mutate()}>
              {createMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <ShieldCheck className="mr-2 h-4 w-4" />}
              保存到图谱
            </Button>
            {!projectId && <p className="text-xs text-amber-600">请选择项目后再新增知识条目。</p>}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
