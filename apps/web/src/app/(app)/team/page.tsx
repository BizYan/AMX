'use client'

import { useEffect, useMemo, useState, type ReactNode } from 'react'
import Link from 'next/link'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Check,
  KeyRound,
  Lock,
  Mail,
  Pencil,
  Plus,
  RefreshCw,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Trash2,
  UserCheck,
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
import {
  auditApi,
  identityApi,
  opsApi,
  type AuditLog,
  type CapabilityActivationAction,
  type CapabilityCommissioningCheck,
  type CapabilityReadinessItem,
  type FieldPermission,
  type PermissionDiagnostics,
  type PermissionSimulationResult,
  type Policy,
  type Role,
  type TenantUser,
} from '@/lib/api-client'

type PermissionAction = 'read' | 'write' | 'review' | 'approve' | 'publish' | 'archive' | 'export' | 'manage'

const permissionCatalog: Array<{
  resource: string
  label: string
  actions: Array<{ key: PermissionAction; label: string }>
}> = [
  {
    resource: 'projects',
    label: '项目',
    actions: [
      { key: 'read', label: '查看' },
      { key: 'write', label: '编辑' },
      { key: 'manage', label: '管理' },
    ],
  },
  {
    resource: 'documents',
    label: '文档',
    actions: [
      { key: 'read', label: '查看' },
      { key: 'write', label: '编写' },
      { key: 'review', label: '评审' },
      { key: 'approve', label: '批准' },
      { key: 'publish', label: '发布' },
      { key: 'archive', label: '归档' },
      { key: 'export', label: '导出' },
    ],
  },
  {
    resource: 'agents',
    label: '智能编排',
    actions: [
      { key: 'read', label: '查看' },
      { key: 'write', label: '配置' },
      { key: 'manage', label: '运行管理' },
    ],
  },
  {
    resource: 'team',
    label: '团队权限',
    actions: [
      { key: 'read', label: '查看' },
      { key: 'write', label: '维护' },
      { key: 'manage', label: '授权' },
    ],
  },
]

const roleTemplates: Array<{
  key: string
  name: string
  description: string
  permissions: string[]
}> = [
  {
    key: 'delivery_admin',
    name: '交付管理员',
    description: '负责项目、文档、智能编排、团队权限和导出交付的全流程管理。',
    permissions: [
      'projects:read',
      'projects:write',
      'projects:manage',
      'documents:read',
      'documents:write',
      'documents:review',
      'documents:approve',
      'documents:publish',
      'documents:archive',
      'documents:export',
      'agents:read',
      'agents:write',
      'agents:manage',
      'team:read',
      'team:write',
      'team:manage',
    ],
  },
  {
    key: 'project_lead',
    name: '项目负责人',
    description: '负责项目推进、成员协作、文档评审和交付物发布前把关。',
    permissions: [
      'projects:read',
      'projects:write',
      'projects:manage',
      'documents:read',
      'documents:write',
      'documents:review',
      'documents:approve',
      'documents:archive',
      'documents:export',
      'agents:read',
      'agents:write',
      'team:read',
    ],
  },
  {
    key: 'consultant',
    name: '咨询顾问',
    description: '负责资料整理、知识图谱补充、文档编写和智能编排执行。',
    permissions: [
      'projects:read',
      'projects:write',
      'documents:read',
      'documents:write',
      'documents:export',
      'agents:read',
      'agents:write',
      'team:read',
    ],
  },
  {
    key: 'reviewer',
    name: '业务评审人',
    description: '负责文档审阅、意见反馈、审批和交付风险复核。',
    permissions: [
      'projects:read',
      'documents:read',
      'documents:review',
      'documents:approve',
      'team:read',
    ],
  },
  {
    key: 'ops_owner',
    name: '平台运维负责人',
    description: '负责智能编排运行、权限审计、导出交付和平台级运维检查。',
    permissions: [
      'projects:read',
      'documents:read',
      'documents:archive',
      'documents:export',
      'agents:read',
      'agents:manage',
      'team:read',
      'team:manage',
    ],
  },
]

const fieldCatalog = [
  { resource: 'document', field: 'commercial_terms', label: '商务条款' },
  { resource: 'document', field: 'client_contact', label: '客户联系人' },
  { resource: 'document', field: 'risk_assessment', label: '风险评估' },
  { resource: 'project', field: 'budget', label: '项目预算' },
  { resource: 'project', field: 'contract_scope', label: '合同范围' },
  { resource: 'agent_run', field: 'provider_payload', label: '供应商调用载荷' },
]

const permissionSimulationTargets = [
  { key: 'projects.read', label: '查看项目资料', resource: 'projects', action: 'read', resourceType: 'project', fieldName: '' },
  { key: 'documents.write', label: '编写项目文档', resource: 'documents', action: 'write', resourceType: 'document', fieldName: '' },
  { key: 'documents.review', label: '评审项目文档', resource: 'documents', action: 'review', resourceType: 'document', fieldName: '' },
  { key: 'documents.export', label: '导出交付包', resource: 'documents', action: 'export', resourceType: 'document', fieldName: '' },
  { key: 'agents.manage', label: '运行智能编排', resource: 'agents', action: 'manage', resourceType: 'agent_run', fieldName: '' },
  { key: 'team.manage', label: '管理团队权限', resource: 'team', action: 'manage', resourceType: '', fieldName: '' },
]

const fieldPermissionLabels: Record<string, string> = {
  read: '可读',
  write: '可写',
  none: '不可见',
}

function initials(name: string) {
  return name.trim().slice(0, 2).toUpperCase() || 'AM'
}

function normalizeRolePermissions(permissions: Role['permissions'] | undefined): Record<string, string[]> {
  if (!permissions) return {}
  if (Array.isArray(permissions)) {
    return { '*': permissions.map(String) }
  }

  const normalized: Record<string, string[]> = {}
  Object.entries(permissions).forEach(([resource, value]) => {
    if (value === '*' || value === true) {
      normalized[resource] = ['manage']
    } else if (Array.isArray(value)) {
      normalized[resource] = value.map(String)
    } else if (typeof value === 'string') {
      normalized[resource] = [value]
    } else if (value && typeof value === 'object') {
      normalized[resource] = Object.entries(value)
        .filter(([, enabled]) => Boolean(enabled))
        .map(([action]) => action)
    }
  })
  return normalized
}

function buildPermissionPayload(selected: Set<string>) {
  const payload: Record<string, string[]> = {}
  selected.forEach((entry) => {
    const [resource, action] = entry.split(':')
    if (!resource || !action) return
    payload[resource] = [...(payload[resource] ?? []), action]
  })
  return payload
}

function roleTemplatePermissionPayload(template: { permissions: string[] }) {
  return buildPermissionPayload(new Set(template.permissions))
}

function fieldLabel(resourceType: string, fieldName: string) {
  return fieldCatalog.find((item) => item.resource === resourceType && item.field === fieldName)?.label ?? fieldName
}

function selectedPermissionSet(role?: Role) {
  const normalized = normalizeRolePermissions(role?.permissions)
  const selected = new Set<string>()
  if (normalized['*']?.length) {
    permissionCatalog.forEach((group) => {
      group.actions.forEach((action) => selected.add(`${group.resource}:${action.key}`))
    })
    return selected
  }

  Object.entries(normalized).forEach(([resource, actions]) => {
    actions.forEach((action) => selected.add(`${resource}:${action}`))
  })
  return selected
}

function hasAdminPower(role: Role) {
  const permissions = normalizeRolePermissions(role.permissions)
  return permissions['*']?.length || permissions.team?.includes('manage') || permissions.documents?.includes('publish')
}

function userName(user: TenantUser) {
  return user.full_name || user.email.split('@')[0]
}

function roleNames(user: TenantUser) {
  return (user.roles ?? []).map((role) => role.name).filter(Boolean)
}

function auditSummary(event: AuditLog) {
  return event.extra_data?.summary || `${event.action} ${event.resource_type ?? 'system'}`
}

function errorMessage(error: unknown) {
  if (!error) return ''
  if (error instanceof Error) return error.message
  return String(error)
}

function evidenceNumber(evidence: Record<string, any> | undefined, keys: string[], fallback = 0) {
  if (!evidence) return fallback
  for (const key of keys) {
    const value = Number(evidence[key])
    if (Number.isFinite(value)) return value
  }
  return fallback
}

const decisionReasonLabel: Record<string, string> = {
  admin: '管理员授权',
  rbac: '角色授权',
  allow_policy: '策略放行',
  deny_policy: '拒绝策略',
  no_grant: '未授权',
}

const fieldPermissionText: Record<string, string> = {
  read: '可读',
  write: '可写',
  none: '不可见',
}

function StatCard({ icon, title, value, detail }: { icon: ReactNode; title: string; value: number | string; detail: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-3">
          <CardDescription>{title}</CardDescription>
          <div className="text-slate-400">{icon}</div>
        </div>
        <CardTitle className="text-3xl">{value}</CardTitle>
      </CardHeader>
      <CardContent className="text-sm text-slate-500">{detail}</CardContent>
    </Card>
  )
}

export default function TeamAccessPage() {
  const queryClient = useQueryClient()
  const { addToast } = useToast()
  const [activeTab, setActiveTab] = useState('members')
  const [memberDialogOpen, setMemberDialogOpen] = useState(false)
  const [roleDialogOpen, setRoleDialogOpen] = useState(false)
  const [policyDialogOpen, setPolicyDialogOpen] = useState(false)
  const [editingRoleId, setEditingRoleId] = useState<string | null>(null)
  const [editingPolicyId, setEditingPolicyId] = useState<string | null>(null)
  const [selectedRoleId, setSelectedRoleId] = useState('')
  const [selectedFieldResource, setSelectedFieldResource] = useState('document')
  const [memberForm, setMemberForm] = useState({ fullName: '', email: '', roleId: '' })
  const [roleForm, setRoleForm] = useState({ name: '', description: '', permissions: new Set<string>(['projects:read', 'documents:read']) })
  const [createdMemberCredential, setCreatedMemberCredential] = useState<{ email: string; password: string } | null>(null)
  const [policyForm, setPolicyForm] = useState({
    name: '',
    description: '',
    effect: 'allow' as 'allow' | 'deny',
    actions: 'read,write',
    resources: 'projects:*,documents:*',
    conditions: '{"tenant_id":"{{tenant_id}}"}',
  })
  const [simulationForm, setSimulationForm] = useState({
    userId: '',
    targetKey: 'documents.export',
    resource: 'documents',
    action: 'export',
    resourceType: 'document',
    fieldName: '',
  })
  const [simulationResult, setSimulationResult] = useState<PermissionSimulationResult | null>(null)

  const usersQuery = useQuery({
    queryKey: ['team-console-users'],
    queryFn: () => identityApi.listUsers({ pageSize: 100 }),
  })
  const rolesQuery = useQuery({
    queryKey: ['team-console-roles'],
    queryFn: () => identityApi.listRoles({ pageSize: 100 }),
  })
  const policiesQuery = useQuery({
    queryKey: ['team-console-policies'],
    queryFn: () => identityApi.listPolicies({ pageSize: 100 }),
  })
  const diagnosticsQuery = useQuery({
    queryKey: ['team-console-permission-diagnostics'],
    queryFn: () => identityApi.getPermissionDiagnostics(),
  })
  const commandCenterQuery = useQuery({
    queryKey: ['team-console-permission-command-center'],
    queryFn: () => identityApi.getPermissionCommandCenter(),
  })
  const auditQuery = useQuery({
    queryKey: ['team-console-audit'],
    queryFn: () => auditApi.listLogs({ pageSize: 20 }),
  })
  const readinessQuery = useQuery({
    queryKey: ['team-console-readiness'],
    queryFn: () => opsApi.getCapabilityReadiness(),
  })
  const activationPlanQuery = useQuery({
    queryKey: ['team-console-activation-plan'],
    queryFn: () => opsApi.getCapabilityActivationPlan(),
  })
  const commissioningQuery = useQuery({
    queryKey: ['team-console-commissioning'],
    queryFn: () => opsApi.getCapabilityCommissioning(),
  })

  const roles = useMemo(() => rolesQuery.data?.items ?? [], [rolesQuery.data?.items])
  const users = useMemo(() => usersQuery.data?.items ?? [], [usersQuery.data?.items])
  const policies = useMemo(() => policiesQuery.data?.items ?? [], [policiesQuery.data?.items])
  const existingRoleNames = useMemo(() => new Set(roles.map((role) => role.name.trim())), [roles])
  const missingRoleTemplates = useMemo(
    () => roleTemplates.filter((template) => !existingRoleNames.has(template.name)),
    [existingRoleNames]
  )
  const diagnostics = diagnosticsQuery.data as PermissionDiagnostics | undefined
  const selectedRole = roles.find((role) => role.id === selectedRoleId)
  const teamCapability = readinessQuery.data?.capabilities.find((capability: CapabilityReadinessItem) => capability.key === 'team_access')
  const teamActivationActions = (activationPlanQuery.data?.actions ?? []).filter((action: CapabilityActivationAction) => action.capability_key === 'team_access')
  const teamCommissioningCheck = (commissioningQuery.data?.checks ?? []).find((check: CapabilityCommissioningCheck) => check.key === 'team_permission_audit')
  const teamEvidence = teamCapability?.evidence as Record<string, any> | undefined
  const teamEvidenceItems = [
    {
      key: 'active_user_count',
      label: '活跃成员',
      value: evidenceNumber(teamEvidence, ['active_user_count', 'users'], users.filter((user) => user.is_active !== false).length),
    },
    {
      key: 'role_count',
      label: '角色',
      value: evidenceNumber(teamEvidence, ['role_count', 'roles'], roles.length),
    },
    {
      key: 'policy_count',
      label: 'ABAC 策略',
      value: evidenceNumber(teamEvidence, ['policy_count', 'policies'], policies.length),
    },
    {
      key: 'field_permission_count',
      label: '字段权限',
      value: evidenceNumber(teamEvidence, ['field_permission_count', 'field_permissions'], diagnostics?.summary.field_restricted ?? 0),
    },
    {
      key: 'audit_log_count',
      label: '审计记录',
      value: evidenceNumber(teamEvidence, ['audit_log_count', 'audit_logs'], auditQuery.data?.items?.length ?? 0),
    },
  ]

  useEffect(() => {
    if (!selectedRoleId && roles[0]?.id) {
      setSelectedRoleId(roles[0].id)
    }
  }, [roles, selectedRoleId])

  useEffect(() => {
    if (!simulationForm.userId && users[0]?.id) {
      setSimulationForm((value) => ({ ...value, userId: users[0].id }))
    }
  }, [simulationForm.userId, users])

  const fieldPermissionsQuery = useQuery({
    queryKey: ['team-console-field-permissions', selectedRoleId, selectedFieldResource],
    queryFn: () => identityApi.listFieldPermissions(selectedRoleId, selectedFieldResource),
    enabled: Boolean(selectedRoleId),
  })

  const risks = useMemo(() => {
    const result: Array<{ severity: 'high' | 'medium'; title: string; detail: string }> = []
    const usersWithoutRole = users.filter((user) => roleNames(user).length === 0)
    const inactiveUsers = users.filter((user) => user.is_active === false)
    const highPrivilegeRoles = roles.filter(hasAdminPower)
    const denyPolicies = policies.filter((policy) => policy.effect === 'deny')

    if (usersWithoutRole.length) {
      result.push({ severity: 'high', title: '存在未授权成员', detail: `${usersWithoutRole.length} 个成员没有角色，无法证明最小权限边界。` })
    }
    if (highPrivilegeRoles.length) {
      result.push({ severity: 'medium', title: '高权限角色需要复核', detail: `${highPrivilegeRoles.length} 个角色包含发布、授权或全局权限。` })
    }
    if (inactiveUsers.length) {
      result.push({ severity: 'medium', title: '停用成员待清理', detail: `${inactiveUsers.length} 个账号已停用，建议确认是否需要删除或保留审计。` })
    }
    if (denyPolicies.length) {
      result.push({ severity: 'medium', title: '存在拒绝策略', detail: `${denyPolicies.length} 条 deny 策略会覆盖角色授权，需要确认命中范围。` })
    }
    if (missingRoleTemplates.length) {
      result.push({ severity: 'medium', title: '缺少标准角色模板', detail: `${missingRoleTemplates.length} 个咨询交付常用角色尚未创建，新项目授权需要手工补齐。` })
    }
    return result
  }, [missingRoleTemplates.length, policies, roles, users])

  const policyConditionValidation = useMemo(() => {
    const text = policyForm.conditions.trim()
    if (!text) return { valid: true, message: '' }
    try {
      JSON.parse(text)
      return { valid: true, message: '' }
    } catch {
      return { valid: false, message: '条件 JSON 格式不正确，请修正后保存。' }
    }
  }, [policyForm.conditions])

  const refreshAll = () => {
    queryClient.invalidateQueries({ queryKey: ['team-console-users'] })
    queryClient.invalidateQueries({ queryKey: ['team-console-roles'] })
    queryClient.invalidateQueries({ queryKey: ['team-console-policies'] })
    queryClient.invalidateQueries({ queryKey: ['team-console-permission-diagnostics'] })
    queryClient.invalidateQueries({ queryKey: ['team-console-permission-command-center'] })
    queryClient.invalidateQueries({ queryKey: ['team-console-field-permissions'] })
    queryClient.invalidateQueries({ queryKey: ['team-console-audit'] })
    queryClient.invalidateQueries({ queryKey: ['team-console-readiness'] })
    queryClient.invalidateQueries({ queryKey: ['team-console-activation-plan'] })
    queryClient.invalidateQueries({ queryKey: ['team-console-commissioning'] })
  }

  const runActivationMutation = useMutation({
    mutationFn: (actions: string[]) =>
      opsApi.runCapabilityActivation({
        dry_run: false,
        confirm: true,
        actions,
      }),
    onSuccess: () => {
      refreshAll()
      addToast({ title: '团队权限证据已初始化', description: '角色、ABAC 策略、字段级权限和审计证据已重新检查。' })
    },
    onError: (error: Error) => addToast({ title: '初始化失败', description: error.message, variant: 'destructive' }),
  })

  const runCommissioningMutation = useMutation({
    mutationFn: (checks: string[]) => opsApi.runCapabilityCommissioning({ checks }),
    onSuccess: () => {
      refreshAll()
      addToast({ title: '团队权限校准已完成', description: '生产可用性检查结果已刷新。' })
    },
    onError: (error: Error) => addToast({ title: '校准失败', description: error.message, variant: 'destructive' }),
  })

  const resetRoleForm = () => {
    setEditingRoleId(null)
    setRoleForm({ name: '', description: '', permissions: new Set(['projects:read', 'documents:read']) })
  }

  const openCreateRoleDialog = () => {
    resetRoleForm()
    setRoleDialogOpen(true)
  }

  const openEditRoleDialog = (role: Role) => {
    setEditingRoleId(role.id)
    setRoleForm({
      name: role.name,
      description: role.description || '',
      permissions: selectedPermissionSet(role),
    })
    setRoleDialogOpen(true)
  }

  const resetPolicyForm = () => {
    setEditingPolicyId(null)
    setPolicyForm({
      name: '',
      description: '',
      effect: 'allow',
      actions: 'read,write',
      resources: 'projects:*,documents:*',
      conditions: '{"tenant_id":"{{tenant_id}}"}',
    })
  }

  const openCreatePolicyDialog = () => {
    resetPolicyForm()
    setPolicyDialogOpen(true)
  }

  const openEditPolicyDialog = (policy: Policy) => {
    setEditingPolicyId(policy.id)
    setPolicyForm({
      name: policy.name,
      description: policy.description || '',
      effect: policy.effect === 'deny' ? 'deny' : 'allow',
      actions: policy.actions.join(','),
      resources: policy.resources.join(','),
      conditions: JSON.stringify(policy.conditions ?? {}, null, 2),
    })
    setPolicyDialogOpen(true)
  }

  const createMemberMutation = useMutation({
    mutationFn: async () => {
      const email = memberForm.email.trim()
      const created = await identityApi.createUser({
        email,
        full_name: memberForm.fullName.trim() || email.split('@')[0],
      })
      if (!created.temporary_password) {
        throw new Error('Temporary password was not returned by the server')
      }
      if (memberForm.roleId) {
        await identityApi.assignRole(memberForm.roleId, created.id)
      }
      return { created, password: created.temporary_password }
    },
    onSuccess: ({ created, password }) => {
      refreshAll()
      setMemberDialogOpen(false)
      setCreatedMemberCredential({ email: created.email, password })
      setMemberForm({ fullName: '', email: '', roleId: '' })
      addToast({ title: '成员已创建', description: '请立即复制一次性临时密码并交付给成员。' })
    },
    onError: (error: Error) => addToast({ title: '创建成员失败', description: error.message, variant: 'destructive' }),
  })

  const saveRoleMutation = useMutation({
    mutationFn: () =>
      (editingRoleId ? identityApi.updateRole(editingRoleId, {
        name: roleForm.name.trim(),
        description: roleForm.description.trim() || undefined,
        permissions: buildPermissionPayload(roleForm.permissions),
      }) : identityApi.createRole({
        name: roleForm.name.trim(),
        description: roleForm.description.trim() || undefined,
        permissions: buildPermissionPayload(roleForm.permissions),
      })),
    onSuccess: () => {
      refreshAll()
      setRoleDialogOpen(false)
      resetRoleForm()
      addToast({
        title: editingRoleId ? '角色已更新' : '角色已创建',
        description: '权限矩阵已写入后端角色配置。',
      })
    },
    onError: (error: Error) => addToast({ title: '保存角色失败', description: error.message, variant: 'destructive' }),
  })

  const createRoleTemplateMutation = useMutation({
    mutationFn: (template: (typeof roleTemplates)[number]) =>
      identityApi.createRole({
        name: template.name,
        description: template.description,
        permissions: roleTemplatePermissionPayload(template),
      }),
    onSuccess: () => {
      refreshAll()
      addToast({ title: '角色模板已创建', description: '标准咨询交付权限已写入角色矩阵。' })
    },
    onError: (error: Error) => addToast({ title: '创建角色模板失败', description: error.message, variant: 'destructive' }),
  })

  const createAllRoleTemplatesMutation = useMutation({
    mutationFn: async () => {
      for (const template of missingRoleTemplates) {
        await identityApi.createRole({
          name: template.name,
          description: template.description,
          permissions: roleTemplatePermissionPayload(template),
        })
      }
      return missingRoleTemplates.length
    },
    onSuccess: (count) => {
      refreshAll()
      addToast({ title: '标准角色已补齐', description: `已创建 ${count} 个咨询交付角色模板。` })
    },
    onError: (error: Error) => addToast({ title: '批量创建角色模板失败', description: error.message, variant: 'destructive' }),
  })

  const assignRoleMutation = useMutation({
    mutationFn: ({ roleId, userId }: { roleId: string; userId: string }) => identityApi.assignRole(roleId, userId),
    onSuccess: () => {
      refreshAll()
      addToast({ title: '角色已分配' })
    },
    onError: (error: Error) => addToast({ title: '分配角色失败', description: error.message, variant: 'destructive' }),
  })

  const revokeRoleMutation = useMutation({
    mutationFn: ({ roleId, userId }: { roleId: string; userId: string }) => identityApi.revokeRole(roleId, userId),
    onSuccess: () => {
      refreshAll()
      addToast({ title: '角色已撤销' })
    },
    onError: (error: Error) => addToast({ title: '撤销角色失败', description: error.message, variant: 'destructive' }),
  })

  const deleteRoleMutation = useMutation({
    mutationFn: (roleId: string) => identityApi.deleteRole(roleId),
    onSuccess: () => {
      refreshAll()
      addToast({ title: '角色已删除', description: '未使用角色已从权限矩阵移除。' })
    },
    onError: (error: Error) => addToast({ title: '删除角色失败', description: error.message, variant: 'destructive' }),
  })

  const toggleUserMutation = useMutation({
    mutationFn: (user: TenantUser) => identityApi.updateUser(user.id, { is_active: !user.is_active }),
    onSuccess: () => {
      refreshAll()
      addToast({ title: '成员状态已更新' })
    },
    onError: (error: Error) => addToast({ title: '更新成员状态失败', description: error.message, variant: 'destructive' }),
  })

  const savePolicyMutation = useMutation({
    mutationFn: () => {
      if (!policyConditionValidation.valid) {
        throw new Error(policyConditionValidation.message)
      }
      let conditions: Record<string, any> = {}
      if (policyForm.conditions.trim()) {
        conditions = JSON.parse(policyForm.conditions)
      }
      const payload = {
        name: policyForm.name.trim(),
        description: policyForm.description.trim() || undefined,
        effect: policyForm.effect,
        actions: policyForm.actions.split(',').map((item) => item.trim()).filter(Boolean),
        resources: policyForm.resources.split(',').map((item) => item.trim()).filter(Boolean),
        conditions,
      }
      return editingPolicyId ? identityApi.updatePolicy(editingPolicyId, payload) : identityApi.createPolicy(payload)
    },
    onSuccess: () => {
      refreshAll()
      setPolicyDialogOpen(false)
      resetPolicyForm()
      addToast({
        title: editingPolicyId ? '策略已更新' : '策略已创建',
        description: 'ABAC 规则已进入租户策略列表。',
      })
    },
    onError: (error: Error) => addToast({ title: '保存策略失败', description: error.message, variant: 'destructive' }),
  })

  const deletePolicyMutation = useMutation({
    mutationFn: (policyId: string) => identityApi.deletePolicy(policyId),
    onSuccess: () => {
      refreshAll()
      addToast({ title: '策略已删除' })
    },
    onError: (error: Error) => addToast({ title: '删除策略失败', description: error.message, variant: 'destructive' }),
  })

  const setFieldPermissionMutation = useMutation({
    mutationFn: (data: { field: string; permission: 'read' | 'write' | 'none' }) =>
      identityApi.setFieldPermission({
        role_id: selectedRoleId,
        resource_type: selectedFieldResource,
        field_name: data.field,
        permission: data.permission,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['team-console-field-permissions'] })
      queryClient.invalidateQueries({ queryKey: ['team-console-permission-command-center'] })
      queryClient.invalidateQueries({ queryKey: ['team-console-audit'] })
      addToast({ title: '字段权限已保存' })
    },
    onError: (error: Error) => addToast({ title: '保存字段权限失败', description: error.message, variant: 'destructive' }),
  })

  const simulatePermissionMutation = useMutation({
    mutationFn: () =>
      identityApi.simulatePermission({
        user_id: simulationForm.userId,
        resource: simulationForm.resource.trim(),
        action: simulationForm.action.trim(),
        resource_type: simulationForm.resourceType.trim() || undefined,
        field_name: simulationForm.fieldName.trim() || undefined,
      }),
    onSuccess: (result) => {
      setSimulationResult(result)
      queryClient.invalidateQueries({ queryKey: ['team-console-permission-command-center'] })
      queryClient.invalidateQueries({ queryKey: ['team-console-audit'] })
      addToast({ title: '权限模拟已完成', description: result.allowed ? '该操作会被允许。' : '该操作会被拒绝。' })
    },
    onError: (error: Error) => addToast({ title: '权限模拟失败', description: error.message, variant: 'destructive' }),
  })

  const permissionLookup = new Map((fieldPermissionsQuery.data ?? []).map((item: FieldPermission) => [item.field_name, item.permission]))
  const selectedRoleUsers = users.filter((user) => user.roles?.some((role) => role.id === selectedRoleId))
  const selectedSimulationUser = users.find((item) => item.id === simulationForm.userId)
  const queryErrors = [
    usersQuery.error,
    rolesQuery.error,
    policiesQuery.error,
    diagnosticsQuery.error,
    commandCenterQuery.error,
    auditQuery.error,
    readinessQuery.error,
    activationPlanQuery.error,
    commissioningQuery.error,
  ].filter(Boolean)
  const copyTemporaryPassword = async () => {
    if (!createdMemberCredential) return
    await navigator.clipboard.writeText(`${createdMemberCredential.email}\n${createdMemberCredential.password}`)
    addToast({ title: '临时密码已复制' })
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">团队权限</h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-500">
            统一管理租户成员、角色矩阵、ABAC 策略、字段级权限和权限审计，支持项目文档、智能编排与导出交付的授权闭环。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={refreshAll}>
            <RefreshCw className="mr-2 h-4 w-4" />
            刷新
          </Button>
          <Button variant="outline" asChild>
            <Link href="/audit">
              <Activity className="mr-2 h-4 w-4" />
              审计日志
            </Link>
          </Button>
          <Button onClick={() => setMemberDialogOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            新增成员
          </Button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard icon={<Users className="h-5 w-5" />} title="租户成员" value={users.length} detail={`${users.filter((user) => user.is_active !== false).length} 个启用账号`} />
        <StatCard icon={<Shield className="h-5 w-5" />} title="角色" value={roles.length} detail={`${roles.filter(hasAdminPower).length} 个高权限角色`} />
        <StatCard icon={<KeyRound className="h-5 w-5" />} title="策略" value={policies.length} detail={`${policies.filter((policy) => policy.effect === 'deny').length} 条拒绝策略`} />
        <StatCard icon={<ShieldAlert className="h-5 w-5" />} title="风险项" value={risks.length} detail={risks.length ? '需要权限管理员复核' : '当前无明显权限阻塞'} />
      </div>

      {commandCenterQuery.data ? (
        <section
          data-testid="team-permission-command-center"
          className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950/40"
        >
          <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-3">
                <h2 className="text-lg font-semibold text-slate-900 dark:text-white">权限治理指挥台</h2>
                <Badge
                  data-testid="team-permission-release-gate"
                  variant={
                    commandCenterQuery.data.release_gate.status === 'blocked'
                      ? 'destructive'
                      : commandCenterQuery.data.release_gate.status === 'passed'
                        ? 'secondary'
                        : 'outline'
                  }
                >
                  {commandCenterQuery.data.release_gate.label}
                </Badge>
              </div>
              <p className="mt-2 max-w-4xl text-sm text-slate-600 dark:text-slate-300">
                {commandCenterQuery.data.release_gate.summary}
              </p>
              <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
                {[
                  ['启用成员', commandCenterQuery.data.summary.active_users ?? 0],
                  ['无角色', commandCenterQuery.data.summary.users_without_roles ?? 0],
                  ['角色', commandCenterQuery.data.summary.role_count ?? 0],
                  ['高权限', commandCenterQuery.data.summary.high_privilege_roles ?? 0],
                  ['策略', commandCenterQuery.data.summary.policy_count ?? 0],
                  ['拒绝策略', commandCenterQuery.data.summary.deny_policy_count ?? 0],
                  ['字段限制', commandCenterQuery.data.summary.field_restricted_count ?? 0],
                  ['审计记录', commandCenterQuery.data.summary.audit_log_count ?? 0],
                ].map(([label, value]) => (
                  <div key={label as string} className="border-b border-slate-200 pb-2 dark:border-slate-800">
                    <p className="text-lg font-semibold text-slate-900 dark:text-white">{value}</p>
                    <p className="text-xs text-slate-500">{label}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="grid shrink-0 gap-2 sm:grid-cols-2 xl:w-[520px]">
              {commandCenterQuery.data.priority_actions.map((action) => (
                <Button key={action.code} asChild variant={action.priority === 'critical' ? 'destructive' : 'outline'}>
                  <Link href={action.href}>
                    <ArrowRight className="mr-2 h-4 w-4" />
                    {action.title}
                  </Link>
                </Button>
              ))}
            </div>
          </div>

          <div className="mt-5 grid gap-3 lg:grid-cols-3">
            {commandCenterQuery.data.risk_items.map((risk) => (
              <Link
                key={risk.code}
                href={risk.href}
                className="rounded-md border border-slate-200 p-4 transition hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-900"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-medium text-slate-900 dark:text-white">{risk.title}</p>
                    <p className="mt-1 text-sm text-slate-500">{risk.detail}</p>
                  </div>
                  <Badge variant={risk.severity === 'critical' || risk.severity === 'high' ? 'destructive' : 'outline'}>
                    {risk.count}
                  </Badge>
                </div>
              </Link>
            ))}
            {commandCenterQuery.data.risk_items.length === 0 ? (
              <div className="rounded-md border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-slate-700">
                当前没有团队权限治理风险。
              </div>
            ) : null}
          </div>
        </section>
      ) : null}

      {queryErrors.length > 0 ? (
        <Card className="border-rose-200 bg-rose-50/70 dark:border-rose-900 dark:bg-rose-950/20">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <AlertTriangle className="h-5 w-5 text-rose-600" />
              团队权限数据加载受限
            </CardTitle>
            <CardDescription>
              {errorMessage(queryErrors[0]) || '当前账号可能缺少团队权限或运维读取权限，部分生产校准信息暂不可见。'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="outline" onClick={refreshAll}>
              <RefreshCw className="mr-2 h-4 w-4" />
              重新加载
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {createdMemberCredential ? (
        <Card className="border-blue-200 bg-blue-50/70 dark:border-blue-900 dark:bg-blue-950/20">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <KeyRound className="h-5 w-5 text-blue-600" />
              新成员临时登录信息
            </CardTitle>
            <CardDescription>该密码只在本次创建后显示，请立即交付给成员并要求首次登录后修改。</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="text-sm">
              <p className="font-medium text-slate-900 dark:text-white">{createdMemberCredential.email}</p>
              <p className="mt-1 font-mono text-slate-700 dark:text-slate-200">{createdMemberCredential.password}</p>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" onClick={copyTemporaryPassword}>复制</Button>
              <Button variant="outline" onClick={() => setCreatedMemberCredential(null)}>已保存</Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      <Card data-testid="team-role-template-panel">
        <CardHeader>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <CardTitle>标准角色模板</CardTitle>
              <CardDescription>
                内置咨询交付常用岗位，帮助新租户快速形成成员、角色、字段权限和审计的可验收基线。
              </CardDescription>
            </div>
            <Button
              variant="outline"
              disabled={!missingRoleTemplates.length || createAllRoleTemplatesMutation.isPending}
              onClick={() => createAllRoleTemplatesMutation.mutate()}
              data-testid="team-create-all-role-templates"
            >
              <UserCheck className="mr-2 h-4 w-4" />
              {missingRoleTemplates.length ? `补齐 ${missingRoleTemplates.length} 个模板` : '模板已齐全'}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          {roleTemplates.map((template) => {
            const exists = existingRoleNames.has(template.name)
            return (
              <div key={template.key} className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-semibold text-slate-900 dark:text-white">{template.name}</p>
                    <p className="mt-1 text-sm text-slate-500">{template.description}</p>
                  </div>
                  <Badge variant={exists ? 'secondary' : 'outline'}>{exists ? '已创建' : '缺失'}</Badge>
                </div>
                <div className="mt-3 flex flex-wrap gap-1">
                  {template.permissions.slice(0, 5).map((permission) => (
                    <Badge key={permission} variant="outline">{permission}</Badge>
                  ))}
                  {template.permissions.length > 5 ? <Badge variant="outline">+{template.permissions.length - 5}</Badge> : null}
                </div>
                <Button
                  className="mt-4 w-full"
                  variant="outline"
                  size="sm"
                  disabled={exists || createRoleTemplateMutation.isPending || createAllRoleTemplatesMutation.isPending}
                  onClick={() => createRoleTemplateMutation.mutate(template)}
                  data-testid={`team-create-role-template-${template.key}`}
                >
                  {exists ? '已在角色矩阵中' : '创建模板'}
                </Button>
              </div>
            )
          })}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <CardTitle>团队权限生产闭环</CardTitle>
              <CardDescription>把成员、角色、审计证据和生产校准放在同一个入口，便于确认该栏目是否真正可用。</CardDescription>
            </div>
            <Badge variant={teamCapability?.status === 'ready' ? 'secondary' : teamCapability?.status === 'blocked' ? 'destructive' : 'outline'}>
              {readinessQuery.isLoading ? '检查中' : teamCapability?.status === 'ready' ? '已就绪' : teamCapability?.status === 'degraded' ? '需补证据' : teamCapability?.status === 'blocked' ? '阻塞' : '未校准'}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="space-y-3">
            <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="font-semibold text-slate-900 dark:text-white">{teamCapability?.label || '团队权限与审计'}</p>
                  <p className="mt-1 text-sm text-slate-500">{teamCapability?.summary || '正在读取团队权限生产准备度。'}</p>
                </div>
                <div className="rounded-md border px-3 py-2 text-sm font-semibold text-slate-700 dark:text-slate-200">
                  {teamCapability?.score ?? 0}
                </div>
              </div>
              <div data-testid="team-production-evidence-grid" className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
                {teamEvidenceItems.map((item) => (
                  <div
                    key={item.key}
                    data-testid={`team-production-evidence-${item.key}`}
                    className="rounded-md border border-slate-200 px-3 py-2 dark:border-slate-800"
                  >
                    <p className="text-xs text-slate-500">{item.label}</p>
                    <p className="mt-1 text-lg font-semibold text-slate-900 dark:text-white">{item.value}</p>
                  </div>
                ))}
              </div>
              {teamCapability?.blockers?.length ? (
                <div className="mt-3 rounded-md bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
                  {teamCapability.blockers[0]}
                </div>
              ) : null}
              {teamCapability?.recommended_actions?.length ? (
                <p className="mt-3 text-sm text-slate-500">建议：{teamCapability.recommended_actions[0]}</p>
              ) : null}
            </div>
            {teamCommissioningCheck ? (
              <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-semibold text-slate-900 dark:text-white">{teamCommissioningCheck.label}</p>
                    <p className="mt-1 text-sm text-slate-500">{teamCommissioningCheck.summary}</p>
                  </div>
                  <Badge variant={teamCommissioningCheck.status === 'passed' ? 'secondary' : teamCommissioningCheck.status === 'failed' ? 'destructive' : 'outline'}>
                    {teamCommissioningCheck.status === 'passed' ? '通过' : teamCommissioningCheck.status === 'failed' ? '失败' : '待校准'}
                  </Badge>
                </div>
                {teamCommissioningCheck.blockers.length ? (
                  <p className="mt-3 text-sm text-amber-700 dark:text-amber-200">{teamCommissioningCheck.blockers[0]}</p>
                ) : null}
              </div>
            ) : null}
          </div>
          <div className="space-y-3 rounded-lg border border-slate-200 p-4 dark:border-slate-800">
            <p className="font-semibold text-slate-900 dark:text-white">闭环动作</p>
            {teamActivationActions.length ? (
              teamActivationActions.map((action) => (
                <Button
                  key={action.key}
                  data-testid={`team-activation-action-${action.key}`}
                  variant="outline"
                  className="w-full justify-between"
                  disabled={!action.can_execute || runActivationMutation.isPending}
                  onClick={() => runActivationMutation.mutate([action.key])}
                >
                  <span>{action.label}</span>
                  <ArrowRight className="h-4 w-4" />
                </Button>
              ))
            ) : (
              <p className="text-sm text-slate-500">当前没有可执行初始化动作。</p>
            )}
            <Button
              className="w-full justify-between"
              disabled={!teamCommissioningCheck?.can_run || runCommissioningMutation.isPending}
              onClick={() => runCommissioningMutation.mutate(['team_permission_audit'])}
            >
              <span>{runCommissioningMutation.isPending ? '校准中...' : '运行团队权限校准'}</span>
              <Activity className="h-4 w-4" />
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <CardTitle>权限自检</CardTitle>
              <CardDescription>用当前账号真实权限计算项目、文档、导出、智能编排和团队管理是否可执行。</CardDescription>
            </div>
            <div className="grid grid-cols-3 gap-2 text-center text-sm">
              <div className="rounded-md border border-slate-200 px-3 py-2 dark:border-slate-800">
                <p className="text-xs text-slate-500">放行</p>
                <p className="font-semibold text-emerald-700 dark:text-emerald-300">{diagnostics?.summary.allowed ?? 0}</p>
              </div>
              <div className="rounded-md border border-slate-200 px-3 py-2 dark:border-slate-800">
                <p className="text-xs text-slate-500">拒绝</p>
                <p className="font-semibold text-rose-700 dark:text-rose-300">{diagnostics?.summary.denied ?? 0}</p>
              </div>
              <div className="rounded-md border border-slate-200 px-3 py-2 dark:border-slate-800">
                <p className="text-xs text-slate-500">字段管控</p>
                <p className="font-semibold text-amber-700 dark:text-amber-300">{diagnostics?.summary.field_restricted ?? 0}</p>
              </div>
            </div>
          </div>
        </CardHeader>
        <CardContent className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(280px,0.8fr)]">
          <div className="space-y-3">
            {diagnosticsQuery.isLoading ? (
              <div className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500 dark:border-slate-700">
                正在计算当前账号权限...
              </div>
            ) : diagnostics?.checks.length ? (
              diagnostics.checks.map((check) => (
                <div key={check.key} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 p-3 text-sm dark:border-slate-800">
                  <div>
                    <p className="font-medium text-slate-900 dark:text-white">{check.label}</p>
                    <p className="mt-1 text-xs text-slate-500">{check.resource}.{check.action} | {decisionReasonLabel[check.reason] ?? check.reason}</p>
                  </div>
                  <Badge variant={check.allowed ? 'secondary' : 'destructive'}>{check.allowed ? '允许' : '拒绝'}</Badge>
                </div>
              ))
            ) : (
              <div className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500 dark:border-slate-700">
                暂无权限诊断结果。
              </div>
            )}
          </div>
          <div className="space-y-3">
            <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
              <p className="font-semibold text-slate-900 dark:text-white">字段管控</p>
              <div className="mt-3 space-y-2">
                {(diagnostics?.field_controls ?? []).length ? (
                  diagnostics?.field_controls.slice(0, 6).map((control) => (
                    <div key={`${control.role_id}-${control.resource_type}-${control.field_name}`} className="rounded-md bg-slate-50 p-3 text-sm dark:bg-slate-900">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium text-slate-900 dark:text-white">{fieldLabel(control.resource_type, control.field_name)}</span>
                        <Badge variant={control.permission === 'none' ? 'destructive' : 'outline'}>{fieldPermissionText[control.permission] ?? control.permission}</Badge>
                      </div>
                      <p className="mt-1 text-xs text-slate-500">{control.role_name} | {control.resource_type}</p>
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-slate-500">当前角色没有显式字段限制。</p>
                )}
              </div>
            </div>
            <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
              <p className="font-semibold text-slate-900 dark:text-white">策略证据</p>
              <div className="mt-3 space-y-2">
                {(diagnostics?.policy_evidence ?? []).slice(0, 4).map((policy) => (
                  <div key={policy.id} className="rounded-md bg-slate-50 p-3 text-sm dark:bg-slate-900">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-slate-900 dark:text-white">{policy.name}</span>
                      <Badge variant={policy.effect === 'deny' ? 'destructive' : 'secondary'}>{policy.effect === 'deny' ? '拒绝' : '允许'}</Badge>
                    </div>
                    <p className="mt-1 text-xs text-slate-500">{policy.actions.join(', ')} | {policy.resources.join(', ')}</p>
                  </div>
                ))}
                {!(diagnostics?.policy_evidence ?? []).length ? (
                  <p className="text-sm text-slate-500">当前租户尚未配置 ABAC 策略。</p>
                ) : null}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {risks.length ? (
        <Card className="border-amber-200 bg-amber-50/60 dark:border-amber-900 dark:bg-amber-950/20">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <AlertTriangle className="h-5 w-5 text-amber-600" />
              权限风险队列
            </CardTitle>
            <CardDescription>这些事项会影响最小权限、发布授权或审计可解释性。</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 lg:grid-cols-2 xl:grid-cols-4">
            {risks.map((risk) => (
              <div key={risk.title} className="rounded-lg border border-amber-200 bg-white p-4 text-sm dark:border-amber-900 dark:bg-slate-950/40">
                <Badge variant={risk.severity === 'high' ? 'destructive' : 'outline'}>{risk.severity === 'high' ? '高' : '中'}</Badge>
                <p className="mt-3 font-semibold text-slate-900 dark:text-white">{risk.title}</p>
                <p className="mt-1 text-slate-600 dark:text-slate-300">{risk.detail}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      ) : (
        <Card className="border-emerald-200 bg-emerald-50/60 dark:border-emerald-900 dark:bg-emerald-950/20">
          <CardContent className="flex items-center gap-3 py-4 text-sm text-emerald-800 dark:text-emerald-100">
            <ShieldCheck className="h-5 w-5" />
            当前成员、角色、策略和字段权限没有明显阻塞项。
          </CardContent>
        </Card>
      )}

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="overview">总览</TabsTrigger>
          <TabsTrigger value="members">成员</TabsTrigger>
          <TabsTrigger value="roles">角色矩阵</TabsTrigger>
          <TabsTrigger value="policies">策略</TabsTrigger>
          <TabsTrigger value="fields">字段权限</TabsTrigger>
          <TabsTrigger value="simulation">权限模拟</TabsTrigger>
          <TabsTrigger value="audit">审计</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-6">
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
            <Card>
              <CardHeader>
                <CardTitle>角色授权覆盖</CardTitle>
                <CardDescription>按业务资源展示角色权限，便于检查项目文档、智能编排和团队管理的授权边界。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {rolesQuery.isLoading ? (
                  <div className="py-10 text-center text-sm text-slate-500">正在加载角色...</div>
                ) : roles.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700">
                    暂无角色。请先创建顾问、评审人或管理员角色。
                  </div>
                ) : (
                  roles.map((role) => {
                    const selected = selectedPermissionSet(role)
                    return (
                      <div key={role.id} className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <p className="font-semibold text-slate-900 dark:text-white">{role.name}</p>
                            <p className="mt-1 text-sm text-slate-500">{role.description || '暂无角色说明'}</p>
                          </div>
                          <Badge variant={hasAdminPower(role) ? 'destructive' : 'secondary'}>{hasAdminPower(role) ? '高权限' : '标准权限'}</Badge>
                        </div>
                        <div className="mt-4 grid gap-3 lg:grid-cols-2">
                          {permissionCatalog.map((group) => (
                            <div key={group.resource} className="rounded-md bg-slate-50 p-3 text-sm dark:bg-slate-900">
                              <p className="font-medium text-slate-800 dark:text-slate-100">{group.label}</p>
                              <div className="mt-2 flex flex-wrap gap-2">
                                {group.actions.map((action) => (
                                  <Badge key={action.key} variant={selected.has(`${group.resource}:${action.key}`) ? 'secondary' : 'outline'}>
                                    {action.label}
                                  </Badge>
                                ))}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )
                  })
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>最近权限事件</CardTitle>
                <CardDescription>成员、角色、策略和字段权限相关操作的审计摘要。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {(auditQuery.data?.items ?? []).slice(0, 8).map((event) => (
                  <div key={event.id} className="rounded-lg border border-slate-200 p-3 text-sm dark:border-slate-800">
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-medium text-slate-900 dark:text-white">{auditSummary(event)}</span>
                      <Badge variant="outline">{event.resource_type || 'system'}</Badge>
                    </div>
                    <p className="mt-1 text-xs text-slate-500">{new Date(event.created_at).toLocaleString('zh-CN')}</p>
                  </div>
                ))}
                {(auditQuery.data?.items ?? []).length === 0 && (
                  <div className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500 dark:border-slate-700">
                    暂无权限审计事件。
                  </div>
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

        <TabsContent value="members">
          <Card>
            <CardHeader>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <CardTitle>租户成员列表</CardTitle>
                  <CardDescription>创建成员、停用账号，并为成员分配当前租户角色。</CardDescription>
                </div>
                <Button onClick={() => setMemberDialogOpen(true)}>
                  <Mail className="mr-2 h-4 w-4" />
                  新增成员
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {usersQuery.isLoading ? (
                <div className="py-10 text-center text-sm text-slate-500">正在加载成员...</div>
              ) : users.length === 0 ? (
                <div className="rounded-lg border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700">暂无成员。</div>
              ) : (
                users.map((user) => {
                  const assignedRoleIds = new Set((user.roles ?? []).map((role) => role.id))
                  return (
                    <div key={user.id} className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
                      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                        <div className="flex items-center gap-3">
                          <Avatar>
                            <AvatarFallback>{initials(userName(user))}</AvatarFallback>
                          </Avatar>
                          <div>
                            <p className="font-semibold text-slate-900 dark:text-white">{userName(user)}</p>
                            <p className="text-sm text-slate-500">{user.email}</p>
                          </div>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant={user.is_active === false ? 'destructive' : 'secondary'}>{user.is_active === false ? '停用' : '启用'}</Badge>
                          {roleNames(user).length ? (
                            roleNames(user).map((roleName) => <Badge key={roleName} variant="outline">{roleName}</Badge>)
                          ) : (
                            <Badge variant="destructive">未分配角色</Badge>
                          )}
                          <Button variant="outline" size="sm" onClick={() => toggleUserMutation.mutate(user)}>
                            {user.is_active === false ? '启用账号' : '停用账号'}
                          </Button>
                        </div>
                      </div>
                      <div className="mt-4 flex flex-wrap gap-2">
                        {roles.map((role) => (
                          <Button
                            key={role.id}
                            variant={assignedRoleIds.has(role.id) ? 'secondary' : 'outline'}
                            size="sm"
                            disabled={assignRoleMutation.isPending || revokeRoleMutation.isPending}
                            onClick={() =>
                              assignedRoleIds.has(role.id)
                                ? revokeRoleMutation.mutate({ roleId: role.id, userId: user.id })
                                : assignRoleMutation.mutate({ roleId: role.id, userId: user.id })
                            }
                          >
                            {assignedRoleIds.has(role.id) ? <Check className="mr-2 h-4 w-4" /> : <UserCheck className="mr-2 h-4 w-4" />}
                            {assignedRoleIds.has(role.id) ? `撤销 ${role.name}` : role.name}
                          </Button>
                        ))}
                      </div>
                    </div>
                  )
                })
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="roles">
          <Card>
            <CardHeader>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <CardTitle>角色权限矩阵</CardTitle>
                  <CardDescription>用结构化权限代替散落的按钮权限，后端保存为角色 permissions。</CardDescription>
                </div>
                <Button onClick={openCreateRoleDialog}>
                  <Shield className="mr-2 h-4 w-4" />
                  新建角色
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {roles.map((role) => {
                const selected = selectedPermissionSet(role)
                const assignedCount = users.filter((user) => user.roles?.some((item) => item.id === role.id)).length
                return (
                  <div key={role.id} className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="font-semibold text-slate-900 dark:text-white">{role.name}</p>
                        <p className="mt-1 text-sm text-slate-500">{role.description || '暂无角色说明'}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge variant={hasAdminPower(role) ? 'destructive' : 'outline'}>{hasAdminPower(role) ? '高权限' : '普通权限'}</Badge>
                        <Badge variant="secondary">{assignedCount} 人</Badge>
                        <Button variant="outline" size="sm" onClick={() => openEditRoleDialog(role)}>
                          <Pencil className="mr-2 h-4 w-4" />
                          编辑
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={assignedCount > 0 || deleteRoleMutation.isPending}
                          onClick={() => deleteRoleMutation.mutate(role.id)}
                        >
                          <Trash2 className="mr-2 h-4 w-4" />
                          删除
                        </Button>
                      </div>
                    </div>
                    <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                      {permissionCatalog.map((group) => (
                        <div key={group.resource} className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
                          <p className="text-sm font-medium text-slate-900 dark:text-white">{group.label}</p>
                          <div className="mt-2 flex flex-wrap gap-2">
                            {group.actions.map((action) => (
                              <Badge key={action.key} variant={selected.has(`${group.resource}:${action.key}`) ? 'secondary' : 'outline'}>
                                {action.label}
                              </Badge>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )
              })}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="policies">
          <Card>
            <CardHeader>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <CardTitle>ABAC 策略</CardTitle>
                  <CardDescription>策略用于在角色授权之外补充 allow/deny 规则，deny 策略优先生效。</CardDescription>
                </div>
                <Button onClick={openCreatePolicyDialog}>
                  <Lock className="mr-2 h-4 w-4" />
                  新建策略
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {policies.length === 0 ? (
                <div className="rounded-lg border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700">暂无策略。角色权限将直接决定访问结果。</div>
              ) : (
                policies.map((policy: Policy) => (
                  <div key={policy.id} className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <p className="font-semibold text-slate-900 dark:text-white">{policy.name}</p>
                        <p className="mt-1 text-sm text-slate-500">{policy.description || '暂无策略说明'}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge variant={policy.effect === 'deny' ? 'destructive' : 'secondary'}>{policy.effect === 'deny' ? '拒绝' : '允许'}</Badge>
                        <Button variant="outline" size="sm" onClick={() => openEditPolicyDialog(policy)}>
                          <Pencil className="mr-2 h-4 w-4" />
                          编辑
                        </Button>
                        <Button variant="outline" size="sm" disabled={deletePolicyMutation.isPending} onClick={() => deletePolicyMutation.mutate(policy.id)}>
                          <Trash2 className="mr-2 h-4 w-4" />
                          删除
                        </Button>
                      </div>
                    </div>
                    <div className="mt-3 grid gap-3 text-sm md:grid-cols-3">
                      <div>
                        <p className="text-slate-500">动作</p>
                        <p className="mt-1 font-medium text-slate-900 dark:text-white">{policy.actions.join(', ')}</p>
                      </div>
                      <div>
                        <p className="text-slate-500">资源</p>
                        <p className="mt-1 font-medium text-slate-900 dark:text-white">{policy.resources.join(', ')}</p>
                      </div>
                      <div>
                        <p className="text-slate-500">条件</p>
                        <p className="mt-1 break-all font-mono text-xs text-slate-700 dark:text-slate-200">{JSON.stringify(policy.conditions ?? {})}</p>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="fields">
          <Card>
            <CardHeader>
              <CardTitle>字段级权限</CardTitle>
              <CardDescription>对敏感字段设置可读、可写或不可见，覆盖文档、项目和运行记录的局部字段。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>角色</Label>
                  <Select value={selectedRoleId} onValueChange={setSelectedRoleId}>
                    {roles.map((role) => (
                      <SelectOption key={role.id} value={role.id}>{role.name}</SelectOption>
                    ))}
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>资源类型</Label>
                  <Select value={selectedFieldResource} onValueChange={setSelectedFieldResource}>
                    <SelectOption value="document">文档</SelectOption>
                    <SelectOption value="project">项目</SelectOption>
                    <SelectOption value="agent_run">Agent 运行</SelectOption>
                  </Select>
                </div>
              </div>

              {selectedRole ? (
                <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="font-semibold text-slate-900 dark:text-white">{selectedRole.name}</p>
                      <p className="mt-1 text-sm text-slate-500">当前有 {selectedRoleUsers.length} 个成员使用此角色。</p>
                    </div>
                    <Badge variant="outline">{selectedFieldResource}</Badge>
                  </div>
                  <div className="mt-4 grid gap-3 lg:grid-cols-2">
                    {fieldCatalog.filter((item) => item.resource === selectedFieldResource).map((field) => (
                      <div key={field.field} className="flex flex-col gap-3 rounded-md bg-slate-50 p-3 dark:bg-slate-900 sm:flex-row sm:items-center sm:justify-between">
                        <div>
                          <p className="font-medium text-slate-900 dark:text-white">{field.label}</p>
                          <p className="text-xs text-slate-500">{field.field}</p>
                        </div>
                        <div className="flex items-center gap-2">
                          <Select
                            value={String(permissionLookup.get(field.field) ?? 'read')}
                            onValueChange={(permission) => setFieldPermissionMutation.mutate({ field: field.field, permission: permission as 'read' | 'write' | 'none' })}
                          >
                            <SelectOption value="read">{fieldPermissionLabels.read}</SelectOption>
                            <SelectOption value="write">{fieldPermissionLabels.write}</SelectOption>
                            <SelectOption value="none">{fieldPermissionLabels.none}</SelectOption>
                          </Select>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="rounded-lg border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700">请先创建角色，再配置字段权限。</div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="simulation">
          <div className="grid gap-6 xl:grid-cols-[minmax(0,460px)_1fr]">
            <Card data-testid="team-permission-simulation-panel">
              <CardHeader>
                <CardTitle>权限模拟器</CardTitle>
                <CardDescription>
                  调用后端真实权限判定器，模拟某个成员执行项目、文档、智能编排或团队管理动作时会被允许还是拒绝。
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label>成员</Label>
                  <Select value={simulationForm.userId} onValueChange={(userId) => setSimulationForm((value) => ({ ...value, userId }))}>
                    {users.map((user) => (
                      <SelectOption key={user.id} value={user.id}>{userName(user)} · {user.email}</SelectOption>
                    ))}
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>常见操作</Label>
                  <Select
                    value={simulationForm.targetKey}
                    onValueChange={(targetKey) => {
                      const target = permissionSimulationTargets.find((item) => item.key === targetKey)
                      if (!target) return
                      setSimulationForm((value) => ({
                        ...value,
                        targetKey,
                        resource: target.resource,
                        action: target.action,
                        resourceType: target.resourceType,
                        fieldName: target.fieldName,
                      }))
                    }}
                  >
                    {permissionSimulationTargets.map((target) => (
                      <SelectOption key={target.key} value={target.key}>{target.label}</SelectOption>
                    ))}
                  </Select>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="simulation-resource">资源</Label>
                    <Input
                      id="simulation-resource"
                      value={simulationForm.resource}
                      onChange={(event) => setSimulationForm((value) => ({ ...value, resource: event.target.value }))}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="simulation-action">动作</Label>
                    <Input
                      id="simulation-action"
                      value={simulationForm.action}
                      onChange={(event) => setSimulationForm((value) => ({ ...value, action: event.target.value }))}
                    />
                  </div>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="simulation-resource-type">字段资源类型</Label>
                    <Input
                      id="simulation-resource-type"
                      value={simulationForm.resourceType}
                      placeholder="document / project / agent_run"
                      onChange={(event) => setSimulationForm((value) => ({ ...value, resourceType: event.target.value }))}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="simulation-field-name">字段名</Label>
                    <Input
                      id="simulation-field-name"
                      value={simulationForm.fieldName}
                      placeholder="可选，例如 commercial_terms"
                      onChange={(event) => setSimulationForm((value) => ({ ...value, fieldName: event.target.value }))}
                    />
                  </div>
                </div>
                <Button
                  className="w-full"
                  disabled={!simulationForm.userId || !simulationForm.resource.trim() || !simulationForm.action.trim() || simulatePermissionMutation.isPending}
                  onClick={() => simulatePermissionMutation.mutate()}
                  data-testid="team-run-permission-simulation"
                >
                  <ShieldCheck className="mr-2 h-4 w-4" />
                  {simulatePermissionMutation.isPending ? '模拟中...' : '运行权限模拟'}
                </Button>
              </CardContent>
            </Card>

            <Card data-testid="team-permission-simulation-result">
              <CardHeader>
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <CardTitle>模拟结果与证据</CardTitle>
                    <CardDescription>
                      结果来自后端权限判定器，并写入权限模拟审计事件，便于生产验收时复核授权边界。
                    </CardDescription>
                  </div>
                  {simulationResult ? (
                    <Badge variant={simulationResult.allowed ? 'secondary' : 'destructive'}>
                      {simulationResult.allowed ? '允许' : '拒绝'}
                    </Badge>
                  ) : (
                    <Badge variant="outline">未运行</Badge>
                  )}
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {!simulationResult ? (
                  <div className="rounded-lg border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700">
                    选择成员和操作后运行模拟，这里会显示角色、策略和字段级证据。
                  </div>
                ) : (
                  <>
                    <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <p className="font-semibold text-slate-900 dark:text-white">
                            {simulationResult.target_user_name || (selectedSimulationUser ? userName(selectedSimulationUser) : simulationResult.target_user_email)}
                          </p>
                          <p className="mt-1 text-sm text-slate-500">
                            {simulationResult.resource}.{simulationResult.action} · {decisionReasonLabel[simulationResult.reason] ?? simulationResult.reason}
                          </p>
                        </div>
                        <Badge variant={simulationResult.allowed ? 'secondary' : 'destructive'}>
                          {simulationResult.allowed ? '后端判定允许' : '后端判定拒绝'}
                        </Badge>
                      </div>
                    </div>
                    <div className="grid gap-4 lg:grid-cols-3">
                      <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
                        <p className="font-semibold text-slate-900 dark:text-white">角色证据</p>
                        <div className="mt-3 space-y-2">
                          {simulationResult.roles.map((role) => (
                            <div key={role.id} className="rounded-md bg-slate-50 p-3 text-sm dark:bg-slate-900">
                              <p className="font-medium text-slate-900 dark:text-white">{role.name}</p>
                              <p className="mt-1 break-all font-mono text-xs text-slate-500">{JSON.stringify(role.permissions)}</p>
                            </div>
                          ))}
                          {simulationResult.roles.length === 0 ? <p className="text-sm text-slate-500">该成员没有角色。</p> : null}
                        </div>
                      </div>
                      <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
                        <p className="font-semibold text-slate-900 dark:text-white">策略证据</p>
                        <div className="mt-3 space-y-2">
                          {simulationResult.policy_evidence.map((policy) => (
                            <div key={policy.id} className="rounded-md bg-slate-50 p-3 text-sm dark:bg-slate-900">
                              <div className="flex items-center justify-between gap-2">
                                <p className="font-medium text-slate-900 dark:text-white">{policy.name}</p>
                                <Badge variant={policy.effect === 'deny' ? 'destructive' : 'secondary'}>{policy.effect === 'deny' ? '拒绝' : '允许'}</Badge>
                              </div>
                              <p className="mt-1 text-xs text-slate-500">{policy.resources.join(', ')} · {policy.actions.join(', ')}</p>
                            </div>
                          ))}
                          {simulationResult.policy_evidence.length === 0 ? <p className="text-sm text-slate-500">没有命中策略。</p> : null}
                        </div>
                      </div>
                      <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
                        <p className="font-semibold text-slate-900 dark:text-white">字段证据</p>
                        <div className="mt-3 space-y-2">
                          {simulationResult.field_controls.map((control) => (
                            <div key={`${control.role_id}-${control.resource_type}-${control.field_name}`} className="rounded-md bg-slate-50 p-3 text-sm dark:bg-slate-900">
                              <div className="flex items-center justify-between gap-2">
                                <p className="font-medium text-slate-900 dark:text-white">{fieldLabel(control.resource_type, control.field_name)}</p>
                                <Badge variant={control.permission === 'none' ? 'destructive' : 'outline'}>{fieldPermissionText[control.permission] ?? control.permission}</Badge>
                              </div>
                              <p className="mt-1 text-xs text-slate-500">{control.role_name} · {control.resource_type}</p>
                            </div>
                          ))}
                          {simulationResult.field_controls.length === 0 ? <p className="text-sm text-slate-500">没有字段级限制证据。</p> : null}
                        </div>
                      </div>
                    </div>
                  </>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="audit">
          <Card>
            <CardHeader>
              <CardTitle>权限审计</CardTitle>
              <CardDescription>展示最近的权限相关操作，同时保留跳转到全量审计中心的入口。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {(auditQuery.data?.items ?? []).map((event) => (
                <div key={event.id} className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="font-semibold text-slate-900 dark:text-white">{auditSummary(event)}</p>
                      <p className="mt-1 text-sm text-slate-500">{event.action} · {new Date(event.created_at).toLocaleString('zh-CN')}</p>
                    </div>
                    <Badge variant="outline">{event.resource_type || 'system'}</Badge>
                  </div>
                </div>
              ))}
              <Button asChild variant="outline" className="w-full justify-between">
                <Link href="/audit">
                  打开审计中心
                  <ArrowRight className="h-4 w-4" />
                </Link>
              </Button>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <Dialog open={memberDialogOpen} onOpenChange={setMemberDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新增成员</DialogTitle>
            <DialogDescription>创建租户成员，并可立即分配一个初始角色。</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="member-name">姓名</Label>
              <Input id="member-name" value={memberForm.fullName} onChange={(event) => setMemberForm((value) => ({ ...value, fullName: event.target.value }))} placeholder="例如：业务顾问" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="member-email">邮箱</Label>
              <Input id="member-email" type="email" value={memberForm.email} onChange={(event) => setMemberForm((value) => ({ ...value, email: event.target.value }))} placeholder="输入成员邮箱" />
            </div>
            <div className="space-y-2">
              <Label>初始角色</Label>
              <Select value={memberForm.roleId} onValueChange={(roleId) => setMemberForm((value) => ({ ...value, roleId }))}>
                <SelectOption value="">暂不分配</SelectOption>
                {roles.map((role) => (
                  <SelectOption key={role.id} value={role.id}>{role.name}</SelectOption>
                ))}
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setMemberDialogOpen(false)}>取消</Button>
            <Button disabled={!memberForm.email.trim() || createMemberMutation.isPending} onClick={() => createMemberMutation.mutate()}>
              {createMemberMutation.isPending ? '创建中...' : '创建成员'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={roleDialogOpen} onOpenChange={(open) => {
        setRoleDialogOpen(open)
        if (!open) resetRoleForm()
      }}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>{editingRoleId ? '编辑角色' : '新建角色'}</DialogTitle>
            <DialogDescription>按岗位职责勾选最小必要权限，系统会保存为结构化权限矩阵。</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="role-name">角色名称</Label>
                <Input id="role-name" value={roleForm.name} onChange={(event) => setRoleForm((value) => ({ ...value, name: event.target.value }))} placeholder="例如：文档评审负责人" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="role-description">说明</Label>
                <Input id="role-description" value={roleForm.description} onChange={(event) => setRoleForm((value) => ({ ...value, description: event.target.value }))} placeholder="说明角色职责边界" />
              </div>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              {permissionCatalog.map((group) => (
                <div key={group.resource} className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                  <p className="font-medium text-slate-900 dark:text-white">{group.label}</p>
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    {group.actions.map((action) => {
                      const key = `${group.resource}:${action.key}`
                      return (
                        <label key={key} className="flex items-center gap-2 rounded-md bg-slate-50 p-2 text-sm dark:bg-slate-900">
                          <input
                            type="checkbox"
                            checked={roleForm.permissions.has(key)}
                            onChange={(event) => {
                              setRoleForm((value) => {
                                const permissions = new Set(value.permissions)
                                if (event.target.checked) {
                                  permissions.add(key)
                                } else {
                                  permissions.delete(key)
                                }
                                return { ...value, permissions }
                              })
                            }}
                          />
                          {action.label}
                        </label>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRoleDialogOpen(false)}>取消</Button>
            <Button disabled={!roleForm.name.trim() || roleForm.permissions.size === 0 || saveRoleMutation.isPending} onClick={() => saveRoleMutation.mutate()}>
              {saveRoleMutation.isPending ? '保存中...' : editingRoleId ? '保存角色' : '创建角色'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={policyDialogOpen} onOpenChange={(open) => {
        setPolicyDialogOpen(open)
        if (!open) resetPolicyForm()
      }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingPolicyId ? '编辑策略' : '新建策略'}</DialogTitle>
            <DialogDescription>使用逗号分隔 actions/resources，conditions 使用 JSON。</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="policy-name">策略名称</Label>
              <Input id="policy-name" value={policyForm.name} onChange={(event) => setPolicyForm((value) => ({ ...value, name: event.target.value }))} placeholder="例如：仅允许当前租户访问" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="policy-description">说明</Label>
              <Input id="policy-description" value={policyForm.description} onChange={(event) => setPolicyForm((value) => ({ ...value, description: event.target.value }))} placeholder="说明策略用途和适用范围" />
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label>效果</Label>
                <Select value={policyForm.effect} onValueChange={(effect) => setPolicyForm((value) => ({ ...value, effect: effect as 'allow' | 'deny' }))}>
                  <SelectOption value="allow">允许</SelectOption>
                  <SelectOption value="deny">拒绝</SelectOption>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="policy-actions">动作</Label>
                <Input id="policy-actions" value={policyForm.actions} onChange={(event) => setPolicyForm((value) => ({ ...value, actions: event.target.value }))} />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="policy-resources">资源</Label>
              <Input id="policy-resources" value={policyForm.resources} onChange={(event) => setPolicyForm((value) => ({ ...value, resources: event.target.value }))} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="policy-conditions">条件 JSON</Label>
              <textarea
                id="policy-conditions"
                className="min-h-24 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                value={policyForm.conditions}
                onChange={(event) => setPolicyForm((value) => ({ ...value, conditions: event.target.value }))}
              />
              {!policyConditionValidation.valid ? (
                <p className="text-sm text-rose-600 dark:text-rose-300">{policyConditionValidation.message}</p>
              ) : (
                <p className="text-sm text-slate-500">留空表示不设置条件；填写时必须是合法 JSON。</p>
              )}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPolicyDialogOpen(false)}>取消</Button>
            <Button disabled={!policyForm.name.trim() || !policyConditionValidation.valid || savePolicyMutation.isPending} onClick={() => savePolicyMutation.mutate()}>
              {savePolicyMutation.isPending ? '保存中...' : editingPolicyId ? '保存策略' : '创建策略'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
