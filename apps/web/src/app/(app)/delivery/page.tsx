'use client'

import Link from 'next/link'
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CalendarClock, ExternalLink, Pencil, Search, ShieldAlert, UserRound } from 'lucide-react'

import {
  identityApi,
  projectsApi,
  type SystemDeliveryMilestoneDigest,
} from '@/lib/api-client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectOption } from '@/components/ui/select'
import { useToast } from '@/components/ui/toast'

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

function toDateInput(value?: string | null) {
  return value ? value.slice(0, 10) : ''
}

function toIsoDate(value: string) {
  return value ? new Date(`${value}T12:00:00`).toISOString() : null
}

function statusVariant(status: string) {
  if (status === 'blocked') return 'destructive' as const
  if (status === 'completed') return 'default' as const
  return 'secondary' as const
}

export default function DeliveryPortfolioPage() {
  const queryClient = useQueryClient()
  const { addToast } = useToast()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('active')
  const [risk, setRisk] = useState('all')
  const [ownerId, setOwnerId] = useState('all')
  const [editing, setEditing] = useState<SystemDeliveryMilestoneDigest | null>(null)
  const [editOwnerId, setEditOwnerId] = useState('')
  const [editPriority, setEditPriority] = useState('medium')
  const [editDueAt, setEditDueAt] = useState('')

  const portfolioQuery = useQuery({
    queryKey: ['delivery-portfolio'],
    queryFn: projectsApi.getDeliveryPortfolio,
  })
  const usersQuery = useQuery({
    queryKey: ['delivery-portfolio-users'],
    queryFn: () => identityApi.listUsers({ pageSize: 100 }),
  })
  const portfolio = portfolioQuery.data?.portfolio
  const users = usersQuery.data?.items || []
  const filtered = useMemo(() => {
    const items = portfolio?.upcoming || []
    const normalized = search.trim().toLowerCase()
    return items.filter((item) => {
      const matchesSearch = !normalized || `${item.project_name} ${item.title} ${item.owner_name}`.toLowerCase().includes(normalized)
      const matchesStatus = status === 'all' || (status === 'active' ? item.status !== 'completed' : item.status === status)
      const matchesRisk = risk === 'all' || (risk === 'overdue' ? item.is_overdue : risk === 'blocked' ? item.status === 'blocked' || item.gate_blocker_count > 0 : item.owner_id === null)
      const matchesOwner = ownerId === 'all' || (ownerId === 'unassigned' ? item.owner_id === null : item.owner_id === ownerId)
      return matchesSearch && matchesStatus && matchesRisk && matchesOwner
    })
  }, [ownerId, portfolio?.upcoming, risk, search, status])

  const updateMutation = useMutation({
    mutationFn: () => projectsApi.updateMilestone(editing!.project_id, editing!.milestone_id, {
      owner_id: editOwnerId || null,
      priority: editPriority as 'low' | 'medium' | 'high' | 'critical',
      due_at: toIsoDate(editDueAt),
    }),
    onSuccess: () => {
      setEditing(null)
      queryClient.invalidateQueries({ queryKey: ['delivery-portfolio'] })
      queryClient.invalidateQueries({ queryKey: ['system-delivery-overview'] })
      addToast({ title: '组合里程碑已更新', description: '责任、优先级和截止日期已同步到项目交付计划。' })
    },
    onError: (error: Error) => addToast({ title: '更新失败', description: error.message, variant: 'destructive' }),
  })

  const openEdit = (item: SystemDeliveryMilestoneDigest) => {
    setEditing(item)
    setEditOwnerId(item.owner_id || '')
    setEditPriority(item.priority)
    setEditDueAt(toDateInput(item.due_at))
  }

  if (portfolioQuery.isLoading) return <div className="py-16 text-center text-sm text-slate-500">正在加载交付组合...</div>
  if (!portfolio) return <div className="py-16 text-center text-sm text-red-600">交付组合加载失败，请稍后重试。</div>

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">跨项目交付组合</h1>
        <p className="mt-1 text-sm text-slate-500">集中识别跨项目里程碑风险、责任负载和截止日期，并直接调整执行责任。</p>
      </div>

      <section data-testid="delivery-portfolio-summary" className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        {[
          ['项目', portfolioQuery.data?.project_count ?? 0],
          ['活动里程碑', portfolio.totals.active || 0],
          ['阻塞', portfolio.totals.blocked || 0],
          ['逾期', portfolio.totals.overdue || 0],
          ['未分配', portfolio.totals.unassigned || 0],
          ['已完成', portfolio.totals.completed || 0],
        ].map(([label, value]) => (
          <Card key={label as string}>
            <CardContent className="pt-4">
              <p className="text-2xl font-semibold text-slate-900 dark:text-white">{value}</p>
              <p className="mt-1 text-xs text-slate-500">{label}</p>
            </CardContent>
          </Card>
        ))}
      </section>

      <section className="grid gap-3 rounded-md border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900 lg:grid-cols-[minmax(240px,1fr)_160px_160px_220px]">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <Input className="pl-10" placeholder="搜索项目、里程碑或负责人" value={search} onChange={(event) => setSearch(event.target.value)} />
        </div>
        <Select data-testid="portfolio-status-filter" value={status} onValueChange={setStatus}>
          <SelectOption value="active">活动里程碑</SelectOption>
          <SelectOption value="all">全部状态</SelectOption>
          <SelectOption value="planned">待开始</SelectOption>
          <SelectOption value="in_progress">进行中</SelectOption>
          <SelectOption value="blocked">受阻</SelectOption>
          <SelectOption value="completed">已完成</SelectOption>
        </Select>
        <Select value={risk} onValueChange={setRisk}>
          <SelectOption value="all">全部风险</SelectOption>
          <SelectOption value="blocked">门禁阻塞</SelectOption>
          <SelectOption value="overdue">已逾期</SelectOption>
          <SelectOption value="unassigned">未分配</SelectOption>
        </Select>
        <Select value={ownerId} onValueChange={setOwnerId}>
          <SelectOption value="all">全部负责人</SelectOption>
          <SelectOption value="unassigned">未分配</SelectOption>
          {users.map((user) => <SelectOption key={user.id} value={user.id}>{user.full_name || user.email}</SelectOption>)}
        </Select>
      </section>

      <section data-testid="delivery-portfolio-table" className="overflow-hidden rounded-md border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
        <div className="hidden grid-cols-[minmax(220px,1.2fr)_150px_160px_130px_120px] gap-3 border-b border-slate-200 px-4 py-3 text-xs font-semibold text-slate-500 dark:border-slate-700 lg:grid">
          <span>项目与里程碑</span><span>负责人</span><span>截止与风险</span><span>状态</span><span>操作</span>
        </div>
        {filtered.map((item) => (
          <div key={item.milestone_id} className="grid gap-3 border-b border-slate-200 p-4 last:border-b-0 dark:border-slate-700 lg:grid-cols-[minmax(220px,1.2fr)_150px_160px_130px_120px] lg:items-center">
            <div>
              <p className="text-xs text-slate-500">{item.project_name}</p>
              <p className="mt-1 font-semibold text-slate-900 dark:text-white">{item.title}</p>
            </div>
            <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300"><UserRound className="h-4 w-4" />{item.owner_name}</div>
            <div className="space-y-1 text-sm">
              <p className="flex items-center gap-2 text-slate-600 dark:text-slate-300"><CalendarClock className="h-4 w-4" />{item.due_at ? new Date(item.due_at).toLocaleDateString('zh-CN') : '未设置'}</p>
              {item.is_overdue ? <Badge variant="destructive">已逾期</Badge> : null}
              {item.gate_blocker_count ? <Badge variant="outline">{item.gate_blocker_count} 个门禁阻塞</Badge> : null}
            </div>
            <div className="flex flex-wrap gap-2"><Badge variant={statusVariant(item.status)}>{STATUS_LABELS[item.status] || item.status}</Badge><Badge variant={item.priority === 'critical' ? 'destructive' : 'outline'}>{PRIORITY_LABELS[item.priority] || item.priority}</Badge></div>
            <div className="flex gap-2">
              <Button data-testid={`edit-portfolio-${item.milestone_id}`} size="sm" variant="outline" onClick={() => openEdit(item)}><Pencil className="h-4 w-4" /></Button>
              <Button size="sm" variant="ghost" asChild><Link href={item.action_href}><ExternalLink className="h-4 w-4" /></Link></Button>
            </div>
          </div>
        ))}
        {filtered.length === 0 ? <div className="flex items-center justify-center gap-2 p-10 text-sm text-slate-500"><ShieldAlert className="h-4 w-4" />没有匹配的交付里程碑。</div> : null}
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-md border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
          <h2 className="flex items-center gap-2 font-semibold text-slate-900 dark:text-white"><AlertTriangle className="h-4 w-4 text-amber-600" />阻塞队列</h2>
          <div className="mt-3 space-y-2">{portfolio.blocked.slice(0, 8).map((item) => <Link key={item.milestone_id} href={item.action_href} className="block border-b border-slate-200 py-2 text-sm last:border-b-0 dark:border-slate-700">{item.project_name} · {item.title}</Link>)}</div>
        </div>
        <div className="rounded-md border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
          <h2 className="flex items-center gap-2 font-semibold text-slate-900 dark:text-white"><UserRound className="h-4 w-4 text-indigo-600" />责任负载</h2>
          <div className="mt-3 space-y-2">{portfolio.owner_load.slice(0, 8).map((owner) => <div key={owner.owner_id || 'unassigned'} className="flex justify-between border-b border-slate-200 py-2 text-sm last:border-b-0 dark:border-slate-700"><span>{owner.owner_name}</span><span className="text-slate-500">活动 {owner.active_count} · 阻塞 {owner.blocked_count} · 逾期 {owner.overdue_count}</span></div>)}</div>
        </div>
      </section>

      <Dialog open={Boolean(editing)} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>调整组合里程碑责任</DialogTitle><DialogDescription>{editing?.project_name} · {editing?.title}</DialogDescription></DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2"><Label>负责人</Label><Select value={editOwnerId} onValueChange={setEditOwnerId}><SelectOption value="">未分配</SelectOption>{users.map((user) => <SelectOption key={user.id} value={user.id}>{user.full_name || user.email}</SelectOption>)}</Select></div>
            <div className="space-y-2"><Label>优先级</Label><Select data-testid="portfolio-milestone-priority" value={editPriority} onValueChange={setEditPriority}><SelectOption value="low">低</SelectOption><SelectOption value="medium">中</SelectOption><SelectOption value="high">高</SelectOption><SelectOption value="critical">紧急</SelectOption></Select></div>
            <div className="space-y-2"><Label>截止日期</Label><Input type="date" value={editDueAt} onChange={(event) => setEditDueAt(event.target.value)} /></div>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setEditing(null)}>取消</Button><Button data-testid="save-portfolio-milestone" onClick={() => updateMutation.mutate()} disabled={updateMutation.isPending}>保存调整</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
