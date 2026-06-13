'use client'

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useCurrentUser } from '@/lib/auth'
import { opsApi, providersApi } from '@/lib/api-client'
import Link from 'next/link'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useToast } from '@/components/ui/toast'
import {
  Activity,
  AlertTriangle,
  Download,
  RefreshCw,
  Server,
  ShieldAlert,
  TrendingUp,
  Zap,
} from 'lucide-react'

type QuotaData = {
  used: number
  limit: number
  resetAt: string
  period: string
}

type RateLimitData = {
  endpoint: string
  limit: number
  remaining: number
  resetAt: string
}

type UsageStats = {
  totalRequests: number
  successfulRequests: number
  failedRequests: number
  averageLatency: number
}

type ProviderOpsProfile = {
  health?: 'healthy' | 'degraded' | 'unhealthy'
  quota_impact?: string
  sandbox_fallback?: boolean
}

type ProviderRisk = {
  id: string
  name: string
  health: 'degraded' | 'unhealthy'
  impact: string
  fallback: boolean
}

type ExportCell = string | number

const PERIOD_LABELS: Record<string, string> = {
  day: '每日',
  daily: '每日',
  week: '每周',
  weekly: '每周',
  month: '每月',
  monthly: '每月',
  year: '每年',
  yearly: '每年',
}

function matchesApiQuota(quotaType: string) {
  const normalized = quotaType.toLowerCase()
  return normalized === 'api_calls' || normalized === 'api_requests' || normalized === 'api'
}

function quotaRisk(percentage: number, failureRate: number) {
  if (percentage >= 90 || failureRate >= 5) return { label: '高风险', className: 'bg-rose-100 text-rose-800 dark:bg-rose-900 dark:text-rose-100' }
  if (percentage >= 70 || failureRate >= 2) return { label: '中风险', className: 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-100' }
  return { label: '低风险', className: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100' }
}

function progressColor(percentage: number) {
  if (percentage >= 90) return 'bg-rose-500'
  if (percentage >= 70) return 'bg-amber-500'
  return 'bg-emerald-500'
}

export default function QuotasPage() {
  const { data: currentUser } = useCurrentUser()
  const tenantId = currentUser?.tenantId
  const { addToast } = useToast()
  const [actionNotice, setActionNotice] = useState<string | null>(null)

  const { data: commandCenter, isLoading: commandCenterLoading, refetch: refetchCommandCenter } = useQuery({
    queryKey: ['quota-command-center', tenantId],
    queryFn: () => opsApi.getQuotaCommandCenter(tenantId!),
    enabled: !!tenantId,
  })

  const { data: quotasData, isLoading: quotasLoading, refetch: refetchQuotas } = useQuery({
    queryKey: ['quotas', tenantId],
    queryFn: async () => {
      if (!tenantId) return null
      const response = await opsApi.listQuotas(tenantId)
      const quotas = response.quotas || []
      const apiQuota = quotas.find((quota: any) => matchesApiQuota(String(quota.quota_type || '')))
      const apiUsed = apiQuota?.used_amount || 0
      const apiLimit = apiQuota?.limit_amount || 10000

      return {
        quotaData: {
          used: Math.round(apiUsed),
          limit: apiLimit,
          resetAt: apiQuota?.reset_at || new Date(Date.now() + 86400000 * 5).toISOString(),
          period: apiQuota?.period || 'month',
        } as QuotaData,
      }
    },
    enabled: !!tenantId,
  })

  const { data: usageStatsData, isLoading: usageStatsLoading, refetch: refetchUsageStats } = useQuery({
    queryKey: ['usage-stats', tenantId],
    queryFn: async () => {
      if (!tenantId) return null
      const response = await opsApi.getUsageStats(tenantId)
      return {
        totalRequests: response.total_requests,
        successfulRequests: response.successful_requests,
        failedRequests: response.failed_requests,
        averageLatency: response.average_latency_ms,
      } as UsageStats
    },
    enabled: !!tenantId,
  })

  const { data: rateLimitsData, isLoading: rateLimitsLoading, refetch: refetchRateLimits } = useQuery({
    queryKey: ['rate-limits', tenantId],
    queryFn: async () => {
      if (!tenantId) return []
      const response = await opsApi.getRateLimits(tenantId)
      return response.rate_limits.map((limit: any) => ({
        endpoint: limit.endpoint,
        limit: limit.limit,
        remaining: limit.remaining,
        resetAt: limit.reset_at,
      })) as RateLimitData[]
    },
    enabled: !!tenantId,
  })

  const { data: providersResponse } = useQuery({
    queryKey: ['providers'],
    queryFn: () => providersApi.list({ pageSize: 100 }),
  })

  const { data: circuitBreakers } = useQuery({
    queryKey: ['circuit-breakers'],
    queryFn: () => opsApi.listCircuitBreakers(),
  })

  const quotaData = quotasData?.quotaData || { used: 0, limit: 10000, resetAt: '', period: 'month' }
  const usageStats = usageStatsData || { totalRequests: 0, successfulRequests: 0, failedRequests: 0, averageLatency: 0 }
  const rateLimits = rateLimitsData || []
  const providers = useMemo(() => providersResponse?.items || [], [providersResponse?.items])
  const breakers = useMemo(() => circuitBreakers?.breakers || [], [circuitBreakers?.breakers])

  const isLoading = quotasLoading || usageStatsLoading || rateLimitsLoading || commandCenterLoading
  const quotaPercentage = quotaData.limit > 0 ? Math.round((quotaData.used / quotaData.limit) * 100) : 0
  const quotaRemaining = Math.max(quotaData.limit - quotaData.used, 0)
  const failureRate = usageStats.totalRequests > 0 ? Number(((usageStats.failedRequests / usageStats.totalRequests) * 100).toFixed(1)) : 0
  const risk = quotaRisk(quotaPercentage, failureRate)
  const dailyBurn = Math.max(Math.round(usageStats.totalRequests / 7), 1)
  const daysRemaining = Math.max(Math.floor(quotaRemaining / dailyBurn), 0)

  const providerRisks = useMemo<ProviderRisk[]>(() => providers
    .map((provider: any) => {
      const opsProfile = (provider.ops_profile || {}) as ProviderOpsProfile
      const type = String(provider.type || provider.provider_type || '').toLowerCase()
      const breaker = breakers.find((item: { name: string; state: string }) => item.name.toLowerCase().includes(type) || provider.name.toLowerCase().includes(item.name.toLowerCase().replace('-service-breaker', '')))
      const health = opsProfile.health || (breaker?.state === 'open' ? 'unhealthy' : breaker?.state === 'half_open' ? 'degraded' : 'healthy')
      return {
        id: provider.id,
        name: provider.name,
        health,
        impact: opsProfile.quota_impact || (health === 'healthy' ? '配额消耗稳定' : '失败重试正在推高 API 调用消耗'),
        fallback: Boolean(opsProfile.sandbox_fallback),
      }
    })
    .filter((item: { health: string; fallback: boolean }) => item.health !== 'healthy' || item.fallback)
    .map((item: { id: string; name: string; health: string; impact: string; fallback: boolean }) => ({
      ...item,
      health: item.health === 'unhealthy' ? 'unhealthy' : 'degraded',
    })), [providers, breakers])

  const handleRefresh = async () => {
    await Promise.all([refetchCommandCenter(), refetchQuotas(), refetchUsageStats(), refetchRateLimits()])
    setActionNotice('监控数据已刷新，供应商风险与限流端点已重新计算')
    addToast({ title: '监控数据已刷新' })
  }

  const handleExport = () => {
    const rows: ExportCell[][] = [
      ['指标', '数值'],
      ['API 配额已用', quotaData.used],
      ['API 配额上限', quotaData.limit],
      ['配额剩余', quotaRemaining],
      ['API 配额使用率', `${quotaPercentage}%`],
      ['风险等级', risk.label],
      ['失败率', `${failureRate}%`],
      ['平均延迟(ms)', usageStats.averageLatency],
      ['消耗趋势', `${daysRemaining} 天后触顶`],
      [],
      ['限流端点', '剩余', '上限', '重置时间'],
      ...rateLimits.map((limit) => [limit.endpoint, limit.remaining, limit.limit, limit.resetAt ? new Date(limit.resetAt).toLocaleString('zh-CN') : '']),
      [],
      ['供应商风险影响', '状态', '影响'],
      ...providerRisks.map((provider) => [provider.name, provider.health, provider.impact]),
    ]
    const csv = rows.map((row: ExportCell[]) => row.map((cell: ExportCell) => `"${String(cell ?? '').replace(/"/g, '""')}"`).join(',')).join('\n')
    const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = window.document.createElement('a')
    link.href = url
    link.download = `quota-ops-report-${new Date().toISOString().slice(0, 10)}.csv`
    link.click()
    URL.revokeObjectURL(url)
    setActionNotice('配额运营报告已导出，包含供应商风险影响和限流端点')
    addToast({ title: '配额运营报告已导出' })
  }

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="text-slate-500">正在加载配额运营数据...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">配额运营视图</h1>
          <p className="mt-1 text-sm text-slate-500">把配额剩余、消耗趋势、限流端点和供应商风险放在同一处处置。</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={handleRefresh}>
            <RefreshCw className="mr-2 h-4 w-4" />
            刷新
          </Button>
          <Button variant="outline" onClick={handleExport}>
            <Download className="mr-2 h-4 w-4" />
            导出报告
          </Button>
        </div>
      </div>

      {actionNotice && (
        <div className="rounded-md border border-indigo-200 bg-indigo-50 px-4 py-3 text-sm text-indigo-900 dark:border-indigo-900 dark:bg-indigo-950 dark:text-indigo-100">
          {actionNotice}
        </div>
      )}

      {commandCenter && (
        <section className="space-y-4" data-testid="quota-command-center">
          <Card
            className={
              commandCenter.release_gate.status === 'blocked'
                ? 'border-rose-300 dark:border-rose-800'
                : commandCenter.release_gate.status === 'attention'
                  ? 'border-amber-300 dark:border-amber-800'
                  : 'border-emerald-300 dark:border-emerald-800'
            }
            data-testid="quota-operating-gate"
          >
            <CardHeader>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <CardTitle>生产配额操作门禁</CardTitle>
                  <CardDescription className="mt-1">{commandCenter.release_gate.summary}</CardDescription>
                </div>
                <Badge
                  className={
                    commandCenter.release_gate.status === 'blocked'
                      ? 'bg-rose-100 text-rose-800'
                      : commandCenter.release_gate.status === 'attention'
                        ? 'bg-amber-100 text-amber-800'
                        : 'bg-emerald-100 text-emerald-800'
                  }
                >
                  {commandCenter.release_gate.label}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <div><p className="text-xs text-slate-500">API 使用率</p><p className="text-xl font-semibold">{commandCenter.summary.api_usage_percent}%</p></div>
              <div><p className="text-xs text-slate-500">失败率</p><p className="text-xl font-semibold">{commandCenter.summary.failure_rate_percent}%</p></div>
              <div><p className="text-xs text-slate-500">风险端点</p><p className="text-xl font-semibold">{commandCenter.summary.risky_endpoint_count}</p></div>
              <div><p className="text-xs text-slate-500">打开熔断器</p><p className="text-xl font-semibold">{commandCenter.summary.open_breaker_count}</p></div>
            </CardContent>
          </Card>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <Card data-testid="quota-priority-actions">
              <CardHeader>
                <CardTitle>优先处置动作</CardTitle>
                <CardDescription>后端基于配额、限流、Provider 和熔断器证据生成。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {commandCenter.priority_actions.length === 0 ? (
                  <p className="text-sm text-slate-500">当前没有需要立即处置的动作。</p>
                ) : commandCenter.priority_actions.map((action) => (
                  <div key={action.code} className="flex flex-col gap-3 border-b border-slate-100 pb-3 last:border-0 last:pb-0 sm:flex-row sm:items-start sm:justify-between dark:border-slate-800">
                    <div>
                      <p className="font-medium text-slate-900 dark:text-white">{action.title}</p>
                      <p className="mt-1 text-sm text-slate-500">{action.description}</p>
                    </div>
                    <Button asChild variant="outline" size="sm"><Link href={action.href}>进入处置</Link></Button>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card data-testid="quota-rate-limit-risks">
              <CardHeader>
                <CardTitle>高风险限流端点</CardTitle>
                <CardDescription>仅显示剩余额度低于或等于 10% 的端点。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {commandCenter.rate_limit_risks.length === 0 ? (
                  <p className="text-sm text-slate-500">当前没有高风险限流端点。</p>
                ) : commandCenter.rate_limit_risks.map((item) => (
                  <div key={item.endpoint} className="flex items-center justify-between gap-3 rounded-md bg-slate-50 p-3 dark:bg-slate-900">
                    <div>
                      <p className="font-medium text-slate-900 dark:text-white">{item.endpoint}</p>
                      <p className="text-xs text-slate-500">已使用 {item.used_percentage}%</p>
                    </div>
                    <Badge variant="secondary">{item.remaining} / {item.limit}</Badge>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>
        </section>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center gap-3">
              <Activity className="h-5 w-5 text-indigo-500" />
              <div>
                <p className="text-2xl font-bold">{quotaRemaining.toLocaleString()}</p>
                <p className="text-xs text-slate-500">配额剩余</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center gap-3">
              <TrendingUp className="h-5 w-5 text-amber-500" />
              <div>
                <p className="text-2xl font-bold">{daysRemaining} 天</p>
                <p className="text-xs text-slate-500">消耗趋势</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center gap-3">
              <ShieldAlert className="h-5 w-5 text-rose-500" />
              <div>
                <Badge className={risk.className}>{risk.label}</Badge>
                <p className="mt-1 text-xs text-slate-500">风险等级</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center gap-3">
              <Zap className="h-5 w-5 text-emerald-500" />
              <div>
                <p className="text-2xl font-bold">{usageStats.averageLatency}ms</p>
                <p className="text-xs text-slate-500">平均延迟</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <div className="flex items-start justify-between gap-3">
              <div>
                <CardTitle>API 配额使用情况</CardTitle>
                <CardDescription>重置时间：{quotaData.resetAt ? new Date(quotaData.resetAt).toLocaleDateString('zh-CN') : '-'}</CardDescription>
              </div>
              <Badge className={risk.className}>已使用 {quotaPercentage}%</Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-600 dark:text-slate-400">{quotaData.used.toLocaleString()} / {quotaData.limit.toLocaleString()} 次请求</span>
                <span className="font-medium text-slate-900 dark:text-white">{PERIOD_LABELS[quotaData.period] || quotaData.period}</span>
              </div>
              <div className="relative h-4 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                <div className={`absolute inset-y-0 left-0 ${progressColor(quotaPercentage)} transition-all duration-500`} style={{ width: `${quotaPercentage}%` }} />
              </div>
            </div>
            <div className="grid grid-cols-1 gap-4 border-t border-slate-100 pt-4 sm:grid-cols-3 dark:border-slate-800">
              <div>
                <p className="text-xs text-slate-500">请求总数</p>
                <p className="text-2xl font-bold text-slate-900 dark:text-white">{usageStats.totalRequests.toLocaleString()}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500">失败率</p>
                <p className="text-2xl font-bold text-slate-900 dark:text-white">{failureRate}%</p>
              </div>
              <div>
                <p className="text-xs text-slate-500">失败请求</p>
                <p className="text-2xl font-bold text-slate-900 dark:text-white">{usageStats.failedRequests.toLocaleString()}</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>供应商风险影响</CardTitle>
            <CardDescription>异常供应商会推高失败重试和配额消耗。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {providerRisks.length === 0 ? (
              <div className="text-sm text-slate-500">当前供应商风险未放大配额消耗。</div>
            ) : (
              providerRisks.map((provider) => (
                <div key={provider.id} className="rounded-md bg-slate-50 p-3 text-sm dark:bg-slate-900">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-slate-900 dark:text-white">{provider.name}</span>
                    <Badge className={provider.health === 'unhealthy' ? 'bg-rose-100 text-rose-800' : 'bg-amber-100 text-amber-800'}>
                      {provider.health === 'unhealthy' ? '异常' : '降级'}
                    </Badge>
                  </div>
                  <p className="mt-2 text-slate-600 dark:text-slate-300">{provider.impact}</p>
                  {provider.fallback && <p className="mt-1 text-xs font-medium text-amber-700 dark:text-amber-300">Graphify 沙箱 fallback 触发额外重试</p>}
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>限流端点</CardTitle>
          <CardDescription>剩余额度低的端点优先排查调用重试和熔断来源。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {rateLimits.map((limit) => {
            const usedPercentage = limit.limit > 0 ? Math.round(((limit.limit - limit.remaining) / limit.limit) * 100) : 0
            return (
              <div key={limit.endpoint} className="space-y-2">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-center gap-2">
                    <Server className="h-4 w-4 text-slate-400" />
                    <span className="text-sm font-medium text-slate-900 dark:text-white">{limit.endpoint}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-slate-500">重置：{new Date(limit.resetAt).toLocaleTimeString('zh-CN')}</span>
                    <Badge variant="secondary" className="text-xs">{limit.remaining} / {limit.limit}</Badge>
                  </div>
                </div>
                <div className="relative h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                  <div className={`absolute inset-y-0 left-0 ${progressColor(usedPercentage)} transition-all duration-500`} style={{ width: `${usedPercentage}%` }} />
                </div>
              </div>
            )
          })}
        </CardContent>
      </Card>

      {(quotaPercentage >= 70 || failureRate >= 2) && (
        <Card className="border-amber-200 dark:border-amber-800">
          <CardContent className="py-4">
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 text-amber-500" />
              <div>
                <h4 className="font-medium text-slate-900 dark:text-white">处置建议</h4>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
                  当前 API 配额已使用 {quotaPercentage}%，失败率 {failureRate}%。请优先处理降级供应商、减少失败重试，并在触顶前导出报告给运营负责人。
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
