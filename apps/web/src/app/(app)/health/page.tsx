'use client'

import Link from 'next/link'
import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useCurrentUser } from '@/lib/auth'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import {
  auditApi,
  opsApi,
  providersApi,
  type AuditLog,
  type CapabilityActivationAction,
  type CapabilityActivationResponse,
  type CapabilityCommissioningCheck,
  type CapabilityCommissioningResponse,
  type CapabilityReadinessItem,
  type PlatformMetrics,
  type NotificationDelivery,
  type OpsReadinessDashboard,
  type QuotaUsage,
  type RateLimitsResult,
  type TenantMetrics,
  type UsageStatsResult,
} from '@/lib/api-client'
import {
  Activity,
  AlertTriangle,
  CheckCircle,
  Clock,
  Database,
  HardDrive,
  Server,
  XCircle,
  Zap,
  Users,
  FileText,
  Bot,
  RefreshCw,
  ShieldCheck,
  PlayCircle,
  Wrench,
  ClipboardCheck,
  ExternalLink,
  Bell,
  Gauge,
  ServerCog,
} from 'lucide-react'

interface ProviderHealth {
  id: string
  name: string
  type: string
  is_active: boolean
  config: Record<string, any>
}

interface CircuitBreakerState {
  name: string
  state: 'closed' | 'open' | 'half_open'
  failure_count: number
  last_failure_time: string | null
}

interface AuditEventView {
  id: string
  description: string
  user_email?: string
  timestamp: string
  severity: 'info' | 'warning' | 'error'
}

export default function HealthDashboardPage() {
  const { data: currentUser } = useCurrentUser()
  const tenantId = currentUser?.tenant_id || currentUser?.tenantId
  const [activationRunData, setActivationRunData] = useState<CapabilityActivationResponse | null>(null)
  const [commissioningRunData, setCommissioningRunData] = useState<CapabilityCommissioningResponse | null>(null)
  const [evidenceExporting, setEvidenceExporting] = useState(false)
  const [evidenceExportError, setEvidenceExportError] = useState<string | null>(null)

  // Fetch provider health
  const { data: providersData, isLoading: providersLoading, refetch: refetchProviders } = useQuery({
    queryKey: ['providers'],
    queryFn: () => providersApi.list({ pageSize: 100 }),
  })

  // Fetch circuit breakers
  const { data: circuitBreakersData, refetch: refetchCircuitBreakers, error: circuitBreakersError } = useQuery({
    queryKey: ['circuit-breakers'],
    queryFn: () => opsApi.listCircuitBreakers(),
  })

  const { data: platformMetricsData, refetch: refetchPlatformMetrics, error: platformMetricsError } = useQuery<PlatformMetrics>({
    queryKey: ['platform-metrics'],
    queryFn: () => opsApi.getMetrics(),
  })

  const { data: tenantMetricsData, refetch: refetchTenantMetrics, error: tenantMetricsError } = useQuery<TenantMetrics | null>({
    queryKey: ['tenant-metrics', tenantId],
    queryFn: () => tenantId ? opsApi.getTenantMetrics(tenantId) : Promise.resolve(null),
    enabled: Boolean(tenantId),
  })

  const { data: quotaStatusData, refetch: refetchQuotaStatus, error: quotaStatusError } = useQuery({
    queryKey: ['quota-status'],
    queryFn: () => opsApi.getQuota(),
  })

  const { data: quotasData, refetch: refetchQuotas, error: quotasError } = useQuery({
    queryKey: ['quota-list', tenantId],
    queryFn: () => tenantId ? opsApi.listQuotas(tenantId) : Promise.resolve({ quotas: [], total: 0 }),
    enabled: Boolean(tenantId),
  })

  const { data: usageStatsData, refetch: refetchUsageStats, error: usageStatsError } = useQuery<UsageStatsResult | null>({
    queryKey: ['usage-stats', tenantId],
    queryFn: () => tenantId ? opsApi.getUsageStats(tenantId) : Promise.resolve(null),
    enabled: Boolean(tenantId),
  })

  const { data: rateLimitsData, refetch: refetchRateLimits, error: rateLimitsError } = useQuery<RateLimitsResult | null>({
    queryKey: ['rate-limits', tenantId],
    queryFn: () => tenantId ? opsApi.getRateLimits(tenantId) : Promise.resolve(null),
    enabled: Boolean(tenantId),
  })

  const { data: auditLogsData, refetch: refetchAuditLogs } = useQuery({
    queryKey: ['health-audit-logs', tenantId],
    queryFn: () => auditApi.listLogs({ tenantId, pageSize: 8 }),
    enabled: Boolean(tenantId),
  })
  const { data: notificationDeliveriesData, refetch: refetchNotificationDeliveries, error: notificationDeliveriesError } = useQuery({
    queryKey: ['notification-deliveries', tenantId],
    queryFn: () => tenantId ? opsApi.listNotificationDeliveries(tenantId, { limit: 8 }) : Promise.resolve(null),
    enabled: Boolean(tenantId),
  })
  const retryNotificationDelivery = useMutation({
    mutationFn: (eventId: string) => opsApi.retryNotificationDelivery(eventId),
    onSuccess: () => refetchNotificationDeliveries(),
  })

  const { data: readinessData, isLoading: readinessLoading, refetch: refetchReadiness } = useQuery({
    queryKey: ['capability-readiness'],
    queryFn: () => opsApi.getCapabilityReadiness(),
  })

  const { data: productionOpsData, refetch: refetchProductionOps, error: productionOpsError } = useQuery({
    queryKey: ['production-ops-command-center'],
    queryFn: () => opsApi.getProductionCommandCenter(),
    enabled: Boolean(tenantId),
  })

  const { data: opsReadinessDashboardData, refetch: refetchOpsReadinessDashboard, error: opsReadinessDashboardError } = useQuery<OpsReadinessDashboard>({
    queryKey: ['ops-readiness-dashboard'],
    queryFn: () => opsApi.getReadinessDashboard(),
    enabled: Boolean(tenantId),
  })

  const {
    data: activationPlanData,
    isLoading: activationPlanLoading,
    refetch: refetchActivationPlan,
  } = useQuery({
    queryKey: ['capability-activation-plan'],
    queryFn: () => opsApi.getCapabilityActivationPlan(),
    enabled: false,
  })

  const runActivationMutation = useMutation({
    mutationFn: (actions: string[]) =>
      opsApi.runCapabilityActivation({
        dry_run: false,
        confirm: true,
        actions,
      }),
    onSuccess: (result) => {
      setActivationRunData(result)
      refetchReadiness()
    },
  })

  const {
    data: commissioningData,
    isLoading: commissioningLoading,
    refetch: refetchCommissioning,
  } = useQuery({
    queryKey: ['capability-commissioning'],
    queryFn: () => opsApi.getCapabilityCommissioning(),
    enabled: false,
  })

  const runCommissioningMutation = useMutation({
    mutationFn: (checks: string[]) =>
      opsApi.runCapabilityCommissioning({
        checks,
      }),
    onSuccess: (result) => {
      setCommissioningRunData(result)
      refetchReadiness()
    },
  })

  const opsDataErrors = [
    circuitBreakersError,
    platformMetricsError,
    tenantMetricsError,
    quotaStatusError,
    quotasError,
    usageStatsError,
    rateLimitsError,
    notificationDeliveriesError,
    productionOpsError,
    opsReadinessDashboardError,
  ].filter(Boolean)
  const opsAccessLimited = opsDataErrors.length > 0
  const opsAccessMessage = opsDataErrors[0] instanceof Error ? opsDataErrors[0].message : 'Ops permission required'

  const providers = (providersData?.items || []).map((provider: any) => ({
    ...provider,
    type: provider.type || provider.provider_type || 'provider',
    is_active: provider.is_active ?? provider.isActive ?? provider.status === 'active',
  })) as ProviderHealth[]
  const circuitBreakers = circuitBreakersData?.breakers || []
  const metrics: PlatformMetrics = platformMetricsData ?? {
    timestamp: null,
    total_tenants: 0,
    active_users_24h: 0,
    total_api_calls_24h: 0,
    error_rate_percent: 0,
    avg_latency_ms: 0,
  }
  const quotas: QuotaUsage[] = quotasData?.quotas || []
  const usageStats = usageStatsData
  const rateLimits = rateLimitsData?.rate_limits || []
  const tightRateLimit = rateLimits
    .filter((limit) => limit.limit > 0)
    .sort((a, b) => (a.remaining / a.limit) - (b.remaining / b.limit))[0]
  const auditEvents: AuditEventView[] = (auditLogsData?.items || []).map((event: AuditLog) => {
    const action = event.action || ''
    const severity: AuditEventView['severity'] =
      action.includes('delete') || action.includes('failed') || action.includes('deny')
        ? 'warning'
        : action.includes('error')
          ? 'error'
          : 'info'
    return {
      id: event.id,
      description: event.extra_data?.summary || `${event.action} ${event.resource_type || 'system'}`,
      user_email: event.extra_data?.user_email || event.extra_data?.user_name || undefined,
      timestamp: event.created_at,
      severity,
    }
  })

  const readinessCapabilities = readinessData?.capabilities || []
  const visibleActivationData = activationRunData || activationPlanData
  const activationActions = visibleActivationData?.actions || []
  const executableActivationActions = activationActions.filter((action) => action.can_execute)
  const visibleCommissioningData = commissioningRunData || commissioningData
  const commissioningChecks = visibleCommissioningData?.checks || []
  const runnableCommissioningChecks = commissioningChecks.filter((check) => check.can_run)

  const getProviderIcon = (type: string) => {
    switch (type) {
      case 'graphify':
        return <Zap className="h-5 w-5" />
      case 'gitnexus':
        return <Database className="h-5 w-5" />
      case 'minimax':
        return <Bot className="h-5 w-5" />
      default:
        return <Server className="h-5 w-5" />
    }
  }

  const getProviderStatusColor = (isActive: boolean) => {
    return isActive
      ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-100'
      : 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100'
  }

  const getCircuitBreakerIcon = (state: string) => {
    switch (state) {
      case 'closed':
        return <CheckCircle className="h-4 w-4 text-green-500" />
      case 'open':
        return <XCircle className="h-4 w-4 text-red-500" />
      case 'half_open':
        return <RefreshCw className="h-4 w-4 text-yellow-500" />
      default:
        return <AlertTriangle className="h-4 w-4 text-slate-500" />
    }
  }

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'error':
        return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100'
      case 'warning':
        return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-100'
      default:
        return 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-100'
    }
  }

  const getReadinessColor = (status: string) => {
    switch (status) {
      case 'ready':
        return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100'
      case 'degraded':
        return 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-100'
      case 'blocked':
        return 'bg-rose-100 text-rose-800 dark:bg-rose-900 dark:text-rose-100'
      default:
        return 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-100'
    }
  }

  const getReadinessLabel = (status: string) => {
    switch (status) {
      case 'ready':
        return '可用'
      case 'degraded':
        return '受限'
      case 'blocked':
        return '阻断'
      default:
        return '未知'
    }
  }

  const getReleaseGateColor = (status: string) => {
    switch (status) {
      case 'ready':
        return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100'
      case 'blocked':
        return 'bg-rose-100 text-rose-800 dark:bg-rose-900 dark:text-rose-100'
      default:
        return 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-100'
    }
  }

  const getReleaseGateLabel = (status: string) => {
    switch (status) {
      case 'ready':
        return '可以发布'
      case 'blocked':
        return '发布阻塞'
      default:
        return '需要关注'
    }
  }

  const getActivationStatusColor = (action: CapabilityActivationAction) => {
    if (action.status === 'completed') {
      return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100'
    }
    if (action.action_type === 'manual') {
      return 'bg-sky-100 text-sky-800 dark:bg-sky-900 dark:text-sky-100'
    }
    if (action.status === 'blocked' || action.status === 'failed') {
      return 'bg-rose-100 text-rose-800 dark:bg-rose-900 dark:text-rose-100'
    }
    return 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-100'
  }

  const getActivationStatusLabel = (action: CapabilityActivationAction) => {
    if (action.status === 'completed') return '已完成'
    if (action.status === 'skipped') return '已跳过'
    if (action.status === 'blocked') return '阻断'
    if (action.status === 'failed') return '失败'
    if (action.action_type === 'manual') return '需人工'
    return '可执行'
  }

  const getCommissioningStatusColor = (check: CapabilityCommissioningCheck) => {
    if (check.status === 'passed') {
      return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100'
    }
    if (check.status === 'warning') {
      return 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-100'
    }
    if (check.status === 'failed') {
      return 'bg-rose-100 text-rose-800 dark:bg-rose-900 dark:text-rose-100'
    }
    return 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-100'
  }

  const getCommissioningStatusLabel = (check: CapabilityCommissioningCheck) => {
    if (check.run_status === 'passed') return '已通过'
    if (check.run_status === 'failed') return '未通过'
    if (check.run_status === 'skipped') return '已跳过'
    if (check.status === 'passed') return '证据通过'
    if (check.status === 'warning') return '需关注'
    if (check.status === 'failed') return '待处理'
    return '未运行'
  }

  const evidenceEntries = (capability: CapabilityReadinessItem) =>
    Object.entries(capability.evidence || {})
      .filter(([, value]) => typeof value === 'number' || typeof value === 'string' || typeof value === 'boolean')
      .slice(0, 4)

  const commissioningEvidenceEntries = (check: CapabilityCommissioningCheck) =>
    Object.entries(check.evidence || {})
      .filter(([, value]) => typeof value === 'number' || typeof value === 'string' || typeof value === 'boolean')
      .slice(0, 4)

  const commissioningRequiredFields = (check: CapabilityCommissioningCheck) => {
    const fields = check.configuration_requirements?.required_fields
    return Array.isArray(fields) ? fields.map(String).slice(0, 5) : []
  }

  const compactList = (values?: string[]) => (values || []).slice(0, 3)

  const apiCallsQuota = quotas.find(q => q.quota_type === 'API_CALLS') || (quotaStatusData ? {
    quota_type: 'API_CALLS',
    used_amount: quotaStatusData.used,
    limit_amount: quotaStatusData.limit,
    period: 'current',
    reset_at: quotaStatusData.resetAt,
  } : undefined)
  const storageQuota = quotas.find(q => q.quota_type === 'STORAGE_BYTES')
  const usersQuota = quotas.find(q => q.quota_type === 'USER_COUNT')

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`
  }

  const formatEvidenceValue = (value: unknown) => {
    if (value === null || value === undefined || value === '') return 'not recorded'
    return String(value)
  }

  const downloadOpsEvidence = async () => {
    setEvidenceExporting(true)
    setEvidenceExportError(null)
    try {
      const evidence = await opsApi.getReleaseEvidenceExport()
      const blob = new Blob([JSON.stringify(evidence, null, 2)], {
        type: 'application/json',
      })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'amx-release-evidence.json'
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)
    } catch {
      setEvidenceExportError('Release evidence export failed. Refresh the runtime evidence and retry.')
    } finally {
      setEvidenceExporting(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">健康状态</h1>
          <p className="text-sm text-slate-500 mt-1">系统健康、指标和监控</p>
        </div>
        <Button
          variant="outline"
          onClick={() => {
            refetchProviders()
            refetchCircuitBreakers()
            refetchPlatformMetrics()
            refetchTenantMetrics()
            refetchQuotaStatus()
            refetchQuotas()
            refetchUsageStats()
            refetchRateLimits()
            refetchAuditLogs()
            refetchReadiness()
            refetchProductionOps()
            refetchOpsReadinessDashboard()
            refetchNotificationDeliveries()
            if (activationPlanData || activationRunData) {
              setActivationRunData(null)
              refetchActivationPlan()
            }
            if (commissioningData || commissioningRunData) {
              setCommissioningRunData(null)
              refetchCommissioning()
            }
          }}
        >
          <RefreshCw className="mr-2 h-4 w-4" />
          刷新
        </Button>
      </div>

      <nav
        data-testid="platform-operations-navigation"
        aria-label="平台运维子功能"
        className="flex flex-wrap gap-2 border-b border-slate-200 pb-4 dark:border-slate-800"
      >
        <Button variant="secondary" size="sm" aria-current="page">
          <Activity className="mr-2 h-4 w-4" />
          运维总览
        </Button>
        <Button variant="outline" size="sm" asChild>
          <Link href="/providers">
            <ServerCog className="mr-2 h-4 w-4" />
            模型服务
          </Link>
        </Button>
        <Button variant="outline" size="sm" asChild>
          <Link href="/quotas">
            <Gauge className="mr-2 h-4 w-4" />
            资源配额
          </Link>
        </Button>
      </nav>

      {opsAccessLimited && (
        <Card className="border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950">
          <CardContent className="flex flex-col gap-3 py-4 text-sm text-amber-900 dark:text-amber-100 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
              <div>
                <p className="font-medium">生产运维数据受限</p>
                <p className="mt-1">
                  当前账号缺少 Ops 读取或管理权限，指标、配额、熔断器和投产校准数据可能无法完整展示。后端返回：{opsAccessMessage}
                </p>
              </div>
            </div>
            <Link href="/team" className="inline-flex shrink-0 items-center rounded-md border border-amber-300 px-3 py-2 font-medium hover:bg-amber-100 dark:border-amber-800 dark:hover:bg-amber-900">
              <ShieldCheck className="mr-2 h-4 w-4" />
              检查团队权限
            </Link>
          </CardContent>
        </Card>
      )}

      {opsReadinessDashboardData && (
        <Card data-testid="ops-readiness-dashboard" className="border-emerald-200 dark:border-emerald-900">
          <CardHeader>
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <CardTitle className="flex items-center gap-2">
                  <ShieldCheck className="h-5 w-5" />
                  Release Evidence Console
                </CardTitle>
                <CardDescription>
                  Single read-only runtime evidence boundary. Missing evidence never defaults to a passing release gate.
                </CardDescription>
              </div>
              <Button variant="outline" onClick={downloadOpsEvidence} disabled={evidenceExporting}>
                <FileText className="mr-2 h-4 w-4" />
                {evidenceExporting ? 'Exporting evidence...' : 'Export sanitized evidence'}
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="flex flex-wrap items-center gap-3 rounded-md border border-slate-200 p-4 dark:border-slate-800">
              <Badge
                variant={opsReadinessDashboardData.release_evidence.status === 'blocked' ? 'destructive' : opsReadinessDashboardData.release_evidence.status === 'ready' ? 'default' : 'secondary'}
              >
                {opsReadinessDashboardData.release_evidence.status}
              </Badge>
              <span className="text-sm text-slate-600 dark:text-slate-300">
                Environment: <strong>{formatEvidenceValue(opsReadinessDashboardData.release_evidence.environment)}</strong>
              </span>
              <span
                data-testid="sha-match-indicator"
                className="text-sm text-slate-600 dark:text-slate-300"
              >
                {opsReadinessDashboardData.release_evidence.sha_matches === true
                  ? 'SHA match'
                  : opsReadinessDashboardData.release_evidence.sha_matches === false
                    ? 'SHA mismatch'
                    : 'SHA comparison not recorded'}
              </span>
            </div>

            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                <p className="text-xs text-slate-500">Runtime SHA</p>
                <p className="mt-2 break-all font-mono text-xs">{formatEvidenceValue(opsReadinessDashboardData.release_evidence.deployed_sha)}</p>
              </div>
              <div className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                <p className="text-xs text-slate-500">Expected SHA</p>
                <p className="mt-2 break-all font-mono text-xs">{formatEvidenceValue(opsReadinessDashboardData.release_evidence.expected_sha)}</p>
              </div>
              <div className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                <p className="text-xs text-slate-500">Release tag / deployed ref</p>
                <p className="mt-2 font-medium">{formatEvidenceValue(opsReadinessDashboardData.release_evidence.release_tag)}</p>
                <p className="mt-1 text-xs text-slate-500">{formatEvidenceValue(opsReadinessDashboardData.release_evidence.deployed_ref)}</p>
              </div>
              <div className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                <p className="text-xs text-slate-500">Latest evidence export</p>
                <p className="mt-2 text-sm">{formatEvidenceValue(opsReadinessDashboardData.release_evidence.latest_evidence_export_at)}</p>
                <p className="mt-1 text-xs text-slate-500">{opsReadinessDashboardData.release_evidence.source}</p>
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                <p className="text-xs text-slate-500">Smoke</p>
                <p className="mt-2 font-medium">{formatEvidenceValue(opsReadinessDashboardData.release_evidence.smoke_status)}</p>
                {opsReadinessDashboardData.release_evidence.authenticated_smoke_run_url && (
                  <a className="mt-2 inline-flex items-center text-xs text-blue-600 hover:underline" href={opsReadinessDashboardData.release_evidence.authenticated_smoke_run_url} target="_blank" rel="noreferrer">
                    Authenticated smoke <ExternalLink className="ml-1 h-3 w-3" />
                  </a>
                )}
              </div>
              <div className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                <p className="text-xs text-slate-500">Provenance</p>
                <p className="mt-2 font-medium">{formatEvidenceValue(opsReadinessDashboardData.release_evidence.provenance_status)}</p>
              </div>
              <div className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                <p className="text-xs text-slate-500">GitNexus</p>
                <p className="mt-2 font-medium">{formatEvidenceValue(opsReadinessDashboardData.release_evidence.gitnexus_status)}</p>
                <p className="mt-1 break-all font-mono text-xs text-slate-500">{formatEvidenceValue(opsReadinessDashboardData.release_evidence.gitnexus_indexed_sha)}</p>
              </div>
              <div className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                <p className="text-xs text-slate-500">Workflow evidence</p>
                <div className="mt-2 flex flex-col items-start gap-2 text-xs">
                  {opsReadinessDashboardData.release_evidence.candidate_verification_run_url ? (
                    <a className="inline-flex items-center text-blue-600 hover:underline" href={opsReadinessDashboardData.release_evidence.candidate_verification_run_url} target="_blank" rel="noreferrer">
                      Candidate verification <ExternalLink className="ml-1 h-3 w-3" />
                    </a>
                  ) : <span className="text-slate-500">Candidate verification not recorded</span>}
                  {opsReadinessDashboardData.release_evidence.production_deployment_run_url ? (
                    <a className="inline-flex items-center text-blue-600 hover:underline" href={opsReadinessDashboardData.release_evidence.production_deployment_run_url} target="_blank" rel="noreferrer">
                      Production deployment <ExternalLink className="ml-1 h-3 w-3" />
                    </a>
                  ) : <span className="text-slate-500">Production deployment not recorded</span>}
                </div>
              </div>
            </div>

            {evidenceExportError && (
              <p role="alert" className="text-sm text-red-600">{evidenceExportError}</p>
            )}

            <div className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="font-medium text-slate-900 dark:text-white">Release evidence blockers</h3>
                <Badge variant={opsReadinessDashboardData.release_evidence.blockers.length ? 'destructive' : 'secondary'}>
                  {opsReadinessDashboardData.release_evidence.blockers.length}
                </Badge>
              </div>
              {opsReadinessDashboardData.release_evidence.blockers.length === 0 ? (
                <p className="text-sm text-slate-500">No release evidence blockers recorded.</p>
              ) : (
                <div className="space-y-2">
                  {opsReadinessDashboardData.release_evidence.blockers.map((blocker) => (
                    <div key={blocker.code} className="rounded border border-slate-200 p-3 text-sm dark:border-slate-800">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant={blocker.severity === 'critical' || blocker.severity === 'high' ? 'destructive' : 'secondary'}>{blocker.severity}</Badge>
                        <span className="font-medium">{blocker.summary}</span>
                      </div>
                      <p className="mt-1 font-mono text-xs text-slate-500">{blocker.code}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                <p className="text-xs text-slate-500">Provider readiness</p>
                <p className="mt-2 text-2xl font-semibold">{opsReadinessDashboardData.provider_readiness.readiness_score}%</p>
                <p className="mt-1 text-sm text-slate-500">
                  {opsReadinessDashboardData.provider_readiness.production_ready ? 'production ready' : 'not production ready'}
                </p>
              </div>
              <div className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                <p className="text-xs text-slate-500">Capability readiness</p>
                <p className="mt-2 text-2xl font-semibold">{opsReadinessDashboardData.capability_readiness.overall_score}%</p>
                <p className="mt-1 text-sm text-slate-500">{opsReadinessDashboardData.capability_readiness.overall_status}</p>
              </div>
              <div className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                <p className="text-xs text-slate-500">Quota</p>
                <p className="mt-2 text-2xl font-semibold">{formatEvidenceValue(opsReadinessDashboardData.quota.usage_percent)}%</p>
                <p className="mt-1 text-sm text-slate-500">
                  {formatEvidenceValue(opsReadinessDashboardData.quota.used)} / {formatEvidenceValue(opsReadinessDashboardData.quota.limit)}
                </p>
              </div>
              <div className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                <p className="text-xs text-slate-500">Agent health</p>
                <p className="mt-2 text-2xl font-semibold">{formatEvidenceValue(opsReadinessDashboardData.agent_run_health.status)}</p>
                <p className="mt-1 text-sm text-slate-500">
                  {formatEvidenceValue(opsReadinessDashboardData.agent_run_health.running)} running, {formatEvidenceValue(opsReadinessDashboardData.agent_run_health.failed_24h)} failed 24h
                </p>
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-3">
              <div className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                <p className="text-xs text-slate-500">Metrics</p>
                <p className="mt-2 font-medium">{formatEvidenceValue(opsReadinessDashboardData.metrics.total_events)} events</p>
                <p className="mt-1 text-xs text-slate-500">
                  error rate {formatEvidenceValue(opsReadinessDashboardData.metrics.error_rate_percent)}%, latency {formatEvidenceValue(opsReadinessDashboardData.metrics.avg_latency_ms)}ms
                </p>
              </div>
              <div className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                <p className="text-xs text-slate-500">Alerts</p>
                <p className="mt-2 font-medium">{formatEvidenceValue(opsReadinessDashboardData.alerts.active_rules)} active rules</p>
                <p className="mt-1 text-xs text-slate-500">
                  {formatEvidenceValue(opsReadinessDashboardData.alerts.failed_notifications)} failed, {formatEvidenceValue(opsReadinessDashboardData.alerts.pending_notifications)} pending
                </p>
              </div>
              <div className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                <p className="text-xs text-slate-500">Evidence export</p>
                <p className="mt-2 font-medium">{formatEvidenceValue(opsReadinessDashboardData.evidence_export.format)}</p>
                <p className="mt-1 text-xs text-slate-500">
                  {opsReadinessDashboardData.evidence_export.sanitized ? 'sanitized' : 'not sanitized'}
                </p>
              </div>
            </div>

            <div className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="font-medium text-slate-900 dark:text-white">Latest critical failures</h3>
                <Badge variant={opsReadinessDashboardData.latest_critical_failures.length ? 'destructive' : 'secondary'}>
                  {opsReadinessDashboardData.latest_critical_failures.length}
                </Badge>
              </div>
              {opsReadinessDashboardData.latest_critical_failures.length === 0 ? (
                <p className="text-sm text-slate-500">No critical failures recorded in the dashboard snapshot.</p>
              ) : (
                <div className="space-y-2">
                  {opsReadinessDashboardData.latest_critical_failures.map((failure, index) => (
                    <div key={`${failure.source}-${failure.summary}-${index}`} className="rounded border border-slate-200 p-3 text-sm dark:border-slate-800">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline">{failure.source}</Badge>
                        <Badge variant={failure.severity === 'critical' ? 'destructive' : 'secondary'}>{failure.severity}</Badge>
                        <span className="font-medium">{failure.summary}</span>
                      </div>
                      <p className="mt-1 text-xs text-slate-500">{formatEvidenceValue(failure.occurred_at)}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {productionOpsData && (
        <Card data-testid="production-ops-command-center" className="border-indigo-200 dark:border-indigo-900">
          <CardHeader>
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <CardTitle className="flex items-center gap-2">
                  <ClipboardCheck className="h-5 w-5" />
                  生产运维指挥台
                </CardTitle>
                <CardDescription>
                  聚合核心能力就绪、投产校准、关键阻塞和处置入口，作为发布前的第一层运维判断。
                </CardDescription>
              </div>
              <div data-testid="production-ops-release-gate" className="flex items-center gap-3">
                <div className="max-w-xs text-right">
                  <Badge className={getReleaseGateColor(productionOpsData.release_gate.status)}>
                    {getReleaseGateLabel(productionOpsData.release_gate.status)}
                  </Badge>
                  <p className="mt-2 text-xs text-slate-500">{productionOpsData.release_gate.summary}</p>
                </div>
                <div className="text-right">
                  <div className="text-2xl font-bold text-slate-900 dark:text-white">
                    {productionOpsData.release_gate.readiness_score}/{productionOpsData.release_gate.commissioning_score}
                  </div>
                  <div className="text-xs text-slate-500">就绪 / 校准</div>
                </div>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="rounded-md border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-900">
              <p className="font-medium text-slate-900 dark:text-white">{productionOpsData.release_gate.summary}</p>
              <div className="mt-3 grid gap-3 text-sm sm:grid-cols-4">
                <div>
                  <p className="text-xs text-slate-500">关键阻塞</p>
                  <p className="mt-1 text-xl font-semibold text-rose-600">{productionOpsData.summary.critical_blockers || 0}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">高优先级</p>
                  <p className="mt-1 text-xl font-semibold text-amber-600">{productionOpsData.summary.high_blockers || 0}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">可运行校准</p>
                  <p className="mt-1 text-xl font-semibold">{productionOpsData.summary.runnable_checks || 0}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">阻塞能力</p>
                  <p className="mt-1 text-xl font-semibold">{productionOpsData.summary.blocked_capabilities || 0}</p>
                </div>
              </div>
            </div>

            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
              <div className="space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="font-medium text-slate-900 dark:text-white">关键阻塞队列</h3>
                  <Badge variant={productionOpsData.blockers.length ? 'destructive' : 'secondary'}>
                    {productionOpsData.blockers.length} 项
                  </Badge>
                </div>
                {productionOpsData.blockers.length === 0 ? (
                  <div className="rounded-md border border-dashed border-slate-200 p-5 text-center text-sm text-slate-500 dark:border-slate-700">
                    当前没有发布前关键阻塞。
                  </div>
                ) : (
                  productionOpsData.blockers.slice(0, 5).map((blocker) => (
                    <div key={`${blocker.source}-${blocker.key}`} className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                        <div>
                          <div className="flex flex-wrap items-center gap-2">
                            <h4 className="font-medium text-slate-900 dark:text-white">{blocker.label}</h4>
                            <Badge className={blocker.severity === 'critical' ? 'bg-rose-100 text-rose-800 dark:bg-rose-900 dark:text-rose-100' : 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-100'}>
                              {blocker.severity === 'critical' ? '关键' : '高优先级'}
                            </Badge>
                            <Badge variant="outline">{blocker.source === 'commissioning' ? '投产校准' : '能力就绪'}</Badge>
                          </div>
                          <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{blocker.summary}</p>
                          {blocker.api_endpoint && <p className="mt-1 text-xs text-slate-500">{blocker.api_endpoint}</p>}
                        </div>
                        {blocker.action_href && (
                          <Link href={blocker.action_href} className="inline-flex shrink-0 items-center rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800">
                            <ExternalLink className="mr-2 h-4 w-4" />
                            {blocker.action_label || '处理'}
                          </Link>
                        )}
                      </div>
                    </div>
                  ))
                )}
              </div>

              <div className="space-y-3">
                <h3 className="font-medium text-slate-900 dark:text-white">优先处置动作</h3>
                {productionOpsData.priority_actions.length === 0 ? (
                  <div className="rounded-md border border-dashed border-slate-200 p-5 text-center text-sm text-slate-500 dark:border-slate-700">
                    暂无需要立即执行的动作。
                  </div>
                ) : (
                  productionOpsData.priority_actions.slice(0, 5).map((action) => (
                    <Link
                      key={`${action.capability_key}-${action.href}`}
                      href={action.href}
                      className="block rounded-md border border-slate-200 p-3 text-sm hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-900"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium text-slate-900 dark:text-white">{action.label}</span>
                        <ExternalLink className="h-4 w-4 text-slate-400" />
                      </div>
                      <p className="mt-2 text-slate-500">{action.description}</p>
                    </Link>
                  ))
                )}
                <div className="rounded-md bg-slate-50 p-3 text-sm text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                  <p className="font-medium text-slate-900 dark:text-white">下一步</p>
                  <ul className="mt-2 space-y-1">
                    {productionOpsData.next_steps.slice(0, 3).map((step) => (
                      <li key={step} className="flex gap-2">
                        <span className="mt-2 h-1.5 w-1.5 rounded-full bg-indigo-500" />
                        <span>{step}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <ShieldCheck className="h-5 w-5" />
                核心能力就绪
              </CardTitle>
              <CardDescription>统一判断文档、编排、知识、集成、导出和 Provider 是否形成生产闭环</CardDescription>
            </div>
            <div className="flex items-center gap-3">
              <Badge className={getReadinessColor(readinessData?.overall_status || 'unknown')}>
                {getReadinessLabel(readinessData?.overall_status || 'unknown')}
              </Badge>
              <div className="text-right">
                <div className="text-2xl font-bold text-slate-900 dark:text-white">
                  {readinessData?.overall_score ?? 0}
                </div>
                <div className="text-xs text-slate-500">综合评分</div>
              </div>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {readinessLoading ? (
            <div className="py-8 text-center text-slate-500">正在加载核心能力状态...</div>
          ) : (
            <>
              <div className="flex flex-col gap-3 rounded-md border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-900 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <p className="font-medium text-slate-900 dark:text-white">
                    {readinessData?.production_ready ? '当前租户具备生产闭环基础' : '当前租户仍有核心能力阻断或受限项'}
                  </p>
                  <p className="mt-1 text-sm text-slate-500">
                    最近检查：{readinessData?.generated_at ? new Date(readinessData.generated_at).toLocaleString('zh-CN') : '-'}
                  </p>
                </div>
                <Progress value={readinessData?.overall_score || 0} max={100} className="h-2 w-full lg:w-64" />
              </div>

              <div className="rounded-md border border-slate-200 p-4 dark:border-slate-800" data-testid="capability-activation-panel">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <h3 className="flex items-center gap-2 font-medium text-slate-900 dark:text-white">
                      <Wrench className="h-4 w-4" />
                      核心能力激活中心
                    </h3>
                    <p className="mt-1 text-sm text-slate-500">
                      自动补齐可安全初始化的模板、Skill、Agent 和工作流；真实 Provider、知识源、集成和导出验证保留为人工动作。
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setActivationRunData(null)
                        refetchActivationPlan()
                      }}
                      disabled={activationPlanLoading}
                    >
                      <RefreshCw className="mr-2 h-4 w-4" />
                      生成激活计划
                    </Button>
                    <Button
                      size="sm"
                      onClick={() => runActivationMutation.mutate(executableActivationActions.map((action) => action.key))}
                      disabled={executableActivationActions.length === 0 || runActivationMutation.isPending}
                    >
                      <PlayCircle className="mr-2 h-4 w-4" />
                      执行安全激活
                    </Button>
                  </div>
                </div>

                {activationPlanLoading ? (
                  <div className="mt-4 text-sm text-slate-500">正在生成激活计划...</div>
                ) : activationActions.length === 0 ? (
                  <div className="mt-4 rounded-md bg-slate-50 p-3 text-sm text-slate-500 dark:bg-slate-900">
                    尚未生成计划。生成计划不会写入数据，只会列出可执行动作和人工阻断项。
                  </div>
                ) : (
                  <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-2">
                    {activationActions.map((action) => (
                      <div key={action.key} className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="font-medium text-slate-900 dark:text-white">{action.label}</p>
                            <p className="mt-1 text-sm text-slate-500">{action.description}</p>
                          </div>
                          <Badge className={getActivationStatusColor(action)}>{getActivationStatusLabel(action)}</Badge>
                        </div>
                        {Object.keys(action.result || {}).length > 0 && (
                          <div className="mt-3 flex flex-wrap gap-2">
                            {Object.entries(action.result)
                              .filter(([, value]) => typeof value === 'number' || typeof value === 'string' || typeof value === 'boolean')
                              .slice(0, 4)
                              .map(([key, value]) => (
                                <span key={key} className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                                  {key}: {String(value)}
                                </span>
                              ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="rounded-md border border-slate-200 p-4 dark:border-slate-800" data-testid="capability-commissioning-panel">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <h3 className="flex items-center gap-2 font-medium text-slate-900 dark:text-white">
                      <ClipboardCheck className="h-4 w-4" />
                      核心能力投产校准中心
                    </h3>
                    <p className="mt-1 text-sm text-slate-500">
                      按真实生产证据校准 Provider、知识图谱、外部集成和导出链路，失败项会指向对应处理入口。
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setCommissioningRunData(null)
                        refetchCommissioning()
                      }}
                      disabled={commissioningLoading}
                    >
                      <RefreshCw className="mr-2 h-4 w-4" />
                      生成校准清单
                    </Button>
                    <Button
                      size="sm"
                      onClick={() => runCommissioningMutation.mutate(runnableCommissioningChecks.map((check) => check.key))}
                      disabled={runnableCommissioningChecks.length === 0 || runCommissioningMutation.isPending}
                    >
                      <PlayCircle className="mr-2 h-4 w-4" />
                      运行校准检查
                    </Button>
                  </div>
                </div>

                {visibleCommissioningData && (
                  <div className="mt-4 flex flex-col gap-3 rounded-md bg-slate-50 p-3 dark:bg-slate-900 lg:flex-row lg:items-center lg:justify-between">
                    <div>
                      <p className="font-medium text-slate-900 dark:text-white">
                        {visibleCommissioningData.production_usable ? '生产可用证据已通过' : '仍有生产投产证据未通过'}
                      </p>
                      <p className="mt-1 text-sm text-slate-500">
                        校准评分 {visibleCommissioningData.overall_score}，失败检查 {visibleCommissioningData.summary.failed_check_count ?? 0} 项
                      </p>
                    </div>
                    <Progress value={visibleCommissioningData.overall_score || 0} max={100} className="h-2 w-full lg:w-64" />
                  </div>
                )}

                {commissioningLoading ? (
                  <div className="mt-4 text-sm text-slate-500">正在生成投产校准清单...</div>
                ) : commissioningChecks.length === 0 ? (
                  <div className="mt-4 rounded-md bg-slate-50 p-3 text-sm text-slate-500 dark:bg-slate-900">
                    尚未生成校准清单。校准不会写入业务数据，只会读取当前证据并标出待处理入口。
                  </div>
                ) : (
                  <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-2">
                    {commissioningChecks.map((check) => (
                      <div key={check.key} className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="font-medium text-slate-900 dark:text-white">{check.label}</p>
                            <p className="mt-1 text-sm text-slate-500">{check.summary}</p>
                          </div>
                          <Badge className={getCommissioningStatusColor(check)}>{getCommissioningStatusLabel(check)}</Badge>
                        </div>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {commissioningEvidenceEntries(check).map(([key, value]) => (
                            <span key={key} className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                              {key}: {String(value)}
                            </span>
                          ))}
                        </div>
                        {check.blockers.length > 0 && (
                          <div className="mt-3 rounded-md bg-rose-50 p-3 text-sm text-rose-800 dark:bg-rose-950 dark:text-rose-100">
                            <p className="font-medium">阻塞项</p>
                            <p className="mt-1">{check.blockers[0]}</p>
                          </div>
                        )}
                        {(commissioningRequiredFields(check).length > 0 || compactList(check.validation_steps).length > 0 || compactList(check.evidence_requirements).length > 0) && (
                          <div className="mt-3 grid gap-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
                            {commissioningRequiredFields(check).length > 0 && (
                              <div>
                                <p className="font-medium text-slate-800 dark:text-slate-100">配置要求</p>
                                <p className="mt-1">{commissioningRequiredFields(check).join('、')}</p>
                              </div>
                            )}
                            {compactList(check.validation_steps).length > 0 && (
                              <div>
                                <p className="font-medium text-slate-800 dark:text-slate-100">验证步骤</p>
                                <ul className="mt-1 list-disc space-y-1 pl-4">
                                  {compactList(check.validation_steps).map((step) => (
                                    <li key={step}>{step}</li>
                                  ))}
                                </ul>
                              </div>
                            )}
                            {compactList(check.evidence_requirements).length > 0 && (
                              <div>
                                <p className="font-medium text-slate-800 dark:text-slate-100">投产证据</p>
                                <p className="mt-1">{compactList(check.evidence_requirements).join('、')}</p>
                              </div>
                            )}
                          </div>
                        )}
                        <div className="mt-3 flex items-center justify-between gap-3">
                          <p className="text-xs text-slate-500">{check.action.description}</p>
                          <Link href={check.action.href} className="inline-flex shrink-0 items-center rounded-md border border-slate-200 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800">
                            <ExternalLink className="mr-1 h-3 w-3" />
                            处理
                          </Link>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                {readinessCapabilities.map((capability) => (
                  <div key={capability.key} className="rounded-md border border-slate-200 p-4 dark:border-slate-800">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <h3 className="font-medium text-slate-900 dark:text-white">{capability.label}</h3>
                        <p className="mt-1 text-sm text-slate-500">{capability.summary}</p>
                      </div>
                      <Badge className={getReadinessColor(capability.status)}>{getReadinessLabel(capability.status)}</Badge>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {evidenceEntries(capability).map(([key, value]) => (
                        <span key={key} className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                          {key}: {String(value)}
                        </span>
                      ))}
                    </div>
                    {capability.blockers.length > 0 && (
                      <div className="mt-3 rounded-md bg-rose-50 p-3 text-sm text-rose-800 dark:bg-rose-950 dark:text-rose-100">
                        <p className="font-medium">阻断项</p>
                        <p className="mt-1">{capability.blockers[0]}</p>
                      </div>
                    )}
                    {capability.recommended_actions.length > 0 && (
                      <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">
                        建议：{capability.recommended_actions[0]}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Provider Health Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {providersLoading ? (
          <Card>
            <CardContent className="py-8 text-center text-slate-500">正在加载提供商...</CardContent>
          </Card>
        ) : providers.length === 0 ? (
          <Card className="md:col-span-3">
            <CardContent className="py-8 text-center text-slate-500">
              暂未配置提供商
            </CardContent>
          </Card>
        ) : (
          providers.map((provider) => (
            <Card key={provider.id}>
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <div className="flex items-center gap-3">
                  <div className="rounded-lg bg-indigo-100 dark:bg-indigo-900 p-2">
                    {getProviderIcon(provider.type)}
                    <span className="text-indigo-600 dark:text-indigo-400 h-5 w-5" />
                  </div>
                  <div>
                    <CardTitle className="text-base">{provider.name}</CardTitle>
                    <CardDescription className="text-xs capitalize">{provider.type}</CardDescription>
                  </div>
                </div>
                <Badge className={getProviderStatusColor(provider.is_active)}>
                  {provider.is_active ? '启用' : '停用'}
                </Badge>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-slate-500">状态</span>
                    <span className={provider.is_active ? 'text-green-600' : 'text-red-600'}>
                      {provider.is_active ? '运行正常' : '离线'}
                    </span>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))
        )}
      </div>

      {/* Metrics Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-slate-500">API 调用（24 小时）</CardTitle>
            <Activity className="h-4 w-4 text-slate-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {metrics?.total_api_calls_24h?.toLocaleString() || '0'}
            </div>
            <p className="text-xs text-slate-500 mt-1">
              {metrics?.active_users_24h || 0} 个活跃用户
            </p>
            {tenantMetricsData && (
              <p className="mt-1 text-xs text-slate-500">
                当前租户本月 {tenantMetricsData.api_calls_this_month.toLocaleString()} 次调用
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-slate-500">错误率</CardTitle>
            <AlertTriangle className="h-4 w-4 text-slate-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {metrics?.error_rate_percent?.toFixed(2) || '0.00'}%
            </div>
            <Progress
              value={metrics?.error_rate_percent || 0}
              max={100}
              className="mt-2 h-1"
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-slate-500">平均延迟</CardTitle>
            <Clock className="h-4 w-4 text-slate-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {metrics?.avg_latency_ms?.toFixed(0) || '0'} ms
            </div>
            <p className="text-xs text-slate-500 mt-1">最近 24 小时</p>
            {usageStats && (
              <p className="mt-1 text-xs text-slate-500">
                租户平均 {usageStats.average_latency_ms.toFixed(0)} ms
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-slate-500">活跃租户</CardTitle>
            <Users className="h-4 w-4 text-slate-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {metrics?.total_tenants || 0}
            </div>
            <p className="text-xs text-slate-500 mt-1">租户总数</p>
            {tenantMetricsData && (
              <p className="mt-1 text-xs text-slate-500">
                当前租户 {tenantMetricsData.user_count} 用户 / {tenantMetricsData.active_agents} 活跃 Agent
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Circuit Breakers */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Zap className="h-5 w-5" />
              熔断器
            </CardTitle>
            <CardDescription>提供商集成健康状态</CardDescription>
          </CardHeader>
          <CardContent>
            {circuitBreakers.length === 0 ? (
              <div className="text-center py-8 text-slate-500">
                <CheckCircle className="mx-auto h-10 w-10 text-slate-300" />
                <p className="mt-2">所有系统运行正常</p>
                <p className="text-sm">未触发熔断器</p>
              </div>
            ) : (
              <div className="space-y-3">
                {circuitBreakers.map((breaker) => (
                  <div
                    key={breaker.name}
                    className="flex items-center justify-between p-3 rounded-lg border border-slate-200 dark:border-slate-700"
                  >
                    <div className="flex items-center gap-3">
                      {getCircuitBreakerIcon(breaker.state)}
                      <div>
                        <p className="font-medium text-slate-900 dark:text-white">{breaker.name}</p>
                        <p className="text-xs text-slate-500 capitalize">{breaker.state.replace('_', ' ')}</p>
                      </div>
                    </div>
                    <div className="text-right">
                      <p className="text-sm text-slate-500">{breaker.failure_count} 次失败</p>
                      {breaker.last_failure_time && (
                        <p className="text-xs text-slate-400">
                          最近：{new Date(breaker.last_failure_time).toLocaleString('zh-CN')}
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Quota Usage */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <HardDrive className="h-5 w-5" />
              配额使用
            </CardTitle>
            <CardDescription>当前资源消耗</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {apiCallsQuota && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-slate-600 dark:text-slate-400">API 调用</span>
                    <span className="font-medium">
                      {apiCallsQuota.used_amount.toLocaleString()} / {apiCallsQuota.limit_amount.toLocaleString()}
                    </span>
                  </div>
                  <Progress
                    value={(apiCallsQuota.used_amount / apiCallsQuota.limit_amount) * 100}
                    max={100}
                    className="h-2"
                  />
                </div>
              )}

              {storageQuota && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-slate-600 dark:text-slate-400">存储</span>
                    <span className="font-medium">
                      {formatBytes(storageQuota.used_amount)} / {formatBytes(storageQuota.limit_amount)}
                    </span>
                  </div>
                  <Progress
                    value={(storageQuota.used_amount / storageQuota.limit_amount) * 100}
                    max={100}
                    className="h-2"
                  />
                </div>
              )}

              {usersQuota && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-slate-600 dark:text-slate-400">用户</span>
                    <span className="font-medium">
                      {usersQuota.used_amount} / {usersQuota.limit_amount}
                    </span>
                  </div>
                  <Progress
                    value={(usersQuota.used_amount / usersQuota.limit_amount) * 100}
                    max={100}
                    className="h-2"
                  />
                </div>
              )}

              {usageStats && (
                <div className="rounded-md bg-slate-50 p-3 text-sm text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                  <div className="flex items-center justify-between gap-3">
                    <span>租户请求成功率</span>
                    <span className="font-medium text-slate-900 dark:text-white">
                      {usageStats.total_requests > 0
                        ? `${Math.round((usageStats.successful_requests / usageStats.total_requests) * 100)}%`
                        : '无请求'}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    {usageStats.successful_requests.toLocaleString()} 成功 / {usageStats.failed_requests.toLocaleString()} 失败
                  </p>
                </div>
              )}

              {tightRateLimit && (
                <div className="rounded-md bg-slate-50 p-3 text-sm text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                  <div className="flex items-center justify-between gap-3">
                    <span>最紧张限流</span>
                    <span className="font-medium text-slate-900 dark:text-white">
                      {tightRateLimit.remaining}/{tightRateLimit.limit}
                    </span>
                  </div>
                  <p className="mt-1 truncate text-xs text-slate-500">{tightRateLimit.endpoint}</p>
                </div>
              )}

              {!apiCallsQuota && quotas.length === 0 && (
                <div className="text-center py-8 text-slate-500">
                  <FileText className="mx-auto h-10 w-10 text-slate-300" />
                  <p className="mt-2">暂无配额数据</p>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card data-testid="notification-delivery-operations">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Bell className="h-5 w-5" />
            通知投递运行记录
          </CardTitle>
          <CardDescription>邮件、Webhook 与系统渠道的投递证据和失败重试</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-4">
            <div className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
              <p className="text-xs text-slate-500">总投递</p>
              <p className="mt-1 text-xl font-semibold">{notificationDeliveriesData?.total || 0}</p>
            </div>
            <div className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
              <p className="text-xs text-slate-500">已发送</p>
              <p className="mt-1 text-xl font-semibold text-emerald-600">{notificationDeliveriesData?.sent_count || 0}</p>
            </div>
            <div className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
              <p className="text-xs text-slate-500">失败</p>
              <p className="mt-1 text-xl font-semibold text-rose-600">{notificationDeliveriesData?.failed_count || 0}</p>
            </div>
            <div className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
              <p className="text-xs text-slate-500">处理中</p>
              <p className="mt-1 text-xl font-semibold text-amber-600">{notificationDeliveriesData?.pending_count || 0}</p>
            </div>
          </div>
          {(notificationDeliveriesData?.items || []).length === 0 ? (
            <div className="rounded-md bg-slate-50 p-5 text-center text-sm text-slate-500 dark:bg-slate-900">暂无通知投递记录。</div>
          ) : (
            <div className="divide-y divide-slate-100 overflow-hidden rounded-md border border-slate-200 dark:divide-slate-700 dark:border-slate-700">
              {(notificationDeliveriesData?.items || []).map((delivery: NotificationDelivery) => (
                <div key={delivery.id} className="flex flex-wrap items-center justify-between gap-3 p-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-slate-900 dark:text-white">{delivery.title}</span>
                      <Badge className={delivery.status === 'sent' ? 'bg-emerald-100 text-emerald-800' : delivery.status === 'failed' ? 'bg-rose-100 text-rose-800' : 'bg-amber-100 text-amber-800'}>
                        {delivery.status}
                      </Badge>
                      <Badge variant="outline">{delivery.channel}</Badge>
                    </div>
                    <p className="mt-1 text-xs text-slate-500">重试 {delivery.retry_count} 次{delivery.error_message ? ` · ${delivery.error_message}` : ''}</p>
                  </div>
                  {delivery.status === 'failed' && (
                    <Button
                      size="sm"
                      variant="outline"
                      data-testid={`retry-notification-delivery-${delivery.id}`}
                      disabled={retryNotificationDelivery.isPending}
                      onClick={() => retryNotificationDelivery.mutate(delivery.id)}
                    >
                      <RefreshCw className="mr-2 h-4 w-4" />
                      重试投递
                    </Button>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Recent Audit Events */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-5 w-5" />
            最近审计事件
          </CardTitle>
          <CardDescription>最新系统事件和活动</CardDescription>
        </CardHeader>
        <CardContent>
          {auditEvents.length === 0 ? (
            <div className="text-center py-12 text-slate-500">
              <Clock className="mx-auto h-12 w-12 text-slate-300" />
              <p className="mt-4 text-lg font-medium">暂无最近事件</p>
              <p className="mt-2 text-sm">审计事件会显示在这里</p>
            </div>
          ) : (
            <div className="space-y-3">
              {auditEvents.map((event) => (
                <div
                  key={event.id}
                  className="flex items-start gap-4 p-4 rounded-lg border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800"
                >
                  <div className="flex-shrink-0 mt-0.5">
                    <Badge className={getSeverityColor(event.severity)}>
                      {event.severity}
                    </Badge>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-slate-900 dark:text-white">{event.description}</p>
                    <div className="flex items-center gap-3 mt-1 text-xs text-slate-500">
                      {event.user_email && <span>{event.user_email}</span>}
                      <span>{new Date(event.timestamp).toLocaleString('zh-CN')}</span>
                    </div>
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
