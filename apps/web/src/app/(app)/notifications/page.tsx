'use client'

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, Bell, CheckCheck, CircleAlert, ExternalLink, Save, Search, ShieldCheck } from 'lucide-react'
import { useRouter } from 'next/navigation'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectOption } from '@/components/ui/select'
import { useToast } from '@/components/ui/toast'
import { notificationsApi, type UserNotification } from '@/lib/api-client'
import { formatDistanceToNow } from '@/lib/utils'

const categoryLabels: Record<string, string> = {
  document_lifecycle: '文档流程',
  document_review: '文档评审',
  comment: '评论协作',
  agent_run: '智能编排',
  operations_alert: '运维告警',
  system: '系统通知',
}

const priorityLabels: Record<string, string> = {
  low: '低',
  normal: '普通',
  high: '高',
  urgent: '紧急',
}

function priorityVariant(priority: string) {
  if (priority === 'urgent' || priority === 'high') return 'destructive' as const
  if (priority === 'normal') return 'secondary' as const
  return 'outline' as const
}

export default function NotificationsPage() {
  const router = useRouter()
  const queryClient = useQueryClient()
  const { addToast } = useToast()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<'active' | 'unread' | 'archived' | 'escalated'>('active')
  const [category, setCategory] = useState('all')
  const [priority, setPriority] = useState('all')
  const [acknowledgement, setAcknowledgement] = useState('all')

  const query = useQuery({
    queryKey: ['notifications', 'list', status, category, priority, search, acknowledgement],
    queryFn: () => notificationsApi.list({
      unreadOnly: status === 'unread',
      archivedOnly: status === 'archived',
      category: category === 'all' ? undefined : category,
      priority: priority === 'all' ? undefined : priority,
      search: search || undefined,
      acknowledgement: acknowledgement === 'all' ? undefined : acknowledgement as 'required' | 'acknowledged',
      escalated: status === 'escalated' ? true : undefined,
    }),
  })
  const preferenceQuery = useQuery({
    queryKey: ['notifications', 'preferences'],
    queryFn: notificationsApi.getPreferences,
  })
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['notifications'] })
  const markRead = useMutation({ mutationFn: notificationsApi.markRead, onSuccess: invalidate })
  const markAllRead = useMutation({
    mutationFn: notificationsApi.markAllRead,
    onSuccess: (result) => {
      invalidate()
      addToast({ title: '通知已处理', description: `已将 ${result.changed} 条通知标记为已读。` })
    },
  })
  const archive = useMutation({
    mutationFn: notificationsApi.archive,
    onSuccess: () => {
      invalidate()
      addToast({ title: '通知已归档' })
    },
  })
  const acknowledge = useMutation({
    mutationFn: notificationsApi.acknowledge,
    onSuccess: () => {
      invalidate()
      addToast({ title: '关键通知已确认', description: '确认时间和处理证据已记录。' })
    },
  })
  const savePreferences = useMutation({
    mutationFn: notificationsApi.updatePreferences,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] })
      addToast({ title: '通知偏好已保存' })
    },
  })

  const items = useMemo(() => query.data?.items || [], [query.data?.items])

  const openNotification = async (notification: UserNotification) => {
    if (!notification.read_at) await markRead.mutateAsync(notification.id)
    if (notification.action_url) router.push(notification.action_url)
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6" data-testid="notification-center">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">通知中心</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">集中处理文档评审、协作评论、智能编排和运维告警。</p>
        </div>
        <Button
          variant="outline"
          className="gap-2"
          onClick={() => markAllRead.mutate()}
          disabled={!query.data?.unread_count || markAllRead.isPending}
          data-testid="notification-read-all"
        >
          <CheckCheck className="h-4 w-4" />
          全部已读
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm text-slate-500">未读通知</CardTitle></CardHeader>
          <CardContent data-testid="notification-unread-kpi" className="text-2xl font-semibold">{query.data?.unread_count || 0}</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm text-slate-500">当前列表</CardTitle></CardHeader>
          <CardContent className="text-2xl font-semibold">{items.length}</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm text-slate-500">紧急事项</CardTitle></CardHeader>
          <CardContent className="text-2xl font-semibold text-red-600">{items.filter((item) => item.priority === 'urgent').length}</CardContent>
        </Card>
      </div>

      {preferenceQuery.data && (
        <div className="rounded-md border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800" data-testid="notification-preferences">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h2 className="flex items-center gap-2 font-medium text-slate-900 dark:text-white">
                <ShieldCheck className="h-4 w-4" />
                通知偏好与确认时限
              </h2>
              <p className="mt-1 text-sm text-slate-500">紧急通知始终投递；普通通知按最低优先级过滤。</p>
            </div>
            <Button
              size="sm"
              className="gap-2"
              data-testid="notification-preferences-save"
              disabled={savePreferences.isPending}
              onClick={() => savePreferences.mutate({
                in_app_enabled: preferenceQuery.data.in_app_enabled,
                email_enabled: preferenceQuery.data.email_enabled,
                min_priority: preferenceQuery.data.min_priority,
                daily_digest: preferenceQuery.data.daily_digest,
                ack_timeout_minutes: preferenceQuery.data.ack_timeout_minutes,
              })}
            >
              <Save className="h-4 w-4" />
              保存偏好
            </Button>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-4">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={preferenceQuery.data.in_app_enabled}
                onChange={(event) => queryClient.setQueryData(['notifications', 'preferences'], { ...preferenceQuery.data, in_app_enabled: event.target.checked })}
              />
              启用站内通知
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={preferenceQuery.data.email_enabled}
                onChange={(event) => queryClient.setQueryData(['notifications', 'preferences'], { ...preferenceQuery.data, email_enabled: event.target.checked })}
              />
              启用邮件通知
            </label>
            <Select
              value={preferenceQuery.data.min_priority}
              onChange={(event) => queryClient.setQueryData(['notifications', 'preferences'], { ...preferenceQuery.data, min_priority: event.target.value })}
              aria-label="最低通知优先级"
            >
              {Object.entries(priorityLabels).map(([value, label]) => <SelectOption key={value} value={value}>最低：{label}</SelectOption>)}
            </Select>
            <Input
              type="number"
              min={5}
              max={10080}
              aria-label="默认确认时限"
              value={preferenceQuery.data.ack_timeout_minutes}
              onChange={(event) => queryClient.setQueryData(['notifications', 'preferences'], { ...preferenceQuery.data, ack_timeout_minutes: Number(event.target.value) })}
            />
          </div>
        </div>
      )}

      <div className="grid gap-3 rounded-md border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800 md:grid-cols-[minmax(220px,1fr)_150px_150px_150px_150px]">
        <div className="relative">
          <Search className="absolute left-3 top-3 h-4 w-4 text-slate-400" />
          <Input className="pl-9" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索通知标题或内容" />
        </div>
        <Select value={status} onChange={(event) => setStatus(event.target.value as typeof status)}>
          <SelectOption value="active">当前通知</SelectOption>
          <SelectOption value="unread">仅未读</SelectOption>
          <SelectOption value="archived">已归档</SelectOption>
          <SelectOption value="escalated">已升级</SelectOption>
        </Select>
        <Select value={category} onChange={(event) => setCategory(event.target.value)}>
          <SelectOption value="all">全部分类</SelectOption>
          {Object.entries(categoryLabels).map(([value, label]) => <SelectOption key={value} value={value}>{label}</SelectOption>)}
        </Select>
        <Select value={priority} onChange={(event) => setPriority(event.target.value)}>
          <SelectOption value="all">全部优先级</SelectOption>
          {Object.entries(priorityLabels).map(([value, label]) => <SelectOption key={value} value={value}>{label}</SelectOption>)}
        </Select>
        <Select value={acknowledgement} onChange={(event) => setAcknowledgement(event.target.value)}>
          <SelectOption value="all">全部确认状态</SelectOption>
          <SelectOption value="required">待确认</SelectOption>
          <SelectOption value="acknowledged">已确认</SelectOption>
        </Select>
      </div>

      <div className="overflow-hidden rounded-md border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800">
        {query.isLoading ? (
          <div className="p-10 text-center text-sm text-slate-500">正在加载通知...</div>
        ) : query.isError ? (
          <div className="flex flex-col items-center gap-3 p-10 text-center text-sm text-red-600">
            <CircleAlert className="h-6 w-6" />
            通知暂时无法加载，请稍后重试。
          </div>
        ) : items.length ? (
          items.map((notification) => (
            <div key={notification.id} className={`flex gap-4 border-b border-slate-100 p-4 last:border-b-0 dark:border-slate-700 ${notification.read_at ? '' : 'bg-indigo-50/60 dark:bg-indigo-950/20'}`}>
              <div className={`mt-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-md ${notification.read_at ? 'bg-slate-100 text-slate-500 dark:bg-slate-700' : 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-200'}`}>
                <Bell className="h-4 w-4" />
              </div>
              <button type="button" className="min-w-0 flex-1 text-left" onClick={() => openNotification(notification)}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-slate-900 dark:text-white">{notification.title}</span>
                  <Badge variant={priorityVariant(notification.priority)}>{priorityLabels[notification.priority] || notification.priority}</Badge>
                  <Badge variant="outline">{categoryLabels[notification.category] || notification.category}</Badge>
                  {notification.escalation_level > 0 && <Badge variant="destructive">已升级</Badge>}
                  {notification.ack_required && !notification.acknowledged_at && <Badge variant="outline">待确认</Badge>}
                </div>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{notification.body}</p>
                <p className="mt-2 text-xs text-slate-400">{formatDistanceToNow(notification.created_at)}</p>
              </button>
              <div className="flex shrink-0 items-start gap-1">
                {notification.ack_required && !notification.acknowledged_at && (
                  <Button
                    variant="outline"
                    size="sm"
                    aria-label="确认关键通知"
                    data-testid={`notification-acknowledge-${notification.id}`}
                    disabled={acknowledge.isPending}
                    onClick={() => acknowledge.mutate(notification.id)}
                  >
                    <CheckCheck className="h-4 w-4" />
                  </Button>
                )}
                {notification.action_url && (
                  <Button variant="ghost" size="sm" aria-label="打开相关事项" onClick={() => openNotification(notification)}>
                    <ExternalLink className="h-4 w-4" />
                  </Button>
                )}
                {!notification.archived_at && (
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label="归档通知"
                    onClick={() => archive.mutate(notification.id)}
                    data-testid={`notification-archive-${notification.id}`}
                  >
                    <Archive className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </div>
          ))
        ) : (
          <div className="flex flex-col items-center gap-3 p-12 text-center text-sm text-slate-500">
            <Bell className="h-7 w-7" />
            当前筛选条件下没有通知。
          </div>
        )}
      </div>
    </div>
  )
}
