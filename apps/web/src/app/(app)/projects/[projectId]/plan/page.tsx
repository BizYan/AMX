'use client'

import Link from 'next/link'
import { use, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  CalendarClock,
  CheckCircle2,
  CircleDashed,
  ExternalLink,
  Pencil,
  Play,
  Plus,
  RotateCcw,
  ShieldAlert,
  Trash2,
  UserRound,
} from 'lucide-react'

import {
  identityApi,
  projectsApi,
  type ProjectDeliveryPlan,
  type ProjectMilestone,
  type ProjectMilestoneCreateInput,
} from '@/lib/api-client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { Select, SelectOption } from '@/components/ui/select'
import { useToast } from '@/components/ui/toast'
import { getDocumentTypeLabel } from '@/lib/document-labels'

const STATUS_LABELS: Record<string, string> = {
  planned: '待开始',
  in_progress: '进行中',
  blocked: '受阻',
  completed: '已完成',
}

const PRIORITY_LABELS: Record<string, string> = {
  low: '低',
  medium: '中',
  high: '高',
  critical: '紧急',
}

const GATE_LABELS: Record<string, string> = {
  'required-documents': '必需文档',
  'document-approval': '文档批准',
  'active-work-items': '协同工作项',
}

const EMPTY_FORM: ProjectMilestoneCreateInput = {
  key: '',
  title: '',
  description: '',
  owner_id: null,
  priority: 'medium',
  planned_start_at: null,
  due_at: null,
  required_document_types: [],
  required_workflow_template_ids: [],
}

function toDateInput(value?: string | null) {
  return value ? value.slice(0, 10) : ''
}

function toIsoDate(value: string) {
  return value ? new Date(`${value}T12:00:00`).toISOString() : null
}

function splitCsv(value: string) {
  return value.split(',').map((item) => item.trim()).filter(Boolean)
}

function priorityVariant(priority: string) {
  return priority === 'critical' ? 'destructive' as const : priority === 'high' ? 'outline' as const : 'secondary' as const
}

export default function ProjectDeliveryPlanPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = use(params)
  const queryClient = useQueryClient()
  const { addToast } = useToast()
  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState<ProjectMilestone | null>(null)
  const [deleting, setDeleting] = useState<ProjectMilestone | null>(null)
  const [form, setForm] = useState<ProjectMilestoneCreateInput>(EMPTY_FORM)
  const [documentTypes, setDocumentTypes] = useState('')
  const [workflowIds, setWorkflowIds] = useState('')

  const planQuery = useQuery<ProjectDeliveryPlan>({
    queryKey: ['project-delivery-plan', projectId],
    queryFn: () => projectsApi.getDeliveryPlan(projectId),
    retry: false,
  })
  const usersQuery = useQuery({
    queryKey: ['delivery-plan-users'],
    queryFn: () => identityApi.listUsers({ pageSize: 100 }),
  })
  const plan = planQuery.data
  const users = usersQuery.data?.items || []
  const blockedMilestones = useMemo(
    () => plan?.milestones.filter((item) => item.status === 'blocked' || item.gate_results_json.some((gate) => gate.status === 'blocked')) || [],
    [plan],
  )

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['project-delivery-plan', projectId] })
  const transition = useMutation({
    mutationFn: ({ action, milestone }: { action: 'start' | 'complete' | 'reopen'; milestone: ProjectMilestone }) =>
      action === 'start'
        ? projectsApi.startMilestone(projectId, milestone.id)
        : action === 'complete'
          ? projectsApi.completeMilestone(projectId, milestone.id)
          : projectsApi.reopenMilestone(projectId, milestone.id),
    onSuccess: (milestone, variables) => {
      refresh()
      if (milestone.status === 'blocked') {
        addToast({ title: '里程碑被门禁阻塞', description: milestone.gate_results_json.filter((gate) => gate.status === 'blocked').map((gate) => gate.message).join('；'), variant: 'destructive' })
        return
      }
      addToast({ title: variables.action === 'start' ? '里程碑已开始' : variables.action === 'complete' ? '里程碑已完成' : '里程碑已重开' })
    },
    onError: (error: Error) => addToast({ title: '里程碑操作未完成', description: error.message, variant: 'destructive' }),
  })
  const initialize = useMutation({
    mutationFn: () => projectsApi.initializeDeliveryPlan(projectId),
    onSuccess: () => {
      refresh()
      addToast({ title: '交付计划已初始化' })
    },
  })
  const save = useMutation({
    mutationFn: () => {
      const payload = {
        ...form,
        key: form.key.trim(),
        title: form.title.trim(),
        description: form.description?.trim(),
        required_document_types: splitCsv(documentTypes),
        required_workflow_template_ids: splitCsv(workflowIds),
      }
      return editing
        ? projectsApi.updateMilestone(projectId, editing.id, payload)
        : projectsApi.createMilestone(projectId, payload)
    },
    onSuccess: () => {
      setEditorOpen(false)
      refresh()
      addToast({ title: editing ? '里程碑已更新并重新评估' : '里程碑已创建' })
    },
    onError: (error: Error) => addToast({ title: '保存里程碑失败', description: error.message, variant: 'destructive' }),
  })
  const deleteMutation = useMutation({
    mutationFn: () => projectsApi.deleteMilestone(projectId, deleting!.id),
    onSuccess: () => {
      setDeleting(null)
      refresh()
      addToast({ title: '里程碑已删除' })
    },
    onError: (error: Error) => addToast({ title: '删除里程碑失败', description: error.message, variant: 'destructive' }),
  })
  const reorder = useMutation({
    mutationFn: (ids: string[]) => projectsApi.reorderMilestones(projectId, ids),
    onSuccess: refresh,
  })

  const openCreate = () => {
    setEditing(null)
    setForm(EMPTY_FORM)
    setDocumentTypes('')
    setWorkflowIds('')
    setEditorOpen(true)
  }
  const openEdit = (milestone: ProjectMilestone) => {
    setEditing(milestone)
    setForm({
      key: milestone.key,
      title: milestone.title,
      description: milestone.description,
      owner_id: milestone.owner_id,
      priority: milestone.priority as ProjectMilestoneCreateInput['priority'],
      planned_start_at: milestone.planned_start_at,
      due_at: milestone.due_at,
      required_document_types: milestone.required_document_types_json,
      required_workflow_template_ids: milestone.required_workflow_template_ids_json,
    })
    setDocumentTypes(milestone.required_document_types_json.join(','))
    setWorkflowIds(milestone.required_workflow_template_ids_json.join(','))
    setEditorOpen(true)
  }
  const move = (index: number, direction: -1 | 1) => {
    if (!plan) return
    const target = index + direction
    if (target < 0 || target >= plan.milestones.length) return
    const ids = plan.milestones.map((item) => item.id)
    ;[ids[index], ids[target]] = [ids[target], ids[index]]
    reorder.mutate(ids)
  }

  if (planQuery.isLoading) return <div className="p-8 text-sm text-slate-500">正在加载交付计划...</div>
  if (!plan || planQuery.error) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" asChild><Link href={`/projects/${projectId}`}><ArrowLeft className="mr-2 h-4 w-4" />返回项目</Link></Button>
        <Card>
          <CardHeader><CardTitle>尚未建立交付计划</CardTitle><CardDescription>为已有项目生成可执行里程碑、责任任务和交付门禁。</CardDescription></CardHeader>
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
            <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">项目交付执行中枢</h1>
            <p className="text-sm text-slate-500">以里程碑、负责人、交付门禁和协同责任项推动项目闭环。</p>
          </div>
        </div>
        <Button data-testid="open-create-milestone" onClick={openCreate}><Plus className="mr-2 h-4 w-4" />新建里程碑</Button>
      </div>

      <section data-testid="delivery-plan-summary" className="grid gap-4 md:grid-cols-4">
        <Card className="md:col-span-2"><CardContent className="pt-5"><div className="flex justify-between text-sm"><span>交付进度</span><strong>{plan.summary.progress_percent}%</strong></div><Progress className="mt-3" value={plan.summary.progress_percent} /></CardContent></Card>
        <Card><CardContent className="pt-5"><p className="text-xs text-slate-500">受阻里程碑</p><p className="mt-1 text-2xl font-semibold">{plan.summary.blocked_count}</p></CardContent></Card>
        <Card><CardContent className="pt-5"><p className="text-xs text-slate-500">逾期里程碑</p><p className="mt-1 text-2xl font-semibold">{plan.summary.overdue_count}</p></CardContent></Card>
      </section>

      <section data-testid="delivery-plan-risk-summary" className="rounded-md border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-5 w-5 text-amber-600" />
          <h2 className="font-semibold text-slate-900 dark:text-white">执行风险与下一步</h2>
        </div>
        {blockedMilestones.length ? (
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {blockedMilestones.map((milestone) => (
              <div key={milestone.id} className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
                <p className="font-semibold">{milestone.title}</p>
                <p className="mt-1">{milestone.gate_results_json.filter((gate) => gate.status === 'blocked').map((gate) => gate.message).join('；')}</p>
              </div>
            ))}
          </div>
        ) : <p className="mt-3 text-sm text-slate-500">当前没有阻塞门禁，按顺序推进下一里程碑。</p>}
      </section>

      <div data-testid="delivery-plan-milestones" className="space-y-3">
        {plan.milestones.map((milestone, index) => {
          const owner = users.find((user) => user.id === milestone.owner_id)
          return (
            <Card key={milestone.id} data-testid={`milestone-${milestone.key}`}>
              <CardHeader>
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div className="flex gap-3">
                    {milestone.status === 'completed' ? <CheckCircle2 className="mt-1 h-5 w-5 text-green-600" /> : milestone.status === 'blocked' ? <ShieldAlert className="mt-1 h-5 w-5 text-red-600" /> : <CircleDashed className="mt-1 h-5 w-5 text-slate-400" />}
                    <div>
                      <CardTitle className="text-base">{index + 1}. {milestone.title}</CardTitle>
                      <CardDescription className="mt-1">{milestone.description || '未填写里程碑说明'}</CardDescription>
                      <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
                        <span className="flex items-center gap-1"><UserRound className="h-3.5 w-3.5" />{owner?.full_name || owner?.email || '未分配负责人'}</span>
                        <span className="flex items-center gap-1"><CalendarClock className="h-3.5 w-3.5" />{milestone.due_at ? `截止 ${new Date(milestone.due_at).toLocaleDateString('zh-CN')}` : '未设置截止日期'}</span>
                      </div>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={milestone.status === 'blocked' ? 'destructive' : milestone.status === 'completed' ? 'default' : 'secondary'}>{STATUS_LABELS[milestone.status] || milestone.status}</Badge>
                    <Badge variant={priorityVariant(milestone.priority)}>{PRIORITY_LABELS[milestone.priority] || milestone.priority}</Badge>
                    <Button data-testid={`edit-milestone-${milestone.key}`} variant="ghost" size="sm" aria-label="编辑里程碑" onClick={() => openEdit(milestone)}><Pencil className="h-4 w-4" /></Button>
                    <Button data-testid={`delete-milestone-${milestone.key}`} variant="ghost" size="sm" aria-label="删除里程碑" onClick={() => setDeleting(milestone)}><Trash2 className="h-4 w-4" /></Button>
                    <Button variant="ghost" size="sm" aria-label="上移" onClick={() => move(index, -1)} disabled={index === 0 || reorder.isPending}><ArrowUp className="h-4 w-4" /></Button>
                    <Button variant="ghost" size="sm" aria-label="下移" onClick={() => move(index, 1)} disabled={index === plan.milestones.length - 1 || reorder.isPending}><ArrowDown className="h-4 w-4" /></Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex flex-wrap gap-2">
                  {milestone.required_document_types_json.map((type) => <Badge key={type} variant="outline">{getDocumentTypeLabel(type)}</Badge>)}
                  {milestone.required_workflow_template_ids_json.map((id) => <Badge key={id} variant="secondary">工作流：{id}</Badge>)}
                </div>
                <div className="grid gap-2 md:grid-cols-3">
                  {milestone.gate_results_json.map((gate) => (
                    <div key={gate.key} className={`rounded-md border p-3 text-sm ${gate.status === 'blocked' ? 'border-red-200 bg-red-50 text-red-800' : 'border-green-200 bg-green-50 text-green-800'}`}>
                      <strong>{GATE_LABELS[gate.key] || gate.key}</strong>
                      <p className="mt-1 text-xs">{gate.message}</p>
                      {gate.status === 'blocked' && gate.action_href ? <Link className="mt-2 inline-flex items-center gap-1 text-xs font-semibold underline" href={gate.action_href}>处理阻塞<ExternalLink className="h-3 w-3" /></Link> : null}
                    </div>
                  ))}
                </div>
                <div className="flex flex-wrap gap-2">
                  {milestone.status !== 'completed' && <Button data-testid={`start-milestone-${milestone.key}`} variant="outline" size="sm" onClick={() => transition.mutate({ action: 'start', milestone })}><Play className="mr-2 h-4 w-4" />开始</Button>}
                  {milestone.status !== 'completed' && <Button size="sm" onClick={() => transition.mutate({ action: 'complete', milestone })}><CheckCircle2 className="mr-2 h-4 w-4" />完成并检查门禁</Button>}
                  {milestone.status === 'completed' && <Button variant="outline" size="sm" onClick={() => transition.mutate({ action: 'reopen', milestone })}><RotateCcw className="mr-2 h-4 w-4" />重开</Button>}
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>

      <Dialog open={editorOpen} onOpenChange={setEditorOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader><DialogTitle>{editing ? '编辑交付里程碑' : '新建交付里程碑'}</DialogTitle><DialogDescription>配置责任、时间、必需交付物和工作流门禁。编辑受阻里程碑后会重新进入待开始状态。</DialogDescription></DialogHeader>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2"><Label htmlFor="milestone-key">标识</Label><Input id="milestone-key" data-testid="milestone-key" value={form.key} disabled={Boolean(editing)} onChange={(event) => setForm({ ...form, key: event.target.value })} /></div>
            <div className="space-y-2"><Label htmlFor="milestone-title">名称</Label><Input id="milestone-title" data-testid="milestone-title" value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></div>
            <div className="space-y-2 md:col-span-2"><Label htmlFor="milestone-description">说明</Label><textarea id="milestone-description" data-testid="milestone-description" className="min-h-20 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800" value={form.description || ''} onChange={(event) => setForm({ ...form, description: event.target.value })} /></div>
            <div className="space-y-2"><Label>负责人</Label><Select value={form.owner_id || ''} onValueChange={(value) => setForm({ ...form, owner_id: value || null })}><SelectOption value="">未分配</SelectOption>{users.map((user) => <SelectOption key={user.id} value={user.id}>{user.full_name || user.email}</SelectOption>)}</Select></div>
            <div className="space-y-2"><Label>优先级</Label><Select data-testid="milestone-priority" value={form.priority || 'medium'} onValueChange={(value) => setForm({ ...form, priority: value as ProjectMilestoneCreateInput['priority'] })}><SelectOption value="low">低</SelectOption><SelectOption value="medium">中</SelectOption><SelectOption value="high">高</SelectOption><SelectOption value="critical">紧急</SelectOption></Select></div>
            <div className="space-y-2"><Label>计划开始</Label><Input type="date" value={toDateInput(form.planned_start_at)} onChange={(event) => setForm({ ...form, planned_start_at: toIsoDate(event.target.value) })} /></div>
            <div className="space-y-2"><Label>截止日期</Label><Input type="date" value={toDateInput(form.due_at)} onChange={(event) => setForm({ ...form, due_at: toIsoDate(event.target.value) })} /></div>
            <div className="space-y-2"><Label>必需文档类型</Label><Input data-testid="milestone-required-documents" placeholder="urs,brd,prd" value={documentTypes} onChange={(event) => setDocumentTypes(event.target.value)} /></div>
            <div className="space-y-2"><Label>必需工作流模板</Label><Input placeholder="document-quality-assessment" value={workflowIds} onChange={(event) => setWorkflowIds(event.target.value)} /></div>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setEditorOpen(false)}>取消</Button><Button data-testid={editing ? 'save-milestone' : 'create-milestone'} onClick={() => save.mutate()} disabled={!form.key.trim() || !form.title.trim() || save.isPending}>{editing ? '保存并重新评估' : '创建'}</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(deleting)} onOpenChange={(open) => !open && setDeleting(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>删除里程碑</DialogTitle><DialogDescription>将删除“{deleting?.title}”及其同步协同责任项，并自动重排后续里程碑。此操作不可撤销。</DialogDescription></DialogHeader>
          <DialogFooter><Button variant="outline" onClick={() => setDeleting(null)}>取消</Button><Button data-testid="confirm-delete-milestone" variant="destructive" onClick={() => deleteMutation.mutate()} disabled={deleteMutation.isPending}>确认删除</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
