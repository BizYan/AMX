'use client'

import { use, useEffect, useState } from 'react'
import Link from 'next/link'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, CheckCircle2, Copy, Link2, PackageCheck, Plus, RotateCcw, Trash2, XCircle } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useToast } from '@/components/ui/toast'
import { CustomerPortalLinkCreated, ProjectAcceptanceItem, ProjectAcceptanceUpdate, projectsApi } from '@/lib/api-client'

const emptyItem = (): ProjectAcceptanceItem => ({
  key: '',
  title: '',
  status: 'pending',
  evidence: '',
})

export default function ProjectAcceptancePage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = use(params)
  const queryClient = useQueryClient()
  const { addToast } = useToast()
  const [form, setForm] = useState<ProjectAcceptanceUpdate>({
    customer_name: '',
    contact_name: '',
    contact_email: '',
    decision: 'pending',
    notes: '',
    items: [],
  })
  const [portalEmail, setPortalEmail] = useState('')
  const [createdPortal, setCreatedPortal] = useState<CustomerPortalLinkCreated | null>(null)

  const acceptanceQuery = useQuery({
    queryKey: ['project-acceptance', projectId],
    queryFn: () => projectsApi.getAcceptance(projectId),
  })
  const projectQuery = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => projectsApi.get(projectId),
  })
  const portalLinksQuery = useQuery({
    queryKey: ['customer-portal-links', projectId],
    queryFn: () => projectsApi.listCustomerPortalLinks(projectId),
  })

  useEffect(() => {
    if (!acceptanceQuery.data) return
    setForm({
      customer_name: acceptanceQuery.data.customer_name,
      contact_name: acceptanceQuery.data.contact_name,
      contact_email: acceptanceQuery.data.contact_email,
      decision: acceptanceQuery.data.decision,
      notes: acceptanceQuery.data.notes,
      items: acceptanceQuery.data.items,
    })
  }, [acceptanceQuery.data])

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['project-acceptance', projectId] })
    queryClient.invalidateQueries({ queryKey: ['project-delivery-plan', projectId] })
    queryClient.invalidateQueries({ queryKey: ['delivery-portfolio'] })
  }
  const saveMutation = useMutation({
    mutationFn: () => projectsApi.updateAcceptance(projectId, form),
    onSuccess: () => {
      refresh()
      addToast({ title: '客户验收记录已保存', description: '关闭门禁已按最新证据重新计算。' })
    },
    onError: (error: Error) => addToast({ title: '保存失败', description: error.message, variant: 'destructive' }),
  })
  const closeMutation = useMutation({
    mutationFn: () => projectsApi.closeDelivery(projectId),
    onSuccess: () => {
      refresh()
      addToast({ title: '正式交付已关闭', description: '客户验收、交付包与里程碑证据已形成闭环。' })
    },
    onError: (error: Error) => addToast({ title: '关闭门禁未通过', description: error.message, variant: 'destructive' }),
  })
  const reopenMutation = useMutation({
    mutationFn: () => projectsApi.reopenDelivery(projectId),
    onSuccess: () => {
      refresh()
      addToast({ title: '正式交付已重新打开', description: '可继续处理客户后续事项。' })
    },
  })
  const createPortalMutation = useMutation({
    mutationFn: () => projectsApi.createCustomerPortalLink(projectId, {
      label: '客户验收门户',
      customer_email: portalEmail,
      expires_in_days: 14,
    }),
    onSuccess: (created) => {
      setCreatedPortal(created)
      setPortalEmail('')
      queryClient.invalidateQueries({ queryKey: ['customer-portal-links', projectId] })
      addToast({ title: '客户门户链接已创建', description: '原始链接仅在本次创建后显示，请立即发送给客户。' })
    },
    onError: (error: Error) => addToast({ title: '创建链接失败', description: error.message, variant: 'destructive' }),
  })
  const revokePortalMutation = useMutation({
    mutationFn: (linkId: string) => projectsApi.revokeCustomerPortalLink(projectId, linkId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['customer-portal-links', projectId] }),
  })

  const acceptance = acceptanceQuery.data
  if (acceptanceQuery.isLoading) return <div className="py-16 text-center text-sm text-slate-500">正在加载客户验收...</div>
  if (!acceptance) return <div className="py-16 text-center text-sm text-red-600">客户验收记录加载失败。</div>

  const updateItem = (index: number, patch: Partial<ProjectAcceptanceItem>) => {
    setForm((current) => ({
      ...current,
      items: current.items.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item),
    }))
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="flex items-start gap-3">
          <Button variant="ghost" size="sm" asChild><Link href={`/projects/${projectId}`}><ArrowLeft className="h-4 w-4" /></Link></Button>
          <div>
            <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">客户验收与正式交付</h1>
            <p className="mt-1 text-sm text-slate-500">{projectQuery.data?.name || '项目'} · 记录签署结论、验收证据和正式关闭状态。</p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" asChild><Link href="/exports"><PackageCheck className="mr-2 h-4 w-4" />交付包</Link></Button>
          {acceptance.closed_at ? (
            <Button variant="outline" onClick={() => reopenMutation.mutate()}><RotateCcw className="mr-2 h-4 w-4" />重新打开</Button>
          ) : (
            <Button data-testid="close-formal-delivery" disabled={acceptance.gate.status !== 'passed'} onClick={() => closeMutation.mutate()}>
              <CheckCircle2 className="mr-2 h-4 w-4" />正式关闭
            </Button>
          )}
        </div>
      </div>

      <section className="grid gap-3 md:grid-cols-3" data-testid="acceptance-summary">
        <Card><CardContent className="pt-4"><p className="text-xs text-slate-500">关闭门禁</p><p className="mt-1 text-lg font-semibold">{acceptance.gate.label}</p></CardContent></Card>
        <Card><CardContent className="pt-4"><p className="text-xs text-slate-500">正式交付包</p><p className="mt-1 text-lg font-semibold">{acceptance.package_ready ? '证据就绪' : '尚未就绪'}</p></CardContent></Card>
        <Card><CardContent className="pt-4"><p className="text-xs text-slate-500">正式关闭</p><p className="mt-1 text-lg font-semibold">{acceptance.closed_at ? '已关闭' : '未关闭'}</p></CardContent></Card>
      </section>

      {(acceptance.gate.blockers.length > 0 || acceptance.gate.warnings.length > 0) && (
        <Card data-testid="acceptance-gate">
          <CardHeader><CardTitle>正式交付门禁</CardTitle><CardDescription>所有阻塞项处理后才能关闭项目交付。</CardDescription></CardHeader>
          <CardContent className="space-y-2 text-sm">
            {acceptance.gate.blockers.map((item) => <p key={item} className="text-red-600">阻塞：{item}</p>)}
            {acceptance.gate.warnings.map((item) => <p key={item} className="text-amber-600">跟进：{item}</p>)}
          </CardContent>
        </Card>
      )}

      <Card data-testid="acceptance-follow-ups">
        <CardHeader><CardTitle>客户整改执行队列</CardTitle><CardDescription>客户拒绝或待确认的验收项会自动进入协同中心，完成后客户可重新提交验收。</CardDescription></CardHeader>
        <CardContent className="space-y-2">
          {(acceptance.follow_ups || []).map((item) => (
            <div key={item.key} className="flex items-center justify-between rounded-md border p-3 text-sm">
              <div><p className="font-medium">{item.title}</p><p className="text-xs text-slate-500">{item.priority} · {new Date(item.updated_at).toLocaleString()}</p></div>
              <Badge variant={item.status === 'done' ? 'default' : 'secondary'}>{item.status}</Badge>
            </div>
          ))}
          {!acceptance.follow_ups?.length && <p className="text-sm text-slate-500">当前没有客户整改事项。</p>}
          <Button variant="outline" asChild><Link href="/collaboration">打开协同中心</Link></Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>客户签署记录</CardTitle><CardDescription>由项目负责人维护客户、联系人和最终验收结论。</CardDescription></CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <Input data-testid="acceptance-customer-name" placeholder="客户名称" value={form.customer_name} onChange={(event) => setForm({ ...form, customer_name: event.target.value })} />
          <Input data-testid="acceptance-contact-name" placeholder="签署联系人" value={form.contact_name} onChange={(event) => setForm({ ...form, contact_name: event.target.value })} />
          <Input data-testid="acceptance-contact-email" placeholder="联系人邮箱" value={form.contact_email} onChange={(event) => setForm({ ...form, contact_email: event.target.value })} />
          <select data-testid="acceptance-decision" className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm dark:border-slate-700 dark:bg-slate-900" value={form.decision} onChange={(event) => setForm({ ...form, decision: event.target.value as ProjectAcceptanceUpdate['decision'] })}>
            <option value="pending">待验收</option>
            <option value="accepted">通过验收</option>
            <option value="accepted_with_followups">有后续事项通过</option>
            <option value="rejected">拒绝验收</option>
          </select>
          <textarea className="min-h-24 rounded-md border border-slate-300 bg-white p-3 text-sm md:col-span-2 dark:border-slate-700 dark:bg-slate-900" placeholder="验收结论与后续事项" value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} />
        </CardContent>
      </Card>

      <Card data-testid="customer-portal-links">
        <CardHeader>
          <CardTitle>客户交付门户</CardTitle>
          <CardDescription>为客户创建有期限、可撤销的验收链接。系统仅保存令牌哈希，原始链接只显示一次。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input
              data-testid="customer-portal-email"
              placeholder="客户签署邮箱"
              value={portalEmail}
              onChange={(event) => setPortalEmail(event.target.value)}
            />
            <Button
              data-testid="create-customer-portal"
              disabled={!portalEmail || createPortalMutation.isPending}
              onClick={() => createPortalMutation.mutate()}
            >
              <Link2 className="mr-2 h-4 w-4" />创建 14 天链接
            </Button>
          </div>
          {createdPortal && (
            <div className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm dark:border-emerald-800 dark:bg-emerald-950/30">
              <p className="font-medium">一次性可见门户地址</p>
              <div className="mt-2 flex items-center gap-2">
                <code data-testid="created-customer-portal-url" className="min-w-0 flex-1 break-all">{`${window.location.origin}${createdPortal.portal_path}`}</code>
                <Button
                  size="sm"
                  variant="outline"
                  title="复制门户地址"
                  onClick={() => navigator.clipboard.writeText(`${window.location.origin}${createdPortal.portal_path}`)}
                >
                  <Copy className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
          <div className="space-y-2">
            {(portalLinksQuery.data || []).map((link) => (
              <div key={link.id} className="flex flex-col gap-2 rounded-md border border-slate-200 p-3 text-sm sm:flex-row sm:items-center sm:justify-between dark:border-slate-700">
                <div>
                  <p className="font-medium">{link.label} · {link.customer_email}</p>
                  <p className="text-slate-500">
                    到期：{new Date(link.expires_at).toLocaleString()} · {link.submitted_at ? '客户已提交' : link.revoked_at ? '已撤销' : '等待客户'}
                  </p>
                  <p className="text-xs text-slate-500">
                    下载 {link.download_count || 0} 次{link.last_downloaded_at ? ` · 最近 ${new Date(link.last_downloaded_at).toLocaleString()}` : ''}
                    {link.receipt_id ? ` · 回执 ${link.receipt_id}` : ''}
                  </p>
                </div>
                {!link.revoked_at && (
                  <Button variant="ghost" size="sm" onClick={() => revokePortalMutation.mutate(link.id)}>
                    <XCircle className="mr-2 h-4 w-4" />撤销
                  </Button>
                )}
              </div>
            ))}
            {!portalLinksQuery.data?.length && <p className="py-4 text-center text-sm text-slate-500">尚未创建客户门户链接。</p>}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between"><div><CardTitle>逐项验收证据</CardTitle><CardDescription>每项均保留状态和证据说明。</CardDescription></div><Button data-testid="add-acceptance-item" variant="outline" onClick={() => setForm({ ...form, items: [...form.items, emptyItem()] })}><Plus className="mr-2 h-4 w-4" />添加验收项</Button></div>
        </CardHeader>
        <CardContent className="space-y-3" data-testid="acceptance-items">
          {form.items.map((item, index) => (
            <div key={item.key} className="grid gap-3 rounded-md border border-slate-200 p-3 md:grid-cols-[1fr_180px_1fr_auto] dark:border-slate-700">
              <Input placeholder="验收项" value={item.title} onChange={(event) => updateItem(index, { title: event.target.value })} />
              <select className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm dark:border-slate-700 dark:bg-slate-900" value={item.status} onChange={(event) => updateItem(index, { status: event.target.value as ProjectAcceptanceItem['status'] })}>
                <option value="pending">待确认</option><option value="accepted">已接受</option><option value="rejected">已拒绝</option>
              </select>
              <Input placeholder="证据或会议纪要" value={item.evidence} onChange={(event) => updateItem(index, { evidence: event.target.value })} />
              <Button variant="ghost" size="sm" onClick={() => setForm({ ...form, items: form.items.filter((_, itemIndex) => itemIndex !== index) })}><Trash2 className="h-4 w-4" /></Button>
            </div>
          ))}
          {!form.items.length && <p className="py-6 text-center text-sm text-slate-500">尚未登记验收项。</p>}
          <div className="flex items-center justify-between border-t border-slate-200 pt-4 dark:border-slate-700">
            <Badge variant={acceptance.gate.status === 'passed' ? 'default' : 'secondary'}>{acceptance.gate.label}</Badge>
            <Button data-testid="save-acceptance" onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>保存验收记录</Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
