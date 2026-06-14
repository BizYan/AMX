'use client'

import { use, useEffect, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { CheckCircle2, Download, FileCheck2, PackageCheck, ShieldCheck } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  CustomerPortalAcceptanceSubmit,
  ProjectAcceptanceItem,
  customerPortalApi,
} from '@/lib/api-client'

export default function CustomerDeliveryPortalPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params)
  const portalQuery = useQuery({
    queryKey: ['customer-delivery-portal', token],
    queryFn: () => customerPortalApi.get(token),
    retry: false,
  })
  const [form, setForm] = useState<CustomerPortalAcceptanceSubmit>({
    contact_name: '',
    contact_email: '',
    decision: 'accepted',
    notes: '',
    items: [],
  })

  useEffect(() => {
    if (!portalQuery.data) return
    setForm((current) => ({ ...current, items: portalQuery.data.criteria }))
  }, [portalQuery.data])

  const submitMutation = useMutation({
    mutationFn: () => customerPortalApi.submitAcceptance(token, form),
    onSuccess: () => portalQuery.refetch(),
  })
  const updateItem = (index: number, patch: Partial<ProjectAcceptanceItem>) => {
    setForm((current) => ({
      ...current,
      items: current.items.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item),
    }))
  }

  if (portalQuery.isLoading) return <main className="mx-auto max-w-5xl p-8 text-center text-sm text-slate-500">正在验证客户交付门户...</main>
  if (!portalQuery.data) return <main className="mx-auto max-w-3xl p-8 text-center"><h1 className="text-xl font-semibold">客户交付门户不可用</h1><p className="mt-2 text-sm text-slate-500">{portalQuery.error instanceof Error ? portalQuery.error.message : '链接无效、已过期或已撤销。'}</p></main>

  const portal = portalQuery.data
  return (
    <main className="mx-auto min-h-screen max-w-5xl space-y-6 p-5 md:p-10">
      <header>
        <div className="flex items-center gap-2 text-sm text-slate-500"><ShieldCheck className="h-4 w-4" />安全客户交付门户</div>
        <h1 className="mt-2 text-3xl font-semibold">{portal.project_name}</h1>
        <p className="mt-2 text-slate-500">请核对交付证据并提交正式验收结论。</p>
      </header>

      <section className="grid gap-3 md:grid-cols-3">
        <Card><CardContent className="pt-5"><PackageCheck className="h-5 w-5" /><p className="mt-3 text-sm text-slate-500">正式交付包</p><p className="font-semibold">{portal.package_ready ? '已就绪' : '尚未就绪'}</p></CardContent></Card>
        <Card><CardContent className="pt-5"><CheckCircle2 className="h-5 w-5" /><p className="mt-3 text-sm text-slate-500">当前结论</p><p className="font-semibold">{portal.decision}</p></CardContent></Card>
        <Card><CardContent className="pt-5"><ShieldCheck className="h-5 w-5" /><p className="mt-3 text-sm text-slate-500">交付门禁</p><p className="font-semibold">{portal.gate.label}</p></CardContent></Card>
      </section>

      <Card>
        <CardHeader><CardTitle>验收标准与证据</CardTitle><CardDescription>逐项确认状态，拒绝项会阻止正式交付关闭。</CardDescription></CardHeader>
        <CardContent className="space-y-3">
          {form.items.map((item, index) => (
            <div key={item.key} className="grid gap-3 rounded-md border p-3 md:grid-cols-[1fr_180px_1fr]">
              <div><p className="font-medium">{item.title}</p><p className="mt-1 text-xs text-slate-500">{item.evidence || '暂无证据说明'}</p></div>
              <select className="h-10 rounded-md border bg-background px-3 text-sm" value={item.status} onChange={(event) => updateItem(index, { status: event.target.value as ProjectAcceptanceItem['status'] })}>
                <option value="pending">待确认</option><option value="accepted">接受</option><option value="rejected">拒绝</option>
              </select>
              <Input placeholder="客户补充证据或说明" value={item.evidence} onChange={(event) => updateItem(index, { evidence: event.target.value })} />
            </div>
          ))}
          {!form.items.length && <p className="text-sm text-slate-500">项目方尚未登记验收标准，请联系项目负责人。</p>}
        </CardContent>
      </Card>

      <Card data-testid="portal-artifacts">
        <CardHeader><CardTitle>正式交付物</CardTitle><CardDescription>以下文件来自已完成的正式项目交付包，下载行为会记录到交付证据。</CardDescription></CardHeader>
        <CardContent className="space-y-2">
          {portal.artifacts.map((artifact) => (
            <div key={artifact.id} className="flex flex-col gap-2 rounded-md border p-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <p className="truncate font-medium">{artifact.filename}</p>
                <p className="text-xs text-slate-500">{Math.ceil(artifact.file_size / 1024)} KB · {artifact.content_type} · SHA-256 {artifact.file_hash || '未提供'}</p>
              </div>
              <Button variant="outline" asChild>
                <a href={customerPortalApi.downloadArtifact(token, artifact.id)} target="_blank" rel="noreferrer">
                  <Download className="mr-2 h-4 w-4" />下载
                </a>
              </Button>
            </div>
          ))}
          {!portal.artifacts.length && <p className="text-sm text-slate-500">正式交付物尚未发布。</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>提交验收结论</CardTitle><CardDescription>签署邮箱必须与收到本链接的邮箱一致。</CardDescription></CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2">
          <Input data-testid="portal-contact-name" placeholder="签署人姓名" value={form.contact_name} onChange={(event) => setForm({ ...form, contact_name: event.target.value })} />
          <Input data-testid="portal-contact-email" placeholder="签署邮箱" value={form.contact_email} onChange={(event) => setForm({ ...form, contact_email: event.target.value })} />
          <select data-testid="portal-decision" className="h-10 rounded-md border bg-background px-3 text-sm" value={form.decision} onChange={(event) => setForm({ ...form, decision: event.target.value as CustomerPortalAcceptanceSubmit['decision'] })}>
            <option value="accepted">通过验收</option><option value="accepted_with_followups">有后续事项通过</option><option value="rejected">拒绝验收</option>
          </select>
          <Input placeholder="验收说明与后续事项" value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} />
          <div className="flex items-center justify-between md:col-span-2">
            {portal.submitted_at ? <Badge>已于 {new Date(portal.submitted_at).toLocaleString()} 提交</Badge> : <span />}
            <Button data-testid="submit-customer-acceptance" disabled={!form.contact_name || !form.contact_email || submitMutation.isPending} onClick={() => submitMutation.mutate()}>
              提交正式验收
            </Button>
          </div>
          {submitMutation.isError && <p className="text-sm text-red-600 md:col-span-2">{submitMutation.error.message}</p>}
        </CardContent>
      </Card>

      {portal.receipt && (
        <Card data-testid="acceptance-receipt">
          <CardHeader><CardTitle>验收回执</CardTitle><CardDescription>该回执用于追溯本次客户验收提交。</CardDescription></CardHeader>
          <CardContent className="grid gap-3 text-sm md:grid-cols-2">
            <div><p className="text-slate-500">回执编号</p><p className="font-mono">{portal.receipt.id}</p></div>
            <div><p className="text-slate-500">提交时间</p><p>{new Date(portal.receipt.submitted_at).toLocaleString()}</p></div>
            <div><p className="text-slate-500">签署人</p><p>{portal.receipt.contact_name} · {portal.receipt.contact_email}</p></div>
            <div><p className="text-slate-500">验收证据</p><p><FileCheck2 className="mr-1 inline h-4 w-4" />已接受 {portal.receipt.accepted_item_count}/{portal.receipt.item_count} 项</p></div>
          </CardContent>
        </Card>
      )}
    </main>
  )
}
