'use client'

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowLeft, Check, GitCompare, Link2, Network, Search, X } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { changeApi, documentsApi } from '@/lib/api-client'
import type { DocumentImpactAnalysis, DocumentSyncProposal } from '@/lib/api-client'
import { getDocumentTypeLabel } from '@/lib/document-labels'
import { useToast } from '@/components/ui/toast'

interface TraceabilityPageProps {
  params: { projectId: string }
}

const riskLabels: Record<string, string> = {
  critical: 'P0',
  high: 'P1',
  medium: 'P2',
  low: 'P3',
}

const actionLabels: Record<string, string> = {
  pending: '待人工确认',
  applied: '已确认同步',
  rejected: '已忽略建议',
}

function riskVariant(level: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (level === 'critical' || level === 'high') return 'destructive'
  if (level === 'medium') return 'secondary'
  return 'outline'
}

function proposalRisk(proposal: DocumentSyncProposal) {
  return proposal.metadata_json?.risk_level || proposal.impact_level || 'medium'
}

export default function TraceabilityPage({ params }: TraceabilityPageProps) {
  const { projectId } = params
  const router = useRouter()
  const queryClient = useQueryClient()
  const { addToast } = useToast()
  const [search, setSearch] = useState('')
  const [feedback, setFeedback] = useState('')
  const [latestAnalysis, setLatestAnalysis] = useState<DocumentImpactAnalysis | null>(null)
  const [selectedProposalId, setSelectedProposalId] = useState<string | null>(null)
  const [localDecisions, setLocalDecisions] = useState<Record<string, 'applied' | 'rejected'>>({})

  const { data: documentsData, isLoading: documentsLoading } = useQuery({
    queryKey: ['project-documents', projectId, 'traceability-board'],
    queryFn: () => documentsApi.list({ projectId, pageSize: 100, includePlaceholders: false }),
  })

  const { data: matrixData } = useQuery({
    queryKey: ['traceability-matrix', projectId],
    queryFn: () => changeApi.getTraceabilityMatrix(projectId),
  })

  const { data: coverageData, isLoading: coverageLoading } = useQuery({
    queryKey: ['traceability-coverage', projectId],
    queryFn: () => changeApi.getTraceabilityCoverage(projectId),
  })

  const documents = useMemo(() => documentsData?.items || [], [documentsData?.items])
  const documentMap = useMemo(() => new Map(documents.map((doc) => [doc.id, doc])), [documents])
  const publishedSource = documents.find((doc) => doc.type === 'urs' && doc.status === 'published') || documents[0]
  const summary = coverageData?.summary

  const runAnalysisMutation = useMutation({
    mutationFn: () =>
      changeApi.createDocumentImpactAnalysis(publishedSource?.id || '', {
        trigger_type: 'content_changed',
        summary: 'URS 变更影响 PRD，触发下游同步提案与人工确认节点。',
      }),
    onSuccess: (analysis) => {
      setLatestAnalysis(analysis)
      setSelectedProposalId(analysis.proposals[0]?.id || null)
      setFeedback('影响分析已生成，等待人工确认')
      addToast({ title: '影响分析已生成', description: `${analysis.proposals.length} 条同步提案待处理` })
    },
    onError: (error: Error) => {
      addToast({ title: '影响分析失败', description: error.message, variant: 'destructive' })
    },
  })

  const proposalMutation = useMutation({
    mutationFn: ({ proposal, action }: { proposal: DocumentSyncProposal; action: 'apply' | 'reject' }) => {
      const note = action === 'apply' ? '确认同步到 PRD' : '忽略建议，保留人工确认记录'
      return action === 'apply'
        ? changeApi.applySyncProposal(proposal.id, { decision_note: note })
        : changeApi.rejectSyncProposal(proposal.id, { decision_note: note })
    },
    onSuccess: async (proposal, variables) => {
      const status = variables.action === 'apply' ? 'applied' : 'rejected'
      setLocalDecisions((current) => ({ ...current, [proposal.id]: status }))
      setFeedback(status === 'applied' ? '已确认同步：同步提案进入处置记录' : '已忽略建议：保留人工确认记录')
      if (latestAnalysis) {
        try {
          setLatestAnalysis(await changeApi.getDocumentImpactAnalysis(latestAnalysis.id))
        } catch {
          setLatestAnalysis((current) => current && {
            ...current,
            proposals: current.proposals.map((item) => item.id === proposal.id ? { ...item, status } : item),
          })
        }
      }
      queryClient.invalidateQueries({ queryKey: ['traceability-coverage', projectId] })
      addToast({ title: status === 'applied' ? '已确认同步' : '已忽略建议' })
    },
    onError: (error: Error) => {
      addToast({ title: '处理同步提案失败', description: error.message, variant: 'destructive' })
    },
  })

  const acceptSuggestionsMutation = useMutation({
    mutationFn: () => changeApi.acceptTraceabilitySuggestions(projectId),
    onSuccess: (result) => {
      setFeedback(`已建立 ${result.created} 条正式追溯引用，跳过 ${result.skipped} 条。`)
      queryClient.invalidateQueries({ queryKey: ['traceability-coverage', projectId] })
      queryClient.invalidateQueries({ queryKey: ['traceability-matrix', projectId] })
      addToast({ title: '追溯引用已建立', description: `新增 ${result.created} 条正式引用。` })
    },
    onError: (error: Error) => {
      addToast({ title: '建立追溯引用失败', description: error.message, variant: 'destructive' })
    },
  })

  const proposals = latestAnalysis?.proposals || []
  const suggestionCount = coverageData?.suggestions.length ?? 0
  const selectedProposal = proposals.find((proposal) => proposal.id === selectedProposalId) || proposals[0]
  const normalizedSearch = search.trim().toLowerCase()
  const filteredGaps = (coverageData?.gaps || []).filter((gap) => {
    if (!normalizedSearch) return true
    return [gap.document_title, gap.document_type, gap.reason, gap.suggested_action]
      .join(' ')
      .toLowerCase()
      .includes(normalizedSearch)
  })

  const filteredProposals = proposals.filter((proposal) => {
    if (!normalizedSearch) return true
    const target = documentMap.get(proposal.target_document_id)
    return [target?.name, proposal.reason, proposal.suggested_action, proposal.metadata_json?.risk_level]
      .join(' ')
      .toLowerCase()
      .includes(normalizedSearch)
  })

  const proposalStatus = (proposal: DocumentSyncProposal): string => localDecisions[proposal.id] || proposal.status

  if (documentsLoading) {
    return <div className="flex h-64 items-center justify-center text-slate-500">正在加载追溯处置台...</div>
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center">
        <Button variant="ghost" size="sm" onClick={() => router.push(`/projects/${projectId}`)} className="w-fit">
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex flex-1 items-center gap-3">
          <div className="rounded-lg bg-indigo-100 p-2 dark:bg-indigo-900">
            <Network className="h-6 w-6 text-indigo-600 dark:text-indigo-300" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">追溯与变更处置台</h1>
            <p className="text-sm text-slate-500">集中查看上游变更、覆盖率、同步提案、风险分级和人工确认记录。</p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            onClick={() => acceptSuggestionsMutation.mutate()}
            disabled={!suggestionCount || acceptSuggestionsMutation.isPending}
            data-testid="trace-accept-suggestions"
          >
            <Link2 className="mr-2 h-4 w-4" />
            建立建议引用
          </Button>
          <Button onClick={() => runAnalysisMutation.mutate()} disabled={!publishedSource || runAnalysisMutation.isPending} data-testid="trace-run-analysis">
            <GitCompare className="mr-2 h-4 w-4" />
            生成影响分析
          </Button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">覆盖率</CardTitle></CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold" data-testid="trace-coverage-rate">
              {coverageLoading ? '加载中' : `${summary?.coverage_rate ?? 0}%`}
            </div>
            <p className="text-xs text-slate-500">{summary?.referenced_documents ?? 0} / {summary?.published_documents ?? 0} 已发布文档已引用</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">待同步提案</CardTitle></CardHeader>
          <CardContent><div className="text-3xl font-semibold">{summary?.pending_sync_proposals ?? proposals.length}</div></CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">未闭环缺口</CardTitle></CardHeader>
          <CardContent><div className="text-3xl font-semibold">{coverageData?.gaps.length ?? 0}</div></CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">处置反馈</CardTitle></CardHeader>
          <CardContent><div className="text-sm text-slate-600" data-testid="trace-feedback">{feedback || '等待操作'}</div></CardContent>
        </Card>
      </div>

      <Card>
        <CardContent className="flex flex-col gap-3 py-4 md:flex-row md:items-center">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
            <Input data-testid="trace-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索文档、PRD、测试用例缺失或风险原因" className="pl-9" />
          </div>
          <Button variant="outline" onClick={() => runAnalysisMutation.mutate()} disabled={runAnalysisMutation.isPending}>刷新提案</Button>
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-[1fr_1.1fr]">
        <Card data-testid="trace-matrix">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base"><Link2 className="h-4 w-4" />追溯矩阵与上下游引用</CardTitle>
            <CardDescription>URS &gt; BRD &gt; PRD &gt; 设计 &gt; 测试用例，矩阵记录 {matrixData?.total ?? 0} 条。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {documents.map((doc) => (
              <div key={doc.id} className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-slate-200 p-3 dark:border-slate-700">
                <div>
                  <div className="font-medium text-slate-900 dark:text-white">{doc.name}</div>
                  <div className="text-xs text-slate-500">{getDocumentTypeLabel(doc.type)} · 上游/下游引用待处置台汇总</div>
                </div>
                <Badge variant={doc.status === 'published' ? 'default' : 'secondary'}>{doc.type.toUpperCase()}</Badge>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card data-testid="impact-summary">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base"><AlertTriangle className="h-4 w-4" />影响分析摘要</CardTitle>
            <CardDescription>URS 变更影响 PRD，下游测试用例缺失，需要人工确认节点。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="rounded-md bg-amber-50 p-4 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-100">
              URS 业务规则更新后，PRD 验收标准与测试用例需要同步复核；P0/P1/P2/P3 风险分级用于安排处置顺序。
            </div>
            {filteredProposals.length === 0 ? (
              <div className="rounded-md border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">点击“生成影响分析”查看待同步提案</div>
            ) : filteredProposals.map((proposal) => {
              const risk = proposalRisk(proposal)
              const target = documentMap.get(proposal.target_document_id)
              const status = proposalStatus(proposal)
              return (
                <button
                  key={proposal.id}
                  type="button"
                  onClick={() => setSelectedProposalId(proposal.id)}
                  className="w-full rounded-md border border-slate-200 p-4 text-left hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
                  data-testid={`sync-proposal-select-${proposal.id}`}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={riskVariant(risk)}>{riskLabels[risk] || risk}</Badge>
                    <span className="font-medium text-slate-900 dark:text-white">{target?.name || proposal.target_document_id}</span>
                    <Badge variant="outline">{actionLabels[status] || status}</Badge>
                  </div>
                  <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{proposal.reason}</p>
                </button>
              )
            })}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <Card data-testid="trace-gap-list">
          <CardHeader>
            <CardTitle className="text-base">覆盖缺口</CardTitle>
            <CardDescription>包含测试用例缺失、PRD 待同步和孤立文档。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {filteredGaps.map((gap) => (
              <div key={`${gap.document_id}-${gap.code}`} className="rounded-md border border-slate-200 p-4 dark:border-slate-700">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={riskVariant(gap.severity)}>{riskLabels[gap.severity] || gap.severity}</Badge>
                  <span className="font-medium">{gap.document_title}</span>
                  <span className="text-xs text-slate-500">{gap.document_type.toUpperCase()}</span>
                </div>
                <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{gap.reason}</p>
                <p className="mt-1 text-xs text-slate-500">{gap.suggested_action}</p>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card data-testid="sync-proposal-detail">
          <CardHeader>
            <CardTitle className="text-base">同步提案详情</CardTitle>
            <CardDescription>选中提案后确认同步或忽略建议，按钮均有可见反馈。</CardDescription>
          </CardHeader>
          <CardContent>
            {selectedProposal ? (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={riskVariant(proposalRisk(selectedProposal))}>{riskLabels[proposalRisk(selectedProposal)] || proposalRisk(selectedProposal)}</Badge>
                  <Badge variant="secondary">{actionLabels[proposalStatus(selectedProposal)] || proposalStatus(selectedProposal)}</Badge>
                </div>
                <div>
                  <div className="text-sm font-medium text-slate-900 dark:text-white">{documentMap.get(selectedProposal.target_document_id)?.name || selectedProposal.target_document_id}</div>
                  <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{selectedProposal.reason}</p>
                  <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{selectedProposal.candidate_content}</p>
                  <p className="mt-2 text-xs text-slate-500">{selectedProposal.suggested_action || '确认同步到 PRD'} · 人工确认节点</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    onClick={() => proposalMutation.mutate({ proposal: selectedProposal, action: 'apply' })}
                    disabled={proposalMutation.isPending || proposalStatus(selectedProposal) !== 'pending'}
                    data-testid={`sync-proposal-confirm-${selectedProposal.id}`}
                  >
                    <Check className="mr-2 h-4 w-4" />
                    确认同步
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => proposalMutation.mutate({ proposal: selectedProposal, action: 'reject' })}
                    disabled={proposalMutation.isPending || proposalStatus(selectedProposal) !== 'pending'}
                    data-testid={`sync-proposal-ignore-${selectedProposal.id}`}
                  >
                    <X className="mr-2 h-4 w-4" />
                    忽略建议
                  </Button>
                </div>
              </div>
            ) : (
              <div className="rounded-md border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">尚未选择同步提案</div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
