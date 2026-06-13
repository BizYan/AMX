'use client'

import Link from 'next/link'
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  CloudCog,
  DatabaseZap,
  Link2,
  Play,
  Plus,
  RefreshCw,
  Send,
  Webhook,
} from 'lucide-react'

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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useToast } from '@/components/ui/toast'
import {
  integrationsApi,
  projectsApi,
  type IntegrationProvider,
  type IntegrationSyncPreview,
} from '@/lib/api-client'

const statusLabel: Record<string, string> = {
  healthy: '生产可用',
  ready: '已就绪',
  degraded: '需处理',
  blocked: '阻塞',
  connected: '连接成功',
  unconfigured: '未配置',
  disabled: '已停用',
  unreachable: '不可达',
}

const providerLabels: Record<string, string> = {
  zentao: '禅道',
  jira: 'Jira',
  confluence: 'Confluence',
  gitnexus: 'GitNexus',
  custom: '自定义',
}

const evidenceLabels: Record<string, string> = {
  integration_count: '集成总数',
  enabled_integration_count: '已启用',
  configured_integration_count: '已配置',
  synced_integration_count: '已同步',
  webhook_count: 'Webhook',
  active_webhook_count: '活跃 Webhook',
  successful_delivery_count: '成功投递',
  failed_delivery_count: '失败投递',
  pending_outbox_count: '待发布事件',
  failed_outbox_count: '失败事件',
  project_binding_count: '项目绑定',
  completed_project_sync_count: '项目同步',
  synced_asset_count: '同步资产',
}

function formatStatus(status?: string | null) {
  if (!status) return '无记录'
  return statusLabel[status] || status
}

function providerLabel(providerType: string) {
  return providerLabels[providerType] || providerType
}

function isConfigured(integration: IntegrationProvider) {
  const config = integration.config_json || {}
  return Boolean(config.base_url && config.api_key)
}

export default function IntegrationsPage() {
  const queryClient = useQueryClient()
  const { addToast } = useToast()
  const [selectedIntegrationId, setSelectedIntegrationId] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [actionResult, setActionResult] = useState('')
  const [preview, setPreview] = useState<IntegrationSyncPreview | null>(null)
  const [form, setForm] = useState({
    name: '',
    provider_type: 'zentao',
    base_url: '',
    api_key: '',
  })

  const integrationsQuery = useQuery({
    queryKey: ['integrations'],
    queryFn: () => integrationsApi.list({ page: 1, pageSize: 50 }),
  })
  const summaryQuery = useQuery({
    queryKey: ['integrations', 'operations-summary'],
    queryFn: integrationsApi.getOperationsSummary,
  })
  const commandCenterQuery = useQuery({
    queryKey: ['integrations', 'production-command-center'],
    queryFn: integrationsApi.getProductionCommandCenter,
  })
  const incidentQueueQuery = useQuery({
    queryKey: ['integrations', 'incident-queue'],
    queryFn: integrationsApi.getIncidentQueue,
  })
  const projectsQuery = useQuery({
    queryKey: ['projects', 'integration-binding-options'],
    queryFn: () => projectsApi.list({ page: 1, pageSize: 20 }),
  })

  const integrations = useMemo(() => integrationsQuery.data?.items || [], [integrationsQuery.data?.items])
  const selectedIntegration = useMemo(
    () => integrations.find((item) => item.id === selectedIntegrationId) || integrations[0],
    [integrations, selectedIntegrationId],
  )
  const selectedId = selectedIntegration?.id

  const bindingsQuery = useQuery({
    queryKey: ['integrations', selectedId, 'project-bindings'],
    queryFn: () => integrationsApi.listProjectBindings(selectedId as string),
    enabled: Boolean(selectedId),
  })
  const webhooksQuery = useQuery({
    queryKey: ['integrations', selectedId, 'webhooks'],
    queryFn: () => integrationsApi.listWebhooks(selectedId as string, { page: 1, pageSize: 30 }),
    enabled: Boolean(selectedId),
  })
  const outboxQuery = useQuery({
    queryKey: ['integrations', 'outbox'],
    queryFn: () => integrationsApi.listOutboxEvents({ page: 1, pageSize: 20 }),
  })

  const createMutation = useMutation({
    mutationFn: () => integrationsApi.create({
      name: form.name,
      provider_type: form.provider_type,
      is_enabled: true,
      config_json: {
        base_url: form.base_url,
        api_key: form.api_key,
        health_path: '/health',
      },
    }),
    onSuccess: async (integration) => {
      setActionResult(`集成已创建：${integration.name}`)
      setSelectedIntegrationId(integration.id)
      setCreateOpen(false)
      setForm({ name: '', provider_type: 'zentao', base_url: '', api_key: '' })
      await queryClient.invalidateQueries({ queryKey: ['integrations'] })
      await queryClient.invalidateQueries({ queryKey: ['integrations', 'production-command-center'] })
      addToast({ title: '集成已创建', description: integration.name })
    },
  })

  const testMutation = useMutation({
    mutationFn: (id: string) => integrationsApi.test(id),
    onSuccess: (result) => {
      setActionResult(`${formatStatus(result.status)}：${result.message}`)
      queryClient.invalidateQueries({ queryKey: ['integrations', 'production-command-center'] })
    },
  })

  const syncMutation = useMutation({
    mutationFn: (id: string) => integrationsApi.sync(id),
    onSuccess: async (result) => {
      setActionResult(result.success ? `同步完成：${result.message}` : `同步未完成：${result.message}`)
      await queryClient.invalidateQueries({ queryKey: ['integrations'] })
      await queryClient.invalidateQueries({ queryKey: ['integrations', 'production-command-center'] })
    },
  })

  const previewMutation = useMutation({
    mutationFn: (bindingId: string) => integrationsApi.previewProjectBinding(bindingId, 10),
    onSuccess: (result) => {
      setPreview(result)
      setActionResult(`预览完成：发现 ${result.total} 条候选资产`)
    },
  })

  const bindingSyncMutation = useMutation({
    mutationFn: (bindingId: string) => integrationsApi.syncProjectBinding(bindingId),
    onSuccess: async (result) => {
      setActionResult(`项目同步完成：新增 ${result.created_count}，更新 ${result.updated_count}，失败 ${result.failed_count}`)
      await queryClient.invalidateQueries({ queryKey: ['integrations', selectedId, 'project-bindings'] })
      await queryClient.invalidateQueries({ queryKey: ['integrations', 'production-command-center'] })
    },
  })

  const outboxMutation = useMutation({
    mutationFn: () => integrationsApi.publishOutbox(20),
    onSuccess: async (result) => {
      setActionResult(`已发布 ${result.published} 个事件，失败 ${result.failed}`)
      await queryClient.invalidateQueries({ queryKey: ['integrations', 'outbox'] })
      await queryClient.invalidateQueries({ queryKey: ['integrations', 'operations-summary'] })
      await queryClient.invalidateQueries({ queryKey: ['integrations', 'production-command-center'] })
    },
  })

  const incidentRetryMutation = useMutation({
    mutationFn: (incident: { id: string; action_type: string }) => {
      if (incident.action_type === 'retry_sync') return integrationsApi.retryProjectBindingRun(incident.id)
      if (incident.action_type === 'retry_webhook') return integrationsApi.retryWebhookDelivery(incident.id)
      return integrationsApi.retryOutboxEvent(incident.id)
    },
    onSuccess: async () => {
      setActionResult('失败任务已重试或重新进入发布队列。')
      await queryClient.invalidateQueries({ queryKey: ['integrations', 'incident-queue'] })
      await queryClient.invalidateQueries({ queryKey: ['integrations', 'production-command-center'] })
      await queryClient.invalidateQueries({ queryKey: ['integrations', 'operations-summary'] })
      await queryClient.invalidateQueries({ queryKey: ['integrations', 'outbox'] })
    },
  })

  const summary = summaryQuery.data
  const evidence = summary?.evidence || {}
  const bindings = bindingsQuery.data || []
  const webhooks = webhooksQuery.data?.items || []
  const outboxEvents = outboxQuery.data?.items || []
  const incidents = incidentQueueQuery.data?.items || []

  return (
    <main data-testid="integration-operations-center" className="space-y-6 p-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p className="text-sm text-slate-500">首页 / 集成中心</p>
          <h1 className="mt-2 text-3xl font-semibold text-slate-950 dark:text-white">集成中心</h1>
          <p className="mt-2 text-slate-500">管理外部系统接入、项目资料同步、Webhook 投递和 Outbox 发布证据。</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => {
            queryClient.invalidateQueries({ queryKey: ['integrations'] })
            queryClient.invalidateQueries({ queryKey: ['integrations', 'operations-summary'] })
            queryClient.invalidateQueries({ queryKey: ['integrations', 'production-command-center'] })
          }}>
            <RefreshCw className="mr-2 h-4 w-4" />
            刷新
          </Button>
          <Button data-testid="integration-open-create" onClick={() => setCreateOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            新建集成
          </Button>
        </div>
      </div>

      {commandCenterQuery.data ? (
        <section
          data-testid="integration-production-command-center"
          className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950/40"
        >
          <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-3">
                <h2 className="text-lg font-semibold text-slate-950 dark:text-white">生产联调指挥台</h2>
                <Badge
                  data-testid="integration-release-gate"
                  variant={
                    commandCenterQuery.data.release_gate.status === 'blocked'
                      ? 'destructive'
                      : commandCenterQuery.data.release_gate.status === 'passed'
                        ? 'default'
                        : 'secondary'
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
                  ['评分', commandCenterQuery.data.summary.score ?? 0],
                  ['已配置', commandCenterQuery.data.summary.configured_integration_count ?? 0],
                  ['已同步', commandCenterQuery.data.summary.synced_integration_count ?? 0],
                  ['项目绑定', commandCenterQuery.data.summary.project_binding_count ?? 0],
                  ['项目同步', commandCenterQuery.data.summary.completed_project_sync_count ?? 0],
                  ['同步资产', commandCenterQuery.data.summary.synced_asset_count ?? 0],
                  ['Webhook 失败', commandCenterQuery.data.summary.failed_delivery_count ?? 0],
                  ['Outbox 待发', commandCenterQuery.data.summary.pending_outbox_count ?? 0],
                ].map(([label, value]) => (
                  <div key={label as string} className="border-b border-slate-200 pb-2 dark:border-slate-800">
                    <p className="text-lg font-semibold text-slate-950 dark:text-white">{value}</p>
                    <p className="text-xs text-slate-500">{label}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="grid shrink-0 gap-2 sm:grid-cols-2 xl:w-[520px]">
              {commandCenterQuery.data.priority_actions.map((action) => (
                <Button key={action.code} asChild variant={action.priority === 'critical' ? 'destructive' : 'outline'}>
                  <Link href={action.href}>
                    <Play className="mr-2 h-4 w-4" />
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
                    <p className="font-medium text-slate-950 dark:text-white">{risk.title}</p>
                    <p className="mt-1 text-sm text-slate-500">{risk.detail}</p>
                  </div>
                  <Badge variant={risk.severity === 'critical' || risk.severity === 'high' ? 'destructive' : 'secondary'}>
                    {risk.count}
                  </Badge>
                </div>
              </Link>
            ))}
            {commandCenterQuery.data.risk_items.length === 0 ? (
              <div className="rounded-md border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-slate-700">
                当前没有外部集成生产联调风险。
              </div>
            ) : null}
          </div>
        </section>
      ) : null}

      <section className="grid gap-4 lg:grid-cols-[1.2fr_2fr]">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="h-5 w-5 text-indigo-500" />
              生产状态
            </CardTitle>
            <CardDescription>{summary?.summary || '正在读取集成运行证据。'}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-end justify-between">
              <div>
                <p className="text-sm text-slate-500">就绪评分</p>
                <p data-testid="integration-summary-score" className="text-4xl font-semibold text-slate-950 dark:text-white">
                  {summary?.score ?? '--'}
                </p>
              </div>
              <Badge variant={summary?.status === 'healthy' ? 'default' : 'secondary'}>
                {formatStatus(summary?.status)}
              </Badge>
            </div>
            <div className="grid grid-cols-2 gap-3">
              {Object.entries(evidenceLabels).map(([key, label]) => (
                <div key={key} className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
                  <p className="text-xs text-slate-500">{label}</p>
                  <p data-testid={`integration-evidence-${key}`} className="mt-1 text-lg font-semibold text-slate-950 dark:text-white">
                    {Number((evidence as Record<string, number | undefined>)[key] ?? 0)}
                  </p>
                </div>
              ))}
            </div>
            {(summary?.blockers || []).length > 0 && (
              <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
                <div className="mb-2 flex items-center gap-2 font-medium">
                  <AlertTriangle className="h-4 w-4" />
                  阻塞项
                </div>
                <ul className="space-y-1">
                  {summary?.blockers.map((item) => <li key={item}>{item}</li>)}
                </ul>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CloudCog className="h-5 w-5 text-indigo-500" />
              集成清单
            </CardTitle>
            <CardDescription>连接测试、同步和项目绑定从这里发起，所有动作返回可见结果。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {integrations.map((integration) => (
              <div
                key={integration.id}
                className="grid gap-3 rounded-md border border-slate-200 p-4 dark:border-slate-800 lg:grid-cols-[1fr_auto]"
              >
                <button
                  type="button"
                  data-testid={`integration-select-${integration.id}`}
                  className="text-left"
                  onClick={() => {
                    setSelectedIntegrationId(integration.id)
                    setPreview(null)
                  }}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-medium text-slate-950 dark:text-white">{integration.name}</p>
                    <Badge variant={integration.is_enabled ? 'default' : 'secondary'}>
                      {integration.is_enabled ? '已启用' : '已停用'}
                    </Badge>
                    <Badge variant={isConfigured(integration) ? 'secondary' : 'destructive'}>
                      {isConfigured(integration) ? '配置完整' : '缺少凭据'}
                    </Badge>
                  </div>
                  <p className="mt-1 text-sm text-slate-500">
                    {providerLabel(integration.provider_type)} · {integration.config_json?.base_url || '未配置服务地址'}
                  </p>
                </button>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    data-testid={`integration-test-${integration.id}`}
                    variant="outline"
                    onClick={() => testMutation.mutate(integration.id)}
                  >
                    <Play className="mr-2 h-4 w-4" />
                    测试
                  </Button>
                  <Button
                    data-testid={`integration-sync-${integration.id}`}
                    variant="outline"
                    onClick={() => syncMutation.mutate(integration.id)}
                  >
                    <RefreshCw className="mr-2 h-4 w-4" />
                    同步
                  </Button>
                </div>
              </div>
            ))}
            {integrations.length === 0 && (
              <div className="rounded-md border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">
                暂无外部集成。先创建禅道、Jira、Confluence 或自定义连接。
              </div>
            )}
          </CardContent>
        </Card>
      </section>

      {actionResult && (
        <div data-testid="integration-action-result" className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-100">
          {actionResult}
        </div>
      )}

      <Tabs defaultValue="incidents">
        <TabsList>
          <TabsTrigger value="incidents">失败处置</TabsTrigger>
          <TabsTrigger value="bindings">项目同步</TabsTrigger>
          <TabsTrigger value="webhooks">Webhook</TabsTrigger>
          <TabsTrigger value="outbox">Outbox</TabsTrigger>
        </TabsList>

        <TabsContent value="incidents">
          <Card data-testid="integration-incident-queue">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <AlertTriangle className="h-5 w-5 text-red-500" />
                生产失败处置队列
              </CardTitle>
              <CardDescription>
                汇总项目同步、Webhook 和 Outbox 失败，支持按失败证据直接重试。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-3 gap-3 text-sm">
                <div><p className="text-slate-500">失败总数</p><p className="text-xl font-semibold">{incidentQueueQuery.data?.total ?? 0}</p></div>
                <div><p className="text-slate-500">严重阻塞</p><p className="text-xl font-semibold">{incidentQueueQuery.data?.critical_count ?? 0}</p></div>
                <div><p className="text-slate-500">可重试</p><p className="text-xl font-semibold">{incidentQueueQuery.data?.retryable_count ?? 0}</p></div>
              </div>
              {incidents.map((incident) => (
                <div key={`${incident.category}-${incident.id}`} className="flex flex-col gap-3 rounded-md border border-slate-200 p-4 dark:border-slate-800 md:flex-row md:items-center md:justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <p className="font-medium text-slate-950 dark:text-white">{incident.title}</p>
                      <Badge variant={incident.severity === 'critical' ? 'destructive' : 'secondary'}>{incident.category}</Badge>
                    </div>
                    <p className="mt-1 text-sm text-slate-500">{incident.detail}</p>
                    <p className="mt-1 text-xs text-slate-400">尝试 {incident.attempts} 次 · {incident.occurred_at}</p>
                  </div>
                  <Button data-testid={`retry-incident-${incident.id}`} variant="outline" onClick={() => incidentRetryMutation.mutate(incident)}>
                    <RefreshCw className="mr-2 h-4 w-4" />
                    重试
                  </Button>
                </div>
              ))}
              {!incidents.length && <p className="py-8 text-center text-sm text-slate-500">当前没有需要处置的外部集成失败。</p>}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="bindings">
          <Card data-testid="integration-binding-panel">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Link2 className="h-5 w-5 text-indigo-500" />
                项目绑定与同步
              </CardTitle>
              <CardDescription>
                当前集成：{selectedIntegration?.name || '未选择'}；可预览外部事项并同步为项目资料和知识资产。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="text-sm text-slate-500">
                可绑定项目：{projectsQuery.data?.items?.map((project) => project.name).join('、') || '暂无项目'}
              </div>
              {bindings.map((binding) => (
                <div key={binding.id} className="grid gap-3 rounded-md border border-slate-200 p-4 dark:border-slate-800 lg:grid-cols-[1fr_auto]">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-medium text-slate-950 dark:text-white">{binding.name}</p>
                      <Badge variant={binding.is_enabled ? 'default' : 'secondary'}>{binding.is_enabled ? '已启用' : '已停用'}</Badge>
                      <Badge variant={binding.last_sync_status === 'completed' ? 'secondary' : 'outline'}>
                        {formatStatus(binding.last_sync_status)}
                      </Badge>
                    </div>
                    <p className="mt-1 text-sm text-slate-500">
                      项目 {binding.project_id} · 最近同步 {binding.last_synced_at || '无记录'}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      data-testid={`integration-preview-${binding.id}`}
                      variant="outline"
                      onClick={() => previewMutation.mutate(binding.id)}
                    >
                      <DatabaseZap className="mr-2 h-4 w-4" />
                      预览
                    </Button>
                    <Button
                      data-testid={`integration-sync-${binding.id}`}
                      onClick={() => bindingSyncMutation.mutate(binding.id)}
                    >
                      <RefreshCw className="mr-2 h-4 w-4" />
                      同步到项目
                    </Button>
                  </div>
                </div>
              ))}
              {preview && (
                <div data-testid="integration-preview-panel" className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                  <p className="font-medium text-slate-950 dark:text-white">同步预览</p>
                  <div className="mt-3 grid gap-2">
                    {preview.items.map((item) => (
                      <div key={item.external_id} className="rounded-md bg-slate-50 p-3 text-sm dark:bg-slate-900">
                        <p className="font-medium">{item.title}</p>
                        <p className="mt-1 text-slate-500">{item.content}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="webhooks">
          <Card data-testid="integration-webhook-panel">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Webhook className="h-5 w-5 text-indigo-500" />
                Webhook 投递
              </CardTitle>
              <CardDescription>展示当前集成的回调订阅和启用状态。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {webhooks.map((webhook) => (
                <div key={webhook.id} className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="font-medium text-slate-950 dark:text-white">
                        {webhook.events.includes('delivery.ready') ? '交付系统 Webhook' : 'Webhook 订阅'}
                      </p>
                      <p className="mt-1 text-sm text-slate-500">{webhook.url}</p>
                    </div>
                    <Badge variant={webhook.is_active ? 'default' : 'secondary'}>
                      {webhook.is_active ? '活跃' : '停用'}
                    </Badge>
                  </div>
                  <p className="mt-2 text-sm text-slate-500">{webhook.events.join('、') || '未配置事件'}</p>
                </div>
              ))}
              {webhooks.length === 0 && <p className="text-sm text-slate-500">暂无 Webhook 订阅。</p>}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="outbox">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Send className="h-5 w-5 text-indigo-500" />
                Outbox 发布
              </CardTitle>
              <CardDescription>发布待投递事件，避免外部系统与 AMX 状态漂移。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <Button data-testid="integration-publish-outbox" onClick={() => outboxMutation.mutate()}>
                <Send className="mr-2 h-4 w-4" />
                发布待处理事件
              </Button>
              {outboxEvents.map((event) => (
                <div key={event.id} className="rounded-md border border-slate-200 p-4 text-sm dark:border-slate-800">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-medium text-slate-950 dark:text-white">{event.event_type}</p>
                    <Badge variant={event.published ? 'secondary' : 'outline'}>
                      {event.published ? '已发布' : '待发布'}
                    </Badge>
                  </div>
                  <p className="mt-1 text-slate-500">{event.aggregate_type} · {event.aggregate_id}</p>
                </div>
              ))}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新建外部集成</DialogTitle>
            <DialogDescription>保存服务地址和凭据后，可立即测试连接并绑定项目同步。</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="integration-name">名称</Label>
              <Input
                id="integration-name"
                data-testid="integration-create-name"
                value={form.name}
                onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))}
                placeholder="例如：禅道需求同步"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="integration-provider">类型</Label>
              <Input
                id="integration-provider"
                data-testid="integration-create-provider"
                value={form.provider_type}
                onChange={(event) => setForm((value) => ({ ...value, provider_type: event.target.value }))}
                placeholder="zentao / jira / confluence / custom"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="integration-base-url">服务地址</Label>
              <Input
                id="integration-base-url"
                data-testid="integration-create-base-url"
                value={form.base_url}
                onChange={(event) => setForm((value) => ({ ...value, base_url: event.target.value }))}
                placeholder="https://example.com"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="integration-api-key">服务 Key</Label>
              <Input
                id="integration-api-key"
                data-testid="integration-create-api-key"
                value={form.api_key}
                onChange={(event) => setForm((value) => ({ ...value, api_key: event.target.value }))}
                placeholder="由外部系统签发"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>取消</Button>
            <Button
              data-testid="integration-submit-create"
              onClick={() => createMutation.mutate()}
              disabled={!form.name || !form.provider_type || !form.base_url || !form.api_key || createMutation.isPending}
            >
              <CheckCircle2 className="mr-2 h-4 w-4" />
              保存集成
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </main>
  )
}
