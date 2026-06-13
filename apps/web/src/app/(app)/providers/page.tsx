'use client'

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Pause,
  Play,
  Plus,
  RefreshCw,
  ServerCog,
  Settings,
  ShieldAlert,
  Trash2,
  Zap,
} from 'lucide-react'
import { providersApi, Provider, ProviderTestResult, opsApi, CircuitBreaker, type ProviderReadinessSummary, type ProviderTestRequest } from '@/lib/api-client'
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
import { useToast } from '@/components/ui/toast'

type ProviderHealthStatus = 'healthy' | 'degraded' | 'unhealthy'
type ProviderTestState = 'passed' | 'failed' | 'fallback'

type ProviderOpsProfile = {
  health?: ProviderHealthStatus
  latency_ms?: number | null
  last_test_at?: string | null
  last_test_result?: ProviderTestState | null
  risk?: string | null
  quota_impact?: string | null
  sandbox_fallback?: boolean | null
}

type ProviderWithOps = Provider & {
  provider_type?: string
  status?: string
  ops_profile?: ProviderOpsProfile
}

type ProviderRow = {
  provider: ProviderWithOps
  normalizedType: string
  typeLabel: string
  breaker?: CircuitBreaker
  health: ProviderHealthStatus
  testState: ProviderTestState
  latencyMs: number | null
  risk: string
  quotaImpact: string
  sandboxFallback: boolean
  latestTest?: ProviderTestResult
}

const PROVIDER_TYPES = [
  { value: 'llm', label: 'LLM 模型供应商' },
  { value: 'graphify', label: 'Graphify 图谱服务' },
  { value: 'gitnexus', label: 'GitNexus 代码索引' },
  { value: 'custom', label: '自定义能力服务' },
]

const PROVIDER_CONFIG_TEMPLATES: Record<string, Record<string, unknown>> = {
  llm: {
    api_key: "",
    base_url: "https://api.example.com/v1",
    model: "production-model",
    mode: "production",
  },
  graphify: {
    service_key: "",
    base_url: "https://graphify.example.com",
    health_path: "/health",
    mode: "production",
  },
  gitnexus: {
    service_key: "",
    endpoint: "https://gitnexus.example.com",
    base_url: "https://gitnexus.example.com",
    health_path: "/api/health",
    repo_url: "https://github.com/org/repo",
    mode: "production",
  },
  custom: {
    api_key: "",
    base_url: "https://api.example.com",
    health_path: "/health",
    mode: "production",
  },
}

function providerConfigTemplate(type: string) {
  return JSON.stringify(PROVIDER_CONFIG_TEMPLATES[type] || PROVIDER_CONFIG_TEMPLATES.custom, null, 2)
}

const HEALTH_LABELS: Record<ProviderHealthStatus, string> = {
  healthy: '健康',
  degraded: '降级',
  unhealthy: '异常',
}

const TEST_LABELS: Record<ProviderTestState, string> = {
  passed: '通过',
  failed: '失败',
  fallback: 'Fallback 接管',
}

const BREAKER_LABELS: Record<string, string> = {
  closed: '关闭',
  half_open: '半开',
  open: '打开',
}

const READINESS_LABELS: Record<string, string> = {
  ready: '生产就绪',
  sandbox: '沙箱配置',
  unconfigured: '未配置',
  inactive: '未启用',
  missing: '缺失',
}

function normalizeProviderType(provider: ProviderWithOps) {
  const rawType = String(provider.type || provider.provider_type || '').toLowerCase()
  const name = provider.name.toLowerCase()

  if (rawType.includes('gitnexus') || name.includes('gitnexus')) return 'gitnexus'
  if (rawType.includes('graphify') || name.includes('graphify')) return 'graphify'
  if (rawType.includes('llm') || rawType.includes('openai') || name.includes('llm') || name.includes('openai')) return 'llm'
  return rawType || 'custom'
}

function getProviderTypeLabel(type: string) {
  return PROVIDER_TYPES.find((item) => item.value === type)?.label || '自定义能力服务'
}

function findBreaker(provider: ProviderWithOps, breakers: CircuitBreaker[]) {
  const type = normalizeProviderType(provider)
  const name = provider.name.toLowerCase()

  return breakers.find((breaker) => {
    const breakerName = breaker.name.toLowerCase()
    const capabilityName = breakerName.replace('-service-breaker', '')
    return breakerName.includes(type) || name.includes(capabilityName)
  })
}

function resolveHealth(provider: ProviderWithOps, breaker?: CircuitBreaker): ProviderHealthStatus {
  if (provider.ops_profile?.health) return provider.ops_profile.health
  if (breaker?.state === 'open') return 'unhealthy'
  if (breaker?.state === 'half_open') return 'degraded'
  return provider.isActive ? 'healthy' : 'unhealthy'
}

function resolveTestState(provider: ProviderWithOps, health: ProviderHealthStatus, latestTest?: ProviderTestResult): ProviderTestState {
  if (latestTest?.sandbox_fallback) return 'fallback'
  if (latestTest) return latestTest.success ? 'passed' : 'failed'
  if (provider.ops_profile?.last_test_result) return provider.ops_profile.last_test_result
  if (health === 'healthy') return 'passed'
  if (health === 'degraded') return 'fallback'
  return 'failed'
}

function formatDateTime(value?: string | null) {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function healthBadgeClass(status: ProviderHealthStatus) {
  if (status === 'healthy') return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-100'
  if (status === 'degraded') return 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-100'
  return 'bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-100'
}

function breakerBadgeClass(state?: string) {
  if (state === 'open') return 'bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-100'
  if (state === 'half_open') return 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-100'
  return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-100'
}

function parseConfig(raw: string) {
  return JSON.parse(raw || '{}') as Record<string, unknown>
}

function stringConfigValue(config: Record<string, any>, keys: string[]) {
  for (const key of keys) {
    const value = config[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return undefined
}

function buildProviderTestRequest(row: ProviderRow): ProviderTestRequest {
  const config = row.provider.config || {}

  if (row.normalizedType === 'gitnexus') {
    const repository = stringConfigValue(config, ['repository', 'repository_full_name']) || 'BizYan/AMX'
    const repoUrl = stringConfigValue(config, ['repo_url', 'repository_url']) || `https://github.com/${repository}`
    return {
      capability_type: 'health',
      params: { repo_url: repoUrl, limit: 5 },
      allow_sandbox: false,
    }
  }

  if (row.normalizedType === 'graphify') {
    return {
      capability_type: 'graph_query',
      params: {
        document_id: 'provider-smoke-test',
        content: 'Provider smoke test for production readiness.',
      },
      allow_sandbox: false,
    }
  }

  return {
    capability_type: 'text_generation',
    params: {},
    allow_sandbox: false,
  }
}

export default function ProvidersPage() {
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [selectedProvider, setSelectedProvider] = useState<ProviderWithOps | null>(null)
  const [createForm, setCreateForm] = useState({
    name: '',
    type: 'llm',
    config: providerConfigTemplate('llm'),
  })
  const [editForm, setEditForm] = useState({ name: '', config: '{}' })
  const [testResults, setTestResults] = useState<Record<string, ProviderTestResult>>({})
  const [actionNotice, setActionNotice] = useState<string | null>(null)

  const queryClient = useQueryClient()
  const { addToast } = useToast()

  const { data: providersResponse, isLoading: providersLoading } = useQuery({
    queryKey: ['providers'],
    queryFn: () => providersApi.list({ pageSize: 100 }),
  })

  const { data: circuitBreakerResponse, isLoading: breakersLoading } = useQuery({
    queryKey: ['circuit-breakers'],
    queryFn: () => opsApi.listCircuitBreakers(),
  })

  const { data: readinessResponse, isLoading: readinessLoading } = useQuery<ProviderReadinessSummary>({
    queryKey: ['provider-production-readiness'],
    queryFn: () => providersApi.readiness(),
  })

  const providers = useMemo(() => (providersResponse?.items || []) as ProviderWithOps[], [providersResponse?.items])
  const breakers = useMemo(() => circuitBreakerResponse?.breakers || [], [circuitBreakerResponse?.breakers])

  const providerRows = useMemo<ProviderRow[]>(() => providers.map((provider) => {
    const normalizedType = normalizeProviderType(provider)
    const breaker = findBreaker(provider, breakers)
    const health = resolveHealth(provider, breaker)
    const latestTest = testResults[provider.id]
    const testState = resolveTestState(provider, health, latestTest)
    const sandboxFallback = Boolean(latestTest?.sandbox_fallback || provider.ops_profile?.sandbox_fallback || testState === 'fallback')

    return {
      provider,
      normalizedType,
      typeLabel: getProviderTypeLabel(normalizedType),
      breaker,
      health,
      testState,
      latencyMs: latestTest?.latency_ms ?? provider.ops_profile?.latency_ms ?? null,
      risk: provider.ops_profile?.risk || (health === 'healthy'
        ? '调用稳定，错误率低于运营阈值。'
        : '能力链路存在异常，调度、重试和人工兜底成本会上升。'),
      quotaImpact: provider.ops_profile?.quota_impact || (health === 'healthy'
        ? '配额消耗处于正常区间。'
        : '失败重试可能推高 API 调用量，需要限制并发或切换备用能力。'),
      sandboxFallback,
      latestTest,
    }
  }), [breakers, providers, testResults])

  const riskRows = providerRows.filter((row) => row.health !== 'healthy' || row.breaker?.state === 'open' || row.breaker?.state === 'half_open' || row.sandboxFallback)
  const openBreakers = breakers.filter((breaker) => breaker.state === 'open')
  const readiness = readinessResponse

  const stats = [
    { label: '接入能力', value: providerRows.length, icon: ServerCog, tone: 'text-slate-500' },
    { label: '健康能力', value: providerRows.filter((row) => row.health === 'healthy').length, icon: CheckCircle2, tone: 'text-emerald-500' },
    { label: '降级/异常', value: providerRows.filter((row) => row.health !== 'healthy').length, icon: ShieldAlert, tone: 'text-amber-500' },
    { label: '打开断路器', value: openBreakers.length, icon: AlertCircle, tone: 'text-rose-500' },
  ]

  const refreshProviderOps = () => {
    queryClient.invalidateQueries({ queryKey: ['providers'] })
    queryClient.invalidateQueries({ queryKey: ['provider-production-readiness'] })
    queryClient.invalidateQueries({ queryKey: ['circuit-breakers'] })
  }

  const createMutation = useMutation({
    mutationFn: (data: Partial<Provider>) => providersApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['providers'] })
      queryClient.invalidateQueries({ queryKey: ['provider-production-readiness'] })
      setShowCreateDialog(false)
      setCreateForm({
        name: '',
        type: 'llm',
        config: providerConfigTemplate('llm'),
      })
      setActionNotice('Provider 已创建，并纳入健康、断路器和配额风险巡检。')
      addToast({ title: 'Provider 已创建' })
    },
    onError: (error: Error) => {
      setActionNotice(`创建失败：${error.message}`)
      addToast({ title: '创建 Provider 失败', description: error.message, variant: 'destructive' })
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<Provider> }) => providersApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['providers'] })
      queryClient.invalidateQueries({ queryKey: ['provider-production-readiness'] })
      setSelectedProvider(null)
      setActionNotice('Provider 配置已保存，下一次联调测试会使用新配置。')
      addToast({ title: 'Provider 配置已保存' })
    },
    onError: (error: Error) => {
      setActionNotice(`保存失败：${error.message}`)
      addToast({ title: '保存 Provider 失败', description: error.message, variant: 'destructive' })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => providersApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['providers'] })
      queryClient.invalidateQueries({ queryKey: ['provider-production-readiness'] })
      setActionNotice('Provider 已删除，相关风险项会从运营视图移除。')
      addToast({ title: 'Provider 已删除' })
    },
    onError: (error: Error) => {
      setActionNotice(`删除失败：${error.message}`)
      addToast({ title: '删除 Provider 失败', description: error.message, variant: 'destructive' })
    },
  })

  const toggleMutation = useMutation({
    mutationFn: ({ id, isActive }: { id: string; isActive: boolean }) => providersApi.update(id, { isActive }),
    onSuccess: (_result, variables) => {
      queryClient.invalidateQueries({ queryKey: ['providers'] })
      queryClient.invalidateQueries({ queryKey: ['provider-production-readiness'] })
      const message = variables.isActive ? 'Provider 已启用，调度流量可重新进入该能力。' : 'Provider 已停用，调度流量会绕开该能力。'
      setActionNotice(message)
      addToast({ title: message })
    },
    onError: (error: Error) => {
      setActionNotice(`启停失败：${error.message}`)
      addToast({ title: 'Provider 启停失败', description: error.message, variant: 'destructive' })
    },
  })

  const testMutation = useMutation({
    mutationFn: ({ providerId, request }: { providerId: string; request: ProviderTestRequest }) => providersApi.test(providerId, request),
    onSuccess: (result, variables) => {
      setTestResults((current) => ({ ...current, [variables.providerId]: result }))
      queryClient.invalidateQueries({ queryKey: ['providers'] })
      queryClient.invalidateQueries({ queryKey: ['provider-production-readiness'] })
      const title = result.success ? '联调测试通过' : '联调测试失败'
      const suffix = result.sandbox_fallback ? '，Sandbox fallback 已接管' : ''
      setActionNotice(`${title}：${result.message}${suffix}`)
      addToast({ title, description: result.message, variant: result.success ? 'default' : 'destructive' })
    },
    onError: (error: Error) => {
      setActionNotice(`联调测试失败：${error.message}`)
      addToast({ title: '联调测试失败', description: error.message, variant: 'destructive' })
    },
  })

  const handleCreateProvider = () => {
    if (!createForm.name.trim()) {
      addToast({ title: '请输入 Provider 名称', variant: 'destructive' })
      return
    }

    try {
      const config = parseConfig(createForm.config)
      createMutation.mutate({ name: createForm.name.trim(), type: createForm.type, config, isActive: true })
    } catch {
      addToast({ title: '配置内容不是有效 JSON', description: '请检查引号、逗号和括号。', variant: 'destructive' })
    }
  }

  const openEditDialog = (provider: ProviderWithOps) => {
    setSelectedProvider(provider)
    setEditForm({ name: provider.name, config: JSON.stringify(provider.config || {}, null, 2) })
  }

  const handleUpdateProvider = () => {
    if (!selectedProvider) return
    if (!editForm.name.trim()) {
      addToast({ title: '请输入 Provider 名称', variant: 'destructive' })
      return
    }

    try {
      const config = parseConfig(editForm.config)
      updateMutation.mutate({ id: selectedProvider.id, data: { name: editForm.name.trim(), config } })
    } catch {
      addToast({ title: '配置内容不是有效 JSON', description: '请检查引号、逗号和括号。', variant: 'destructive' })
    }
  }

  if (providersLoading || breakersLoading || readinessLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="text-slate-500">正在加载 Provider 运营数据...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6" data-testid="provider-operations-center">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">Provider 运营控制中心</h1>
          <p className="mt-1 text-sm text-slate-500">
            统一管理 LLM、GitNexus、Graphify 和自定义能力的接入状态、联调证据、断路器与配额风险。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={refreshProviderOps}>
            <RefreshCw className="mr-2 h-4 w-4" />
            刷新状态
          </Button>
          <Button onClick={() => setShowCreateDialog(true)}>
            <Plus className="mr-2 h-4 w-4" />
            新建 Provider
          </Button>
        </div>
      </div>

      {actionNotice && (
        <div className="rounded-md border border-indigo-200 bg-indigo-50 px-4 py-3 text-sm text-indigo-900 dark:border-indigo-900 dark:bg-indigo-950 dark:text-indigo-100">
          {actionNotice}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        {stats.map((item) => (
          <Card key={item.label}>
            <CardContent className="pt-4">
              <div className="flex items-center gap-3">
                <item.icon className={`h-5 w-5 ${item.tone}`} />
                <div>
                  <p className="text-2xl font-bold">{item.value}</p>
                  <p className="text-xs text-slate-500">{item.label}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card data-testid="provider-production-readiness">
        <CardHeader>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <CardTitle>Provider 生产就绪度</CardTitle>
              <CardDescription>
                汇总 LLM、Graphify、GitNexus 三类核心 Provider 的真实凭据、沙箱状态和发布前补齐动作。
              </CardDescription>
            </div>
            <div className="flex items-center gap-3">
              <div className="text-right">
                <p className="text-3xl font-semibold text-slate-900 dark:text-white">{readiness?.readiness_score ?? 0}%</p>
                <p className="text-xs text-slate-500">核心能力覆盖</p>
              </div>
              <Badge className={readiness?.production_ready
                ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-100'
                : 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-100'
              }>
                {readiness?.production_ready ? '生产就绪' : '仍有阻塞'}
              </Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <div className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
              <p className="text-xs text-slate-500">真实 Provider</p>
              <p className="mt-1 text-xl font-semibold">{readiness?.live_providers ?? 0}</p>
            </div>
            <div className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
              <p className="text-xs text-slate-500">沙箱 Provider</p>
              <p className="mt-1 text-xl font-semibold">{readiness?.sandbox_providers ?? 0}</p>
            </div>
            <div className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
              <p className="text-xs text-slate-500">未配置</p>
              <p className="mt-1 text-xl font-semibold">{readiness?.unconfigured_providers ?? 0}</p>
            </div>
            <div className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
              <p className="text-xs text-slate-500">未启用</p>
              <p className="mt-1 text-xl font-semibold">{readiness?.inactive_providers ?? 0}</p>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
            {(readiness?.required_types || []).map((item) => (
              <div key={item.provider_type} className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-medium text-slate-900 dark:text-white">{item.label}</p>
                    <p className="mt-1 text-xs text-slate-500">
                      真实 {item.live_count} · 沙箱 {item.sandbox_count} · 未配置 {item.unconfigured_count}
                    </p>
                  </div>
                  <Badge variant={item.status === 'ready' ? 'secondary' : 'outline'}>
                    {READINESS_LABELS[item.status] || item.status}
                  </Badge>
                </div>
              </div>
            ))}
          </div>

          <div className="rounded-md border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-900/40">
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-indigo-500" />
              <p className="font-medium text-slate-900 dark:text-white">发布前动作</p>
            </div>
            <ul className="mt-3 space-y-2 text-sm text-slate-600 dark:text-slate-300">
              {(readiness?.recommended_actions || ['暂无 Provider 生产就绪建议。']).map((action) => (
                <li key={action} className="flex gap-2">
                  <span className="mt-2 h-1.5 w-1.5 rounded-full bg-indigo-500" />
                  <span>{action}</span>
                </li>
              ))}
            </ul>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <div>
                <CardTitle>风险队列</CardTitle>
                <CardDescription>优先处理断路器打开、Sandbox fallback、联调失败和降级能力。</CardDescription>
              </div>
              <Badge variant={riskRows.length > 0 ? 'destructive' : 'secondary'}>{riskRows.length} 项</Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {riskRows.length === 0 ? (
              <div className="rounded-md border border-dashed border-slate-200 p-6 text-center text-sm text-slate-500 dark:border-slate-700">
                当前没有需要立即处理的 Provider 风险。
              </div>
            ) : riskRows.map((row) => (
              <div key={row.provider.id} className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-medium text-slate-900 dark:text-white">{row.provider.name}</h3>
                      <Badge variant="outline">{row.typeLabel}</Badge>
                      <Badge className={healthBadgeClass(row.health)}>{HEALTH_LABELS[row.health]}</Badge>
                    </div>
                    <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{row.risk}</p>
                    <p className="mt-1 text-xs text-slate-500">{row.quotaImpact}</p>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    data-testid={`provider-test-${row.provider.id}`}
                    onClick={() => testMutation.mutate({ providerId: row.provider.id, request: buildProviderTestRequest(row) })}
                    disabled={testMutation.isPending}
                  >
                    <Zap className="mr-2 h-4 w-4" />
                    联调测试
                  </Button>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>断路器状态</CardTitle>
            <CardDescription>外部能力熔断状态会直接影响调度与人工兜底成本。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {breakers.length === 0 ? (
              <p className="text-sm text-slate-500">暂无断路器数据。</p>
            ) : breakers.map((breaker) => (
              <div key={breaker.name} className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
                <div className="flex items-center justify-between gap-2">
                  <p className="font-medium text-slate-900 dark:text-white">{breaker.name}</p>
                  <Badge className={breakerBadgeClass(breaker.state)}>{BREAKER_LABELS[breaker.state] || breaker.state}</Badge>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-slate-500">
                  <span>失败次数：{breaker.failure_count}</span>
                  <span>最近失败：{formatDateTime(breaker.last_failure_time)}</span>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Provider 清单</CardTitle>
          <CardDescription>查看每个能力的启停、联调结果、配额影响和配置入口。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {providerRows.map((row) => (
            <div key={row.provider.id} className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
              <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(220px,1.2fr)_repeat(4,minmax(120px,0.7fr))_minmax(260px,1fr)]">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <ServerCog className="h-4 w-4 text-indigo-500" />
                    <p className="font-medium text-slate-900 dark:text-white">{row.provider.name}</p>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Badge variant="secondary">{row.typeLabel}</Badge>
                    <Badge className={healthBadgeClass(row.health)}>{HEALTH_LABELS[row.health]}</Badge>
                    {row.sandboxFallback && <Badge className="bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-100">Sandbox fallback</Badge>}
                  </div>
                </div>

                <div>
                  <p className="text-xs text-slate-500">启用状态</p>
                  <p className="mt-1 text-sm font-medium">{row.provider.isActive ? '已启用' : '已停用'}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">联调结果</p>
                  <p className="mt-1 text-sm font-medium">{TEST_LABELS[row.testState]}</p>
                  {row.latestTest && <p className="mt-1 text-xs text-slate-500">{row.latestTest.message}</p>}
                </div>
                <div>
                  <p className="text-xs text-slate-500">平均延迟</p>
                  <p className="mt-1 text-sm font-medium">{row.latencyMs ? `${row.latencyMs}ms` : '-'}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">断路器</p>
                  <p className="mt-1 text-sm font-medium">{BREAKER_LABELS[row.breaker?.state || 'closed'] || row.breaker?.state || '关闭'}</p>
                  <p className="mt-1 text-xs text-slate-500">失败 {row.breaker?.failure_count ?? 0} 次</p>
                </div>

                <div className="flex flex-wrap items-center justify-start gap-2 xl:justify-end">
                  <Button
                    size="sm"
                    variant="outline"
                    data-testid={`provider-config-${row.provider.id}`}
                    onClick={() => openEditDialog(row.provider)}
                  >
                    <Settings className="mr-2 h-4 w-4" />
                    配置
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    data-testid={`provider-list-test-${row.provider.id}`}
                    onClick={() => testMutation.mutate({ providerId: row.provider.id, request: buildProviderTestRequest(row) })}
                    disabled={testMutation.isPending}
                  >
                    <RefreshCw className={`mr-2 h-4 w-4 ${testMutation.isPending ? 'animate-spin' : ''}`} />
                    联调
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => toggleMutation.mutate({ id: row.provider.id, isActive: !row.provider.isActive })}
                    disabled={toggleMutation.isPending}
                  >
                    {row.provider.isActive ? <Pause className="mr-2 h-4 w-4" /> : <Play className="mr-2 h-4 w-4" />}
                    {row.provider.isActive ? '停用' : '启用'}
                  </Button>
                </div>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新建 Provider</DialogTitle>
            <DialogDescription>登记能力接入配置。生产密钥仍应通过受控环境变量或密钥服务托管，不写入仓库。</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="provider-name">Provider 名称</Label>
              <Input
                id="provider-name"
                value={createForm.name}
                placeholder="例如：GitNexus 代码索引服务"
                onChange={(event) => setCreateForm({ ...createForm, name: event.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="provider-type">能力类型</Label>
              <Select id="provider-type" value={createForm.type} onValueChange={(type) => setCreateForm({ ...createForm, type, config: providerConfigTemplate(type) })}>
                {PROVIDER_TYPES.map((type) => (
                  <SelectOption key={type.value} value={type.value}>{type.label}</SelectOption>
                ))}
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="provider-config">配置 JSON</Label>
              <p className="text-xs text-slate-500">
                生产校准要求真实凭据、连接端点和非 sandbox 模式；密钥应通过受控运行时或密钥服务托管，不要提交到仓库。
              </p>
              <textarea
                id="provider-config"
                className="min-h-[150px] w-full resize-none rounded-md border border-slate-200 bg-white p-3 font-mono text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                value={createForm.config}
                onChange={(event) => setCreateForm({ ...createForm, config: event.target.value })}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreateDialog(false)}>取消</Button>
            <Button onClick={handleCreateProvider} disabled={createMutation.isPending}>
              {createMutation.isPending ? '创建中...' : '创建 Provider'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!selectedProvider} onOpenChange={() => setSelectedProvider(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>配置 Provider</DialogTitle>
            <DialogDescription>{selectedProvider?.name}</DialogDescription>
          </DialogHeader>
          {selectedProvider && (
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="edit-provider-name">Provider 名称</Label>
                <Input
                  id="edit-provider-name"
                  data-testid="provider-edit-name"
                  value={editForm.name}
                  onChange={(event) => setEditForm({ ...editForm, name: event.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="edit-provider-config">配置 JSON</Label>
                <textarea
                  id="edit-provider-config"
                  className="min-h-[150px] w-full resize-none rounded-md border border-slate-200 bg-white p-3 font-mono text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                  value={editForm.config}
                  onChange={(event) => setEditForm({ ...editForm, config: event.target.value })}
                />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" data-testid="provider-edit-cancel" onClick={() => setSelectedProvider(null)}>取消</Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (!selectedProvider) return
                deleteMutation.mutate(selectedProvider.id)
                setSelectedProvider(null)
              }}
            >
              <Trash2 className="mr-2 h-4 w-4" />
              删除
            </Button>
            <Button onClick={handleUpdateProvider} disabled={updateMutation.isPending}>
              {updateMutation.isPending ? '保存中...' : '保存修改'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
