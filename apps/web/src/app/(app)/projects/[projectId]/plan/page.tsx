'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ArrowDown, ArrowUp, CheckCircle2, CircleDashed, Play, Plus, RotateCcw, ShieldAlert } from 'lucide-react'

import { projectsApi, ProjectDeliveryPlan, ProjectMilestone } from '@/lib/api-client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { useToast } from '@/components/ui/toast'

const statusLabels: Record<string, string> = {
  planned: '待开始',
  in_progress: '进行中',
  blocked: '受阻',
  completed: '已完成',
}

const gateLabels: Record<string, string> = {
  'required-documents': '必需文档',
  'document-approval': '文档批准',
  'active-work-items': '协同工作项',
}

export default function ProjectDeliveryPlanPage({ params }: { params: { projectId: string } }) {
  const { projectId } = params
  const queryClient = useQueryClient()
  const { addToast } = useToast()
  const [createOpen, setCreateOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [dueAt, setDueAt] = useState('')

  const { data: plan, isLoading, error } = useQuery<ProjectDeliveryPlan>({
    queryKey: ['project-delivery-plan', projectId],
    queryFn: () => projectsApi.getDeliveryPlan(projectId),
    retry: false,
  })

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['project-delivery-plan', projectId] })
  const transition = useMutation({
    mutationFn: ({ action, milestone }: { action: 'start' | 'complete' | 'reopen'; milestone: ProjectMilestone }) =>
      action === 'start'
        ? projectsApi.startMilestone(projectId, milestone.id)
        : action === 'complete'
          ? projectsApi.completeMilestone(projectId, milestone.id)
          : projectsApi.reopenMilestone(projectId, milestone.id),
    onSuccess: (_, variables) => {
      refresh()
      addToast({ title: variables.action === 'start' ? '里程碑已开始' : variables.action === 'complete' ? '里程碑已完成' : '里程碑已重开' })
    },
    onError: (mutationError: Error) => addToast({ title: '里程碑操作未完成', description: mutationError.message, variant: 'destructive' }),
  })
  const initialize = useMutation({
    mutationFn: () => projectsApi.initializeDeliveryPlan(projectId),
    onSuccess: () => {
      refresh()
      addToast({ title: '交付计划已初始化' })
    },
  })
  const create = useMutation({
    mutationFn: () => projectsApi.createMilestone(projectId, {
      key: `custom-${Date.now()}`,
      title,
      due_at: dueAt ? new Date(dueAt).toISOString() : null,
      required_document_types: [],
      required_workflow_template_ids: [],
    }),
    onSuccess: () => {
      setCreateOpen(false)
      setTitle('')
      setDueAt('')
      refresh()
      addToast({ title: '里程碑已创建' })
    },
    onError: (mutationError: Error) => addToast({ title: '创建失败', description: mutationError.message, variant: 'destructive' }),
  })
  const reorder = useMutation({
    mutationFn: (ids: string[]) => projectsApi.reorderMilestones(projectId, ids),
    onSuccess: refresh,
  })

  const move = (index: number, direction: -1 | 1) => {
    if (!plan) return
    const target = index + direction
    if (target < 0 || target >= plan.milestones.length) return
    const ids = plan.milestones.map((item) => item.id)
    ;[ids[index], ids[target]] = [ids[target], ids[index]]
    reorder.mutate(ids)
  }

  if (isLoading) return <div className="p-8 text-sm text-slate-500">正在加载交付计划...</div>

  if (!plan || error) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" asChild><Link href={`/projects/${projectId}`}><ArrowLeft className="mr-2 h-4 w-4" />返回项目</Link></Button>
        <Card>
          <CardHeader><CardTitle>尚未建立交付计划</CardTitle><CardDescription>为已有项目生成可执行里程碑和交付门禁。</CardDescription></CardHeader>
          <CardContent><Button onClick={() => initialize.mutate()} disabled={initialize.isPending}>初始化交付计划</Button></CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" asChild><Link href={`/projects/${projectId}`}><ArrowLeft className="h-4 w-4" /></Link></Button>
          <div>
            <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">项目交付计划</h1>
            <p className="text-sm text-slate-500">以里程碑、责任人和交付门禁推进项目闭环。</p>
          </div>
        </div>
        <Button data-testid="open-create-milestone" onClick={() => setCreateOpen(true)}><Plus className="mr-2 h-4 w-4" />新建里程碑</Button>
      </div>

      <section data-testid="delivery-plan-summary" className="grid gap-4 md:grid-cols-4">
        <Card className="md:col-span-2"><CardContent className="pt-5"><div className="flex justify-between text-sm"><span>交付进度</span><strong>{plan.summary.progress_percent}%</strong></div><Progress className="mt-3" value={plan.summary.progress_percent} /></CardContent></Card>
        <Card><CardContent className="pt-5"><p className="text-xs text-slate-500">受阻里程碑</p><p className="mt-1 text-2xl font-semibold">{plan.summary.blocked_count}</p></CardContent></Card>
        <Card><CardContent className="pt-5"><p className="text-xs text-slate-500">逾期里程碑</p><p className="mt-1 text-2xl font-semibold">{plan.summary.overdue_count}</p></CardContent></Card>
      </section>

      <div data-testid="delivery-plan-milestones" className="space-y-3">
        {plan.milestones.map((milestone, index) => (
          <Card key={milestone.id} data-testid={`milestone-${milestone.key}`}>
            <CardHeader>
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div className="flex gap-3">
                  {milestone.status === 'completed' ? <CheckCircle2 className="mt-1 h-5 w-5 text-green-600" /> : milestone.status === 'blocked' ? <ShieldAlert className="mt-1 h-5 w-5 text-red-600" /> : <CircleDashed className="mt-1 h-5 w-5 text-slate-400" />}
                  <div><CardTitle className="text-base">{index + 1}. {milestone.title}</CardTitle><CardDescription className="mt-1">{milestone.description}</CardDescription></div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={milestone.status === 'completed' ? 'default' : 'secondary'}>{statusLabels[milestone.status] || milestone.status}</Badge>
                  <Button variant="ghost" size="sm" aria-label="上移" onClick={() => move(index, -1)} disabled={index === 0 || reorder.isPending}><ArrowUp className="h-4 w-4" /></Button>
                  <Button variant="ghost" size="sm" aria-label="下移" onClick={() => move(index, 1)} disabled={index === plan.milestones.length - 1 || reorder.isPending}><ArrowDown className="h-4 w-4" /></Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-2 md:grid-cols-3">
                {milestone.gate_results_json.map((gate) => <div key={gate.key} className={`rounded-md border p-3 text-sm ${gate.status === 'blocked' ? 'border-red-200 bg-red-50 text-red-800' : 'border-green-200 bg-green-50 text-green-800'}`}><strong>{gateLabels[gate.key] || gate.key}</strong><p className="mt-1 text-xs">{gate.message}</p></div>)}
              </div>
              <div className="flex flex-wrap gap-2">
                {milestone.status !== 'completed' && <Button data-testid={`start-milestone-${milestone.key}`} variant="outline" size="sm" onClick={() => transition.mutate({ action: 'start', milestone })}><Play className="mr-2 h-4 w-4" />开始</Button>}
                {milestone.status !== 'completed' && <Button size="sm" onClick={() => transition.mutate({ action: 'complete', milestone })}><CheckCircle2 className="mr-2 h-4 w-4" />完成并检查门禁</Button>}
                {milestone.status === 'completed' && <Button variant="outline" size="sm" onClick={() => transition.mutate({ action: 'reopen', milestone })}><RotateCcw className="mr-2 h-4 w-4" />重开</Button>}
                {milestone.due_at && <span className="self-center text-xs text-slate-500">截止：{new Date(milestone.due_at).toLocaleDateString('zh-CN')}</span>}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>新建交付里程碑</DialogTitle><DialogDescription>新增一个可分派、可排序、受门禁控制的交付节点。</DialogDescription></DialogHeader>
          <div className="space-y-4"><div className="space-y-2"><Label htmlFor="milestone-title">里程碑名称</Label><Input id="milestone-title" data-testid="milestone-title" value={title} onChange={(event) => setTitle(event.target.value)} /></div><div className="space-y-2"><Label htmlFor="milestone-due">截止日期</Label><Input id="milestone-due" type="date" value={dueAt} onChange={(event) => setDueAt(event.target.value)} /></div></div>
          <DialogFooter><Button variant="outline" onClick={() => setCreateOpen(false)}>取消</Button><Button data-testid="create-milestone" onClick={() => create.mutate()} disabled={!title.trim() || create.isPending}>创建</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
