'use client'

import { FormEvent, use } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { AlertCircle, CheckCircle2, Clock3, Loader2, LockKeyhole, Mail, ShieldCheck } from 'lucide-react'
import { projectMembersApi } from '@/lib/api-client'
import { setToken, useAuth } from '@/lib/auth'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

interface InvitationPageProps {
  params: Promise<{ token: string }>
}

const statusCopy = {
  invalid: ['邀请链接无效', '请联系项目负责人重新发送邀请。'],
  expired: ['邀请链接已过期', '请联系项目负责人续期后再试。'],
  revoked: ['邀请已撤销', '该邀请已被项目负责人撤销。'],
  accepted: ['邀请已使用', '该邀请已经被接受，不能再次使用。'],
} as const

export default function InvitationPage({ params }: InvitationPageProps) {
  const { token } = use(params)
  const router = useRouter()
  const { isAuthenticated, isLoading: isAuthLoading } = useAuth()
  const previewQuery = useQuery({
    queryKey: ['project-invitation-preview', token],
    queryFn: () => projectMembersApi.previewInvitation(token),
    retry: false,
  })
  const activationMutation = useMutation({
    mutationFn: (data: { full_name: string; password: string }) => projectMembersApi.activateInvitation(token, data),
    onSuccess: (result) => setToken(result.access_token),
  })
  const acceptMutation = useMutation({
    mutationFn: () => projectMembersApi.acceptInvitation(token),
  })
  const result = activationMutation.data ?? acceptMutation.data
  const mutationError = activationMutation.error ?? acceptMutation.error

  const activate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    activationMutation.mutate({
      full_name: String(form.get('full_name') ?? '').trim(),
      password: String(form.get('password') ?? ''),
    })
  }

  if (previewQuery.isLoading || isAuthLoading) {
    return <InvitationShell><Loader2 className="h-8 w-8 animate-spin text-indigo-600" /></InvitationShell>
  }
  if (previewQuery.isError) {
    return <InvitationState title="无法读取邀请" description={previewQuery.error.message} />
  }
  if (result) {
    return (
      <InvitationShell>
        <CheckCircle2 className="h-11 w-11 text-emerald-600" />
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold text-slate-950 dark:text-white">已加入项目</h1>
          <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">
            你已加入“{result.project_name}”，现在可以进入项目工作台。
          </p>
        </div>
        <Button className="w-full" onClick={() => router.push(`/projects/${result.project_id}`)}>进入项目</Button>
      </InvitationShell>
    )
  }

  const preview = previewQuery.data
  if (!preview || preview.status !== 'active') {
    const [title, description] = statusCopy[preview?.status as keyof typeof statusCopy] ?? statusCopy.invalid
    return <InvitationState title={title} description={description} />
  }

  return (
    <InvitationShell>
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-2">
          <p className="text-xs font-medium uppercase text-indigo-600">项目协作邀请</p>
          <h1 className="text-2xl font-semibold text-slate-950 dark:text-white">{preview.project_name}</h1>
          <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">项目负责人邀请你以最低权限成员身份加入协作。</p>
        </div>
        <Mail className="h-10 w-10 shrink-0 text-indigo-600" />
      </div>
      <div className="grid gap-3 rounded-md border border-slate-200 p-4 text-sm dark:border-slate-700">
        <div className="flex items-center gap-3"><ShieldCheck className="h-5 w-5 text-emerald-600" /><span>受邀邮箱：{preview.masked_email}</span></div>
        <div className="flex items-center gap-3"><Clock3 className="h-5 w-5 text-slate-500" /><span>有效期至：{preview.expires_at ? new Date(preview.expires_at).toLocaleString('zh-CN') : '未提供'}</span></div>
      </div>
      {mutationError && (
        <div className="flex gap-3 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
          <AlertCircle className="h-5 w-5 shrink-0" /><p>{mutationError.message}</p>
        </div>
      )}
      {isAuthenticated ? (
        <div className="space-y-3">
          <p className="text-sm text-slate-600 dark:text-slate-300">系统将核对当前登录账号与受邀邮箱。</p>
          <Button className="w-full" disabled={acceptMutation.isPending} onClick={() => acceptMutation.mutate()}>
            {acceptMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}接受邀请并加入项目
          </Button>
        </div>
      ) : (
        <form className="space-y-4" onSubmit={activate}>
          <div className="space-y-2"><Label htmlFor="full_name">姓名</Label><Input id="full_name" name="full_name" minLength={1} maxLength={255} required autoComplete="name" /></div>
          <div className="space-y-2"><Label htmlFor="password">设置密码</Label><Input id="password" name="password" type="password" minLength={8} maxLength={100} required autoComplete="new-password" /></div>
          <Button className="w-full" disabled={activationMutation.isPending} type="submit">
            {activationMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}激活账号并加入项目
          </Button>
          <Button className="w-full" variant="outline" type="button" onClick={() => router.push(`/login?next=/invitations/${token}`)}>已有账号，前往登录</Button>
        </form>
      )}
    </InvitationShell>
  )
}

function InvitationState({ title, description }: { title: string; description: string }) {
  return <InvitationShell><LockKeyhole className="h-10 w-10 text-slate-500" /><div className="space-y-2"><h1 className="text-2xl font-semibold text-slate-950 dark:text-white">{title}</h1><p className="text-sm leading-6 text-slate-600 dark:text-slate-300">{description}</p></div></InvitationShell>
}

function InvitationShell({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-100 px-4 py-10 dark:bg-slate-950">
      <Card className="w-full max-w-lg">
        <CardHeader className="sr-only"><CardTitle>项目邀请</CardTitle><CardDescription>安全加入项目协作</CardDescription></CardHeader>
        <CardContent className="space-y-6 pt-6">{children}</CardContent>
      </Card>
    </main>
  )
}
