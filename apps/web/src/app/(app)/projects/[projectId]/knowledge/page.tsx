'use client'

import Link from 'next/link'
import { use, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  BookOpenCheck,
  CheckCircle2,
  FileText,
  GitBranch,
  Loader2,
  Network,
  PlusCircle,
  RefreshCw,
  Search,
  ShieldCheck,
} from 'lucide-react'

import { apiClient } from '@/lib/api-client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectOption } from '@/components/ui/select'
import { useToast } from '@/components/ui/toast'

interface KnowledgePageProps {
  params: Promise<{ projectId: string }>
}

type KnowledgeFilter = 'all' | 'ready' | 'gap' | 'conflict' | 'isolated'

interface KnowledgeGraphNode {
  id: string
  type: string
  title: string
  summary: string
  project_id: string
  source_file_id?: string | null
  source_label: string
  status: 'ready' | 'gap' | 'conflict' | string
  confidence?: number | null
  metadata: Record<string, any>
  created_at: string
}

interface KnowledgeGraphEdge {
  id: string
  source: string
  target: string
  type: string
  confidence?: number | null
  metadata: Record<string, any>
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

const linkTypeLabel: Record<string, string> = {
  cites: '引用',
  extends: '扩展',
  depends_on: '依赖',
  implements: '实现',
}

function compactText(value: string, max = 120) {
  const normalized = value.replace(/\s+/g, ' ').trim()
  return normalized.length > max ? `${normalized.slice(0, max)}...` : normalized
}

export default function KnowledgePage({ params }: KnowledgePageProps) {
  const { projectId } = use(params)
  const { addToast } = useToast()
  const [searchQuery, setSearchQuery] = useState('')
  const [filter, setFilter] = useState<KnowledgeFilter>('all')
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [newTitle, setNewTitle] = useState('')
  const [newContent, setNewContent] = useState('')
  const [newStatus, setNewStatus] = useState<'ready' | 'gap' | 'conflict'>('ready')

  const graphQuery = useQuery({
    queryKey: ['project-knowledge-workbench', projectId],
    queryFn: () =>
      apiClient.get<KnowledgeGraphWorkbench>('/knowledge/graph', {
        project_id: projectId,
        limit: 240,
      }),
  })

  const graph = graphQuery.data
  const nodes = useMemo(() => graph?.nodes ?? [], [graph?.nodes])
  const isolatedIds = useMemo(() => new Set((graph?.isolated_nodes ?? []).map((node) => node.id)), [graph?.isolated_nodes])

  const filteredNodes = useMemo(() => {
    const normalizedQuery = searchQuery.trim().toLowerCase()
    return nodes.filter((node) => {
      const matchesFilter =
        filter === 'all' ||
        node.status === filter ||
        (filter === 'isolated' && isolatedIds.has(node.id))
      const haystack = [node.title, node.summary, node.source_label, node.type, JSON.stringify(node.metadata)]
        .join(' ')
        .toLowerCase()
      return matchesFilter && (!normalizedQuery || haystack.includes(normalizedQuery))
    })
  }, [filter, isolatedIds, nodes, searchQuery])

  const selectedNodes = nodes.filter((node) => selectedIds.includes(node.id))
  const edgesByNode = useMemo(() => {
    const map = new Map<string, KnowledgeGraphEdge[]>()
    for (const edge of graph?.edges ?? []) {
      map.set(edge.source, [...(map.get(edge.source) ?? []), edge])
      map.set(edge.target, [...(map.get(edge.target) ?? []), edge])
    }
    return map
  }, [graph?.edges])

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
      addToast({ title: '知识条目已保存', description: '已写入项目知识图谱，可用于生成上下文和追溯。' })
    },
    onError: (error) => {
      addToast({
        title: '保存失败',
        description: error instanceof Error ? error.message : '知识条目未能保存。',
        variant: 'destructive',
      })
    },
  })

  const toggleSelected = (id: string) => {
    setSelectedIds((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id].slice(-8)))
  }

  const addSelectedToContext = () => {
    if (!selectedNodes.length) return
    addToast({
      title: '已加入生成上下文',
      description: `${selectedNodes.length} 条知识已准备好随下一次文档生成使用。`,
    })
  }

  if (graphQuery.isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="mr-2 h-5 w-5 animate-spin text-indigo-500" />
        <span className="text-sm text-slate-500">正在加载项目知识...</span>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">项目知识工作台</h1>
          <p className="mt-1 text-sm text-slate-500">
            管理项目材料抽取出的知识、证据、缺口、冲突和图谱关系，并把可信知识送入文档生成流程。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline">
            <Link href={`/projects/${projectId}/files`}>
              <PlusCircle className="mr-2 h-4 w-4" />
              补充资料
            </Link>
          </Button>
          <Button asChild>
            <Link href={`/knowledge/graph?projectId=${projectId}`}>
              <Network className="mr-2 h-4 w-4" />
              打开图谱
            </Link>
          </Button>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-7">
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

      <Card>
        <CardContent className="py-4">
          <div className="grid gap-3 lg:grid-cols-[minmax(260px,1fr)_180px_auto_auto]">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <Input
                placeholder="搜索知识、来源、证据或结论"
                className="pl-10"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
              />
            </div>
            <Select value={filter} onValueChange={(value) => setFilter(value as KnowledgeFilter)}>
              <SelectOption value="all">全部状态</SelectOption>
              <SelectOption value="ready">可用</SelectOption>
              <SelectOption value="gap">缺口</SelectOption>
              <SelectOption value="conflict">冲突</SelectOption>
              <SelectOption value="isolated">孤立节点</SelectOption>
            </Select>
            <Button variant="outline" onClick={() => void graphQuery.refetch()}>
              <RefreshCw className="mr-2 h-4 w-4" />
              刷新
            </Button>
            <Button disabled={!selectedNodes.length} onClick={addSelectedToContext}>
              <BookOpenCheck className="mr-2 h-4 w-4" />
              加入生成上下文
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.45fr)_420px]">
        <Card>
          <CardHeader>
            <CardTitle>项目知识条目</CardTitle>
            <CardDescription>选择条目后可送入生成上下文；有缺口或冲突的条目需要先补证或裁决。</CardDescription>
          </CardHeader>
          <CardContent>
            {filteredNodes.length === 0 ? (
              <div className="py-14 text-center text-slate-500">
                <Network className="mx-auto h-12 w-12 text-slate-300" />
                <p className="mt-3 text-sm">暂无匹配知识。请上传材料、手工补充条目或调整筛选。</p>
              </div>
            ) : (
              <div className="space-y-3">
                {filteredNodes.map((node) => {
                  const selected = selectedIds.includes(node.id)
                  const relatedEdges = edgesByNode.get(node.id) ?? []
                  return (
                    <div
                      key={node.id}
                      className={`rounded-lg border p-4 transition ${
                        selected
                          ? 'border-indigo-400 bg-indigo-50 dark:border-indigo-500 dark:bg-indigo-950/30'
                          : 'border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950/20'
                      }`}
                    >
                      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <h2 className="text-base font-semibold text-slate-900 dark:text-white">{node.title}</h2>
                            <Badge className={statusClass[node.status] ?? statusClass.ready}>
                              {statusLabel[node.status] ?? node.status}
                            </Badge>
                            {isolatedIds.has(node.id) && <Badge variant="outline">待补关系</Badge>}
                          </div>
                          <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{compactText(node.summary, 180)}</p>
                          <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                            <span className="inline-flex items-center gap-1">
                              <FileText className="h-3.5 w-3.5" />
                              来源：{node.source_label}
                            </span>
                            <span>类型：{node.type}</span>
                            <span>关系：{relatedEdges.length}</span>
                            {node.confidence ? <span>可信度：{Math.round(node.confidence * 100)}%</span> : null}
                          </div>
                        </div>
                        <div className="flex shrink-0 flex-wrap gap-2">
                          <Button size="sm" variant={selected ? 'default' : 'outline'} onClick={() => toggleSelected(node.id)}>
                            {selected ? <CheckCircle2 className="mr-2 h-4 w-4" /> : <PlusCircle className="mr-2 h-4 w-4" />}
                            {selected ? '已选择' : '选择'}
                          </Button>
                          <Button asChild size="sm" variant="outline">
                            <Link href={`/knowledge/graph?projectId=${projectId}&selected=${node.id}`}>
                              <GitBranch className="mr-2 h-4 w-4" />
                              图谱定位
                            </Link>
                          </Button>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>缺口/冲突提示</CardTitle>
              <CardDescription>这些项目会影响后续文档生成质量和验收可信度。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {(graph?.gaps ?? []).length === 0 ? (
                <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
                  <CheckCircle2 className="h-4 w-4" />
                  当前没有阻塞性缺口或冲突。
                </div>
              ) : (
                graph!.gaps.map((node) => (
                  <button
                    key={node.id}
                    type="button"
                    className="w-full rounded-lg border border-amber-200 bg-amber-50 p-3 text-left text-sm text-amber-900"
                    onClick={() => {
                      setSearchQuery(node.title)
                      setFilter('all')
                    }}
                  >
                    <div className="flex items-start gap-2">
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                      <div>
                        <p className="font-medium">{node.title}</p>
                        <p className="mt-1">{node.metadata.gap || node.metadata.conflict || node.summary}</p>
                        <p className="mt-1 text-xs">来源：{node.source_label}</p>
                      </div>
                    </div>
                  </button>
                ))
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>下一步动作</CardTitle>
              <CardDescription>把知识结果推进到交付文档和图谱治理。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              <Button asChild className="w-full justify-start">
                <Link href={`/projects/${projectId}/documents/generate`}>
                  <PlusCircle className="mr-2 h-4 w-4" />
                  用项目知识生成文档
                </Link>
              </Button>
              <Button asChild variant="outline" className="w-full justify-start">
                <Link href={`/knowledge/graph?projectId=${projectId}`}>
                  <Network className="mr-2 h-4 w-4" />
                  打开完整知识图谱
                </Link>
              </Button>
              <Button asChild variant="outline" className="w-full justify-start">
                <Link href={`/projects/${projectId}/files`}>
                  <FileText className="mr-2 h-4 w-4" />
                  补充或重传资料
                </Link>
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>手工补充知识</CardTitle>
              <CardDescription>把顾问确认后的事实或待裁决问题写回知识库。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <Input placeholder="条目标题" value={newTitle} onChange={(event) => setNewTitle(event.target.value)} />
              <textarea
                className="min-h-[110px] w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-indigo-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                placeholder="输入确认后的知识、证据、缺口或冲突描述"
                value={newContent}
                onChange={(event) => setNewContent(event.target.value)}
              />
              <Select value={newStatus} onValueChange={(value) => setNewStatus(value as typeof newStatus)}>
                <SelectOption value="ready">可用知识</SelectOption>
                <SelectOption value="gap">待补充缺口</SelectOption>
                <SelectOption value="conflict">待裁决冲突</SelectOption>
              </Select>
              <Button
                className="w-full"
                disabled={!newTitle.trim() || !newContent.trim() || createMutation.isPending}
                onClick={() => createMutation.mutate()}
              >
                {createMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <ShieldCheck className="mr-2 h-4 w-4" />}
                保存到项目知识
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
