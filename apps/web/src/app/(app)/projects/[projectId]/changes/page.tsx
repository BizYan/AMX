'use client'

import { use, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, ArrowLeft, Check, Clock, FileText, GitBranch, Search } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectOption } from '@/components/ui/select'
import { changeApi } from '@/lib/api-client'
import type { ChangeRequest } from '@/lib/api-client'
import { useToast } from '@/components/ui/toast'

interface ChangesPageProps {
  params: Promise<{ projectId: string }>
}

type BoardChange = Omit<ChangeRequest, 'status' | 'priority'> & {
  status: 'draft' | 'open' | 'triage' | 'approved' | 'rejected' | 'applied' | 'cancelled'
  priority: 'critical' | 'high' | 'medium' | 'low'
  impact_level?: 'critical' | 'high' | 'medium' | 'low'
  affected_documents?: Array<{ id: string; title: string; type: string; reason: string }>
  disposition_records?: Array<{ at: string; actor: string; action: string; note: string }>
  human_confirmation_node?: string
  sync_proposal?: string
}

const statusLabels: Record<string, string> = {
  draft: '草稿',
  open: '待处置',
  triage: '待分诊',
  approved: '已确认',
  rejected: '已拒绝',
  applied: '已处置',
  cancelled: '已取消',
}

const priorityLabels: Record<string, string> = {
  critical: 'P0',
  high: 'P1',
  medium: 'P2',
  low: 'P3',
}

function badgeVariant(level: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (level === 'critical' || level === 'high') return 'destructive'
  if (level === 'medium') return 'secondary'
  return 'outline'
}

function titleOf(change: BoardChange) {
  return change.title || (change as any).name || change.description?.split('\n')[0] || '未命名变更'
}

export default function ChangesPage({ params }: ChangesPageProps) {
  const { projectId } = use(params)
  const router = useRouter()
  const queryClient = useQueryClient()
  const { addToast } = useToast()
  const [statusFilter, setStatusFilter] = useState('')
  const [search, setSearch] = useState('')
  const [selectedChangeId, setSelectedChangeId] = useState<string | null>(null)
  const [feedback, setFeedback] = useState('')
  const [localStatuses, setLocalStatuses] = useState<Record<string, BoardChange['status']>>({})
  const [localRecords, setLocalRecords] = useState<Record<string, BoardChange['disposition_records']>>({})

  const { data: changesData, isLoading } = useQuery({
    queryKey: ['project-changes', projectId, 'board'],
    queryFn: () => changeApi.list({ projectId, pageSize: 100 }),
  })

  const changes = useMemo(
    () => (changesData?.items || []).map((change) => ({
      ...(change as BoardChange),
      status: localStatuses[change.id] || change.status,
      disposition_records: localRecords[change.id] || (change as BoardChange).disposition_records || [],
    })),
    [changesData?.items, localRecords, localStatuses]
  )

  const normalizedSearch = search.trim().toLowerCase()
  const filteredChanges = changes.filter((change) => {
    const matchesStatus = !statusFilter || change.status === statusFilter
    const haystack = [
      titleOf(change),
      change.description,
      change.priority,
      change.impact_level,
      change.sync_proposal,
      change.human_confirmation_node,
      ...(change.affected_documents || []).flatMap((doc) => [doc.title, doc.type, doc.reason]),
    ].join(' ').toLowerCase()
    const matchesSearch = !normalizedSearch || haystack.includes(normalizedSearch)
    return matchesStatus && matchesSearch
  })

  const selectedChange = changes.find((change) => change.id === selectedChangeId) || filteredChanges[0] || changes[0]

  const actionMutation = useMutation({
    mutationFn: ({ id }: { id: string }) => changeApi.apply(id),
    onSuccess: (updated) => {
      const record = {
        at: new Date().toISOString(),
        actor: '当前用户',
        action: '已标记处置',
        note: '前端处置台记录人工确认与同步动作反馈。',
      }
      setLocalStatuses((current) => ({ ...current, [updated.id]: 'applied' }))
      setLocalRecords((current) => ({ ...current, [updated.id]: [record, ...(current[updated.id] || [])] }))
      setFeedback('已标记处置：最近处置记录已更新')
      queryClient.invalidateQueries({ queryKey: ['project-changes', projectId, 'board'] })
      addToast({ title: '已标记处置', description: '处置动作已记录在当前工作台' })
    },
    onError: (error: Error) => {
      addToast({ title: '处置变更失败', description: error.message, variant: 'destructive' })
    },
  })

  if (isLoading) {
    return <div className="flex h-64 items-center justify-center text-slate-500">正在加载变更处置台...</div>
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center">
        <Button variant="ghost" size="sm" onClick={() => router.push(`/projects/${projectId}`)} className="w-fit">
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex flex-1 items-center gap-3">
          <div className="rounded-lg bg-indigo-100 p-2 dark:bg-indigo-900">
            <GitBranch className="h-6 w-6 text-indigo-600 dark:text-indigo-300" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">变更请求处置台</h1>
            <p className="text-sm text-slate-500">按优先级、状态、影响文档和人工确认节点处理项目变更。</p>
          </div>
        </div>
        <div className="text-sm text-slate-600" data-testid="change-feedback">{feedback || '等待处置动作'}</div>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        {(['critical', 'high', 'medium', 'low'] as const).map((priority) => (
          <Card key={priority}>
            <CardHeader className="pb-2"><CardTitle className="text-sm">{priorityLabels[priority]} 影响</CardTitle></CardHeader>
            <CardContent>
              <div className="text-3xl font-semibold">{changes.filter((change) => change.priority === priority || change.impact_level === priority).length}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardContent className="grid gap-3 py-4 lg:grid-cols-[1fr_180px_auto] lg:items-center">
          <div className="relative">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
            <Input data-testid="change-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索 URS、PRD、测试用例缺失或处置节点" className="pl-9" />
          </div>
          <Select data-testid="change-status-filter" value={statusFilter} onValueChange={setStatusFilter}>
            <SelectOption value="">全部状态</SelectOption>
            <SelectOption value="triage">待分诊</SelectOption>
            <SelectOption value="open">待处置</SelectOption>
            <SelectOption value="approved">已确认</SelectOption>
            <SelectOption value="applied">已处置</SelectOption>
            <SelectOption value="rejected">已拒绝</SelectOption>
          </Select>
          <div className="text-sm text-slate-500" data-testid="change-count">{filteredChanges.length} 个变更</div>
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(360px,1.05fr)]">
        <Card data-testid="change-queue">
          <CardHeader>
            <CardTitle className="text-base">变更请求队列</CardTitle>
            <CardDescription>优先处理 P0/P1，P2/P3 保留处置记录和人工确认节点。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {filteredChanges.length === 0 ? (
              <div className="rounded-md border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">没有匹配的变更请求</div>
            ) : filteredChanges.map((change) => (
              <button
                key={change.id}
                type="button"
                onClick={() => setSelectedChangeId(change.id)}
                className="w-full rounded-md border border-slate-200 p-4 text-left hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
                data-testid={`change-select-${change.id}`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={badgeVariant(change.priority)}>{priorityLabels[change.priority] || change.priority}</Badge>
                  <Badge variant="outline">{statusLabels[change.status] || change.status}</Badge>
                  <span className="font-medium text-slate-900 dark:text-white">{titleOf(change)}</span>
                </div>
                <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{change.description}</p>
                <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                  {(change.affected_documents || []).map((doc) => (
                    <span key={doc.id} className="rounded bg-slate-100 px-2 py-1 dark:bg-slate-800">{doc.type.toUpperCase()} · {doc.title}</span>
                  ))}
                </div>
              </button>
            ))}
          </CardContent>
        </Card>

        <Card data-testid="change-detail">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base"><AlertCircle className="h-4 w-4" />变更详情与处置动作</CardTitle>
            <CardDescription>查看受影响文档、同步提案、人工确认节点和最近处置记录。</CardDescription>
          </CardHeader>
          <CardContent>
            {selectedChange ? (
              <div className="space-y-5">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={badgeVariant(selectedChange.priority)}>{priorityLabels[selectedChange.priority] || selectedChange.priority}</Badge>
                    <Badge variant="secondary">{statusLabels[selectedChange.status] || selectedChange.status}</Badge>
                  </div>
                  <h2 className="mt-3 text-lg font-semibold text-slate-900 dark:text-white">{titleOf(selectedChange)}</h2>
                  <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{selectedChange.description}</p>
                </div>

                <div>
                  <h3 className="mb-2 flex items-center gap-2 text-sm font-medium"><FileText className="h-4 w-4" />受影响文档</h3>
                  <div className="space-y-2">
                    {(selectedChange.affected_documents || []).map((doc) => (
                      <div key={doc.id} className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
                        <div className="font-medium">{doc.title}</div>
                        <div className="text-xs text-slate-500">{doc.type.toUpperCase()} · {doc.reason}</div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="rounded-md bg-slate-50 p-4 text-sm dark:bg-slate-800">
                  <div className="font-medium">同步提案</div>
                  <p className="mt-1 text-slate-600 dark:text-slate-300">{selectedChange.sync_proposal || '等待同步提案'}</p>
                  <p className="mt-2 text-xs text-slate-500">{selectedChange.human_confirmation_node || '人工确认节点'}</p>
                </div>

                <Button
                  onClick={() => actionMutation.mutate({ id: selectedChange.id })}
                  disabled={actionMutation.isPending || selectedChange.status === 'applied'}
                  data-testid={`change-mark-resolved-${selectedChange.id}`}
                >
                  <Check className="mr-2 h-4 w-4" />
                  标记已处置
                </Button>

                <div data-testid="change-recent-records">
                  <h3 className="mb-2 flex items-center gap-2 text-sm font-medium"><Clock className="h-4 w-4" />最近处置记录</h3>
                  <div className="space-y-2">
                    {(selectedChange.disposition_records || []).length === 0 ? (
                      <div className="rounded-md border border-dashed border-slate-300 p-4 text-sm text-slate-500">暂无处置记录</div>
                    ) : selectedChange.disposition_records?.map((record, index) => (
                      <div key={`${record.at}-${index}`} className="rounded-md border border-slate-200 p-3 text-sm dark:border-slate-700">
                        <div className="font-medium">{record.action}</div>
                        <div className="text-xs text-slate-500">{record.actor} · {record.note}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className="rounded-md border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">请选择变更请求</div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
