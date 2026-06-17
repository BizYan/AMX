'use client'

import Link from 'next/link'
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  collaborationApi,
  projectsApi,
  type CollaborationMember,
  type CollaborationReviewAction,
  type CollaborationReviewItem,
  type CollaborationWorkItem,
} from '@/lib/api-client'
import { Avatar } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectOption } from '@/components/ui/select'
import { useToast } from '@/components/ui/toast'
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  Clock3,
  FileSearch,
  FileText,
  History,
  MessageSquare,
  ListChecks,
  Plus,
  RotateCcw,
  Search,
  Send,
  ShieldCheck,
  UserCheck,
  Users,
} from 'lucide-react'

const EMPTY_MEMBERS: CollaborationMember[] = []
const EMPTY_REVIEWS: CollaborationReviewItem[] = []

const MEMBER_STATUS_LABELS: Record<string, string> = {
  online: '在线',
  pending: '待处理',
  offline: '离线',
}

const REVIEW_STATUS_LABELS: Record<string, string> = {
  PASSED: '通过验收',
  BLOCKED: '退回修订',
  PASSED_WITH_FOLLOW_UPS: '带跟进项通过',
}

const PRIORITY_LABELS: Record<string, string> = {
  critical: '紧急',
  high: '高',
  medium: '中',
  low: '低',
}

const WORK_ITEM_STATUS_LABELS: Record<string, string> = {
  open: '待处理',
  in_progress: '处理中',
  blocked: '受阻',
  done: '已完成',
  cancelled: '已取消',
}

const WORK_ITEM_TYPE_LABELS: Record<string, string> = {
  review: '文档评审',
  comment_resolution: '评论处理',
  follow_up: '修订跟进',
  manual: '协同任务',
}

const ACTION_TOASTS: Record<CollaborationReviewAction, { title: string; description: string }> = {
  'assign-me': { title: '已领取评审', description: '该评审项已进入你的协同待办。' },
  'mark-read': { title: '已标记已读', description: '评论阅读状态已写入评审记录。' },
  'pass-acceptance': { title: '验收已通过', description: '文档状态已更新，未解决评论已关闭。' },
  'return-revision': { title: '已退回修订', description: '文档已进入修订状态，等待责任人处理。' },
}

function statusBadgeClass(status: string) {
  switch (status) {
    case 'online':
    case 'PASSED':
      return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200'
    case 'pending':
    case 'PASSED_WITH_FOLLOW_UPS':
      return 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200'
    case 'BLOCKED':
      return 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200'
    default:
      return 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200'
  }
}

function priorityBadgeClass(priority: string) {
  if (priority === 'critical') return 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200'
  if (priority === 'high') return 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200'
  return 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200'
}

function gateBadgeClass(status: string) {
  if (status === 'blocked') return 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200'
  if (status === 'attention') return 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200'
  return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200'
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function memberMatches(member: CollaborationMember, query: string, role: string, status: string) {
  const text = `${member.name} ${member.email} ${member.role} ${member.current_focus}`.toLowerCase()
  return (!query || text.includes(query)) && (!role || member.role === role) && (!status || member.status === status)
}

function reviewMatches(review: CollaborationReviewItem, query: string, status: string) {
  const text = `${review.title} ${review.document_type} ${review.owner} ${review.role} ${review.summary}`.toLowerCase()
  return (!query || text.includes(query)) && (!status || review.status === status)
}

export default function CollaborationPage() {
  const queryClient = useQueryClient()
  const { addToast } = useToast()
  const [memberSearch, setMemberSearch] = useState('')
  const [documentSearch, setDocumentSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [memberStatusFilter, setMemberStatusFilter] = useState('')
  const [reviewStatusFilter, setReviewStatusFilter] = useState('')
  const [selectedReviewId, setSelectedReviewId] = useState<string | null>(null)
  const [workItemSearch, setWorkItemSearch] = useState('')
  const [workItemStatus, setWorkItemStatus] = useState('')
  const [workItemAssignment, setWorkItemAssignment] = useState<'all' | 'mine' | 'unassigned'>('all')
  const [createWorkItemOpen, setCreateWorkItemOpen] = useState(false)
  const [newWorkItemTitle, setNewWorkItemTitle] = useState('')
  const [newWorkItemDescription, setNewWorkItemDescription] = useState('')
  const [newWorkItemProject, setNewWorkItemProject] = useState('')
  const [newWorkItemAssignee, setNewWorkItemAssignee] = useState('')
  const [newWorkItemPriority, setNewWorkItemPriority] = useState('medium')
  const [newWorkItemDueAt, setNewWorkItemDueAt] = useState('')

  const { data, isLoading, error } = useQuery({
    queryKey: ['collaboration-review-hub'],
    queryFn: collaborationApi.getReviewHub,
  })

  const { data: commandCenter } = useQuery({
    queryKey: ['collaboration-acceptance-command-center'],
    queryFn: collaborationApi.getAcceptanceCommandCenter,
  })

  const { data: workItemBoard, isLoading: workItemsLoading } = useQuery({
    queryKey: ['collaboration-work-items', workItemSearch, workItemStatus, workItemAssignment],
    queryFn: () =>
      collaborationApi.listWorkItems({
        search: workItemSearch || undefined,
        status: workItemStatus || undefined,
        assignment: workItemAssignment,
        pageSize: 100,
      }),
  })

  const { data: projectPage } = useQuery({
    queryKey: ['collaboration-work-item-projects'],
    queryFn: () => projectsApi.list({ pageSize: 100 }),
  })

  const hub = data
  const members = hub?.members ?? EMPTY_MEMBERS
  const reviews = hub?.review_queue ?? EMPTY_REVIEWS
  const selectedReview = reviews.find((review) => review.id === selectedReviewId) || reviews[0] || null

  const roleOptions = useMemo(() => Array.from(new Set(members.map((member) => member.role))), [members])

  const filteredMembers = useMemo(() => {
    const query = memberSearch.trim().toLowerCase()
    return members.filter((member) => memberMatches(member, query, roleFilter, memberStatusFilter))
  }, [memberSearch, memberStatusFilter, members, roleFilter])

  const filteredReviews = useMemo(() => {
    const query = documentSearch.trim().toLowerCase()
    return reviews.filter((review) => reviewMatches(review, query, reviewStatusFilter))
  }, [documentSearch, reviewStatusFilter, reviews])

  const summary = {
    online: members.filter((member) => member.status === 'online').length,
    pendingMembers: members.filter((member) => member.status === 'pending').length,
    pendingComments: reviews.reduce((total, review) => total + review.pending_comments, 0),
    blocked: reviews.filter((review) => review.status === 'BLOCKED').length,
    passed: reviews.filter((review) => review.status === 'PASSED').length,
  }

  const actionMutation = useMutation({
    mutationFn: ({ reviewId, action }: { reviewId: string; action: CollaborationReviewAction }) =>
      collaborationApi.performReviewAction(reviewId, action),
    onSuccess: (updatedReview, variables) => {
      queryClient.setQueryData(['collaboration-review-hub'], (current: typeof hub) => {
        if (!current) return current
        return {
          ...current,
          review_queue: current.review_queue.map((review) =>
            review.id === updatedReview.id ? updatedReview : review
          ),
        }
      })
      queryClient.invalidateQueries({ queryKey: ['collaboration-acceptance-command-center'] })
      setSelectedReviewId(updatedReview.id)
      addToast(ACTION_TOASTS[variables.action])
    },
    onError: (mutationError: Error) => {
      addToast({ title: '协同操作失败', description: mutationError.message, variant: 'destructive' })
    },
  })

  const runAction = (action: CollaborationReviewAction) => {
    if (!selectedReview) return
    actionMutation.mutate({ reviewId: selectedReview.id, action })
  }

  const workItemMutation = useMutation({
    mutationFn: ({ item, action }: { item: CollaborationWorkItem; action: 'claim' | 'complete' | 'reopen' }) => {
      if (action === 'claim') return collaborationApi.claimWorkItem(item.id)
      if (action === 'complete') return collaborationApi.completeWorkItem(item.id)
      return collaborationApi.reopenWorkItem(item.id)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['collaboration-work-items'] })
      queryClient.invalidateQueries({ queryKey: ['collaboration-review-hub'] })
      queryClient.invalidateQueries({ queryKey: ['collaboration-acceptance-command-center'] })
    },
    onError: (mutationError: Error) => {
      addToast({ title: '工作项操作失败', description: mutationError.message, variant: 'destructive' })
    },
  })

  const createWorkItemMutation = useMutation({
    mutationFn: () =>
      collaborationApi.createWorkItem({
        project_id: newWorkItemProject,
        title: newWorkItemTitle,
        description: newWorkItemDescription,
        assigned_to: newWorkItemAssignee || undefined,
        priority: newWorkItemPriority,
        work_type: 'manual',
        due_at: newWorkItemDueAt ? new Date(newWorkItemDueAt).toISOString() : undefined,
      }),
    onSuccess: () => {
      setCreateWorkItemOpen(false)
      setNewWorkItemTitle('')
      setNewWorkItemDescription('')
      setNewWorkItemProject('')
      setNewWorkItemAssignee('')
      setNewWorkItemPriority('medium')
      setNewWorkItemDueAt('')
      queryClient.invalidateQueries({ queryKey: ['collaboration-work-items'] })
      queryClient.invalidateQueries({ queryKey: ['collaboration-acceptance-command-center'] })
      addToast({ title: '协同工作项已创建', description: '任务已进入协同工作台。' })
    },
    onError: (mutationError: Error) => {
      addToast({ title: '创建工作项失败', description: mutationError.message, variant: 'destructive' })
    },
  })

  if (isLoading) {
    return <div className="py-16 text-center text-sm text-slate-500">正在加载协同验收中心...</div>
  }

  if (error || !hub) {
    return <div className="py-16 text-center text-sm text-red-500">协同验收中心加载失败，请稍后重试。</div>
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">协同验收中心</h1>
          <p className="mt-1 text-sm text-slate-500">
            汇总团队成员、文档评审队列、评论待办、快照证据和验收决策。
          </p>
        </div>
        <div className="flex items-center gap-2 rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-600 dark:border-slate-700 dark:text-slate-300">
          <Clock3 className="h-4 w-4" />
          数据更新时间 {reviews[0]?.updated_at ? formatTime(reviews[0].updated_at) : '暂无评审更新时间'}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {[
          ['在线成员', summary.online, <Users key="online" className="h-5 w-5 text-emerald-600" />],
          ['待处理成员', summary.pendingMembers, <UserCheck key="members" className="h-5 w-5 text-amber-600" />],
          ['评论待办', summary.pendingComments, <MessageSquare key="comments" className="h-5 w-5 text-indigo-600" />],
          ['阻塞评审', summary.blocked, <AlertTriangle key="blocked" className="h-5 w-5 text-red-600" />],
          ['已通过', summary.passed, <ShieldCheck key="passed" className="h-5 w-5 text-emerald-600" />],
        ].map(([label, value, icon]) => (
          <Card key={label as string}>
            <CardContent className="pt-4">
              <div className="flex items-center justify-between">
                <p className="text-2xl font-semibold text-slate-900 dark:text-white">{value}</p>
                {icon}
              </div>
              <p className="mt-1 text-xs text-slate-500">{label}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {commandCenter && (
        <section
          data-testid="collaboration-acceptance-command-center"
          className="rounded-md border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900"
        >
          <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-3">
                <h2 className="text-lg font-semibold text-slate-900 dark:text-white">协同验收指挥台</h2>
                <Badge
                  data-testid="collaboration-acceptance-gate"
                  className={gateBadgeClass(commandCenter.release_gate.status)}
                >
                  {commandCenter.release_gate.label}
                </Badge>
              </div>
              <p className="mt-2 max-w-4xl text-sm text-slate-600 dark:text-slate-300">
                {commandCenter.release_gate.summary}
              </p>
              <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
                {[
                  ['评审总数', commandCenter.summary.total_reviews],
                  ['通过评审', commandCenter.summary.passed_reviews],
                  ['阻断评审', commandCenter.summary.blocked_reviews],
                  ['跟进通过', commandCenter.summary.follow_up_reviews],
                  ['评论待办', commandCenter.summary.pending_comments],
                  ['开放工作项', commandCenter.summary.open_work_items],
                  ['待领取', commandCenter.summary.unassigned_work_items],
                  ['逾期', commandCenter.summary.overdue_work_items],
                ].map(([label, value]) => (
                  <div key={label as string} className="border-b border-slate-200 pb-2 dark:border-slate-700">
                    <p className="text-lg font-semibold text-slate-900 dark:text-white">{value}</p>
                    <p className="text-xs text-slate-500">{label}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="grid shrink-0 gap-2 sm:grid-cols-2 xl:w-[520px]">
              {commandCenter.priority_actions.map((action) => (
                <Button key={action.code} asChild variant={action.priority === 'critical' ? 'destructive' : 'outline'}>
                  <Link href={action.href}>
                    <CheckCircle2 className="mr-2 h-4 w-4" />
                    {action.title}
                  </Link>
                </Button>
              ))}
            </div>
          </div>

          <div className="mt-5 grid gap-3 lg:grid-cols-3">
            {commandCenter.risk_items.map((risk) => (
              <Link
                key={risk.code}
                href={risk.href}
                className="rounded-md border border-slate-200 p-4 transition-colors hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-medium text-slate-900 dark:text-white">{risk.title}</p>
                    <p className="mt-1 text-sm text-slate-500">{risk.detail}</p>
                  </div>
                  <Badge className={priorityBadgeClass(risk.severity)}>{risk.count}</Badge>
                </div>
              </Link>
            ))}
            {commandCenter.risk_items.length === 0 && (
              <div className="rounded-md border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-slate-700">
                当前没有验收阻断风险。
              </div>
            )}
          </div>
        </section>
      )}

      <section data-testid="collaboration-work-item-board" className="space-y-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900 dark:text-white">
              <ListChecks className="h-5 w-5 text-indigo-600" />
              协同工作台
            </h2>
            <p className="mt-1 text-sm text-slate-500">集中领取、跟进和关闭评审、评论处理与人工协同任务。</p>
          </div>
          <Button data-testid="create-work-item" onClick={() => setCreateWorkItemOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            新建工作项
          </Button>
        </div>

        <div className="grid grid-cols-3 gap-3">
          {[
            ['我的处理中', workItemBoard?.mine_count ?? 0],
            ['待领取', workItemBoard?.unassigned_count ?? 0],
            ['已逾期', workItemBoard?.overdue_count ?? 0],
          ].map(([label, value]) => (
            <div key={label as string} className="border-b border-slate-200 px-1 pb-3 dark:border-slate-700">
              <p className="text-xl font-semibold text-slate-900 dark:text-white">{value}</p>
              <p className="text-xs text-slate-500">{label}</p>
            </div>
          ))}
        </div>

        <div className="grid gap-3 lg:grid-cols-[1fr_180px_180px]">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <Input
              data-testid="work-item-search"
              className="pl-10"
              placeholder="搜索工作项..."
              value={workItemSearch}
              onChange={(event) => setWorkItemSearch(event.target.value)}
            />
          </div>
          <Select data-testid="work-item-status-filter" value={workItemStatus} onValueChange={setWorkItemStatus}>
            <SelectOption value="">全部状态</SelectOption>
            <SelectOption value="open">待处理</SelectOption>
            <SelectOption value="in_progress">处理中</SelectOption>
            <SelectOption value="blocked">受阻</SelectOption>
            <SelectOption value="done">已完成</SelectOption>
          </Select>
          <Select
            data-testid="work-item-assignment-filter"
            value={workItemAssignment}
            onValueChange={(value) => setWorkItemAssignment(value as 'all' | 'mine' | 'unassigned')}
          >
            <SelectOption value="all">全部分配</SelectOption>
            <SelectOption value="mine">分配给我</SelectOption>
            <SelectOption value="unassigned">待领取</SelectOption>
          </Select>
        </div>

        <div className="grid gap-3 lg:grid-cols-2">
          {(workItemBoard?.items ?? []).map((item) => (
            <div
              key={item.id}
              data-testid={`work-item-${item.id}`}
              className="rounded-md border border-slate-200 p-4 dark:border-slate-700"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-medium text-slate-900 dark:text-white">{item.title}</p>
                  <p className="mt-1 line-clamp-2 text-xs text-slate-500">
                    {WORK_ITEM_TYPE_LABELS[item.work_type] || item.work_type}
                    {item.description ? ` | ${item.description}` : ''}
                  </p>
                  <p className="mt-2 text-xs text-slate-500">
                    {item.project_name || '项目'} | {item.assigned_to_name || (item.assigned_to ? '已分配' : '待领取')}
                  </p>
                </div>
                <div className="flex shrink-0 gap-2">
                  <Badge className={statusBadgeClass(item.status)}>{WORK_ITEM_STATUS_LABELS[item.status] || item.status}</Badge>
                  <Badge className={priorityBadgeClass(item.priority)}>{PRIORITY_LABELS[item.priority] || item.priority}</Badge>
                </div>
              </div>
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-xs text-slate-500">
                <span>{item.due_at ? `截止 ${formatTime(item.due_at)}` : '未设置截止时间'}</span>
                <div className="flex gap-2">
                  {!item.assigned_to && item.status !== 'done' && (
                    <Button size="sm" variant="outline" onClick={() => workItemMutation.mutate({ item, action: 'claim' })}>
                      领取
                    </Button>
                  )}
                  {item.status !== 'done' && (
                    <Button size="sm" onClick={() => workItemMutation.mutate({ item, action: 'complete' })}>
                      完成
                    </Button>
                  )}
                  {item.status === 'done' && (
                    <Button size="sm" variant="outline" onClick={() => workItemMutation.mutate({ item, action: 'reopen' })}>
                      <RotateCcw className="mr-2 h-4 w-4" />
                      重开
                    </Button>
                  )}
                </div>
              </div>
            </div>
          ))}
          {!workItemsLoading && (workItemBoard?.items.length ?? 0) === 0 && (
            <div className="col-span-full rounded-md border border-dashed border-slate-300 py-10 text-center text-sm text-slate-500 dark:border-slate-700">
              当前筛选条件下没有工作项
            </div>
          )}
        </div>
      </section>

      <Dialog open={createWorkItemOpen} onOpenChange={setCreateWorkItemOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>新建协同工作项</DialogTitle>
            <DialogDescription>创建可被领取、跟进、完成和重开的持久化协同任务。</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="work-item-title">工作项标题</Label>
              <Input
                id="work-item-title"
                data-testid="work-item-title"
                value={newWorkItemTitle}
                onChange={(event) => setNewWorkItemTitle(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="work-item-project">所属项目</Label>
              <Select
                id="work-item-project"
                data-testid="work-item-project"
                value={newWorkItemProject}
                onValueChange={setNewWorkItemProject}
              >
                <SelectOption value="">选择项目</SelectOption>
                {(projectPage?.items ?? []).map((project) => (
                  <SelectOption key={project.id} value={project.id}>{project.name}</SelectOption>
                ))}
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="work-item-description">任务说明</Label>
              <textarea
                id="work-item-description"
                data-testid="work-item-description"
                className="min-h-24 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                value={newWorkItemDescription}
                onChange={(event) => setNewWorkItemDescription(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="work-item-assignee">责任人</Label>
              <Select
                id="work-item-assignee"
                data-testid="work-item-assignee"
                value={newWorkItemAssignee}
                onValueChange={setNewWorkItemAssignee}
              >
                <SelectOption value="">暂不分配</SelectOption>
                {members.map((member) => (
                  <SelectOption key={member.id} value={member.id}>{member.name} | {member.role}</SelectOption>
                ))}
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="work-item-priority">优先级</Label>
              <Select id="work-item-priority" value={newWorkItemPriority} onValueChange={setNewWorkItemPriority}>
                <SelectOption value="low">低</SelectOption>
                <SelectOption value="medium">中</SelectOption>
                <SelectOption value="high">高</SelectOption>
                <SelectOption value="critical">紧急</SelectOption>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="work-item-due-at">截止时间</Label>
              <Input
                id="work-item-due-at"
                data-testid="work-item-due-at"
                type="datetime-local"
                value={newWorkItemDueAt}
                onChange={(event) => setNewWorkItemDueAt(event.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateWorkItemOpen(false)}>取消</Button>
            <Button
              data-testid="submit-work-item"
              disabled={!newWorkItemTitle.trim() || !newWorkItemProject || createWorkItemMutation.isPending}
              onClick={() => createWorkItemMutation.mutate()}
            >
              创建工作项
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <div className="grid gap-4 xl:grid-cols-[0.9fr_1.25fr]">
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">团队成员</CardTitle>
            <CardDescription>按成员、角色和处理状态定位协同责任人。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 lg:grid-cols-[1fr_150px_150px]">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <Input
                  data-testid="collaboration-member-search"
                  className="pl-10"
                  placeholder="搜索成员、邮箱或职责..."
                  value={memberSearch}
                  onChange={(event) => setMemberSearch(event.target.value)}
                />
              </div>
              <Select data-testid="collaboration-role-filter" value={roleFilter} onValueChange={setRoleFilter}>
                <SelectOption value="">全部角色</SelectOption>
                {roleOptions.map((role) => (
                  <SelectOption key={role} value={role}>{role}</SelectOption>
                ))}
              </Select>
              <Select data-testid="collaboration-status-filter" value={memberStatusFilter} onValueChange={setMemberStatusFilter}>
                <SelectOption value="">全部状态</SelectOption>
                <SelectOption value="online">在线</SelectOption>
                <SelectOption value="pending">待处理</SelectOption>
                <SelectOption value="offline">离线</SelectOption>
              </Select>
            </div>

            <div className="space-y-3">
              {filteredMembers.map((member) => (
                <div
                  key={member.id}
                  data-testid={`collaboration-member-${member.id}`}
                  className="flex items-center justify-between gap-3 rounded-md border border-slate-200 p-3 dark:border-slate-700"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <Avatar className="h-10 w-10">
                      <div className="flex h-full w-full items-center justify-center bg-indigo-100 text-sm font-medium text-indigo-700">
                        {member.name.slice(0, 1)}
                      </div>
                    </Avatar>
                    <div className="min-w-0">
                      <p className="font-medium text-slate-900 dark:text-white">{member.name}</p>
                      <p className="truncate text-xs text-slate-500">{member.role} | {member.current_focus}</p>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <Badge className={statusBadgeClass(member.status)}>{MEMBER_STATUS_LABELS[member.status] || member.status}</Badge>
                    <span className="text-xs text-slate-500">{member.pending_count} 待办</span>
                  </div>
                </div>
              ))}
              {filteredMembers.length === 0 && (
                <div className="rounded-md border border-dashed border-slate-300 py-8 text-center text-sm text-slate-500 dark:border-slate-700">
                  没有匹配的成员
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-lg">评审队列</CardTitle>
            <CardDescription>集中处理 URS、BRD、PRD、设计、测试与验收材料的评审状态。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 lg:grid-cols-[1fr_220px]">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <Input
                  data-testid="collaboration-document-search"
                  className="pl-10"
                  placeholder="搜索文档、评审人或摘要..."
                  value={documentSearch}
                  onChange={(event) => setDocumentSearch(event.target.value)}
                />
              </div>
              <Select value={reviewStatusFilter} onValueChange={setReviewStatusFilter}>
                <SelectOption value="">全部验收结果</SelectOption>
                <SelectOption value="PASSED">通过验收</SelectOption>
                <SelectOption value="BLOCKED">退回修订</SelectOption>
                <SelectOption value="PASSED_WITH_FOLLOW_UPS">带跟进项通过</SelectOption>
              </Select>
            </div>

            <div className="grid gap-4 lg:grid-cols-[1fr_0.95fr]">
              <div className="space-y-3">
                {filteredReviews.map((review) => (
                  <button
                    key={review.id}
                    data-testid={`collaboration-review-${review.id}`}
                    type="button"
                    onClick={() => setSelectedReviewId(review.id)}
                    className={`w-full rounded-md border p-3 text-left transition-colors ${
                      selectedReview?.id === review.id
                        ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-950/30'
                        : 'border-slate-200 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-medium text-slate-900 dark:text-white">{review.title}</p>
                        <p className="mt-1 text-xs text-slate-500">{review.document_type} | {review.owner} | {review.role}</p>
                      </div>
                      <div className="flex shrink-0 flex-col items-end gap-2">
                        <Badge data-testid={`review-status-${review.status}`} className={statusBadgeClass(review.status)}>
                          {REVIEW_STATUS_LABELS[review.status] || review.status}
                        </Badge>
                        <Badge className={priorityBadgeClass(review.priority)}>{PRIORITY_LABELS[review.priority] || review.priority}</Badge>
                      </div>
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-500">
                      <span>{review.pending_comments} 条评论待办</span>
                      <span>{review.snapshot_count ?? 0} 个快照</span>
                      <span>{review.baseline_count ?? 0} 条基线</span>
                      <span>{formatTime(review.updated_at)}</span>
                    </div>
                  </button>
                ))}
                {filteredReviews.length === 0 && (
                  <div className="rounded-md border border-dashed border-slate-300 py-8 text-center text-sm text-slate-500 dark:border-slate-700">
                    没有匹配的评审项
                  </div>
                )}
              </div>

              <div data-testid="collaboration-review-detail" className="rounded-md border border-slate-200 p-4 dark:border-slate-700">
                {selectedReview ? (
                  <div className="space-y-4">
                    <div>
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <h2 className="text-base font-semibold text-slate-900 dark:text-white">{selectedReview.title}</h2>
                          <p className="mt-1 text-xs text-slate-500">{selectedReview.document_type} | {selectedReview.owner}</p>
                        </div>
                        <Badge className={statusBadgeClass(selectedReview.status)}>
                          {REVIEW_STATUS_LABELS[selectedReview.status] || selectedReview.status}
                        </Badge>
                      </div>
                      <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">{selectedReview.summary}</p>
                    </div>
                    <div className="grid grid-cols-3 gap-2 text-sm">
                      <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900/50">
                        <p className="text-xs text-slate-500">评论待办</p>
                        <p className="mt-1 font-semibold text-slate-900 dark:text-white">{selectedReview.pending_comments}</p>
                      </div>
                      <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900/50">
                        <p className="text-xs text-slate-500">快照</p>
                        <p className="mt-1 font-semibold text-slate-900 dark:text-white">{selectedReview.snapshot_count ?? 0}</p>
                      </div>
                      <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900/50">
                        <p className="text-xs text-slate-500">基线</p>
                        <p className="mt-1 font-semibold text-slate-900 dark:text-white">{selectedReview.baseline_count ?? 0}</p>
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <Button data-testid="collaboration-assign-me" variant="outline" size="sm" onClick={() => runAction('assign-me')}>
                        <UserCheck className="mr-2 h-4 w-4" />
                        领取评审
                      </Button>
                      <Button data-testid="collaboration-mark-read" variant="outline" size="sm" onClick={() => runAction('mark-read')}>
                        <MessageSquare className="mr-2 h-4 w-4" />
                        标记已读
                      </Button>
                      <Button data-testid="collaboration-pass-acceptance" size="sm" onClick={() => runAction('pass-acceptance')}>
                        <CheckCircle2 className="mr-2 h-4 w-4" />
                        通过验收
                      </Button>
                      <Button data-testid="collaboration-return-revision" variant="destructive" size="sm" onClick={() => runAction('return-revision')}>
                        <Send className="mr-2 h-4 w-4" />
                        退回修订
                      </Button>
                    </div>
                    <Button asChild variant="secondary" size="sm" className="w-full">
                      <Link href={selectedReview.action_href || `/projects/${selectedReview.project_id}/documents/${selectedReview.document_id}`}>
                        <FileSearch className="mr-2 h-4 w-4" />
                        打开文档详情
                      </Link>
                    </Button>
                  </div>
                ) : (
                  <div className="py-10 text-center text-sm text-slate-500">选择一个评审项查看详情</div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">评论待办</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {hub.comment_todos.map((todo) => (
              <Link key={todo.id} href={todo.action_href} className="block rounded-md border border-slate-200 p-3 text-sm hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800">
                <div className="flex items-center justify-between gap-3">
                  <p className="font-medium text-slate-900 dark:text-white">{todo.document_title}</p>
                  <Badge variant="secondary">{todo.count} 条</Badge>
                </div>
                <p className="mt-1 text-xs text-slate-500">{todo.assignee} | {todo.due}</p>
              </Link>
            ))}
            {hub.comment_todos.length === 0 && (
              <div className="rounded-md border border-dashed border-slate-300 py-8 text-center text-sm text-slate-500 dark:border-slate-700">
                暂无未解决评论
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-lg">最近活动</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {hub.recent_activities.map((activity) => (
              <div key={activity.id} className="flex gap-3 text-sm">
                <History className="mt-0.5 h-4 w-4 shrink-0 text-indigo-500" />
                <div>
                  <p className="text-slate-900 dark:text-white">{activity.actor} | {activity.action}</p>
                  <p className="mt-1 text-xs text-slate-500">{activity.target} | {formatTime(activity.created_at)}</p>
                </div>
              </div>
            ))}
            {hub.recent_activities.length === 0 && (
              <div className="rounded-md border border-dashed border-slate-300 py-8 text-center text-sm text-slate-500 dark:border-slate-700">
                暂无协同活动
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-lg">验收决策</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {hub.acceptance_decisions.map((decision) => (
              <div key={decision.id} className="flex items-center justify-between rounded-md border border-slate-200 p-3 dark:border-slate-700">
                <div className="flex items-center gap-2">
                  <ClipboardCheck className="h-4 w-4 text-indigo-500" />
                  <div>
                    <p className="text-sm font-medium text-slate-900 dark:text-white">{decision.label}</p>
                    <p className="mt-1 text-xs text-slate-500">{decision.status}</p>
                  </div>
                </div>
                <Badge className={statusBadgeClass(decision.status)}>{decision.count}</Badge>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
