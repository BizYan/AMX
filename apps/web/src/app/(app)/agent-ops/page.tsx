'use client'

import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRouter, useSearchParams } from 'next/navigation'
import {
  AlertTriangle,
  Bot,
  CheckCircle,
  Clock,
  Eye,
  Pause,
  RefreshCw,
  RotateCw,
  Search,
  XCircle,
} from 'lucide-react'
import {
  agentApi,
  type AgentEvent,
  type AgentRun,
  type AgentTask,
} from '@/lib/api-client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectOption } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useToast } from '@/components/ui/toast'
import { formatDistanceToNow } from '@/lib/utils'

const STATUS_LABELS: Record<string, string> = {
  pending: '等待执行',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

const CONTROL_NODE_TYPES = new Set(['human_approval', 'condition', 'parallel_group', 'delay', 'merge'])

function statusBadgeClass(status: string) {
  if (status === 'completed') return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-100'
  if (status === 'running' || status === 'pending') return 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-100'
  if (status === 'failed') return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100'
  if (status === 'cancelled') return 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200'
  return 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200'
}

function statusIcon(status: string) {
  if (status === 'completed') return <CheckCircle className="h-4 w-4 text-green-600" />
  if (status === 'running') return <RefreshCw className="h-4 w-4 animate-spin text-blue-600" />
  if (status === 'failed') return <XCircle className="h-4 w-4 text-red-600" />
  if (status === 'cancelled') return <Pause className="h-4 w-4 text-slate-500" />
  return <Clock className="h-4 w-4 text-slate-400" />
}

function runAgentName(run: AgentRun) {
  const input = run.input_data || {}
  return String(input.agent_name || run.agent_name || run.metadata_json?.agent_name || '工作流运行')
}

function runWorkflowName(run: AgentRun) {
  const input = run.input_data || {}
  return String(input.workflow_name || run.metadata_json?.workflow_name || run.workflow_version_id || '未记录工作流')
}

function summarizeInput(value: Record<string, any> | null | undefined) {
  if (!value || Object.keys(value).length === 0) return '无输入上下文'
  const parts = [
    value.workflow_name ? `工作流：${value.workflow_name}` : null,
    value.document_type ? `文档类型：${value.document_type}` : null,
    value.source ? `来源：${value.source}` : null,
  ].filter(Boolean)
  return parts.join('；') || JSON.stringify(value)
}

function summarizeOutput(run: AgentRun) {
  const output = run.output_data || run.metadata_json?.output_data || run.metadata_json?.output_summary
  if (!output) return run.status === 'completed' ? '已完成，暂无输出摘要' : '暂无输出摘要'
  if (typeof output === 'string') return output
  if (typeof output.summary === 'string') return output.summary
  return JSON.stringify(output)
}

function formatJson(value: Record<string, any> | null | undefined) {
  if (!value || Object.keys(value).length === 0) return '无记录'
  return JSON.stringify(value, null, 2)
}

function formatTime(value: string | null | undefined) {
  if (!value) return '未记录'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function durationSeconds(startedAt: string | null | undefined, completedAt: string | null | undefined) {
  if (!startedAt) return null
  const end = completedAt ? new Date(completedAt).getTime() : Date.now()
  const start = new Date(startedAt).getTime()
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return null
  return Math.round((end - start) / 1000)
}

function calculateProgress(run: AgentRun, tasks: AgentTask[]) {
  if (typeof run.progress_percent === 'number') return Math.max(0, Math.min(100, run.progress_percent))
  if (tasks.length > 0) {
    const finished = tasks.filter((task) => task.status === 'completed' || task.status === 'failed').length
    return Math.round((finished / tasks.length) * 100)
  }
  if (run.status === 'completed') return 100
  if (run.status === 'failed' || run.status === 'cancelled') return 100
  if (run.status === 'running') return 50
  return 0
}

function actionState(run: AgentRun, action: 'retry' | 'cancel') {
  if (action === 'retry') {
    return run.status === 'failed'
      ? { disabled: false, reason: '按原输入重新排队' }
      : { disabled: true, reason: '仅失败运行可重试' }
  }
  return run.status === 'running' || run.status === 'pending'
    ? { disabled: false, reason: '取消当前运行' }
    : { disabled: true, reason: '仅运行中或等待执行的运行可取消' }
}

function runNeedsControl(run: AgentRun) {
  return Boolean(
    run.requires_human_action ||
    run.metadata_json?.requires_human_action ||
    run.gate_summary?.requires_human_action ||
    run.status_hint === 'requires_human_approval'
  )
}

function runNeedsDelayResume(run: AgentRun) {
  return Boolean(
    run.status_hint === 'delay_scheduled' ||
    run.metadata_json?.status_hint === 'delay_scheduled' ||
    run.metadata_json?.resume_after
  )
}

function runNeedsOperatorAction(run: AgentRun) {
  return runNeedsControl(run) || runNeedsDelayResume(run)
}

function isControlTask(task: AgentTask) {
  const nodeType = task.input_data?.node_type || task.output_data?.control_node?.type
  return CONTROL_NODE_TYPES.has(String(nodeType)) || task.output_data?.status === 'requires_human_action'
}

function controlTaskLabel(task: AgentTask | null | undefined) {
  if (!task) return '未定位控制节点'
  const nodeType = String(task.input_data?.node_type || task.output_data?.control_node?.type || 'control')
  if (nodeType === 'human_approval') return '人工审批'
  if (nodeType === 'condition') return '条件分支'
  if (nodeType === 'parallel_group') return '并行编排'
  if (nodeType === 'delay') return '延迟等待'
  if (nodeType === 'merge') return '结果合并'
  return nodeType
}

function EmptyState({ searchQuery }: { searchQuery: string }) {
  return (
    <Card data-testid="agent-ops-empty-state">
      <CardContent className="flex flex-col items-center justify-center py-12 text-center">
        <Bot className="h-12 w-12 text-slate-300" />
        <h3 className="mt-4 text-lg font-medium text-slate-900 dark:text-white">
          {searchQuery ? '没有匹配的运行记录' : '暂无 Agent 运行记录'}
        </h3>
        <p className="mt-2 max-w-md text-sm text-slate-500">
          {searchQuery ? '调整搜索或状态筛选后重试。' : '从配置中心触发 Agent 后，运行状态、任务和事件会显示在这里。'}
        </p>
      </CardContent>
    </Card>
  )
}

export default function AgentOpsPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const runIdParam = searchParams.get('runId')
  const workflowDefinitionIdParam = searchParams.get('workflowDefinitionId')
  const [statusFilter, setStatusFilter] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedRunId, setSelectedRunId] = useState<string | null>(runIdParam)
  const [refreshing, setRefreshing] = useState(false)
  const queryClient = useQueryClient()
  const { addToast } = useToast()

  useEffect(() => {
    if (runIdParam) setSelectedRunId(runIdParam)
  }, [runIdParam])

  const runsQuery = useQuery({
    queryKey: ['agent-runs', workflowDefinitionIdParam],
    queryFn: () => agentApi.listRuns({
      workflowDefinitionId: workflowDefinitionIdParam || undefined,
      pageSize: 100,
    }),
  })

  const selectedRunQuery = useQuery({
    queryKey: ['agent-run', selectedRunId],
    queryFn: () => agentApi.getRun(selectedRunId!),
    enabled: Boolean(selectedRunId),
  })

  const selectedTasksQuery = useQuery({
    queryKey: ['agent-run-tasks', selectedRunId],
    queryFn: () => agentApi.listRunTasks(selectedRunId!, { pageSize: 100 }),
    enabled: Boolean(selectedRunId),
  })

  const selectedEventsQuery = useQuery({
    queryKey: ['agent-run-events', selectedRunId],
    queryFn: () => agentApi.listRunEvents(selectedRunId!, { pageSize: 100 }),
    enabled: Boolean(selectedRunId),
  })

  const retryRunMutation = useMutation({
    mutationFn: (runId: string) => agentApi.retryRun(runId),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['agent-runs'] })
      queryClient.invalidateQueries({ queryKey: ['agent-run'] })
      queryClient.invalidateQueries({ queryKey: ['agent-run-tasks'] })
      queryClient.invalidateQueries({ queryKey: ['agent-run-events'] })
      addToast({ title: '已重新排队', description: result.message || '失败运行已按原输入重新进入队列。' })
    },
    onError: (error: Error) => addToast({ title: '重试失败', description: error.message, variant: 'destructive' }),
  })

  const cancelRunMutation = useMutation({
    mutationFn: (runId: string) => agentApi.cancelRun(runId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agent-runs'] })
      queryClient.invalidateQueries({ queryKey: ['agent-run'] })
      queryClient.invalidateQueries({ queryKey: ['agent-run-tasks'] })
      queryClient.invalidateQueries({ queryKey: ['agent-run-events'] })
      addToast({ title: '运行已取消', description: '运行记录和未完成任务已刷新。' })
    },
    onError: (error: Error) => addToast({ title: '取消失败', description: error.message, variant: 'destructive' }),
  })

  const controlRunMutation = useMutation({
    mutationFn: (data: { runId: string; action: 'approve' | 'reject' | 'resume' | 'skip'; nodeId?: string | null }) =>
      agentApi.controlRun(data.runId, {
        action: data.action,
        node_id: data.nodeId || undefined,
        comment: data.action === 'reject' ? '人工驳回，停止本次编排运行。' : '人工处理通过，继续执行后续节点。',
        output_data: {
          source: 'agent_ops',
          handled_at: new Date().toISOString(),
        },
      }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['agent-runs'] })
      queryClient.invalidateQueries({ queryKey: ['agent-run'] })
      queryClient.invalidateQueries({ queryKey: ['agent-run-tasks'] })
      queryClient.invalidateQueries({ queryKey: ['agent-run-events'] })
      const title = variables.action === 'reject' ? '已驳回控制节点' : variables.action === 'resume' ? '已恢复运行' : '已通过控制节点'
      addToast({ title, description: '运行、任务和事件状态已刷新。' })
    },
    onError: (error: Error) => addToast({ title: '控制动作失败', description: error.message, variant: 'destructive' }),
  })

  const refreshAll = async () => {
    setRefreshing(true)
    try {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['agent-runs'] }),
        queryClient.invalidateQueries({ queryKey: ['agent-run', selectedRunId] }),
        queryClient.invalidateQueries({ queryKey: ['agent-run-tasks', selectedRunId] }),
        queryClient.invalidateQueries({ queryKey: ['agent-run-events', selectedRunId] }),
      ])
      addToast({ title: '运行中心已刷新', description: '运行、任务和事件状态已重新拉取。' })
    } finally {
      setRefreshing(false)
    }
  }

  const runs = useMemo(() => runsQuery.data?.items || [], [runsQuery.data])
  const selectedRun = selectedRunQuery.data || runs.find((run) => run.id === selectedRunId) || null
  const selectedTasks = selectedTasksQuery.data?.items || []
  const selectedEvents = selectedEventsQuery.data?.items || []
  const selectedControlTask = selectedTasks.find((task) => isControlTask(task) && task.status !== 'completed') || selectedTasks.find(isControlTask) || null

  const applyControlAction = (action: 'approve' | 'reject' | 'resume' | 'skip') => {
    if (!selectedRun) return
    controlRunMutation.mutate({
      runId: selectedRun.id,
      action,
      nodeId: selectedControlTask?.node_id || selectedRun.metadata_json?.paused_node || null,
    })
  }

  const statusCounts = useMemo(() => runs.reduce<Record<string, number>>((counts, run) => {
    counts[run.status] = (counts[run.status] || 0) + 1
    return counts
  }, {}), [runs])

  const filteredRuns = useMemo(() => {
    const query = searchQuery.trim().toLowerCase()
    return runs.filter((run) => {
      const searchable = [
        run.id,
        runAgentName(run),
        runWorkflowName(run),
        summarizeInput(run.input_data),
        summarizeOutput(run),
        run.error_message || '',
      ].join(' ').toLowerCase()
      return (!statusFilter || run.status === statusFilter) && (!query || searchable.includes(query))
    })
  }, [runs, searchQuery, statusFilter])

  if (runsQuery.isLoading) {
    return (
      <div className="flex h-64 items-center justify-center text-slate-500">
        <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
        正在加载 Agent 运行中心...
      </div>
    )
  }

  if (runsQuery.isError) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12 text-center">
          <AlertTriangle className="h-10 w-10 text-red-500" />
          <h1 className="mt-3 text-lg font-semibold text-slate-900 dark:text-white">Agent 运行中心加载失败</h1>
          <p className="mt-2 text-sm text-slate-500">{(runsQuery.error as Error).message}</p>
          <Button className="mt-4" onClick={refreshAll}>重试</Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">Agent 运行中心</h1>
          <p className="mt-1 text-sm text-slate-500">监控 Agent run、任务事件、耗时、输入输出摘要和失败处置动作。</p>
        </div>
        <Button data-testid="agent-ops-refresh" variant="outline" onClick={refreshAll} disabled={refreshing}>
          <RefreshCw className={`mr-2 h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
          刷新
        </Button>
      </div>

      {workflowDefinitionIdParam && (
        <Card data-testid="agent-ops-workflow-filter">
          <CardContent className="flex flex-col gap-3 py-3 text-sm text-slate-600 dark:text-slate-300 md:flex-row md:items-center md:justify-between">
            <span>正在查看指定工作流的运行历史：{workflowDefinitionIdParam}</span>
            <Button variant="outline" size="sm" onClick={() => router.push('/agent-ops')}>清除筛选</Button>
          </CardContent>
        </Card>
      )}

      <div data-testid="agent-ops-summary" className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        {[
          ['运行总数', runs.length],
          ['运行中', statusCounts.running || 0],
          ['等待执行', statusCounts.pending || 0],
          ['待控制处理', runs.filter(runNeedsOperatorAction).length],
          ['失败', statusCounts.failed || 0],
          ['可观测事件', runs.reduce((total, run) => total + Number(run.metadata_json?.event_count || 0), 0) || '实时'],
        ].map(([label, value]) => (
          <Card key={label}>
            <CardContent className="pt-4">
              <p className="text-2xl font-semibold text-slate-900 dark:text-white">{value}</p>
              <p className="mt-1 text-xs text-slate-500">{label}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardContent className="grid gap-3 py-4 md:grid-cols-[1fr_180px]">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <Input
              data-testid="agent-ops-search-input"
              className="pl-10"
              placeholder="搜索 Agent、工作流、运行 ID、输入或失败原因"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
            />
          </div>
          <Select data-testid="agent-ops-status-filter" value={statusFilter} onValueChange={setStatusFilter}>
            <SelectOption value="">全部运行</SelectOption>
            <SelectOption value="pending">等待执行</SelectOption>
            <SelectOption value="running">运行中</SelectOption>
            <SelectOption value="completed">已完成</SelectOption>
            <SelectOption value="failed">失败</SelectOption>
            <SelectOption value="cancelled">已取消</SelectOption>
          </Select>
        </CardContent>
      </Card>

      {filteredRuns.length === 0 ? (
        <EmptyState searchQuery={searchQuery || statusFilter} />
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow className="bg-slate-50 dark:bg-slate-800">
                  <TableHead>状态</TableHead>
                  <TableHead>Agent / 工作流</TableHead>
                  <TableHead>输入摘要</TableHead>
                  <TableHead>输出 / 失败</TableHead>
                  <TableHead>耗时</TableHead>
                  <TableHead>操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredRuns.map((run) => {
                  const retry = actionState(run, 'retry')
                  const cancel = actionState(run, 'cancel')
                  const seconds = durationSeconds(run.started_at || run.created_at, run.completed_at)
                  return (
                    <TableRow key={run.id} data-testid={`agent-run-row-${run.id}`}>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          {statusIcon(run.status)}
                          <Badge className={`text-xs ${statusBadgeClass(run.status)}`}>{STATUS_LABELS[run.status] || run.status}</Badge>
                          {runNeedsControl(run) && (
                            <Badge className="bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-100">需人工处理</Badge>
                          )}
                          {runNeedsDelayResume(run) && (
                            <Badge className="bg-cyan-100 text-cyan-800 dark:bg-cyan-900 dark:text-cyan-100">待恢复</Badge>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="space-y-1">
                          <p className="font-medium text-slate-900 dark:text-white">{runAgentName(run)}</p>
                          <p className="text-xs text-slate-500">{runWorkflowName(run)}</p>
                          <p className="text-xs text-slate-400">{run.id}</p>
                        </div>
                      </TableCell>
                      <TableCell className="max-w-[240px] text-sm text-slate-600 dark:text-slate-300">
                        <span className="line-clamp-2">{summarizeInput(run.input_data)}</span>
                      </TableCell>
                      <TableCell className="max-w-[240px] text-sm text-slate-600 dark:text-slate-300">
                        <span className="line-clamp-2">{run.error_message || summarizeOutput(run)}</span>
                      </TableCell>
                      <TableCell className="text-sm text-slate-500">
                        {seconds === null ? '未记录' : `${seconds}s`}
                        <div className="mt-1 text-xs text-slate-400">{formatDistanceToNow(run.started_at || run.created_at)}</div>
                      </TableCell>
                      <TableCell>
                        <div className="flex gap-1">
                          <Button
                            data-testid={`agent-run-view-${run.id}`}
                            variant="ghost"
                            size="sm"
                            onClick={() => setSelectedRunId(run.id)}
                            title="查看运行详情"
                          >
                            <Eye className="h-4 w-4" />
                          </Button>
                          <Button
                            data-testid={`agent-run-retry-${run.id}`}
                            variant="ghost"
                            size="sm"
                            disabled={retry.disabled || retryRunMutation.isPending}
                            onClick={() => retryRunMutation.mutate(run.id)}
                            title={retry.reason}
                          >
                            <RotateCw className={`h-4 w-4 ${retryRunMutation.isPending ? 'animate-spin' : ''}`} />
                          </Button>
                          <Button
                            data-testid={`agent-run-cancel-${run.id}`}
                            variant="ghost"
                            size="sm"
                            disabled={cancel.disabled || cancelRunMutation.isPending}
                            onClick={() => cancelRunMutation.mutate(run.id)}
                            title={cancel.reason}
                          >
                            <Pause className="h-4 w-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <Dialog open={Boolean(selectedRunId)} onOpenChange={(open) => !open && setSelectedRunId(null)}>
        <DialogContent className="max-h-[90vh] max-w-4xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>运行详情</DialogTitle>
            <DialogDescription>查看本次运行的输入、输出、进度、任务、事件和可执行处置动作。</DialogDescription>
          </DialogHeader>
          {selectedRun && (
            <div className="space-y-5 py-4">
              <div className="grid gap-3 md:grid-cols-4">
                <Card className="md:col-span-2">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">{runAgentName(selectedRun)}</CardTitle>
                    <CardDescription>{runWorkflowName(selectedRun)}</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-2 text-sm">
                    <div className="flex items-center gap-2">
                      {statusIcon(selectedRun.status)}
                      <Badge className={statusBadgeClass(selectedRun.status)}>{STATUS_LABELS[selectedRun.status] || selectedRun.status}</Badge>
                      {runNeedsControl(selectedRun) && (
                        <Badge className="bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-100">需人工处理</Badge>
                      )}
                      {runNeedsDelayResume(selectedRun) && (
                        <Badge className="bg-cyan-100 text-cyan-800 dark:bg-cyan-900 dark:text-cyan-100">待恢复</Badge>
                      )}
                    </div>
                    <p className="text-slate-500">运行 ID：{selectedRun.id}</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm">任务进度</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                      <div
                        className="h-full rounded-full bg-indigo-600"
                        style={{ width: `${calculateProgress(selectedRun, selectedTasks)}%` }}
                      />
                    </div>
                    <p className="mt-2 text-sm text-slate-500">{calculateProgress(selectedRun, selectedTasks)}%</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm">耗时</CardTitle>
                  </CardHeader>
                  <CardContent className="text-sm text-slate-500">
                    {durationSeconds(selectedRun.started_at || selectedRun.created_at, selectedRun.completed_at) ?? 0}s
                  </CardContent>
                </Card>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <h3 className="text-sm font-medium text-slate-900 dark:text-white">输入摘要</h3>
                  <pre className="max-h-48 overflow-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">
                    {formatJson(selectedRun.input_data)}
                  </pre>
                </div>
                <div className="space-y-2">
                  <h3 className="text-sm font-medium text-slate-900 dark:text-white">输出摘要</h3>
                  <pre className="max-h-48 overflow-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">
                    {summarizeOutput(selectedRun)}
                  </pre>
                </div>
              </div>

              {selectedRun.error_message && (
                <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-100">
                  <div className="mb-1 font-medium">失败原因</div>
                  {selectedRun.error_message}
                </div>
              )}

              {(runNeedsOperatorAction(selectedRun) || selectedRun.can_resume || selectedControlTask) && (
                <section
                  data-testid="agent-run-control-panel"
                  className="rounded-md border border-amber-200 bg-amber-50 p-4 dark:border-amber-900 dark:bg-amber-950/30"
                >
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div className="space-y-1">
                      <div className="text-sm font-semibold text-amber-900 dark:text-amber-100">编排控制台</div>
                      <p className="text-sm text-amber-800 dark:text-amber-100">
                        {runNeedsControl(selectedRun)
                          ? '当前运行已暂停，等待人工审批后继续执行后续节点。'
                          : runNeedsDelayResume(selectedRun)
                            ? '当前运行处于延迟等待，可在窗口到达后恢复执行后续节点。'
                          : '控制节点已处理，可按需恢复后续执行。'}
                      </p>
                      <p className="text-xs text-amber-700 dark:text-amber-200">
                        节点：{selectedControlTask?.node_id || selectedRun.metadata_json?.paused_node || '未记录'} · 类型：{controlTaskLabel(selectedControlTask)}
                      </p>
                      {selectedRun.status_hint && (
                        <p className="text-xs text-amber-700 dark:text-amber-200">状态提示：{selectedRun.status_hint}</p>
                      )}
                      {selectedRun.metadata_json?.resume_after && (
                        <p className="text-xs text-amber-700 dark:text-amber-200">预计恢复：{formatTime(String(selectedRun.metadata_json.resume_after))}</p>
                      )}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {runNeedsControl(selectedRun) ? (
                        <>
                          <Button
                            data-testid="agent-run-control-approve"
                            size="sm"
                            onClick={() => applyControlAction('approve')}
                            disabled={controlRunMutation.isPending}
                          >
                            <CheckCircle className="mr-2 h-4 w-4" />
                            审批通过
                          </Button>
                          <Button
                            data-testid="agent-run-control-reject"
                            size="sm"
                            variant="outline"
                            onClick={() => applyControlAction('reject')}
                            disabled={controlRunMutation.isPending}
                          >
                            <XCircle className="mr-2 h-4 w-4" />
                            驳回停止
                          </Button>
                        </>
                      ) : (
                        <Button
                          data-testid="agent-run-control-resume"
                          size="sm"
                          onClick={() => applyControlAction('resume')}
                          disabled={controlRunMutation.isPending || !selectedRun.can_resume}
                        >
                          <RotateCw className={`mr-2 h-4 w-4 ${controlRunMutation.isPending ? 'animate-spin' : ''}`} />
                          恢复执行
                        </Button>
                      )}
                    </div>
                  </div>
                </section>
              )}

              <div className="grid gap-4 md:grid-cols-2">
                <section className="space-y-2">
                  <h3 className="text-sm font-medium text-slate-900 dark:text-white">任务明细</h3>
                  <div className="space-y-2 rounded-md border border-slate-200 p-3 dark:border-slate-700">
                    {selectedTasksQuery.isLoading ? (
                      <p className="text-sm text-slate-500">正在加载任务...</p>
                    ) : selectedTasks.length === 0 ? (
                      <p className="text-sm text-slate-500">暂无任务记录</p>
                    ) : (
                      selectedTasks.map((task) => (
                        <div key={task.id} className="rounded-md bg-slate-50 p-3 text-sm dark:bg-slate-900">
                          <div className="flex items-center justify-between gap-3">
                            <span className="font-medium text-slate-900 dark:text-white">{task.node_id}</span>
                            <Badge className={statusBadgeClass(task.status)}>{STATUS_LABELS[task.status] || task.status}</Badge>
                          </div>
                          <p className="mt-1 text-xs text-slate-500">{task.skill_name || task.tool_name || '未绑定执行单元'}</p>
                          {task.error_message && <p className="mt-1 text-xs text-red-600">{task.error_message}</p>}
                        </div>
                      ))
                    )}
                  </div>
                </section>

                <section className="space-y-2">
                  <h3 className="text-sm font-medium text-slate-900 dark:text-white">运行事件</h3>
                  <div className="space-y-2 rounded-md border border-slate-200 p-3 dark:border-slate-700">
                    {selectedEventsQuery.isLoading ? (
                      <p className="text-sm text-slate-500">正在加载事件...</p>
                    ) : selectedEvents.length === 0 ? (
                      <p className="text-sm text-slate-500">暂无事件记录</p>
                    ) : (
                      selectedEvents.map((event: AgentEvent) => (
                        <div key={event.id} className="rounded-md bg-slate-50 p-3 text-sm dark:bg-slate-900">
                          <div className="flex items-center justify-between gap-3">
                            <span className="font-medium text-slate-900 dark:text-white">{event.event_type}</span>
                            <span className="text-xs text-slate-500">{formatTime(event.created_at)}</span>
                          </div>
                          <pre className="mt-2 max-h-24 overflow-auto rounded bg-white p-2 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                            {formatJson(event.event_data)}
                          </pre>
                        </div>
                      ))
                    )}
                  </div>
                </section>
              </div>

              <div className="grid gap-3 text-sm text-slate-500 md:grid-cols-3">
                <div>创建时间：{formatTime(selectedRun.created_at)}</div>
                <div>开始时间：{formatTime(selectedRun.started_at)}</div>
                <div>完成时间：{formatTime(selectedRun.completed_at)}</div>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setSelectedRunId(null)}>关闭</Button>
            {selectedRun && (
              <>
                <Button
                  variant="outline"
                  onClick={() => retryRunMutation.mutate(selectedRun.id)}
                  disabled={actionState(selectedRun, 'retry').disabled || retryRunMutation.isPending}
                  title={actionState(selectedRun, 'retry').reason}
                >
                  <RotateCw className={`mr-2 h-4 w-4 ${retryRunMutation.isPending ? 'animate-spin' : ''}`} />
                  重试
                </Button>
                <Button
                  onClick={() => cancelRunMutation.mutate(selectedRun.id)}
                  disabled={actionState(selectedRun, 'cancel').disabled || cancelRunMutation.isPending}
                  title={actionState(selectedRun, 'cancel').reason}
                >
                  <Pause className="mr-2 h-4 w-4" />
                  取消运行
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
