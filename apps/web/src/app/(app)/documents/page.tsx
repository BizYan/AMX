'use client'

import Link from 'next/link'
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowDownAZ,
  CalendarClock,
  CheckCircle2,
  FileSearch,
  FileText,
  FolderKanban,
  Plus,
  Search,
  ShieldCheck,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectOption } from '@/components/ui/select'
import { documentsApi, type Document } from '@/lib/api-client'
import { getDocumentStatusLabel, getDocumentTypeLabel } from '@/lib/document-labels'
import {
  getUnresolvedTemplatePlaceholders,
  hasTemplatePlaceholderBlocker,
  templatePlaceholderSummary,
} from '@/lib/document-template-placeholders'
import { formatDistanceToNow } from '@/lib/utils'

type RiskLevel = 'blocked' | 'attention' | 'ready'

const EMPTY_DOCUMENTS: Document[] = []

const STATUS_OPTIONS = [
  { value: 'all', label: '全部状态' },
  { value: 'draft', label: '草稿' },
  { value: 'writing', label: '编写中' },
  { value: 'review', label: '评审中' },
  { value: 'pending_review', label: '待评审' },
  { value: 'revision_required', label: '退回修订' },
  { value: 'approved', label: '已批准' },
  { value: 'published', label: '已发布' },
  { value: 'placeholder', label: '占位待补齐' },
]

const RISK_OPTIONS = [
  { value: 'all', label: '全部风险' },
  { value: 'blocked', label: '阻塞' },
  { value: 'attention', label: '需关注' },
  { value: 'ready', label: '可交付' },
]

const SORT_OPTIONS = [
  { value: 'updated_desc', label: '最近更新' },
  { value: 'type_asc', label: '文档类型' },
  { value: 'status_asc', label: '状态' },
  { value: 'name_asc', label: '名称' },
]

function riskLevel(document: Document): RiskLevel {
  const status = document.metadata?.status || document.status || 'draft'
  const metadata = document.metadata || {}
  if (hasTemplatePlaceholderBlocker(document)) return 'blocked'
  if (status === 'revision_required' || metadata.review_state === 'pending_review') return 'blocked'
  if (['draft', 'writing', 'review', 'pending_review', 'in_review'].includes(status)) return 'attention'
  return 'ready'
}

function riskLabel(level: RiskLevel) {
  return {
    blocked: '阻塞',
    attention: '需关注',
    ready: '可交付',
  }[level]
}

function formatDocumentAge(document: Document) {
  const timestamp = document.updatedAt || document.updated_at || document.createdAt
  return timestamp ? formatDistanceToNow(timestamp) : '未提供时间'
}

function riskBadgeClass(level: RiskLevel) {
  if (level === 'blocked') return 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200'
  if (level === 'attention') return 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200'
  return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200'
}

function riskReason(document: Document) {
  const status = document.metadata?.status || document.status || 'draft'
  const unresolvedTemplatePlaceholders = templatePlaceholderSummary(document)
  if (unresolvedTemplatePlaceholders) return `未填模板变量：${unresolvedTemplatePlaceholders}。补齐后才能发布、导出或纳入交付包。`
  if (status === 'placeholder' || document.metadata?.has_placeholders) return '仍是占位内容，需要补齐验收证据或重新生成。'
  if (status === 'revision_required') return '已退回修订，需要责任人处理后重新评审。'
  if (document.metadata?.review_state === 'pending_review') return '已进入评审队列，尚未完成评审闭环。'
  if (['draft', 'writing'].includes(status)) return '仍处于编写阶段，发布前需要评审和批准。'
  if (['review', 'pending_review', 'in_review'].includes(status)) return '正在评审中，需关闭评论和审批动作。'
  return '已达到批准或发布状态，可进入导出和交付检查。'
}

function sortDocuments(documents: Document[], sort: string) {
  const copy = [...documents]
  if (sort === 'type_asc') {
    return copy.sort((a, b) => getDocumentTypeLabel(a.type).localeCompare(getDocumentTypeLabel(b.type), 'zh-CN'))
  }
  if (sort === 'status_asc') {
    return copy.sort((a, b) =>
      getDocumentStatusLabel(a.metadata?.status || a.status).localeCompare(
        getDocumentStatusLabel(b.metadata?.status || b.status),
        'zh-CN'
      )
    )
  }
  if (sort === 'name_asc') {
    return copy.sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
  }
  return copy.sort((a, b) => new Date(b.updatedAt || b.updated_at || 0).getTime() - new Date(a.updatedAt || a.updated_at || 0).getTime())
}

function StatCard({ title, value, detail }: { title: string; value: string | number; detail: string }) {
  return (
    <Card>
      <CardContent className="pt-4">
        <p className="text-2xl font-semibold text-slate-900 dark:text-white">{value}</p>
        <p className="mt-1 text-xs text-slate-500">{title}</p>
        <p className="mt-2 text-xs text-slate-400">{detail}</p>
      </CardContent>
    </Card>
  )
}

export default function DocumentsPage() {
  const [query, setQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [riskFilter, setRiskFilter] = useState('all')
  const [sort, setSort] = useState('updated_desc')

  const documentsQuery = useQuery({
    queryKey: ['documents', 'global-registry'],
    queryFn: () => documentsApi.list({ pageSize: 100, includePlaceholders: true }),
  })
  const statisticsQuery = useQuery({
    queryKey: ['documents', 'statistics'],
    queryFn: documentsApi.getStatistics,
  })

  const documents = documentsQuery.data?.items || EMPTY_DOCUMENTS
  const typeOptions = useMemo(() => {
    const values = Array.from(new Set(documents.map((document) => document.type).filter(Boolean)))
    return [{ value: 'all', label: '全部类型' }, ...values.map((value) => ({ value, label: getDocumentTypeLabel(value) }))]
  }, [documents])

  const filteredDocuments = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()
    const filtered = documents.filter((document) => {
      const status = document.metadata?.status || document.status || 'draft'
      const risk = riskLevel(document)
      const searchable = [
        document.name,
        document.title || '',
        getDocumentTypeLabel(document.type),
        getDocumentStatusLabel(status),
        document.projectId || document.project_id || '',
        riskReason(document),
        getUnresolvedTemplatePlaceholders(document).join(' '),
      ].join(' ').toLowerCase()
      return (
        (!normalizedQuery || searchable.includes(normalizedQuery)) &&
        (typeFilter === 'all' || document.type === typeFilter) &&
        (statusFilter === 'all' || status === statusFilter) &&
        (riskFilter === 'all' || risk === riskFilter)
      )
    })
    return sortDocuments(filtered, sort)
  }, [documents, query, riskFilter, sort, statusFilter, typeFilter])

  const stats = {
    total: statisticsQuery.data?.total_documents ?? documents.length,
    published: statisticsQuery.data?.by_status?.published ?? documents.filter((document) => document.status === 'published').length,
    attention: documents.filter((document) => riskLevel(document) === 'attention').length,
    blocked: documents.filter((document) => riskLevel(document) === 'blocked').length,
  }

  const latestDocument = filteredDocuments[0]

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">全局文档注册表</h1>
          <p className="mt-1 text-sm text-slate-500">
            跨项目检索 URS、BRD、PRD、设计、测试和验收材料，快速定位交付风险和下一步动作。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" asChild>
            <Link href="/projects">
              <FolderKanban className="mr-2 h-4 w-4" />
              进入项目文档
            </Link>
          </Button>
          <Button asChild>
            <Link href="/projects">
              <Plus className="mr-2 h-4 w-4" />
              从项目创建
            </Link>
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <StatCard title="文档总数" value={stats.total} detail="当前租户全局文档资产" />
        <StatCard title="已发布" value={stats.published} detail="可进入导出和交付包" />
        <StatCard title="需关注" value={stats.attention} detail="编写或评审仍未闭环" />
        <StatCard title="阻塞" value={stats.blocked} detail="占位、退回或待评审阻塞" />
      </div>

      <Card>
        <CardContent className="py-4">
          <div className="grid gap-3 xl:grid-cols-[minmax(260px,1fr)_160px_160px_160px_160px]">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <Input
                data-testid="global-document-search"
                className="pl-10"
                placeholder="搜索文档名称、类型、项目 ID 或风险说明..."
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </div>
            <Select data-testid="global-document-type-filter" value={typeFilter} onValueChange={setTypeFilter}>
              {typeOptions.map((option) => (
                <SelectOption key={option.value} value={option.value}>{option.label}</SelectOption>
              ))}
            </Select>
            <Select data-testid="global-document-status-filter" value={statusFilter} onValueChange={setStatusFilter}>
              {STATUS_OPTIONS.map((option) => (
                <SelectOption key={option.value} value={option.value}>{option.label}</SelectOption>
              ))}
            </Select>
            <Select data-testid="global-document-risk-filter" value={riskFilter} onValueChange={setRiskFilter}>
              {RISK_OPTIONS.map((option) => (
                <SelectOption key={option.value} value={option.value}>{option.label}</SelectOption>
              ))}
            </Select>
            <Select data-testid="global-document-sort" value={sort} onValueChange={setSort}>
              {SORT_OPTIONS.map((option) => (
                <SelectOption key={option.value} value={option.value}>{option.label}</SelectOption>
              ))}
            </Select>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <FileSearch className="h-5 w-5" />
              文档资产清单
            </CardTitle>
            <CardDescription>显示 {filteredDocuments.length} 份匹配文档，按当前筛选条件排序。</CardDescription>
          </CardHeader>
          <CardContent>
            {documentsQuery.isLoading ? (
              <div className="py-10 text-center text-sm text-slate-500">正在加载文档...</div>
            ) : documentsQuery.isError ? (
              <div className="py-10 text-center text-sm text-red-500">文档加载失败，请稍后重试。</div>
            ) : filteredDocuments.length === 0 ? (
              <div className="flex flex-col items-center justify-center rounded-md border border-dashed border-slate-300 py-12 text-slate-500 dark:border-slate-700">
                <FileText className="h-12 w-12 text-slate-300" />
                <p className="mt-4 text-sm">没有匹配的文档</p>
                <Button variant="outline" className="mt-4" asChild>
                  <Link href="/projects">
                    <FolderKanban className="mr-2 h-4 w-4" />
                    返回项目文档
                  </Link>
                </Button>
              </div>
            ) : (
              <div className="space-y-3">
                {filteredDocuments.map((document) => {
                  const status = document.metadata?.status || document.status || 'draft'
                  const risk = riskLevel(document)
                  const unresolvedTemplatePlaceholders = getUnresolvedTemplatePlaceholders(document)
                  const href = document.projectId
                    ? `/projects/${document.projectId}/documents/${document.id}`
                    : '/projects'
                  return (
                    <div
                      key={document.id}
                      data-testid="global-document-row"
                      className="rounded-lg border border-slate-200 p-4 dark:border-slate-700"
                    >
                      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <div className="rounded-md bg-indigo-100 p-2 dark:bg-indigo-900">
                              <FileText className="h-4 w-4 text-indigo-600 dark:text-indigo-300" />
                            </div>
                            <p className="font-medium text-slate-900 dark:text-white">{document.name}</p>
                            <Badge variant="secondary">{getDocumentTypeLabel(document.type)}</Badge>
                            <Badge variant="secondary">{getDocumentStatusLabel(status)}</Badge>
                            <Badge className={riskBadgeClass(risk)}>{riskLabel(risk)}</Badge>
                          </div>
                          <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">{riskReason(document)}</p>
                          {unresolvedTemplatePlaceholders.length > 0 && (
                            <div
                              data-testid="global-document-template-placeholders"
                              className="mt-3 rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200"
                            >
                              未填模板变量：{unresolvedTemplatePlaceholders.join('、')}
                            </div>
                          )}
                          <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-500">
                            <span>所属项目：{document.projectId || document.project_id || '未知'}</span>
                            <span>更新：{formatDocumentAge(document)}</span>
                          </div>
                        </div>
                        <div className="flex shrink-0 flex-wrap gap-2">
                          <Button variant="outline" size="sm" asChild>
                            <Link href={href}>查看</Link>
                          </Button>
                          <Button variant="ghost" size="sm" asChild>
                            <Link href={document.projectId ? `/projects/${document.projectId}/documents/generate?docType=${document.type}` : '/projects'}>
                              继续编写
                            </Link>
                          </Button>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">交付风险摘要</CardTitle>
              <CardDescription>按当前文档状态判断是否可进入交付。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center justify-between rounded-md border border-slate-200 p-3 dark:border-slate-700">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 text-red-600" />
                  <span className="text-sm text-slate-700 dark:text-slate-200">阻塞项</span>
                </div>
                <Badge className={riskBadgeClass('blocked')}>{stats.blocked}</Badge>
              </div>
              <div className="flex items-center justify-between rounded-md border border-slate-200 p-3 dark:border-slate-700">
                <div className="flex items-center gap-2">
                  <CalendarClock className="h-4 w-4 text-amber-600" />
                  <span className="text-sm text-slate-700 dark:text-slate-200">需关注</span>
                </div>
                <Badge className={riskBadgeClass('attention')}>{stats.attention}</Badge>
              </div>
              <div className="flex items-center justify-between rounded-md border border-slate-200 p-3 dark:border-slate-700">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                  <span className="text-sm text-slate-700 dark:text-slate-200">可交付</span>
                </div>
                <Badge className={riskBadgeClass('ready')}>{documents.filter((document) => riskLevel(document) === 'ready').length}</Badge>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <ArrowDownAZ className="h-5 w-5" />
                类型分布
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {Object.entries(statisticsQuery.data?.by_type || {}).length === 0 ? (
                <p className="text-sm text-slate-500">暂无类型统计。</p>
              ) : (
                Object.entries(statisticsQuery.data?.by_type || {}).map(([type, count]) => (
                  <div key={type} className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2 text-sm dark:bg-slate-900/50">
                    <span>{getDocumentTypeLabel(type)}</span>
                    <Badge variant="secondary">{count}</Badge>
                  </div>
                ))
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <ShieldCheck className="h-5 w-5" />
                下一步
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm text-slate-600 dark:text-slate-300">
              <p>{latestDocument ? `最近需要处理：${latestDocument.name}` : '暂无可处理文档。'}</p>
              <Button variant="outline" className="w-full" asChild>
                <Link href="/documents/contradictions">查看冲突与追溯</Link>
              </Button>
              <Button variant="outline" className="w-full" asChild>
                <Link href="/exports">进入导出中心</Link>
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
