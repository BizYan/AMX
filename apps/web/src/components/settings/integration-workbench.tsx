'use client'

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Copy,
  Eye,
  FolderSync,
  Link2,
  PlayCircle,
  PlugZap,
  RefreshCw,
  RotateCcw,
  Save,
  ShieldCheck,
  Trash2,
  Webhook,
  XCircle,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectOption } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useToast } from '@/components/ui/toast'
import {
  integrationsApi,
  opsApi,
  projectsApi,
  type CapabilityActivationAction,
  type IntegrationProjectBinding,
  type IntegrationProjectSyncRun,
  type IntegrationSyncPreview,
  type IntegrationProvider,
  type IntegrationSyncResult,
  type IntegrationTestResult,
  type OutboxEvent,
  type WebhookSubscription,
} from '@/lib/api-client'

const INTEGRATION_TYPES = [
  { value: 'jira', label: 'Jira' },
  { value: 'confluence', label: 'Confluence' },
  { value: 'zentao', label: '禅道' },
  { value: 'feishu', label: '飞书' },
  { value: 'custom', label: '自定义' },
]

const CONFIG_TEMPLATES: Record<string, Record<string, unknown>> = {
  jira: {
    base_url: 'https://jira.example.com',
    api_key: '',
    health_path: '/rest/api/2/myself',
    sync_path: '/rest/api/2/search',
    sync_method: 'GET',
    auth_header: 'Authorization',
    auth_scheme: 'Bearer',
  },
  confluence: {
    base_url: 'https://confluence.example.com',
    api_key: '',
    health_path: '/wiki/rest/api/user/current',
    sync_path: '/wiki/rest/api/content',
    sync_method: 'GET',
    auth_header: 'Authorization',
    auth_scheme: 'Bearer',
  },
  zentao: {
    base_url: 'https://zentao.example.com',
    api_key: '',
    health_path: '/api.php/v1/users',
    sync_path: '/api.php/v1/stories',
    sync_method: 'GET',
    auth_header: 'Token',
    auth_scheme: 'raw',
  },
  feishu: {
    base_url: 'https://open.feishu.cn',
    api_key: '',
    health_path: '/open-apis/authen/v1/user_info',
    sync_path: '/open-apis/docx/v1/documents',
    sync_method: 'GET',
    auth_header: 'Authorization',
    auth_scheme: 'Bearer',
  },
  custom: {
    base_url: 'https://api.example.com',
    api_key: '',
    health_path: '/health',
    sync_path: '/sync',
    sync_method: 'POST',
    auth_header: 'Authorization',
    auth_scheme: 'Bearer',
  },
}

function templateFor(type: string) {
  return JSON.stringify(CONFIG_TEMPLATES[type] || CONFIG_TEMPLATES.custom, null, 2)
}

function parseJson(text: string) {
  return JSON.parse(text || '{}') as Record<string, unknown>
}

function formatTime(value?: string | null) {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN')
}

function statusBadgeClass(status: string) {
  if (['connected', 'synced', 'success', 'passed'].includes(status)) {
    return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-100'
  }
  if (['unconfigured', 'authentication_failed', 'unreachable', 'sync_failed', 'failed'].includes(status)) {
    return 'bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-100'
  }
  return 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-100'
}

function hasEndpoint(integration: IntegrationProvider) {
  const config = integration.config_json || {}
  return Boolean(config.base_url || config.endpoint || config.url || config.server_url || config.api_url)
}

function hasAuth(integration: IntegrationProvider) {
  const config = integration.config_json || {}
  return Boolean(config.api_key || config.token || config.access_token || config.secret || config.service_key)
}

function configHasEndpoint(config: Record<string, unknown>) {
  return Boolean(config.base_url || config.endpoint || config.url || config.server_url || config.api_url)
}

function configHasAuth(config: Record<string, unknown>) {
  return Boolean(config.api_key || config.token || config.access_token || config.secret || config.service_key)
}

const sensitiveConfigKeys = ['api_key', 'token', 'access_token', 'secret', 'service_key']

function buildConfigPreflight(configText: string) {
  try {
    const parsed = parseJson(configText)
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
      return {
        isValid: false,
        config: null as Record<string, unknown> | null,
        error: '配置必须是 JSON 对象。',
        hasEndpoint: false,
        hasAuth: false,
        sensitiveKeys: [] as string[],
      }
    }

    return {
      isValid: true,
      config: parsed,
      error: '',
      hasEndpoint: configHasEndpoint(parsed),
      hasAuth: configHasAuth(parsed),
      sensitiveKeys: sensitiveConfigKeys.filter((key) => Object.prototype.hasOwnProperty.call(parsed, key)),
    }
  } catch (error) {
    return {
      isValid: false,
      config: null as Record<string, unknown> | null,
      error: error instanceof Error ? error.message : '配置 JSON 无法解析。',
      hasEndpoint: false,
      hasAuth: false,
      sensitiveKeys: [] as string[],
    }
  }
}

function integrationReadiness(integration: IntegrationProvider) {
  if (!integration.is_enabled) return { status: 'disabled', label: '已停用', score: 20 }
  if (integration.last_sync_at) return { status: 'synced', label: '已同步验证', score: 100 }
  if (hasEndpoint(integration) && hasAuth(integration)) return { status: 'configured', label: '待联调同步', score: 70 }
  if (hasEndpoint(integration)) return { status: 'partial', label: '缺少认证', score: 45 }
  return { status: 'blocked', label: '未配置', score: 15 }
}

export function IntegrationWorkbench() {
  const queryClient = useQueryClient()
  const { addToast } = useToast()
  const [activePanel, setActivePanel] = useState('integrations')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [form, setForm] = useState({
    name: '',
    provider_type: 'jira',
    config: templateFor('jira'),
  })
  const [editingId, setEditingId] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<Record<string, IntegrationTestResult>>({})
  const [syncResults, setSyncResults] = useState<Record<string, IntegrationSyncResult>>({})
  const [webhookForm, setWebhookForm] = useState({
    url: '',
    events: 'document.published,change.approved',
    secret: '',
  })
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [selectedBindingId, setSelectedBindingId] = useState<string | null>(null)
  const [syncPreview, setSyncPreview] = useState<IntegrationSyncPreview | null>(null)
  const [bindingForm, setBindingForm] = useState({
    projectId: '',
    name: '',
    scope: JSON.stringify({ item_path: 'issues', cursor_param: 'updated_after' }, null, 2),
    fieldMapping: JSON.stringify({
      external_id: 'key',
      title: 'fields.summary',
      content: 'fields.description',
      external_url: 'self',
      updated_at: 'fields.updated',
    }, null, 2),
  })

  const integrationsQuery = useQuery({
    queryKey: ['integrations'],
    queryFn: () => integrationsApi.list({ pageSize: 100 }),
  })

  const integrations = useMemo(() => integrationsQuery.data?.items || [], [integrationsQuery.data?.items])

  const selectedIntegration = useMemo(
    () => integrations.find((item) => item.id === selectedId) || integrations[0] || null,
    [integrations, selectedId],
  )

  const webhooksQuery = useQuery({
    queryKey: ['integration-webhooks', selectedIntegration?.id],
    queryFn: () => selectedIntegration ? integrationsApi.listWebhooks(selectedIntegration.id, { pageSize: 100 }) : Promise.resolve({ items: [], total: 0, page: 1, page_size: 100, has_more: false }),
    enabled: Boolean(selectedIntegration),
  })

  const outboxQuery = useQuery({
    queryKey: ['integration-outbox-events'],
    queryFn: () => integrationsApi.listOutboxEvents({ pageSize: 20 }),
  })

  const operationsSummaryQuery = useQuery({
    queryKey: ['integration-operations-summary'],
    queryFn: () => integrationsApi.getOperationsSummary(),
  })

  const activationPlanQuery = useQuery({
    queryKey: ['integration-activation-plan'],
    queryFn: () => opsApi.getCapabilityActivationPlan(),
  })

  const projectsQuery = useQuery({
    queryKey: ['integration-project-options'],
    queryFn: () => projectsApi.list({ pageSize: 100 }),
  })

  const bindingsQuery = useQuery({
    queryKey: ['integration-project-bindings', selectedIntegration?.id],
    queryFn: () => selectedIntegration ? integrationsApi.listProjectBindings(selectedIntegration.id) : Promise.resolve([]),
    enabled: Boolean(selectedIntegration),
  })

  const bindings = useMemo(() => bindingsQuery.data || [], [bindingsQuery.data])
  const selectedBinding = useMemo(
    () => bindings.find((item) => item.id === selectedBindingId) || bindings[0] || null,
    [bindings, selectedBindingId],
  )

  const syncRunsQuery = useQuery({
    queryKey: ['integration-project-sync-runs', selectedBinding?.id],
    queryFn: () => selectedBinding ? integrationsApi.listProjectBindingRuns(selectedBinding.id) : Promise.resolve([]),
    enabled: Boolean(selectedBinding),
  })

  const webhooks = useMemo(() => webhooksQuery.data?.items || [], [webhooksQuery.data?.items])
  const outboxEvents = useMemo(() => outboxQuery.data?.items || [], [outboxQuery.data?.items])
  const operationsSummary = operationsSummaryQuery.data
  const evidence = operationsSummary?.evidence
  const integrationActivationActions = useMemo(
    () => (activationPlanQuery.data?.actions ?? []).filter(
      (action: CapabilityActivationAction) =>
        action.capability_key === 'external_integration_sync' || action.capability_key === 'external_integrations',
    ),
    [activationPlanQuery.data?.actions],
  )
  const refreshOperationsSummary = () => queryClient.invalidateQueries({ queryKey: ['integration-operations-summary'] })
  const configPreflight = useMemo(() => buildConfigPreflight(form.config), [form.config])
  const canSaveIntegration = Boolean(
    form.name.trim() && configPreflight.isValid && configPreflight.hasEndpoint && configPreflight.hasAuth,
  )

  const stats = useMemo(() => {
    const enabled = integrations.filter((item) => item.is_enabled)
    const synced = integrations.filter((item) => Boolean(item.last_sync_at))
    const configured = integrations.filter((item) => hasEndpoint(item) && hasAuth(item))
    return [
      { label: '集成数量', value: integrations.length, detail: `${enabled.length} 个已启用` },
      { label: '可联调配置', value: configured.length, detail: '具备 endpoint 与认证字段' },
      { label: '同步证据', value: synced.length, detail: '已有 last_sync_at' },
      { label: 'Webhook', value: webhooks.length, detail: selectedIntegration ? selectedIntegration.name : '未选择集成' },
    ]
  }, [integrations, selectedIntegration, webhooks.length])

  const resetForm = (type = 'jira') => {
    setEditingId(null)
    setForm({ name: '', provider_type: type, config: templateFor(type) })
  }

  const openEdit = (integration: IntegrationProvider) => {
    setEditingId(integration.id)
    setSelectedId(integration.id)
    setForm({
      name: integration.name,
      provider_type: integration.provider_type,
      config: JSON.stringify(integration.config_json || {}, null, 2),
    })
    setActivePanel('integrations')
  }

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!configPreflight.config) throw new Error('配置 JSON 无法解析')
      const payload = {
        provider_type: form.provider_type,
        name: form.name.trim(),
        config_json: configPreflight.config,
        is_enabled: true,
      }
      return editingId
        ? integrationsApi.update(editingId, payload)
        : integrationsApi.create(payload)
    },
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['integrations'] })
      refreshOperationsSummary()
      setSelectedId(result.id)
      resetForm(form.provider_type)
      addToast({ title: editingId ? '集成配置已保存' : '集成已创建' })
    },
    onError: (error: Error) => {
      addToast({ title: '保存集成失败', description: error.message, variant: 'destructive' })
    },
  })

  const toggleMutation = useMutation({
    mutationFn: (integration: IntegrationProvider) =>
      integrationsApi.update(integration.id, { is_enabled: !integration.is_enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integrations'] })
      refreshOperationsSummary()
      addToast({ title: '集成启停状态已更新' })
    },
    onError: (error: Error) => addToast({ title: '更新集成失败', description: error.message, variant: 'destructive' }),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => integrationsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integrations'] })
      refreshOperationsSummary()
      setSelectedId(null)
      addToast({ title: '集成已删除' })
    },
    onError: (error: Error) => addToast({ title: '删除集成失败', description: error.message, variant: 'destructive' }),
  })

  const testMutation = useMutation({
    mutationFn: (id: string) => integrationsApi.test(id),
    onSuccess: (result, id) => {
      setTestResults((items) => ({ ...items, [id]: result }))
      refreshOperationsSummary()
      addToast({ title: result.status === 'connected' ? '连接测试通过' : '连接测试未通过', description: result.message, variant: result.status === 'connected' ? 'default' : 'destructive' })
    },
    onError: (error: Error) => addToast({ title: '连接测试失败', description: error.message, variant: 'destructive' }),
  })

  const syncMutation = useMutation({
    mutationFn: (id: string) => integrationsApi.sync(id),
    onSuccess: (result, id) => {
      setSyncResults((items) => ({ ...items, [id]: result }))
      queryClient.invalidateQueries({ queryKey: ['integrations'] })
      queryClient.invalidateQueries({ queryKey: ['integration-outbox-events'] })
      refreshOperationsSummary()
      addToast({ title: result.success ? '同步完成' : '同步失败', description: result.message, variant: result.success ? 'default' : 'destructive' })
    },
    onError: (error: Error) => addToast({ title: '同步失败', description: error.message, variant: 'destructive' }),
  })

  const createWebhookMutation = useMutation({
    mutationFn: () => {
      if (!selectedIntegration) throw new Error('请选择集成')
      return integrationsApi.createWebhook(selectedIntegration.id, {
        url: webhookForm.url.trim(),
        events: webhookForm.events.split(',').map((item) => item.trim()).filter(Boolean),
        secret: webhookForm.secret.trim() || null,
        is_active: true,
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integration-webhooks', selectedIntegration?.id] })
      refreshOperationsSummary()
      setWebhookForm({ url: '', events: 'document.published,change.approved', secret: '' })
      addToast({ title: 'Webhook 已创建' })
    },
    onError: (error: Error) => addToast({ title: '创建 Webhook 失败', description: error.message, variant: 'destructive' }),
  })

  const deleteWebhookMutation = useMutation({
    mutationFn: (webhook: WebhookSubscription) => {
      if (!selectedIntegration) throw new Error('请选择集成')
      return integrationsApi.deleteWebhook(selectedIntegration.id, webhook.id)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integration-webhooks', selectedIntegration?.id] })
      refreshOperationsSummary()
      addToast({ title: 'Webhook 已删除' })
    },
    onError: (error: Error) => addToast({ title: '删除 Webhook 失败', description: error.message, variant: 'destructive' }),
  })

  const publishOutboxMutation = useMutation({
    mutationFn: () => integrationsApi.publishOutbox(100),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['integration-outbox-events'] })
      refreshOperationsSummary()
      addToast({ title: 'Outbox 发布已触发', description: `处理 ${result.processed}，发布 ${result.published}，失败 ${result.failed}` })
    },
    onError: (error: Error) => addToast({ title: '发布 Outbox 失败', description: error.message, variant: 'destructive' }),
  })

  const createBindingMutation = useMutation({
    mutationFn: () => {
      if (!selectedIntegration) throw new Error('请选择集成')
      if (!bindingForm.projectId || !bindingForm.name.trim()) throw new Error('请选择项目并填写绑定名称')
      return integrationsApi.createProjectBinding(selectedIntegration.id, {
        project_id: bindingForm.projectId,
        name: bindingForm.name.trim(),
        scope: parseJson(bindingForm.scope),
        field_mapping: parseJson(bindingForm.fieldMapping) as Record<string, string>,
        is_enabled: true,
      })
    },
    onSuccess: (binding) => {
      queryClient.invalidateQueries({ queryKey: ['integration-project-bindings', selectedIntegration?.id] })
      setSelectedBindingId(binding.id)
      setSyncPreview(null)
      addToast({ title: '项目同步绑定已创建' })
    },
    onError: (error: Error) => addToast({ title: '创建项目绑定失败', description: error.message, variant: 'destructive' }),
  })

  const previewBindingMutation = useMutation({
    mutationFn: (binding: IntegrationProjectBinding) => integrationsApi.previewProjectBinding(binding.id),
    onSuccess: (preview) => {
      setSyncPreview(preview)
      addToast({ title: '同步预览已生成', description: `已规范化 ${preview.total} 条外部内容。` })
    },
    onError: (error: Error) => addToast({ title: '同步预览失败', description: error.message, variant: 'destructive' }),
  })

  const syncBindingMutation = useMutation({
    mutationFn: (binding: IntegrationProjectBinding) => integrationsApi.syncProjectBinding(binding.id),
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: ['integration-project-bindings', selectedIntegration?.id] })
      queryClient.invalidateQueries({ queryKey: ['integration-project-sync-runs', run.binding_id] })
      refreshOperationsSummary()
      addToast({
        title: run.status === 'completed' ? '项目知识同步完成' : '项目知识同步需要处理',
        description: `新增 ${run.created_count}，更新 ${run.updated_count}，未变化 ${run.unchanged_count}，失败 ${run.failed_count}`,
        variant: run.status === 'completed' ? 'default' : 'destructive',
      })
    },
    onError: (error: Error) => addToast({ title: '项目知识同步失败', description: error.message, variant: 'destructive' }),
  })

  const retryRunMutation = useMutation({
    mutationFn: (run: IntegrationProjectSyncRun) => integrationsApi.retryProjectBindingRun(run.id),
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: ['integration-project-sync-runs', run.binding_id] })
      queryClient.invalidateQueries({ queryKey: ['integration-project-bindings', selectedIntegration?.id] })
      addToast({ title: '同步重试已完成', description: `状态：${run.status}` })
    },
    onError: (error: Error) => addToast({ title: '同步重试失败', description: error.message, variant: 'destructive' }),
  })

  const runActivationMutation = useMutation({
    mutationFn: (actions: string[]) => opsApi.runCapabilityActivation({
      dry_run: false,
      confirm: true,
      actions,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integrations'] })
      queryClient.invalidateQueries({ queryKey: ['integration-project-bindings'] })
      queryClient.invalidateQueries({ queryKey: ['integration-project-sync-runs'] })
      queryClient.invalidateQueries({ queryKey: ['integration-activation-plan'] })
      refreshOperationsSummary()
      addToast({ title: '外部同步证据已初始化', description: '项目绑定、同步运行和同步资产证据已刷新。' })
    },
    onError: (error: Error) => addToast({ title: '初始化外部同步失败', description: error.message, variant: 'destructive' }),
  })

  const copyEndpoint = async (text: string) => {
    await navigator.clipboard?.writeText(text)
    setCopiedId(text)
    window.setTimeout(() => setCopiedId(null), 1200)
  }

  return (
    <div className="space-y-6" data-testid="integration-workbench">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h2 className="text-xl font-semibold text-slate-900 dark:text-white">外部集成工作台</h2>
          <p className="mt-1 text-sm text-slate-500">
            管理 Jira、Confluence、禅道、飞书和自定义系统的连接、同步、Webhook 与 Outbox 证据。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => {
            queryClient.invalidateQueries({ queryKey: ['integrations'] })
            queryClient.invalidateQueries({ queryKey: ['integration-outbox-events'] })
            refreshOperationsSummary()
          }}>
            <RefreshCw className="mr-2 h-4 w-4" />
            刷新
          </Button>
          <Button onClick={() => resetForm(form.provider_type)}>
            <PlugZap className="mr-2 h-4 w-4" />
            新建集成
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <CardTitle>集成投产总览</CardTitle>
              <CardDescription>
                {operationsSummaryQuery.isLoading
                  ? '正在汇总外部集成、Webhook 与 Outbox 运行证据。'
                  : operationsSummary?.summary || '尚未形成外部集成投产证据。'}
              </CardDescription>
            </div>
            <div className="min-w-[120px] rounded-md border border-slate-200 p-3 text-center dark:border-slate-800">
              <p className="text-xs text-slate-500">生产就绪分</p>
              <p className="mt-1 text-3xl font-semibold text-slate-900 dark:text-white">
                {operationsSummary?.score ?? '-'}
              </p>
              <Badge className={statusBadgeClass(operationsSummary?.status || 'blocked')}>
                {operationsSummary?.status === 'ready' ? '可投产' : operationsSummary?.status === 'degraded' ? '待修复' : '阻塞'}
              </Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
              <p className="text-xs text-slate-500">已配置集成</p>
              <p className="mt-1 text-xl font-semibold">{evidence?.configured_integration_count ?? 0}/{evidence?.integration_count ?? 0}</p>
            </div>
            <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
              <p className="text-xs text-slate-500">同步证据</p>
              <p className="mt-1 text-xl font-semibold">{evidence?.synced_integration_count ?? 0}</p>
            </div>
            <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
              <p className="text-xs text-slate-500">项目知识资产</p>
              <p className="mt-1 text-xl font-semibold">{evidence?.synced_asset_count ?? 0}</p>
            </div>
            <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
              <p className="text-xs text-slate-500">启用 Webhook</p>
              <p className="mt-1 text-xl font-semibold">{evidence?.active_webhook_count ?? 0}/{evidence?.webhook_count ?? 0}</p>
            </div>
            <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
              <p className="text-xs text-slate-500">Webhook 投递失败</p>
              <p className="mt-1 text-xl font-semibold">{evidence?.failed_delivery_count ?? 0}</p>
            </div>
            <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
              <p className="text-xs text-slate-500">Outbox 积压</p>
              <p className="mt-1 text-xl font-semibold">{evidence?.pending_outbox_count ?? 0}</p>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
              <p className="font-medium text-slate-900 dark:text-white">阻塞项</p>
              <div className="mt-3 space-y-2 text-sm text-slate-600 dark:text-slate-300">
                {(operationsSummary?.blockers.length ? operationsSummary.blockers : ['暂无阻塞项。']).map((item) => (
                  <p key={item}>{item}</p>
                ))}
              </div>
            </div>
            <div className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
              <p className="font-medium text-slate-900 dark:text-white">建议动作</p>
              <div className="mt-3 space-y-2 text-sm text-slate-600 dark:text-slate-300">
                {(operationsSummary?.recommended_actions.length ? operationsSummary.recommended_actions : ['保持连接测试、同步和发布批次的运行记录。']).map((item) => (
                  <p key={item}>{item}</p>
                ))}
              </div>
            </div>
          </div>

          <div className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <p className="font-medium text-slate-900 dark:text-white">生产闭环动作</p>
                <p className="mt-1 text-sm text-slate-500">
                  对外部集成同步执行受控初始化，补齐项目绑定、同步运行和同步资产证据。
                </p>
              </div>
              <div className="flex min-w-[260px] flex-col gap-2">
                {integrationActivationActions.length ? (
                  integrationActivationActions.map((action) => (
                    <Button
                      key={action.key}
                      data-testid={`integration-activation-action-${action.key}`}
                      variant={action.action_type === 'safe' ? 'outline' : 'secondary'}
                      className="justify-between"
                      disabled={action.action_type !== 'safe' || !action.can_execute || runActivationMutation.isPending}
                      onClick={() => runActivationMutation.mutate([action.key])}
                    >
                      <span>{runActivationMutation.isPending ? '初始化中...' : action.label}</span>
                      {runActivationMutation.isPending ? <Activity className="h-4 w-4 animate-pulse" /> : <ArrowRight className="h-4 w-4" />}
                    </Button>
                  ))
                ) : (
                  <p className="text-sm text-slate-500">当前没有可执行初始化动作。</p>
                )}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {stats.map((item) => (
          <Card key={item.label}>
            <CardHeader className="pb-2">
              <CardDescription>{item.label}</CardDescription>
              <CardTitle className="text-3xl">{item.value}</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-slate-500">{item.detail}</CardContent>
          </Card>
        ))}
      </div>

      <Tabs value={activePanel} onValueChange={setActivePanel}>
        <TabsList className="flex h-auto flex-wrap justify-start">
          <TabsTrigger value="integrations">集成配置</TabsTrigger>
          <TabsTrigger value="project-sync">项目同步</TabsTrigger>
          <TabsTrigger value="webhooks">Webhook</TabsTrigger>
          <TabsTrigger value="outbox">Outbox</TabsTrigger>
          <TabsTrigger value="evidence">投产证据</TabsTrigger>
        </TabsList>

        <TabsContent value="integrations" className="space-y-4">
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.2fr)_440px]">
            <Card>
              <CardHeader>
                <CardTitle>集成清单</CardTitle>
                <CardDescription>连接测试和同步会形成外部集成投产证据。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {integrationsQuery.isLoading ? (
                  <div className="py-10 text-center text-sm text-slate-500">正在加载集成...</div>
                ) : integrations.length === 0 ? (
                  <div className="rounded-md border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700">
                    暂无外部集成。创建后先执行连接测试，再执行同步验证。
                  </div>
                ) : (
                  integrations.map((integration) => {
                    const readiness = integrationReadiness(integration)
                    const testResult = testResults[integration.id]
                    const syncResult = syncResults[integration.id]
                    return (
                      <div key={integration.id} className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                          <div>
                            <div className="flex flex-wrap items-center gap-2">
                              <Link2 className="h-4 w-4 text-indigo-500" />
                              <p className="font-semibold text-slate-900 dark:text-white">{integration.name}</p>
                              <Badge variant="outline">{integration.provider_type}</Badge>
                              <Badge className={statusBadgeClass(readiness.status)}>{readiness.label}</Badge>
                            </div>
                            <p className="mt-2 text-sm text-slate-500">
                              最近同步：{formatTime(integration.last_sync_at)}
                            </p>
                            <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                              <span className="rounded bg-slate-100 px-2 py-1 dark:bg-slate-800">endpoint: {hasEndpoint(integration) ? '已配置' : '缺失'}</span>
                              <span className="rounded bg-slate-100 px-2 py-1 dark:bg-slate-800">auth: {hasAuth(integration) ? '已配置' : '缺失'}</span>
                              {testResult && <span className="rounded bg-slate-100 px-2 py-1 dark:bg-slate-800">test: {testResult.status}</span>}
                              {syncResult && <span className="rounded bg-slate-100 px-2 py-1 dark:bg-slate-800">sync: {syncResult.status}</span>}
                            </div>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <Button size="sm" variant="outline" onClick={() => openEdit(integration)}>编辑</Button>
                            <Button size="sm" variant="outline" onClick={() => testMutation.mutate(integration.id)} disabled={testMutation.isPending}>
                              <ShieldCheck className="mr-2 h-4 w-4" />
                              测试
                            </Button>
                            <Button size="sm" variant="outline" onClick={() => syncMutation.mutate(integration.id)} disabled={syncMutation.isPending}>
                              <PlayCircle className="mr-2 h-4 w-4" />
                              同步
                            </Button>
                            <Button size="sm" variant="outline" onClick={() => toggleMutation.mutate(integration)} disabled={toggleMutation.isPending}>
                              {integration.is_enabled ? '停用' : '启用'}
                            </Button>
                            <Button size="sm" variant="outline" onClick={() => deleteMutation.mutate(integration.id)} disabled={deleteMutation.isPending}>
                              <Trash2 className="mr-2 h-4 w-4" />
                              删除
                            </Button>
                          </div>
                        </div>
                      </div>
                    )
                  })
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>{editingId ? '编辑集成' : '新建集成'}</CardTitle>
                <CardDescription>密钥应来自运行时密钥服务；这里保存的是连接字段和受控配置。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="integration-name">名称</Label>
                  <Input id="integration-name" value={form.name} onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))} placeholder="例如：Jira 需求池" />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="integration-type">类型</Label>
                  <Select
                    id="integration-type"
                    value={form.provider_type}
                    onValueChange={(provider_type) => setForm((value) => ({
                      ...value,
                      provider_type,
                      config: editingId ? value.config : templateFor(provider_type),
                    }))}
                  >
                    {INTEGRATION_TYPES.map((item) => (
                      <SelectOption key={item.value} value={item.value}>{item.label}</SelectOption>
                    ))}
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="integration-config">配置 JSON</Label>
                  <textarea
                    id="integration-config"
                    className="min-h-[260px] w-full resize-none rounded-md border border-slate-200 bg-white p-3 font-mono text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                    value={form.config}
                    onChange={(event) => setForm((value) => ({ ...value, config: event.target.value }))}
                  />
                </div>
                <div data-testid="integration-config-preflight" className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm dark:border-slate-800 dark:bg-slate-900">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge className={configPreflight.isValid ? statusBadgeClass('passed') : statusBadgeClass('failed')}>
                      JSON {configPreflight.isValid ? '有效' : '无效'}
                    </Badge>
                    <Badge className={configPreflight.hasEndpoint ? statusBadgeClass('passed') : statusBadgeClass('failed')}>
                      Endpoint {configPreflight.hasEndpoint ? '已识别' : '缺失'}
                    </Badge>
                    <Badge className={configPreflight.hasAuth ? statusBadgeClass('passed') : statusBadgeClass('failed')}>
                      认证字段 {configPreflight.hasAuth ? '已识别' : '缺失'}
                    </Badge>
                  </div>
                  {configPreflight.error ? (
                    <p className="mt-2 text-rose-700 dark:text-rose-300">配置预检失败：{configPreflight.error}</p>
                  ) : (
                    <p className="mt-2 text-slate-600 dark:text-slate-300">
                      保存前已完成 JSON、连接端点和认证字段预检。连接测试与同步会继续由后端产生正式投产证据。
                    </p>
                  )}
                  {configPreflight.sensitiveKeys.length > 0 && (
                    <p className="mt-2 text-amber-700 dark:text-amber-300">
                      检测到敏感字段：{configPreflight.sensitiveKeys.join('、')}。生产密钥应来自受控密钥库，不要写入仓库或截图。
                    </p>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button onClick={() => saveMutation.mutate()} disabled={!canSaveIntegration || saveMutation.isPending}>
                    <Save className="mr-2 h-4 w-4" />
                    {saveMutation.isPending ? '保存中...' : '保存集成'}
                  </Button>
                  {editingId && <Button variant="outline" onClick={() => resetForm(form.provider_type)}>取消编辑</Button>}
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="project-sync" className="space-y-4" data-testid="integration-project-sync">
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.2fr)_440px]">
            <Card>
              <CardHeader>
                <CardTitle>项目知识同步</CardTitle>
                <CardDescription>将外部事项和页面幂等同步为项目资料、知识条目、来源证明与追溯记录。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <Select value={selectedIntegration?.id || ''} onValueChange={(value) => {
                  setSelectedId(value)
                  setSelectedBindingId(null)
                  setSyncPreview(null)
                }}>
                  {integrations.map((integration) => (
                    <SelectOption key={integration.id} value={integration.id}>{integration.name}</SelectOption>
                  ))}
                </Select>
                {bindings.length === 0 ? (
                  <div className="rounded-md border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700">
                    当前集成尚未绑定项目。创建绑定后可先预览，再执行正式同步。
                  </div>
                ) : (
                  bindings.map((binding) => (
                    <div key={binding.id} className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                        <button type="button" className="min-w-0 text-left" onClick={() => setSelectedBindingId(binding.id)}>
                          <div className="flex flex-wrap items-center gap-2">
                            <FolderSync className="h-4 w-4 text-indigo-500" />
                            <span className="font-semibold text-slate-900 dark:text-white">{binding.name}</span>
                            <Badge variant="outline">{projectsQuery.data?.items.find((project) => project.id === binding.project_id)?.name || binding.project_id}</Badge>
                            <Badge className={statusBadgeClass(binding.last_sync_status || 'pending')}>{binding.last_sync_status || '未同步'}</Badge>
                          </div>
                          <p className="mt-2 text-xs text-slate-500">最近同步：{formatTime(binding.last_synced_at)} · 游标：{String(binding.cursor_json?.updated_after || '-')}</p>
                          {binding.last_error && <p className="mt-2 text-xs text-rose-600">{binding.last_error}</p>}
                        </button>
                        <div className="flex flex-wrap gap-2">
                          <Button size="sm" variant="outline" onClick={() => previewBindingMutation.mutate(binding)} disabled={previewBindingMutation.isPending}>
                            <Eye className="mr-2 h-4 w-4" />预览
                          </Button>
                          <Button size="sm" onClick={() => syncBindingMutation.mutate(binding)} disabled={syncBindingMutation.isPending}>
                            <FolderSync className="mr-2 h-4 w-4" />同步
                          </Button>
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>新建项目绑定</CardTitle>
                <CardDescription>一个集成可以按外部范围绑定多个项目，并分别维护增量游标。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="binding-project">目标项目</Label>
                  <Select id="binding-project" value={bindingForm.projectId} onValueChange={(projectId) => setBindingForm((value) => ({ ...value, projectId }))}>
                    {(projectsQuery.data?.items || []).map((project) => <SelectOption key={project.id} value={project.id}>{project.name}</SelectOption>)}
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="binding-name">绑定名称</Label>
                  <Input id="binding-name" value={bindingForm.name} onChange={(event) => setBindingForm((value) => ({ ...value, name: event.target.value }))} placeholder="例如：Jira 需求池" />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="binding-scope">同步范围 JSON</Label>
                  <textarea id="binding-scope" className="min-h-[120px] w-full rounded-md border border-slate-200 bg-white p-3 font-mono text-xs dark:border-slate-700 dark:bg-slate-900" value={bindingForm.scope} onChange={(event) => setBindingForm((value) => ({ ...value, scope: event.target.value }))} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="binding-mapping">字段映射 JSON</Label>
                  <textarea id="binding-mapping" className="min-h-[180px] w-full rounded-md border border-slate-200 bg-white p-3 font-mono text-xs dark:border-slate-700 dark:bg-slate-900" value={bindingForm.fieldMapping} onChange={(event) => setBindingForm((value) => ({ ...value, fieldMapping: event.target.value }))} />
                </div>
                <Button onClick={() => createBindingMutation.mutate()} disabled={!selectedIntegration || createBindingMutation.isPending}>
                  <FolderSync className="mr-2 h-4 w-4" />创建项目绑定
                </Button>
              </CardContent>
            </Card>
          </div>

          {syncPreview && (
            <Card data-testid="integration-sync-preview">
              <CardHeader><CardTitle>规范化预览</CardTitle><CardDescription>共 {syncPreview.total} 条；预览不会写入项目资产。</CardDescription></CardHeader>
              <CardContent className="space-y-3">
                {syncPreview.items.map((item) => (
                  <div key={item.external_id} className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
                    <div className="flex flex-wrap items-center gap-2"><Badge variant="outline">{item.external_id}</Badge><span className="font-medium">{item.title}</span></div>
                    <p className="mt-2 line-clamp-3 text-sm text-slate-600 dark:text-slate-300">{item.content}</p>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader><CardTitle>同步运行历史</CardTitle><CardDescription>保留新增、更新、未变化、失败和重试证据。</CardDescription></CardHeader>
            <CardContent className="space-y-3">
              {(syncRunsQuery.data || []).map((run) => (
                <div key={run.id} className="flex flex-col gap-3 rounded-md border border-slate-200 p-4 dark:border-slate-800 lg:flex-row lg:items-center lg:justify-between">
                  <div>
                    <div className="flex flex-wrap items-center gap-2"><Badge className={statusBadgeClass(run.status)}>{run.status}</Badge><span className="text-sm">{formatTime(run.started_at)}</span></div>
                    <p className="mt-2 text-sm text-slate-500">新增 {run.created_count} · 更新 {run.updated_count} · 未变化 {run.unchanged_count} · 失败 {run.failed_count}</p>
                  </div>
                  {(run.status === 'failed' || run.status === 'partial') && (
                    <Button size="sm" variant="outline" onClick={() => retryRunMutation.mutate(run)} disabled={retryRunMutation.isPending}><RotateCcw className="mr-2 h-4 w-4" />重试</Button>
                  )}
                </div>
              ))}
              {!selectedBinding && <p className="py-6 text-center text-sm text-slate-500">选择项目绑定后查看同步历史。</p>}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="webhooks" className="space-y-4">
          <Card>
            <CardHeader>
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <CardTitle>Webhook 订阅</CardTitle>
                  <CardDescription>为选中的集成维护回调订阅和事件范围。</CardDescription>
                </div>
                <Select value={selectedIntegration?.id || ''} onValueChange={setSelectedId}>
                  {integrations.map((integration) => (
                    <SelectOption key={integration.id} value={integration.id}>{integration.name}</SelectOption>
                  ))}
                </Select>
              </div>
            </CardHeader>
            <CardContent className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
              <div className="space-y-3">
                {webhooks.length === 0 ? (
                  <div className="rounded-md border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700">
                    当前集成暂无 Webhook 订阅。
                  </div>
                ) : (
                  webhooks.map((webhook) => (
                    <div key={webhook.id} className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                        <div>
                          <p className="break-all font-medium text-slate-900 dark:text-white">{webhook.url}</p>
                          <div className="mt-2 flex flex-wrap gap-2">
                            <Badge variant={webhook.is_active ? 'secondary' : 'destructive'}>{webhook.is_active ? '启用' : '停用'}</Badge>
                            {webhook.events.map((event) => <Badge key={event} variant="outline">{event}</Badge>)}
                          </div>
                        </div>
                        <Button size="sm" variant="outline" onClick={() => deleteWebhookMutation.mutate(webhook)}>
                          <Trash2 className="mr-2 h-4 w-4" />
                          删除
                        </Button>
                      </div>
                    </div>
                  ))
                )}
              </div>
              <div className="space-y-4 rounded-md border border-slate-200 p-4 dark:border-slate-800">
                <div className="flex items-center gap-2 font-medium">
                  <Webhook className="h-4 w-4" />
                  新建 Webhook
                </div>
                <div className="space-y-2">
                  <Label htmlFor="webhook-url">URL</Label>
                  <Input id="webhook-url" value={webhookForm.url} onChange={(event) => setWebhookForm((value) => ({ ...value, url: event.target.value }))} placeholder="https://example.com/webhook/amx" />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="webhook-events">事件</Label>
                  <Input id="webhook-events" value={webhookForm.events} onChange={(event) => setWebhookForm((value) => ({ ...value, events: event.target.value }))} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="webhook-secret">签名密钥</Label>
                  <Input id="webhook-secret" value={webhookForm.secret} onChange={(event) => setWebhookForm((value) => ({ ...value, secret: event.target.value }))} placeholder="可选" />
                </div>
                <Button onClick={() => createWebhookMutation.mutate()} disabled={!selectedIntegration || !webhookForm.url.trim() || createWebhookMutation.isPending}>
                  创建 Webhook
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="outbox" className="space-y-4">
          <Card>
            <CardHeader>
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <CardTitle>Outbox 事件</CardTitle>
                  <CardDescription>查看待发布/已发布的外发事件，并手动触发一次发布批次。</CardDescription>
                </div>
                <Button onClick={() => publishOutboxMutation.mutate()} disabled={publishOutboxMutation.isPending}>
                  <Activity className="mr-2 h-4 w-4" />
                  发布批次
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {outboxEvents.length === 0 ? (
                <div className="rounded-md border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700">
                  暂无 Outbox 事件。
                </div>
              ) : (
                outboxEvents.map((event: OutboxEvent) => (
                  <div key={event.id} className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant={event.published ? 'secondary' : 'outline'}>{event.published ? '已发布' : '待发布'}</Badge>
                          <p className="font-medium text-slate-900 dark:text-white">{event.event_type}</p>
                          <span className="text-sm text-slate-500">{event.aggregate_type}</span>
                        </div>
                        <p className="mt-2 text-xs text-slate-500">创建：{formatTime(event.created_at)} · 发布：{formatTime(event.published_at)}</p>
                      </div>
                      <Button variant="outline" size="sm" onClick={() => copyEndpoint(JSON.stringify(event.payload, null, 2))}>
                        {copiedId === JSON.stringify(event.payload, null, 2) ? <CheckCircle2 className="mr-2 h-4 w-4" /> : <Copy className="mr-2 h-4 w-4" />}
                        Payload
                      </Button>
                    </div>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="evidence" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>投产证据矩阵</CardTitle>
              <CardDescription>用于判断外部系统集成是否已达到生产可用，而不是只有配置草稿。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {integrations.map((integration) => {
                const readiness = integrationReadiness(integration)
                const passed = readiness.score >= 100
                return (
                  <div key={integration.id} className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                      <div>
                        <p className="font-semibold text-slate-900 dark:text-white">{integration.name}</p>
                        <p className="mt-1 text-sm text-slate-500">生产证据评分 {readiness.score} · {readiness.label}</p>
                      </div>
                      <Badge className={passed ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-100' : 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-100'}>
                        {passed ? '可投产' : '待补证'}
                      </Badge>
                    </div>
                    <div className="mt-3 grid gap-2 text-sm md:grid-cols-4">
                      <div className="rounded bg-slate-50 p-3 dark:bg-slate-900">
                        <p className="font-medium">启用状态</p>
                        <p className="mt-1 text-slate-500">{integration.is_enabled ? '已启用' : '已停用'}</p>
                      </div>
                      <div className="rounded bg-slate-50 p-3 dark:bg-slate-900">
                        <p className="font-medium">连接端点</p>
                        <p className="mt-1 text-slate-500">{hasEndpoint(integration) ? '已配置' : '缺失'}</p>
                      </div>
                      <div className="rounded bg-slate-50 p-3 dark:bg-slate-900">
                        <p className="font-medium">认证字段</p>
                        <p className="mt-1 text-slate-500">{hasAuth(integration) ? '已配置' : '缺失'}</p>
                      </div>
                      <div className="rounded bg-slate-50 p-3 dark:bg-slate-900">
                        <p className="font-medium">同步证据</p>
                        <p className="mt-1 text-slate-500">{integration.last_sync_at ? formatTime(integration.last_sync_at) : '缺失'}</p>
                      </div>
                    </div>
                  </div>
                )
              })}
              {integrations.length === 0 && (
                <div className="rounded-md border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700">
                  暂无集成证据。请先创建集成并执行连接测试与同步。
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <div className="rounded-md border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
        <div className="flex items-start gap-2">
          {integrations.some((item) => integrationReadiness(item).score < 100) ? (
            <XCircle className="mt-0.5 h-4 w-4 text-amber-500" />
          ) : (
            <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-500" />
          )}
          <p>
            生产投产要求：至少一个启用集成具备 endpoint、认证字段，并通过连接测试或同步产生证据。测试响应会遮蔽敏感字段，密钥不要提交到仓库。
          </p>
        </div>
      </div>
    </div>
  )
}
