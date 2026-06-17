'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useToast } from '@/components/ui/toast'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Select, SelectOption } from '@/components/ui/select'
import { useCurrentUser } from '@/lib/auth'
import { changeApi, documentsApi, projectsApi, type Document, type DocumentConflict, type DocumentConflictDecision } from '@/lib/api-client'
import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ClipboardCheck,
  FileSearch,
  FileText,
  GitCompare,
  History,
  Link2,
  RefreshCw,
  Search,
  ShieldCheck,
  XCircle,
} from 'lucide-react'

type ConflictSeverity = 'high' | 'medium' | 'low'
type ConflictState = 'open' | 'analysis_ready' | 'accepted' | 'rejected'

interface Contradiction {
  id: string
  source: Document
  target: Document
  conflictType: 'missing_reference' | 'status_drift' | 'version_gap' | 'duplicate_requirement'
  severity: ConflictSeverity
  title: string
  description: string
  suggestion: string
  affectedSection: string
  evidence: string[]
}

interface DecisionRecord {
  status: ConflictState
  note: string
  decidedAt: string
}

const PERSISTED_CONFLICT_DECISIONS_QUERY_KEY = 'persisted-document-conflict-decisions'

const DOC_TYPE_LABELS: Record<string, string> = {
  urs: 'URS 用户需求',
  brd: 'BRD 商业需求',
  prd: 'PRD 产品需求',
  detailed_design: '设计说明',
  implementation_plan: '实施方案',
  acceptance_report: '验收报告',
}

const DOC_TYPE_ORDER: Record<string, number> = {
  urs: 1,
  brd: 2,
  prd: 3,
  detailed_design: 4,
  implementation_plan: 5,
  acceptance_report: 6,
}

const SEVERITY_LABELS: Record<ConflictSeverity, string> = {
  high: '高',
  medium: '中',
  low: '低',
}

const STATE_LABELS: Record<ConflictState, string> = {
  open: '待处置',
  analysis_ready: '已生成分析',
  accepted: '已接受修订',
  rejected: '无需处理',
}

const EMPTY_DOCUMENTS: Document[] = []

type PersistedConflictAction = 'complete_analysis' | 'accept_risk' | 'accept_revision' | 'close_after_rescan'

function formatDateTime(value?: string | null) {
  if (!value) return 'n/a'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString()
}

function summarizeConflictEvidence(conflict: DocumentConflict) {
  const evidence = conflict.evidence_json || {}
  const values = Object.values(evidence)
    .flatMap((item) => Array.isArray(item) ? item : [item])
    .filter((item) => item !== null && item !== undefined)
    .map((item) => typeof item === 'string' ? item : JSON.stringify(item))
  return values.slice(0, 2)
}

function getDocType(document: Document) {
  return document.doc_type || document.type || 'document'
}

function getDocTitle(document: Document) {
  return document.title || document.name || '未命名文档'
}

function getVersion(document: Document) {
  const metadata = document.metadata_json || document.metadata || {}
  return Number(metadata.version || metadata.current_version || (document as Document & { version?: number }).version || 1)
}

function getDocumentEvidenceTimestamp(document: Document) {
  return document.updated_at || document.created_at || ''
}

function getConflictEvidenceTimestamp(conflict: Contradiction) {
  return [
    getDocumentEvidenceTimestamp(conflict.source),
    getDocumentEvidenceTimestamp(conflict.target),
  ].sort().reverse()[0] || conflict.id
}

function getStatus(document: Document) {
  return String(document.status || document.metadata?.status || document.metadata_json?.status || 'draft').toLowerCase()
}

function hasUpstreamReference(document: Document) {
  const metadata = document.metadata_json || document.metadata || {}
  return Boolean(
    metadata.parent_document_id ||
      metadata.upstream_document_id ||
      metadata.source_document_id ||
      metadata.traceability_parent_id ||
      metadata.references?.length
  )
}

function conflictKey(prefix: string, source: Document, target: Document) {
  return `${prefix}-${source.id}-${target.id}`
}

function buildContradictions(documents: Document[]): Contradiction[] {
  const result: Contradiction[] = []
  const activeDocuments = documents.filter((document) => getStatus(document) !== 'archived')
  const byType = new Map<string, Document[]>()

  for (const document of activeDocuments) {
    const type = getDocType(document)
    byType.set(type, [...(byType.get(type) || []), document])
  }

  for (const target of activeDocuments) {
    const targetType = getDocType(target)
    const targetOrder = DOC_TYPE_ORDER[targetType] || 99
    if (targetOrder <= 1) continue

    const upstream = activeDocuments
      .filter((candidate) => (DOC_TYPE_ORDER[getDocType(candidate)] || 99) < targetOrder)
      .sort((a, b) => (DOC_TYPE_ORDER[getDocType(b)] || 0) - (DOC_TYPE_ORDER[getDocType(a)] || 0))[0]

    if (upstream && !hasUpstreamReference(target)) {
      result.push({
        id: conflictKey('missing-reference', upstream, target),
        source: upstream,
        target,
        conflictType: 'missing_reference',
        severity: targetOrder >= 4 ? 'high' : 'medium',
        title: '缺少正式上游引用',
        description: `${DOC_TYPE_LABELS[targetType] || targetType.toUpperCase()} 尚未绑定已发布的上游文档版本，后续评审缺少可审计依据。`,
        suggestion: '先补齐上游引用，再允许进入发布或验收流程。',
        affectedSection: '文档血缘与发布门禁',
        evidence: [
          `${getDocTitle(target)} 没有 parent_document_id / upstream_document_id`,
          `${getDocTitle(upstream)} 可作为候选上游基线`,
        ],
      })
    }
  }

  const orderedTypes = ['urs', 'brd', 'prd', 'detailed_design', 'implementation_plan', 'acceptance_report']
  for (let index = 0; index < orderedTypes.length - 1; index += 1) {
    const sourceType = orderedTypes[index]
    const targetType = orderedTypes[index + 1]
    const sources = byType.get(sourceType) || []
    const targets = byType.get(targetType) || []

    for (const source of sources) {
      for (const target of targets) {
        const sourceStatus = getStatus(source)
        const targetStatus = getStatus(target)
        if (['published', 'approved'].includes(sourceStatus) && ['draft', 'review', 'under_review'].includes(targetStatus)) {
          result.push({
            id: conflictKey('status-drift', source, target),
            source,
            target,
            conflictType: 'status_drift',
            severity: targetStatus === 'draft' ? 'high' : 'medium',
            title: '上游已发布但下游未同步',
            description: `${getDocTitle(source)} 已进入正式状态，${getDocTitle(target)} 仍处于 ${targetStatus}，需要确认是否生成同步修订。`,
            suggestion: '生成影响分析并由负责人确认是否接受修订建议。',
            affectedSection: '状态流转与同步提案',
            evidence: [
              `${getDocTitle(source)} 状态：${sourceStatus}`,
              `${getDocTitle(target)} 状态：${targetStatus}`,
            ],
          })
        }

        const sourceVersion = getVersion(source)
        const targetVersion = getVersion(target)
        if (sourceVersion > targetVersion) {
          result.push({
            id: conflictKey('version-gap', source, target),
            source,
            target,
            conflictType: 'version_gap',
            severity: sourceVersion - targetVersion > 1 ? 'high' : 'low',
            title: '版本基线落后',
            description: `${getDocTitle(target)} 仍引用旧版本内容，落后 ${getDocTitle(source)} ${sourceVersion - targetVersion} 个版本。`,
            suggestion: '检查差异摘要，必要时创建新的下游版本。',
            affectedSection: '版本基线',
            evidence: [
              `${getDocTitle(source)} v${sourceVersion}`,
              `${getDocTitle(target)} v${targetVersion}`,
            ],
          })
        }
      }
    }
  }

  const requirementOwners = new Map<string, Document>()
  const requirementPattern = /\b(?:REQ|URS|BRD|PRD)-\d{2,}\b/gi
  for (const document of activeDocuments) {
    for (const match of document.content.matchAll(requirementPattern)) {
      const key = match[0].toUpperCase()
      const owner = requirementOwners.get(key)
      if (owner && owner.id !== document.id) {
        result.push({
          id: conflictKey(`duplicate-${key}`, owner, document),
          source: owner,
          target: document,
          conflictType: 'duplicate_requirement',
          severity: 'medium',
          title: '重复需求编号',
          description: `需求编号 ${key} 同时出现在两份文档中，需要确认是否为同一需求或编号误用。`,
          suggestion: '保留一个主编号，并在另一份文档中改为引用或派生编号。',
          affectedSection: key,
          evidence: [
            `${getDocTitle(owner)} 包含 ${key}`,
            `${getDocTitle(document)} 也包含 ${key}`,
          ],
        })
      } else {
        requirementOwners.set(key, document)
      }
    }
  }

  const unique = new Map<string, Contradiction>()
  for (const item of result) {
    unique.set(item.id, item)
  }
  return Array.from(unique.values())
}

function getSeverityClass(severity: ConflictSeverity) {
  switch (severity) {
    case 'high':
      return 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200'
    case 'medium':
      return 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200'
    default:
      return 'bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-200'
  }
}

function getStateClass(state: ConflictState) {
  switch (state) {
    case 'accepted':
      return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200'
    case 'rejected':
      return 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200'
    case 'analysis_ready':
      return 'bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-200'
    default:
      return 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200'
  }
}

function getConflictTypeLabel(type: Contradiction['conflictType']) {
  const labels: Record<Contradiction['conflictType'], string> = {
    missing_reference: '缺少引用',
    status_drift: '状态不同步',
    version_gap: '版本落后',
    duplicate_requirement: '编号重复',
  }
  return labels[type]
}

function PersistedConflictDecisionHistory({ conflictId }: { conflictId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: [PERSISTED_CONFLICT_DECISIONS_QUERY_KEY, conflictId],
    queryFn: () => changeApi.listDocumentConflictDecisions(conflictId),
  })
  const decisions = data?.items ?? []

  return (
    <div
      data-testid={`persisted-conflict-history-${conflictId}`}
      className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-900"
    >
      <div className="flex items-center gap-2 text-sm font-medium text-slate-800 dark:text-slate-100">
        <History className="h-4 w-4" />
        Conflict decision history
      </div>
      {isLoading ? (
        <p className="mt-2 text-xs text-slate-500">Loading decision history...</p>
      ) : decisions.length === 0 ? (
        <p className="mt-2 text-xs text-slate-500">No decisions recorded yet.</p>
      ) : (
        <ol className="mt-2 space-y-2 text-xs text-slate-600 dark:text-slate-300">
          {decisions.slice(-4).reverse().map((decision: DocumentConflictDecision) => (
            <li key={decision.id} className="rounded border border-slate-200 bg-white p-2 dark:border-slate-700 dark:bg-slate-950">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">{decision.action}</Badge>
                <span>
                  {decision.previous_status || 'none'} -&gt; {decision.resulting_status}
                </span>
              </div>
              <p className="mt-1 text-slate-500">
                {formatDateTime(decision.created_at)}
                {decision.reason ? ` - ${decision.reason}` : ''}
              </p>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

export default function ContradictionsPage() {
  const { addToast } = useToast()
  const queryClient = useQueryClient()
  const { data: currentUser } = useCurrentUser()
  const [projectId, setProjectId] = useState('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [severityFilter, setSeverityFilter] = useState('all')
  const [stateFilter, setStateFilter] = useState('all')
  const [selectedConflictId, setSelectedConflictId] = useState<string | null>(null)
  const [decisions, setDecisions] = useState<Record<string, DecisionRecord>>({})
  const [persistedScanSummary, setPersistedScanSummary] = useState<string | null>(null)

  const { data: projectsData } = useQuery({
    queryKey: ['projects'],
    queryFn: () => projectsApi.list({ pageSize: 100 }),
  })

  const {
    data: documentsData,
    isLoading,
    refetch,
  } = useQuery({
    queryKey: ['contradiction-documents', projectId],
    queryFn: () =>
      documentsApi.list({
        projectId: projectId === 'all' ? undefined : projectId,
        pageSize: 100,
        includePlaceholders: true,
      }),
  })

  const projects = projectsData?.items || []
  const persistedProjectId = projectId === 'all' ? projects[0]?.id : projectId
  const documents = documentsData?.items ?? EMPTY_DOCUMENTS
  const persistedConflictQueryKey = ['persisted-document-conflicts', persistedProjectId]

  const {
    data: persistedConflictsData,
    isLoading: isPersistedConflictLoading,
    refetch: refetchPersistedConflicts,
  } = useQuery({
    queryKey: persistedConflictQueryKey,
    queryFn: () => changeApi.listDocumentConflicts(persistedProjectId as string),
    enabled: Boolean(persistedProjectId),
  })

  const persistedConflictMutation = useMutation({
    mutationFn: ({ conflict, action }: { conflict: DocumentConflict; action: PersistedConflictAction }) => {
      const evidence = { source: 'contradiction_resolution_center', action }

      if (action === 'complete_analysis') {
        return changeApi.completeDocumentConflictAnalysis(conflict.id, {
          reason: 'Operator completed analysis from the contradiction resolution center.',
          evidence,
        })
      }

      if (action === 'accept_risk') {
        return changeApi.acceptDocumentConflictRisk(conflict.id, {
          reason: 'Operator accepted this conflict risk with mitigation evidence.',
          mitigation_plan: 'Monitor linked delivery evidence and renew or close before expiry.',
          evidence,
        })
      }

      if (action === 'accept_revision') {
        return changeApi.acceptDocumentConflictRevision(conflict.id, {
          suggested_revision: conflict.accepted_revision_json?.suggested_revision || conflict.summary,
          reason: 'Operator accepted the suggested revision from the governance queue.',
          evidence,
        })
      }

      return changeApi.closeDocumentConflictAfterRescan(conflict.id, {
        reason: 'Operator verified the linked change after rescan.',
        evidence,
      })
    },
    onSuccess: (updatedConflict) => {
      queryClient.invalidateQueries({ queryKey: persistedConflictQueryKey })
      queryClient.invalidateQueries({ queryKey: [PERSISTED_CONFLICT_DECISIONS_QUERY_KEY, updatedConflict.id] })
      addToast({
        title: 'Persisted conflict updated',
        description: `${updatedConflict.summary}: ${updatedConflict.status}`,
      })
    },
    onError: (error) => {
      addToast({
        title: 'Persisted conflict update failed',
        description: error instanceof Error ? error.message : 'Unknown error',
        variant: 'destructive',
      })
    },
  })

  const persistedScanMutation = useMutation({
    mutationFn: () => changeApi.scanDocumentConflicts(persistedProjectId as string),
    onSuccess: (scan) => {
      setPersistedScanSummary(`Scan detected ${scan.detected} persisted conflicts`)
      queryClient.invalidateQueries({ queryKey: persistedConflictQueryKey })
      addToast({
        title: 'Persisted conflict scan completed',
        description: `${scan.detected} conflicts detected.`,
      })
    },
    onError: (error) => {
      addToast({
        title: 'Persisted conflict scan failed',
        description: error instanceof Error ? error.message : 'Unknown error',
        variant: 'destructive',
      })
    },
  })

  const persistedAssignmentMutation = useMutation({
    mutationFn: (conflict: DocumentConflict) => {
      if (!currentUser?.id) {
        throw new Error('Current user is not loaded.')
      }

      return changeApi.assignDocumentConflict(conflict.id, {
        assignee_user_id: currentUser.id,
        reason: 'Operator claimed this conflict from the contradiction resolution center.',
      })
    },
    onSuccess: (updatedConflict) => {
      queryClient.invalidateQueries({ queryKey: persistedConflictQueryKey })
      queryClient.invalidateQueries({ queryKey: [PERSISTED_CONFLICT_DECISIONS_QUERY_KEY, updatedConflict.id] })
      addToast({
        title: 'Persisted conflict assigned',
        description: `${updatedConflict.summary}: assigned to current operator.`,
      })
    },
    onError: (error) => {
      addToast({
        title: 'Persisted conflict assignment failed',
        description: error instanceof Error ? error.message : 'Unknown error',
        variant: 'destructive',
      })
    },
  })

  const persistedConflicts = persistedConflictsData?.items || []
  const persistedConflictSummary = {
    total: persistedConflicts.length,
    high: persistedConflicts.filter((item) => item.severity === 'high').length,
    open: persistedConflicts.filter((item) => !['closed', 'rejected', 'risk_accepted', 'revision_accepted'].includes(item.status)).length,
  }

  const contradictions = useMemo(() => buildContradictions(documents), [documents])
  const filteredContradictions = contradictions.filter((item) => {
    const decisionState = decisions[item.id]?.status || 'open'
    const query = searchQuery.trim().toLowerCase()
    const searchable = `${item.title} ${item.description} ${item.affectedSection} ${getDocTitle(item.source)} ${getDocTitle(item.target)}`.toLowerCase()
    return (
      (!query || searchable.includes(query)) &&
      (severityFilter === 'all' || item.severity === severityFilter) &&
      (stateFilter === 'all' || decisionState === stateFilter)
    )
  })

  const selectedConflict =
    filteredContradictions.find((item) => item.id === selectedConflictId) ||
    filteredContradictions[0] ||
    null

  const summary = {
    total: contradictions.length,
    high: contradictions.filter((item) => item.severity === 'high').length,
    open: contradictions.filter((item) => (decisions[item.id]?.status || 'open') === 'open').length,
    resolved: contradictions.filter((item) => ['accepted', 'rejected'].includes(decisions[item.id]?.status || '')).length,
  }

  const history = contradictions
    .map((item) => ({ conflict: item, decision: decisions[item.id] }))
    .filter((item): item is { conflict: Contradiction; decision: DecisionRecord } => Boolean(item.decision))
    .sort((a, b) => b.decision.decidedAt.localeCompare(a.decision.decidedAt))

  const updateDecision = (conflict: Contradiction, status: ConflictState) => {
    const noteByStatus: Record<ConflictState, string> = {
      open: '重新打开冲突',
      analysis_ready: '已生成影响分析，等待负责人确认',
      accepted: '已接受修订建议，将在下游文档创建新版本',
      rejected: '已标记为无需处理，并保留审计记录',
    }
    setDecisions((current) => ({
      ...current,
      [conflict.id]: {
        status,
        note: noteByStatus[status],
        decidedAt: getConflictEvidenceTimestamp(conflict),
      },
    }))
    addToast({
      title: STATE_LABELS[status],
      description: `${conflict.title}：${noteByStatus[status]}`,
    })
  }

  return (
    <div className="space-y-6" data-testid="contradiction-resolution-center">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">冲突解析中心</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            检查 URS、BRD、PRD、设计和交付文档之间的血缘、状态与版本冲突
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Select value={projectId} onValueChange={setProjectId} className="w-48" data-testid="contradiction-project-filter">
            <SelectOption value="all">全部项目</SelectOption>
            {projects.map((project) => (
              <SelectOption key={project.id} value={project.id}>{project.name}</SelectOption>
            ))}
          </Select>
          <Button
            variant="outline"
            onClick={() => {
              refetch()
              if (persistedProjectId) refetchPersistedConflicts()
            }}
            data-testid="contradiction-rescan"
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            重新扫描
          </Button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <Card data-testid="contradiction-summary">
          <CardContent className="flex items-center gap-3 py-4">
            <GitCompare className="h-5 w-5 text-indigo-500" />
            <div>
              <p className="text-2xl font-bold">{summary.total}</p>
              <p className="text-xs text-slate-500">冲突总数</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 py-4">
            <AlertCircle className="h-5 w-5 text-red-500" />
            <div>
              <p className="text-2xl font-bold">{summary.high}</p>
              <p className="text-xs text-slate-500">高风险</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 py-4">
            <AlertTriangle className="h-5 w-5 text-amber-500" />
            <div>
              <p className="text-2xl font-bold">{summary.open}</p>
              <p className="text-xs text-slate-500">待处置</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 py-4">
            <ShieldCheck className="h-5 w-5 text-emerald-500" />
            <div>
              <p className="text-2xl font-bold">{summary.resolved}</p>
              <p className="text-xs text-slate-500">已闭环</p>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent className="grid gap-3 py-4 lg:grid-cols-[minmax(240px,1fr)_180px_180px]">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <Input
              data-testid="contradiction-search"
              className="pl-9"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="搜索文档、冲突原因或章节"
            />
          </div>
          <Select value={severityFilter} onValueChange={setSeverityFilter} data-testid="contradiction-severity-filter">
            <SelectOption value="all">全部风险</SelectOption>
            <SelectOption value="high">高风险</SelectOption>
            <SelectOption value="medium">中风险</SelectOption>
            <SelectOption value="low">低风险</SelectOption>
          </Select>
          <Select value={stateFilter} onValueChange={setStateFilter} data-testid="contradiction-state-filter">
            <SelectOption value="all">全部状态</SelectOption>
            <SelectOption value="open">待处置</SelectOption>
            <SelectOption value="analysis_ready">已生成分析</SelectOption>
            <SelectOption value="accepted">已接受修订</SelectOption>
            <SelectOption value="rejected">无需处理</SelectOption>
          </Select>
        </CardContent>
      </Card>

      <Card data-testid="persisted-conflict-governance">
        <CardHeader>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <ShieldCheck className="h-5 w-5" />
                Persisted conflict governance
              </CardTitle>
              <CardDescription>
                Backend-governed document conflicts that can block release until rejected, risk-accepted, revised, or closed.
              </CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Button
                size="sm"
                variant="outline"
                data-testid="persisted-conflict-scan"
                disabled={!persistedProjectId || persistedScanMutation.isPending}
                onClick={() => persistedScanMutation.mutate()}
              >
                <RefreshCw className="mr-2 h-4 w-4" />
                Scan persisted
              </Button>
              <Badge variant="outline">total {persistedConflictSummary.total}</Badge>
              <Badge className={getSeverityClass('high')}>high {persistedConflictSummary.high}</Badge>
              <Badge className={getStateClass('open')}>open {persistedConflictSummary.open}</Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {persistedScanSummary && (
            <div className="mb-3 rounded-md border border-indigo-200 bg-indigo-50 p-3 text-sm text-indigo-900 dark:border-indigo-900 dark:bg-indigo-950 dark:text-indigo-100">
              {persistedScanSummary}
            </div>
          )}
          {!persistedProjectId ? (
            <p className="text-sm text-slate-500">Select a project to load persisted conflict governance.</p>
          ) : isPersistedConflictLoading ? (
            <p className="text-sm text-slate-500">Loading persisted conflicts...</p>
          ) : persistedConflicts.length === 0 ? (
            <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200">
              No persisted conflicts are currently open for this project.
            </div>
          ) : (
            <div className="space-y-3">
              {persistedConflicts.map((conflict) => {
                const evidence = summarizeConflictEvidence(conflict)
                return (
                  <div key={conflict.id} className="rounded-md border border-slate-200 p-4 dark:border-slate-700">
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge className={getSeverityClass(conflict.severity as ConflictSeverity)}>{conflict.severity}</Badge>
                          <Badge variant="outline">{conflict.rule_key}</Badge>
                          <Badge className={getStateClass(conflict.status as ConflictState)}>{conflict.status}</Badge>
                        </div>
                        <h3 className="mt-2 font-semibold text-slate-900 dark:text-white">{conflict.summary}</h3>
                        <p className="mt-1 text-xs text-slate-500">
                          Last detected {formatDateTime(conflict.last_detected_at)}
                          {conflict.risk_acceptance_expires_at ? ` · Risk accepted until ${formatDateTime(conflict.risk_acceptance_expires_at)}` : ''}
                          {conflict.linked_change_request_id ? ` · Change ${conflict.linked_change_request_id}` : ''}
                        </p>
                        <p className="mt-1 text-xs text-slate-500">
                          {conflict.assignee_user_id
                            ? conflict.assignee_user_id === currentUser?.id
                              ? 'Assigned to me'
                              : `Assigned to ${conflict.assignee_user_id}`
                            : 'Unassigned'}
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          data-testid={`persisted-conflict-claim-${conflict.id}`}
                          disabled={!currentUser?.id || persistedAssignmentMutation.isPending}
                          onClick={() => persistedAssignmentMutation.mutate(conflict)}
                        >
                          Claim
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={persistedConflictMutation.isPending}
                          onClick={() => persistedConflictMutation.mutate({ conflict, action: 'complete_analysis' })}
                        >
                          Complete analysis
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          data-testid={`persisted-conflict-accept-risk-${conflict.id}`}
                          disabled={persistedConflictMutation.isPending}
                          onClick={() => persistedConflictMutation.mutate({ conflict, action: 'accept_risk' })}
                        >
                          Accept risk
                        </Button>
                        <Button
                          size="sm"
                          disabled={persistedConflictMutation.isPending}
                          onClick={() => persistedConflictMutation.mutate({ conflict, action: 'accept_revision' })}
                        >
                          Accept revision
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={persistedConflictMutation.isPending}
                          onClick={() => persistedConflictMutation.mutate({ conflict, action: 'close_after_rescan' })}
                        >
                          Close after rescan
                        </Button>
                      </div>
                    </div>
                    {evidence.length > 0 && (
                      <ul className="mt-3 space-y-1 text-sm text-slate-600 dark:text-slate-300">
                        {evidence.map((item) => (
                          <li key={item} className="flex gap-2">
                            <span className="mt-2 h-1.5 w-1.5 rounded-full bg-indigo-500" />
                            <span>{item}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                    <PersistedConflictDecisionHistory conflictId={conflict.id} />
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(360px,0.65fr)]">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileSearch className="h-5 w-5" />
              冲突队列
            </CardTitle>
            <CardDescription>先生成影响分析，再由负责人接受修订或标记无需处理。</CardDescription>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="flex h-56 items-center justify-center text-sm text-slate-500">正在扫描文档冲突...</div>
            ) : filteredContradictions.length === 0 ? (
              <div className="flex h-56 flex-col items-center justify-center text-center">
                <CheckCircle2 className="h-12 w-12 text-emerald-500" />
                <p className="mt-3 font-medium text-slate-900 dark:text-white">当前筛选下没有冲突</p>
                <p className="mt-1 text-sm text-slate-500">可以切换项目、状态或风险级别重新查看。</p>
              </div>
            ) : (
              <div className="space-y-3">
                {filteredContradictions.map((item) => {
                  const state = decisions[item.id]?.status || 'open'
                  const selected = selectedConflict?.id === item.id
                  return (
                    <button
                      key={item.id}
                      type="button"
                      data-testid={`contradiction-item-${item.id}`}
                      className={`w-full rounded-md border p-4 text-left transition-colors ${
                        selected
                          ? 'border-indigo-500 bg-indigo-50 dark:border-indigo-400 dark:bg-indigo-950'
                          : 'border-slate-200 bg-white hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:hover:bg-slate-800'
                      }`}
                      onClick={() => setSelectedConflictId(item.id)}
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge className={getSeverityClass(item.severity)}>{SEVERITY_LABELS[item.severity]}风险</Badge>
                            <Badge variant="outline">{getConflictTypeLabel(item.conflictType)}</Badge>
                            <Badge className={getStateClass(state)}>{STATE_LABELS[state]}</Badge>
                          </div>
                          <h3 className="mt-2 font-semibold text-slate-900 dark:text-white">{item.title}</h3>
                        </div>
                        <span className="text-xs text-slate-500">{item.affectedSection}</span>
                      </div>
                      <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{item.description}</p>
                      <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-slate-500">
                        <FileText className="h-4 w-4" />
                        <span>{getDocTitle(item.source)}</span>
                        <ArrowRight className="h-4 w-4" />
                        <span>{getDocTitle(item.target)}</span>
                      </div>
                    </button>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card data-testid="contradiction-detail-panel">
            <CardHeader>
              <CardTitle>处置详情</CardTitle>
              <CardDescription>查看证据、影响和下一步动作。</CardDescription>
            </CardHeader>
            <CardContent>
              {selectedConflict ? (
                <div className="space-y-4">
                  <div>
                    <div className="flex flex-wrap gap-2">
                      <Badge className={getSeverityClass(selectedConflict.severity)}>
                        {SEVERITY_LABELS[selectedConflict.severity]}风险
                      </Badge>
                      <Badge className={getStateClass(decisions[selectedConflict.id]?.status || 'open')}>
                        {STATE_LABELS[decisions[selectedConflict.id]?.status || 'open']}
                      </Badge>
                    </div>
                    <h2 className="mt-3 text-lg font-semibold text-slate-900 dark:text-white">{selectedConflict.title}</h2>
                    <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{selectedConflict.description}</p>
                  </div>

                  <div className="grid gap-3 rounded-md border border-slate-200 p-3 text-sm dark:border-slate-700">
                    <div>
                      <p className="text-xs font-medium text-slate-500">上游文档</p>
                      <Link
                        className="mt-1 inline-flex items-center gap-2 font-medium text-indigo-600 hover:underline dark:text-indigo-300"
                        href={`/projects/${selectedConflict.source.projectId || selectedConflict.source.project_id}/documents/${selectedConflict.source.id}`}
                      >
                        <Link2 className="h-4 w-4" />
                        {getDocTitle(selectedConflict.source)}
                      </Link>
                    </div>
                    <div>
                      <p className="text-xs font-medium text-slate-500">下游文档</p>
                      <Link
                        className="mt-1 inline-flex items-center gap-2 font-medium text-indigo-600 hover:underline dark:text-indigo-300"
                        href={`/projects/${selectedConflict.target.projectId || selectedConflict.target.project_id}/documents/${selectedConflict.target.id}`}
                      >
                        <Link2 className="h-4 w-4" />
                        {getDocTitle(selectedConflict.target)}
                      </Link>
                    </div>
                  </div>

                  <div>
                    <p className="text-sm font-semibold text-slate-900 dark:text-white">证据</p>
                    <ul className="mt-2 space-y-2">
                      {selectedConflict.evidence.map((item) => (
                        <li key={item} className="flex gap-2 text-sm text-slate-600 dark:text-slate-300">
                          <span className="mt-2 h-1.5 w-1.5 rounded-full bg-indigo-500" />
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
                    <p className="text-sm font-semibold text-slate-900 dark:text-white">建议动作</p>
                    <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{selectedConflict.suggestion}</p>
                  </div>

                  <div className="grid gap-2 sm:grid-cols-2">
                    <Button
                      data-testid="contradiction-generate-analysis"
                      variant="outline"
                      onClick={() => updateDecision(selectedConflict, 'analysis_ready')}
                    >
                      <FileSearch className="mr-2 h-4 w-4" />
                      生成影响分析
                    </Button>
                    <Button
                      data-testid="contradiction-accept-revision"
                      onClick={() => updateDecision(selectedConflict, 'accepted')}
                    >
                      <ClipboardCheck className="mr-2 h-4 w-4" />
                      接受修订建议
                    </Button>
                    <Button
                      data-testid="contradiction-reject"
                      variant="outline"
                      onClick={() => updateDecision(selectedConflict, 'rejected')}
                    >
                      <XCircle className="mr-2 h-4 w-4" />
                      标记无需处理
                    </Button>
                    <Button
                      data-testid="contradiction-reopen"
                      variant="outline"
                      onClick={() => updateDecision(selectedConflict, 'open')}
                    >
                      <AlertTriangle className="mr-2 h-4 w-4" />
                      重新打开
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="py-12 text-center text-sm text-slate-500">选择一个冲突后查看处置详情。</div>
              )}
            </CardContent>
          </Card>

          <Card data-testid="contradiction-history">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <History className="h-5 w-5" />
                处置记录
              </CardTitle>
              <CardDescription>记录本次会话中的人工确认动作。</CardDescription>
            </CardHeader>
            <CardContent>
              {history.length === 0 ? (
                <p className="text-sm text-slate-500">尚无处置记录。</p>
              ) : (
                <div className="space-y-3">
                  {history.slice(0, 5).map(({ conflict, decision }) => (
                    <div key={`${conflict.id}-${decision.decidedAt}`} className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-sm font-medium text-slate-900 dark:text-white">{conflict.title}</p>
                        <Badge className={getStateClass(decision.status)}>{STATE_LABELS[decision.status]}</Badge>
                      </div>
                      <p className="mt-1 text-xs text-slate-500">{decision.note}</p>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
