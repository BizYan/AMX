'use client'

import { use } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { CheckCircle2, Mail, ShieldCheck } from 'lucide-react'
import { projectMembersApi } from '@/lib/api-client'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useToast } from '@/components/ui/toast'

interface InvitationAcceptPageProps {
  params: Promise<{ token: string }>
}

export default function InvitationAcceptPage({ params }: InvitationAcceptPageProps) {
  const { token } = use(params)
  const router = useRouter()
  const { addToast } = useToast()

  const acceptMutation = useMutation({
    mutationFn: () => projectMembersApi.acceptInvitation(token),
    onSuccess: (result) => {
      addToast({ title: '已加入项目', description: `你已加入 ${result.project_name}` })
    },
    onError: (error: Error) => {
      addToast({ title: '无法接受邀请', description: error.message, variant: 'destructive' })
    },
  })

  if (acceptMutation.data) {
    return (
      <div className="mx-auto max-w-xl py-16">
        <Card>
          <CardHeader>
            <CheckCircle2 className="mb-3 h-10 w-10 text-emerald-600" />
            <CardTitle>邀请已接受</CardTitle>
            <CardDescription>你已加入项目“{acceptMutation.data.project_name}”，现在可以进入项目工作台。</CardDescription>
          </CardHeader>
          <CardContent>
            <Button className="w-full" onClick={() => router.push(`/projects/${acceptMutation.data?.project_id}`)}>
              进入项目
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-xl py-16">
      <Card>
        <CardHeader>
          <Mail className="mb-3 h-10 w-10 text-indigo-600" />
          <CardTitle>接受项目邀请</CardTitle>
          <CardDescription>系统会核对当前登录账号的邮箱和租户。验证通过后，你将成为项目成员。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-3 rounded-md border border-slate-200 p-4 text-sm text-slate-600 dark:border-slate-700 dark:text-slate-300">
            <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" />
            <p>邀请链接只能使用一次；已过期、已撤销或邮箱不匹配的邀请会被拒绝。</p>
          </div>
          <Button className="w-full" disabled={acceptMutation.isPending} onClick={() => acceptMutation.mutate()}>
            {acceptMutation.isPending ? '正在验证邀请...' : '接受并加入项目'}
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
