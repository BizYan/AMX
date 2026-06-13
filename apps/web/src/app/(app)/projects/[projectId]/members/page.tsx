'use client'

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { identityApi, projectMembersApi } from '@/lib/api-client'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { useToast } from '@/components/ui/toast'
import { ArrowLeft, Copy, Mail, Send, Trash2, UserPlus, Users } from 'lucide-react'
import { formatDistanceToNow } from '@/lib/utils'

interface ProjectMembersPageProps {
  params: { projectId: string }
}

export default function ProjectMembersPage({ params }: ProjectMembersPageProps) {
  const { projectId } = params
  const router = useRouter()
  const queryClient = useQueryClient()
  const { addToast } = useToast()
  const [email, setEmail] = useState('')
  const [lastInvite, setLastInvite] = useState<{ email: string; token: string; expires_at: string } | null>(null)

  const { data: membersData, isLoading } = useQuery({
    queryKey: ['project-members', projectId],
    queryFn: () => projectMembersApi.list(projectId, { pageSize: 100 }),
  })

  const { data: usersData } = useQuery({
    queryKey: ['tenant-users-for-project-members'],
    queryFn: () => identityApi.listUsers({ pageSize: 100 }),
  })

  const inviteMutation = useMutation({
    mutationFn: () => projectMembersApi.invite(projectId, email.trim()),
    onSuccess: (invite) => {
      queryClient.invalidateQueries({ queryKey: ['project-members', projectId] })
      setLastInvite({ email: email.trim(), ...invite })
      addToast({ title: '邀请已创建', description: '系统已生成邀请令牌，请复制后发送给受邀用户。' })
      setEmail('')
    },
    onError: (error: Error) => {
      addToast({ title: '发送邀请失败', description: error.message, variant: 'destructive' })
    },
  })

  const removeMemberMutation = useMutation({
    mutationFn: (userId: string) => projectMembersApi.remove(projectId, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project-members', projectId] })
      addToast({ title: '成员已移除' })
    },
    onError: (error: Error) => {
      addToast({ title: '移除成员失败', description: error.message, variant: 'destructive' })
    },
  })

  const members = membersData?.items || []
  const users = usersData?.items || []
  const isValidEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())

  const getUserLabel = (userId: string) => {
    const user = users.find((item) => item.id === userId)
    return user ? `${user.full_name || user.email} (${user.email})` : userId
  }

  const handleRemoveMember = (userId: string) => {
    if (window.confirm(`确认移除成员 ${getUserLabel(userId)}？`)) {
      removeMemberMutation.mutate(userId)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="sm" onClick={() => router.push(`/projects/${projectId}`)}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">项目成员</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">查看成员并创建邀请</p>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <UserPlus className="h-5 w-5" />
            邀请成员
          </CardTitle>
          <CardDescription>输入邮箱创建项目邀请，并在成员列表中跟踪邀请状态。</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-[1fr_auto] gap-3 items-end">
            <div className="space-y-2">
              <Label htmlFor="invite-email">邮箱</Label>
              <Input
                id="invite-email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="user@example.com"
              />
            </div>
            <Button
              onClick={() => inviteMutation.mutate()}
              disabled={!isValidEmail || inviteMutation.isPending}
            >
              <Send className="mr-2 h-4 w-4" />
              {inviteMutation.isPending ? '处理中...' : '创建邀请'}
            </Button>
          </div>
          {email.trim() && !isValidEmail && (
            <p className="mt-3 text-sm text-amber-600 dark:text-amber-300">请输入有效邮箱地址后再创建邀请。</p>
          )}
          {lastInvite && (
            <div className="mt-4 rounded-lg border border-green-200 bg-green-50 p-4 text-sm text-green-800 dark:border-green-900 dark:bg-green-950 dark:text-green-100">
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div>
                  <p className="font-medium">已为 {lastInvite.email} 创建邀请</p>
                  <p className="mt-1 break-all text-green-700 dark:text-green-200">邀请令牌：{lastInvite.token}</p>
                  <p className="mt-1 text-xs">有效期至 {new Date(lastInvite.expires_at).toLocaleString('zh-CN')}</p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    navigator.clipboard?.writeText(lastInvite.token)
                    addToast({ title: '已复制邀请令牌' })
                  }}
                >
                  <Copy className="mr-2 h-4 w-4" />
                  复制令牌
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="h-5 w-5" />
            成员列表
          </CardTitle>
          <CardDescription>当前项目已授权的成员。</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="py-8 text-center text-slate-500 dark:text-slate-400">正在加载成员...</div>
          ) : members.length === 0 ? (
            <div className="py-12 text-center text-slate-500 dark:text-slate-400">
              <Mail className="mx-auto h-10 w-10 text-slate-300" />
              <p className="mt-3 text-sm">暂无项目成员记录</p>
            </div>
          ) : (
            <div className="space-y-2">
              {members.map((member) => (
                <div
                  key={member.user_id}
                  className="flex items-center justify-between rounded-lg border border-slate-200 dark:border-slate-700 p-3"
                >
                  <div>
                    <p className="text-sm font-medium text-slate-900 dark:text-white">{getUserLabel(member.user_id)}</p>
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      {member.created_at ? `加入于 ${formatDistanceToNow(member.created_at)}` : '成员记录'}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant="secondary">{member.role_id ? '成员' : '成员'}</Badge>
                    {member.role_id !== 'admin' && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleRemoveMember(member.user_id)}
                        disabled={removeMemberMutation.isPending}
                        data-testid={`project-member-remove-${member.user_id}`}
                      >
                        <Trash2 className="mr-2 h-4 w-4" />
                        移除
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
