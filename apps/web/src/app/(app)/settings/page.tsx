'use client'

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import {
  AlertTriangle,
  ArrowRight,
  Check,
  Copy,
  KeyRound,
  LockKeyhole,
  Mail,
  LogOut,
  Power,
  Plus,
  RefreshCw,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Trash2,
  UserCog,
  Users,
} from 'lucide-react'

import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectOption } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useToast } from '@/components/ui/toast'
import { IntegrationWorkbench } from '@/components/settings/integration-workbench'
import { auditApi, authApi, identityApi, apiClient, type Role, type TenantUser } from '@/lib/api-client'

type NormalizedUser = {
  id: string
  name: string
  email: string
  isActive: boolean
  roleNames: string[]
  createdAt?: string
}

const permissionLabels: Record<string, string> = {
  read: '读取',
  write: '写入',
  delete: '删除',
  manage_users: '管理用户',
  manage_settings: '管理设置',
  '*:*': '全局管理',
}

const permissionOptions = ['read', 'write', 'delete', 'manage_users', 'manage_settings']

const privilegedApiKeyPermissions = new Set(['delete', 'manage_users', 'manage_settings', '*:*'])

function normalizePermissions(permissions: Role['permissions'] | undefined): string[] {
  if (!permissions) return []
  if (Array.isArray(permissions)) return permissions.map(String)
  return Object.entries(permissions).map(([resource, action]) => `${resource}:${String(action)}`)
}

function permissionLabel(permission: string) {
  return permissionLabels[permission] ?? permission
}

function formatDateTime(value?: string | null) {
  if (!value) return '暂无记录'
  return new Date(value).toLocaleString('zh-CN')
}

function hasPrivilegedApiKeyScope(permissions: string[]) {
  return permissions.some((permission) => privilegedApiKeyPermissions.has(permission) || permission.startsWith('*:'))
}

function normalizeUser(user: TenantUser): NormalizedUser {
  const raw = user as TenantUser & { name?: string; tenantId?: string }
  return {
    id: user.id,
    name: user.full_name || raw.name || user.email,
    email: user.email,
    isActive: user.is_active !== false,
    roleNames: (user.roles || []).map((role) => role.name).filter(Boolean),
    createdAt: user.created_at,
  }
}

function roleHealth(role: Role) {
  const permissions = normalizePermissions(role.permissions)
  if (permissions.some((item) => item === '*:*' || item === '*:true' || item.startsWith('*:'))) {
    return { label: '高权限', variant: 'destructive' as const }
  }
  if (permissions.includes('manage_users') || permissions.includes('manage_settings')) {
    return { label: '管理权限', variant: 'outline' as const }
  }
  return { label: '标准权限', variant: 'secondary' as const }
}

function StatCard({ title, value, detail }: { title: string; value: string | number; detail: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{title}</CardDescription>
        <CardTitle className="text-3xl">{value}</CardTitle>
      </CardHeader>
      <CardContent className="text-sm text-slate-500">{detail}</CardContent>
    </Card>
  )
}

export default function SettingsPage() {
  const queryClient = useQueryClient()
  const { addToast } = useToast()
  const [activeTab, setActiveTab] = useState('overview')
  const [showUserDialog, setShowUserDialog] = useState(false)
  const [showRoleDialog, setShowRoleDialog] = useState(false)
  const [showApiKeyDialog, setShowApiKeyDialog] = useState(false)
  const [newUser, setNewUser] = useState({ name: '', email: '', role: '' })
  const [newRole, setNewRole] = useState({ name: '', description: '', permissions: ['read'] as string[] })
  const [apiKeyName, setApiKeyName] = useState('')
  const [apiKeyPermissions, setApiKeyPermissions] = useState(['read'])
  const [revealedApiKey, setRevealedApiKey] = useState<{ id: string; token: string } | null>(null)
  const [createdUserCredential, setCreatedUserCredential] = useState<{ email: string; password: string } | null>(null)
  const [copiedKeyId, setCopiedKeyId] = useState<string | null>(null)
  const [passwordForm, setPasswordForm] = useState({ current: '', next: '', confirm: '' })

  const usersQuery = useQuery({
    queryKey: ['tenant-users'],
    queryFn: () => identityApi.listUsers({ pageSize: 100 }),
  })

  const rolesQuery = useQuery({
    queryKey: ['tenant-roles'],
    queryFn: () => identityApi.listRoles({ pageSize: 100 }),
  })

  const auditQuery = useQuery({
    queryKey: ['tenant-permission-audit'],
    queryFn: () => auditApi.listLogs({ pageSize: 12, resourceType: 'role' }),
  })

  const apiKeysQuery = useQuery({
    queryKey: ['tenant-api-keys'],
    queryFn: () => identityApi.listApiKeys({ pageSize: 100 }),
  })
  const accountSecurityQuery = useQuery({
    queryKey: ['account-security'],
    queryFn: () => authApi.getSecurity(),
  })

  const endCurrentSession = () => {
    localStorage.removeItem('auth_token')
    apiClient.setToken(null)
    window.location.assign('/login')
  }

  const changePasswordMutation = useMutation({
    mutationFn: () => authApi.changePassword(passwordForm.current, passwordForm.next),
    onSuccess: () => {
      addToast({ title: '密码已更新', description: '所有现有会话已撤销，请重新登录。' })
      endCurrentSession()
    },
    onError: (error: Error) => addToast({ title: '密码更新失败', description: error.message, variant: 'destructive' }),
  })

  const revokeSessionsMutation = useMutation({
    mutationFn: () => authApi.revokeAllSessions(),
    onSuccess: () => {
      addToast({ title: '所有会话已撤销', description: '请重新登录。' })
      endCurrentSession()
    },
    onError: (error: Error) => addToast({ title: '会话撤销失败', description: error.message, variant: 'destructive' }),
  })

  const deactivateAccountMutation = useMutation({
    mutationFn: () => authApi.deactivateAccount(passwordForm.current),
    onSuccess: () => {
      addToast({ title: '账户已停用' })
      endCurrentSession()
    },
    onError: (error: Error) => addToast({ title: '账户停用失败', description: error.message, variant: 'destructive' }),
  })

  const users = useMemo(() => (usersQuery.data?.items ?? []).map(normalizeUser), [usersQuery.data?.items])
  const roles = rolesQuery.data?.items ?? []
  const apiKeys = apiKeysQuery.data?.items ?? []
  const activeUsers = users.filter((user) => user.isActive)
  const inactiveUsers = users.filter((user) => !user.isActive)
  const highPrivilegeRoles = roles.filter((role) => roleHealth(role).label !== '标准权限')
  const usersWithoutRole = users.filter((user) => user.roleNames.length === 0)
  const activeApiKeys = apiKeys.filter((key) => key.status === 'active')
  const revokedApiKeys = apiKeys.filter((key) => key.status === 'revoked')
  const privilegedApiKeys = apiKeys.filter((key) => key.status === 'active' && hasPrivilegedApiKeyScope(key.permissions))
  const apiKeyScopeCount = new Set(apiKeys.flatMap((key) => key.permissions)).size

  const selectedRole = roles.find((role) => role.id === newUser.role || role.name === newUser.role)

  const inviteUserMutation = useMutation({
    mutationFn: async () => {
      const email = newUser.email.trim()
      const fullName = newUser.name.trim() || email.split('@')[0]
      const created = await identityApi.createUser({
        email,
        full_name: fullName,
      })
      if (!created.temporary_password) {
        throw new Error('Temporary password was not returned by the server')
      }
      if (selectedRole) {
        await identityApi.assignRole(selectedRole.id, created.id)
      }
      return created
    },
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['tenant-users'] })
      setShowUserDialog(false)
      setCreatedUserCredential({ email: created.email, password: created.temporary_password! })
      setNewUser({ name: '', email: '', role: '' })
      addToast({ title: '成员已创建', description: selectedRole ? '已同步分配角色。' : '请在角色矩阵中补充授权。' })
    },
    onError: (error: Error) => addToast({ title: '创建成员失败', description: error.message, variant: 'destructive' }),
  })

  const createRoleMutation = useMutation({
    mutationFn: () =>
      identityApi.createRole({
        name: newRole.name.trim(),
        description: newRole.description.trim() || undefined,
        permissions: newRole.permissions.reduce<Record<string, boolean>>((acc, permission) => {
          acc[permission] = true
          return acc
        }, {}),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tenant-roles'] })
      setShowRoleDialog(false)
      setNewRole({ name: '', description: '', permissions: ['read'] })
      addToast({ title: '角色已创建' })
    },
    onError: (error: Error) => addToast({ title: '创建角色失败', description: error.message, variant: 'destructive' }),
  })

  const toggleUserMutation = useMutation({
    mutationFn: (user: NormalizedUser) => identityApi.updateUser(user.id, { is_active: !user.isActive }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tenant-users'] })
      addToast({ title: '成员状态已更新' })
    },
    onError: (error: Error) => addToast({ title: '更新成员失败', description: error.message, variant: 'destructive' }),
  })

  const deleteUserMutation = useMutation({
    mutationFn: (userId: string) => identityApi.deleteUser(userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tenant-users'] })
      addToast({ title: '成员已删除' })
    },
    onError: (error: Error) => addToast({ title: '删除成员失败', description: error.message, variant: 'destructive' }),
  })

  const refreshAll = () => {
    queryClient.invalidateQueries({ queryKey: ['tenant-users'] })
    queryClient.invalidateQueries({ queryKey: ['tenant-roles'] })
    queryClient.invalidateQueries({ queryKey: ['tenant-permission-audit'] })
    queryClient.invalidateQueries({ queryKey: ['tenant-api-keys'] })
  }

  const createApiKeyMutation = useMutation({
    mutationFn: () =>
      identityApi.createApiKey({
        name: apiKeyName.trim() || '未命名密钥',
        permissions: apiKeyPermissions,
      }),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['tenant-api-keys'] })
      queryClient.invalidateQueries({ queryKey: ['tenant-permission-audit'] })
      setRevealedApiKey({ id: created.id, token: created.api_key })
      setApiKeyName('')
      setApiKeyPermissions(['read'])
      setShowApiKeyDialog(false)
      addToast({ title: 'API Key 已生成', description: '请立即复制，完整密钥只显示一次。' })
    },
    onError: (error: Error) => addToast({ title: '生成 API Key 失败', description: error.message, variant: 'destructive' }),
  })

  const revokeApiKeyMutation = useMutation({
    mutationFn: (keyId: string) => identityApi.revokeApiKey(keyId),
    onSuccess: (_, keyId) => {
      queryClient.invalidateQueries({ queryKey: ['tenant-api-keys'] })
      queryClient.invalidateQueries({ queryKey: ['tenant-permission-audit'] })
      if (revealedApiKey?.id === keyId) setRevealedApiKey(null)
      addToast({ title: 'API Key 已撤销' })
    },
    onError: (error: Error) => addToast({ title: '撤销 API Key 失败', description: error.message, variant: 'destructive' }),
  })

  const copyApiKey = async (keyId: string, token: string) => {
    await navigator.clipboard?.writeText(token)
    setCopiedKeyId(keyId)
    window.setTimeout(() => setCopiedKeyId(null), 1500)
  }

  const copyCreatedUserCredential = async () => {
    if (!createdUserCredential) return
    await navigator.clipboard?.writeText(`${createdUserCredential.email}\n${createdUserCredential.password}`)
    addToast({ title: '临时密码已复制' })
  }

  const riskItems = [
    ...(usersWithoutRole.length
      ? [{ severity: 'high', title: '存在未分配角色成员', detail: `${usersWithoutRole.length} 个成员没有角色, 应补齐最小权限。` }]
      : []),
    ...(inactiveUsers.length
      ? [{ severity: 'medium', title: '存在停用成员', detail: `${inactiveUsers.length} 个成员已停用, 请确认是否需要清理。` }]
      : []),
    ...(highPrivilegeRoles.length
      ? [{ severity: 'medium', title: '高权限角色需复核', detail: `${highPrivilegeRoles.length} 个角色包含管理或全局权限。` }]
      : []),
    ...(privilegedApiKeys.length
      ? [{ severity: 'medium', title: '高权限 API Key 需复核', detail: `${privilegedApiKeys.length} 个启用密钥包含删除、管理或全局权限。` }]
      : []),
  ]

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">团队权限中心</h1>
          <p className="mt-1 text-sm text-slate-500">统一管理租户成员、角色权限、访问风险、API Key 和审计证据。</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={refreshAll}>
            <RefreshCw className="mr-2 h-4 w-4" />
            刷新
          </Button>
          <Button variant="outline" asChild>
            <Link href="/audit">
              <ShieldCheck className="mr-2 h-4 w-4" />
              审计日志
            </Link>
          </Button>
          <Button onClick={() => setShowUserDialog(true)}>
            <Plus className="mr-2 h-4 w-4" />
            新增成员
          </Button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard title="租户成员" value={users.length} detail={`${activeUsers.length} 个启用, ${inactiveUsers.length} 个停用`} />
        <StatCard title="角色数量" value={roles.length} detail={`${highPrivilegeRoles.length} 个需要定期复核`} />
        <StatCard title="权限风险" value={riskItems.length} detail={riskItems.length ? '存在待处理项' : '当前无明显风险'} />
        <StatCard title="服务端 API Key" value={activeApiKeys.length} detail={`${revokedApiKeys.length} 个已撤销, ${apiKeyScopeCount} 类权限范围`} />
      </div>

      {riskItems.length ? (
        <Card className="border-amber-200 bg-amber-50/60 dark:border-amber-900 dark:bg-amber-950/20">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldAlert className="h-5 w-5 text-amber-600" />
              权限风险队列
            </CardTitle>
            <CardDescription>这些事项会影响生产系统的最小权限和审计闭环。</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-3">
            {riskItems.map((item) => (
              <div key={item.title} className="rounded-lg border border-amber-200 bg-white p-4 text-sm dark:border-amber-900 dark:bg-slate-950/40">
                <Badge variant={item.severity === 'high' ? 'destructive' : 'outline'}>{item.severity === 'high' ? '高' : '中'}</Badge>
                <p className="mt-3 font-semibold text-slate-900 dark:text-white">{item.title}</p>
                <p className="mt-1 text-slate-600 dark:text-slate-300">{item.detail}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      ) : (
        <Card className="border-emerald-200 bg-emerald-50/60 dark:border-emerald-900 dark:bg-emerald-950/20">
          <CardContent className="flex items-center gap-3 py-4 text-sm text-emerald-800 dark:text-emerald-100">
            <Check className="h-5 w-5" />
            当前成员、角色和权限矩阵没有明显阻塞项。
          </CardContent>
        </Card>
      )}

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="overview">总览</TabsTrigger>
          <TabsTrigger value="members">成员</TabsTrigger>
          <TabsTrigger value="roles">角色权限</TabsTrigger>
          <TabsTrigger value="integrations">外部集成</TabsTrigger>
          <TabsTrigger value="apiKeys">API Key</TabsTrigger>
          <TabsTrigger value="accountSecurity">账户安全</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-6">
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
            <Card>
              <CardHeader>
                <CardTitle>角色权限矩阵</CardTitle>
                <CardDescription>用于检查每个角色是否符合最小权限原则。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {roles.map((role) => {
                  const health = roleHealth(role)
                  const permissions = normalizePermissions(role.permissions)
                  return (
                    <div key={role.id} className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950/20">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div>
                          <p className="font-semibold text-slate-900 dark:text-white">{role.name}</p>
                          <p className="mt-1 text-sm text-slate-500">{role.description || '暂无角色说明'}</p>
                        </div>
                        <Badge variant={health.variant}>{health.label}</Badge>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {permissions.length ? (
                          permissions.map((permission) => (
                            <Badge key={permission} variant="outline">
                              {permissionLabel(permission)}
                            </Badge>
                          ))
                        ) : (
                          <Badge variant="destructive">未配置权限</Badge>
                        )}
                      </div>
                    </div>
                  )
                })}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>最近权限审计</CardTitle>
                <CardDescription>角色、成员和访问控制相关的最近事件。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {(auditQuery.data?.items ?? []).length === 0 ? (
                  <div className="rounded-lg border border-slate-200 p-4 text-sm text-slate-500 dark:border-slate-800">暂无审计事件。</div>
                ) : (
                  (auditQuery.data?.items ?? []).slice(0, 6).map((event) => (
                    <div key={event.id} className="rounded-lg border border-slate-200 bg-white p-3 text-sm dark:border-slate-800 dark:bg-slate-950/20">
                      <div className="flex items-center justify-between gap-3">
                        <span className="font-medium text-slate-900 dark:text-white">{event.action}</span>
                        <Badge variant="outline">{event.resource_type || 'system'}</Badge>
                      </div>
                      <p className="mt-1 text-xs text-slate-500">{new Date(event.created_at).toLocaleString('zh-CN')}</p>
                    </div>
                  ))
                )}
                <Button asChild variant="outline" className="w-full justify-between">
                  <Link href="/audit">
                    查看完整审计日志
                    <ArrowRight className="h-4 w-4" />
                  </Link>
                </Button>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="members" className="space-y-4">
          {createdUserCredential ? (
            <Card className="border-blue-200 bg-blue-50/70 dark:border-blue-900 dark:bg-blue-950/20">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <KeyRound className="h-5 w-5 text-blue-600" />
                  新成员临时登录信息
                </CardTitle>
                <CardDescription>
                  该密码由服务端生成且只在本次创建后显示，请立即复制并要求成员首次登录后修改。
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="text-sm">
                  <p className="font-medium text-slate-900 dark:text-white">{createdUserCredential.email}</p>
                  <p className="mt-1 font-mono text-slate-700 dark:text-slate-200">{createdUserCredential.password}</p>
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" onClick={copyCreatedUserCredential}>
                    <Copy className="mr-2 h-4 w-4" />
                    复制
                  </Button>
                  <Button variant="outline" onClick={() => setCreatedUserCredential(null)}>已保存</Button>
                </div>
              </CardContent>
            </Card>
          ) : null}

          <Card>
            <CardHeader>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <CardTitle>成员清单</CardTitle>
                  <CardDescription>管理租户内可访问系统的成员。</CardDescription>
                </div>
                <Button onClick={() => setShowUserDialog(true)}>
                  <Mail className="mr-2 h-4 w-4" />
                  创建成员
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {usersQuery.isLoading ? (
                <div className="py-10 text-center text-slate-500">正在加载成员...</div>
              ) : users.length === 0 ? (
                <div className="py-10 text-center text-slate-500">暂无成员。</div>
              ) : (
                users.map((user) => (
                  <div key={user.id} className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950/20 md:flex-row md:items-center md:justify-between">
                    <div className="flex items-center gap-3">
                      <Avatar>
                        <AvatarFallback>{user.name.slice(0, 1).toUpperCase()}</AvatarFallback>
                      </Avatar>
                      <div>
                        <p className="font-semibold text-slate-900 dark:text-white">{user.name}</p>
                        <p className="text-sm text-slate-500">{user.email}</p>
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={user.isActive ? 'secondary' : 'destructive'}>{user.isActive ? '启用' : '停用'}</Badge>
                      {user.roleNames.length ? (
                        user.roleNames.map((role) => (
                          <Badge key={role} variant="outline">
                            {role}
                          </Badge>
                        ))
                      ) : (
                        <Badge variant="destructive">未分配角色</Badge>
                      )}
                      <Button variant="outline" size="sm" onClick={() => toggleUserMutation.mutate(user)}>
                        {user.isActive ? '停用' : '启用'}
                      </Button>
                      <Button variant="outline" size="sm" onClick={() => deleteUserMutation.mutate(user.id)}>
                        <Trash2 className="mr-2 h-4 w-4" />
                        删除
                      </Button>
                    </div>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="roles" className="space-y-4">
          <Card>
            <CardHeader>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <CardTitle>角色权限</CardTitle>
                  <CardDescription>维护角色和权限组合, 控制平台级操作入口。</CardDescription>
                </div>
                <Button onClick={() => setShowRoleDialog(true)}>
                  <Shield className="mr-2 h-4 w-4" />
                  新建角色
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {roles.map((role) => {
                const permissions = normalizePermissions(role.permissions)
                const health = roleHealth(role)
                return (
                  <div key={role.id} className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950/20">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <p className="font-semibold text-slate-900 dark:text-white">{role.name}</p>
                        <p className="mt-1 text-sm text-slate-500">{role.description || '暂无描述'}</p>
                      </div>
                      <Badge variant={health.variant}>{health.label}</Badge>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {permissions.length ? (
                        permissions.map((permission) => (
                          <Badge key={permission} variant="outline">
                            {permissionLabel(permission)}
                          </Badge>
                        ))
                      ) : (
                        <Badge variant="destructive">未配置权限</Badge>
                      )}
                    </div>
                  </div>
                )
              })}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="integrations" className="space-y-4">
          <IntegrationWorkbench />
        </TabsContent>

        <TabsContent value="apiKeys" className="space-y-4" data-testid="settings-api-key-panel">
          <Card>
            <CardHeader>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <CardTitle>API Key 管理</CardTitle>
                  <CardDescription>管理租户级服务端 API Key。密钥由后端生成、hash 存储并写入审计记录。</CardDescription>
                </div>
                <Button onClick={() => setShowApiKeyDialog(true)}>
                  <KeyRound className="mr-2 h-4 w-4" />
                  生成 Key
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <div data-testid="api-key-production-summary" className="grid gap-3 md:grid-cols-3">
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm dark:border-slate-800 dark:bg-slate-950/30">
                  <p className="text-xs text-slate-500">启用密钥</p>
                  <p className="mt-1 text-2xl font-semibold text-slate-900 dark:text-white">{activeApiKeys.length}</p>
                </div>
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm dark:border-slate-800 dark:bg-slate-950/30">
                  <p className="text-xs text-slate-500">已撤销</p>
                  <p className="mt-1 text-2xl font-semibold text-slate-900 dark:text-white">{revokedApiKeys.length}</p>
                </div>
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm dark:border-slate-800 dark:bg-slate-950/30">
                  <p className="text-xs text-slate-500">高权限密钥</p>
                  <p className="mt-1 text-2xl font-semibold text-slate-900 dark:text-white">{privilegedApiKeys.length}</p>
                </div>
              </div>
              {revealedApiKey ? (
                <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/20 dark:text-emerald-100">
                  <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                    <div>
                      <p className="font-semibold">完整密钥只显示一次</p>
                      <p className="mt-1 break-all font-mono text-xs">{revealedApiKey.token}</p>
                    </div>
                    <Button variant="outline" size="sm" onClick={() => copyApiKey(revealedApiKey.id, revealedApiKey.token)}>
                      {copiedKeyId === revealedApiKey.id ? <Check className="mr-2 h-4 w-4" /> : <Copy className="mr-2 h-4 w-4" />}
                      {copiedKeyId === revealedApiKey.id ? '已复制' : '复制密钥'}
                    </Button>
                  </div>
                </div>
              ) : null}
              {apiKeysQuery.isLoading ? (
                <div className="rounded-lg border border-slate-200 p-8 text-center text-sm text-slate-500 dark:border-slate-800">
                  正在加载 API Key...
                </div>
              ) : apiKeys.length === 0 ? (
                <div className="rounded-lg border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700">
                  暂无 API Key。新建密钥后将由后端托管 hash，并写入审计记录。
                </div>
              ) : (
                apiKeys.map((key) => (
                  <div key={key.id} data-testid="api-key-row" className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950/20">
                    <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                      <div>
                        <p className="font-semibold text-slate-900 dark:text-white">{key.name}</p>
                        <p className="mt-1 break-all font-mono text-xs text-slate-500">{key.key_prefix}...</p>
                        <p className="mt-1 text-xs text-slate-500">创建时间：{formatDateTime(key.created_at)}</p>
                        <p className="mt-1 text-xs text-slate-500">最近使用：{formatDateTime(key.last_used_at)}</p>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Badge variant={key.status === 'active' ? 'secondary' : 'destructive'}>
                          {key.status === 'active' ? '启用' : '已撤销'}
                        </Badge>
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={key.status !== 'active' || revokeApiKeyMutation.isPending}
                          onClick={() => revokeApiKeyMutation.mutate(key.id)}
                        >
                          <Trash2 className="mr-2 h-4 w-4" />
                          撤销
                        </Button>
                      </div>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {key.permissions.map((permission) => (
                        <Badge key={permission} variant="outline">
                          {permissionLabel(permission)}
                        </Badge>
                      ))}
                    </div>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="accountSecurity" className="space-y-4" data-testid="account-security-panel">
          <div className="grid gap-4 lg:grid-cols-3">
            <StatCard title="会话安全版本" value={accountSecurityQuery.data?.security_version ?? '-'} detail="每次改密、撤销会话或停用账户都会递增" />
            <StatCard title="最近登录" value={formatDateTime(accountSecurityQuery.data?.last_login_at)} detail="用于识别异常访问活动" />
            <StatCard title="最近改密" value={formatDateTime(accountSecurityQuery.data?.password_changed_at)} detail="长期未改密时应安排更新" />
          </div>

          <div className="grid gap-6 xl:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>修改登录密码</CardTitle>
                <CardDescription>修改成功后会立即撤销当前账户的全部登录会话。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="current-password">当前密码</Label>
                  <Input id="current-password" type="password" value={passwordForm.current} onChange={(event) => setPasswordForm((value) => ({ ...value, current: event.target.value }))} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="new-password">新密码</Label>
                  <Input id="new-password" type="password" value={passwordForm.next} onChange={(event) => setPasswordForm((value) => ({ ...value, next: event.target.value }))} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="confirm-password">确认新密码</Label>
                  <Input id="confirm-password" type="password" value={passwordForm.confirm} onChange={(event) => setPasswordForm((value) => ({ ...value, confirm: event.target.value }))} />
                </div>
                <Button
                  data-testid="change-password"
                  disabled={!passwordForm.current || passwordForm.next.length < 8 || passwordForm.next !== passwordForm.confirm || changePasswordMutation.isPending}
                  onClick={() => changePasswordMutation.mutate()}
                >
                  <LockKeyhole className="mr-2 h-4 w-4" />
                  修改密码并撤销会话
                </Button>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>账户生命周期操作</CardTitle>
                <CardDescription>用于安全事件处置和账户退出，操作会立即生效。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
                  <p className="font-medium text-slate-900 dark:text-white">撤销所有会话</p>
                  <p className="mt-1 text-sm text-slate-500">使所有已签发令牌失效，包括当前浏览器。</p>
                  <Button className="mt-3" variant="outline" data-testid="revoke-all-sessions" onClick={() => revokeSessionsMutation.mutate()}>
                    <LogOut className="mr-2 h-4 w-4" />
                    撤销全部会话
                  </Button>
                </div>
                <div className="rounded-lg border border-red-200 bg-red-50/40 p-4 dark:border-red-900 dark:bg-red-950/10">
                  <p className="font-medium text-red-800 dark:text-red-200">停用我的账户</p>
                  <p className="mt-1 text-sm text-red-700 dark:text-red-300">停用后无法再次登录，需要租户管理员重新启用。</p>
                  <Button className="mt-3" variant="destructive" data-testid="deactivate-account" disabled={!passwordForm.current || deactivateAccountMutation.isPending} onClick={() => deactivateAccountMutation.mutate()}>
                    <Power className="mr-2 h-4 w-4" />
                    停用账户
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>最近安全事件</CardTitle>
              <CardDescription>仅展示当前账户的登录、改密、会话撤销和停用证据。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {(accountSecurityQuery.data?.recent_events ?? []).map((event) => (
                <div key={event.id} className="flex items-center justify-between rounded-lg border border-slate-200 p-3 text-sm dark:border-slate-800">
                  <span className="font-medium">{event.action}</span>
                  <span className="text-slate-500">{formatDateTime(event.created_at)}</span>
                </div>
              ))}
              {!accountSecurityQuery.isLoading && (accountSecurityQuery.data?.recent_events ?? []).length === 0 ? (
                <p className="text-sm text-slate-500">暂无安全事件。</p>
              ) : null}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <Dialog open={showUserDialog} onOpenChange={setShowUserDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新增团队成员</DialogTitle>
            <DialogDescription>创建租户成员并可选分配一个角色。</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="member-name">姓名</Label>
              <Input id="member-name" value={newUser.name} onChange={(event) => setNewUser((value) => ({ ...value, name: event.target.value }))} placeholder="例如: 张三" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="member-email">邮箱</Label>
              <Input id="member-email" type="email" value={newUser.email} onChange={(event) => setNewUser((value) => ({ ...value, email: event.target.value }))} placeholder="输入成员邮箱" />
            </div>
            <div className="space-y-2">
              <Label>角色</Label>
              <Select value={newUser.role} onValueChange={(role) => setNewUser((value) => ({ ...value, role }))}>
                <SelectOption value="">暂不分配</SelectOption>
                {roles.map((role) => (
                  <SelectOption key={role.id} value={role.id}>
                    {role.name}
                  </SelectOption>
                ))}
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowUserDialog(false)}>取消</Button>
            <Button onClick={() => inviteUserMutation.mutate()} disabled={!newUser.email.trim() || inviteUserMutation.isPending}>
              {inviteUserMutation.isPending ? '创建中...' : '创建成员'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showRoleDialog} onOpenChange={setShowRoleDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新建角色</DialogTitle>
            <DialogDescription>角色应按岗位职责组合最小必要权限。</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="role-name">角色名称</Label>
              <Input id="role-name" value={newRole.name} onChange={(event) => setNewRole((value) => ({ ...value, name: event.target.value }))} placeholder="例如: 业务验收负责人" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="role-description">说明</Label>
              <Input id="role-description" value={newRole.description} onChange={(event) => setNewRole((value) => ({ ...value, description: event.target.value }))} placeholder="描述角色职责边界" />
            </div>
            <div className="space-y-2">
              <Label>权限</Label>
              <div className="grid gap-2 sm:grid-cols-2">
                {permissionOptions.map((permission) => (
                  <label key={permission} className="flex items-center gap-2 rounded-md border border-slate-200 p-3 text-sm dark:border-slate-700">
                    <input
                      type="checkbox"
                      checked={newRole.permissions.includes(permission)}
                      onChange={(event) => {
                        setNewRole((value) => ({
                          ...value,
                          permissions: event.target.checked
                            ? [...value.permissions, permission]
                            : value.permissions.filter((item) => item !== permission),
                        }))
                      }}
                    />
                    {permissionLabel(permission)}
                  </label>
                ))}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowRoleDialog(false)}>取消</Button>
            <Button onClick={() => createRoleMutation.mutate()} disabled={!newRole.name.trim() || createRoleMutation.isPending}>
              {createRoleMutation.isPending ? '创建中...' : '创建角色'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showApiKeyDialog} onOpenChange={setShowApiKeyDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>生成 API Key</DialogTitle>
            <DialogDescription>创建可用于系统集成、Provider 接入和自动化调用的租户级服务端密钥。</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="api-key-name">名称</Label>
              <Input id="api-key-name" value={apiKeyName} onChange={(event) => setApiKeyName(event.target.value)} placeholder="例如: GitNexus Provider 联调" />
            </div>
            <div className="space-y-2">
              <Label>权限</Label>
              <div className="grid gap-2 sm:grid-cols-2">
                {permissionOptions.map((permission) => (
                  <label key={permission} className="flex items-center gap-2 rounded-md border border-slate-200 p-3 text-sm dark:border-slate-700">
                    <input
                      type="checkbox"
                      checked={apiKeyPermissions.includes(permission)}
                      onChange={(event) => {
                        setApiKeyPermissions((items) =>
                          event.target.checked ? [...items, permission] : items.filter((item) => item !== permission)
                        )
                      }}
                    />
                    {permissionLabel(permission)}
                  </label>
                ))}
              </div>
            </div>
            <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
              <AlertTriangle className="mt-0.5 h-4 w-4" />
              完整密钥只在创建后显示一次。后端仅保存 hash、权限范围和审计记录，请复制后存入受控密钥库。
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowApiKeyDialog(false)}>取消</Button>
            <Button onClick={() => createApiKeyMutation.mutate()} disabled={apiKeyPermissions.length === 0 || createApiKeyMutation.isPending}>
              <LockKeyhole className="mr-2 h-4 w-4" />
              {createApiKeyMutation.isPending ? '生成中...' : '生成'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

    </div>
  )
}
