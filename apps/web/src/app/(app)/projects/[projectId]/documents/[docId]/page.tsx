'use client'

import { use, useEffect, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  documentsApi,
  collaborationApi,
  exportsApi,
  Document,
  Comment,
  Version,
  DocumentBaseline,
  DocumentSnapshot,
  DocumentStatusCapabilities,
  DocumentStatusCapability,
  DocumentStatusTransition,
} from '@/lib/api-client'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Avatar } from '@/components/ui/avatar'
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from '@/components/ui/tabs'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectOption } from '@/components/ui/select'
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle,
  MessageSquare,
  History,
  Download,
  Edit,
  Send,
  Archive,
  Trash2,
  GitBranch,
  PackageCheck,
  ShieldCheck,
  Users,
  Workflow,
  Cloud,
  CloudOff,
  Loader2,
  MapPin,
  Reply,
} from 'lucide-react'
import { useRouter } from 'next/navigation'
import { formatDistanceToNow } from '@/lib/utils'
import { useToast } from '@/components/ui/toast'
import { getDocumentStatusLabel, getDocumentTypeLabel } from '@/lib/document-labels'
import {
  getUnresolvedTemplatePlaceholders,
  hasUnresolvedTemplatePlaceholders,
  templatePlaceholderSummary,
} from '@/lib/document-template-placeholders'

interface DocumentDetailPageProps {
  params: Promise<{ projectId: string; docId: string }>
}

const DOCUMENT_AUTOSAVE_INTERVAL_MS = 5 * 60 * 1000

function draftSignature(title: string, content: string) {
  return JSON.stringify([title.trim(), content])
}

function normalizeCommentAnchor(line: string) {
  return line.trim().slice(0, 1000)
}

function getDocumentCommentAnchors(content: string) {
  const seen = new Set<string>()
  return content
    .split('\n')
    .map(normalizeCommentAnchor)
    .filter((line) => {
      if (line.length < 8 || seen.has(line)) return false
      seen.add(line)
      return true
    })
    .slice(0, 80)
    .map((line) => ({
      value: line,
      label: line.replace(/^#{1,6}\s+/, '').slice(0, 100),
      type: /^#{1,6}\s+/.test(line) ? '章节' : '段落',
    }))
}

function getDocumentContentPreviewLines(content: string) {
  const occurrences = new Map<string, number>()
  return content.split('\n').map((line) => {
    const anchor = normalizeCommentAnchor(line)
    const keyBase = anchor || 'blank-line'
    const occurrence = (occurrences.get(keyBase) || 0) + 1
    occurrences.set(keyBase, occurrence)

    return {
      line,
      anchor,
      key: occurrence === 1 ? keyBase : `${keyBase}::${occurrence}`,
    }
  })
}

function getStatusReason(status: string) {
  const reasons: Record<string, string> = {
    draft: 'Return to draft for revision',
    review: 'Submit for formal review',
    approved: 'Approve after review completion',
    published: 'Release after comment resolution',
    archived: 'Archive document',
  }
  return reasons[status] || 'Update document workflow status'
}

const STATUS_ACTION_LABELS: Record<string, string> = {
  approved: '批准文档',
  published: '发布文档',
  archived: '归档文档',
}

function statusTransitionKey(item: DocumentStatusTransition) {
  return item.transition_id
    || [
      item.changed_at,
      item.from_status,
      item.to_status,
      item.action,
      item.changed_by || '',
      item.policy_revision,
    ].join('::')
}

function getStatusCapabilityMessage(capability?: DocumentStatusCapability) {
  if (!capability) return '正在核验权限与流程条件'
  if (capability.allowed) return '权限与流程条件已满足'
  if (capability.blockers.length > 0) {
    const blocker = capability.blockers[0]
    const unresolvedCommentMatch = blocker.match(/Document has (\d+) unresolved comments/)
    if (unresolvedCommentMatch) return `仍有 ${unresolvedCommentMatch[1]} 条评论未解决`
    if (blocker.includes('must be approved')) return '文档批准后才能发布'
    if (blocker.includes('unresolved template placeholders')) return '仍有模板变量未补齐'
    if (blocker.includes('placeholder document')) return '占位文档必须重新生成后才能进入正式流程'
    if (blocker.includes('Document delivery readiness blocks publish')) return '交付准备度未达标，请先处理未完成或低质量章节'
    if (blocker.includes('Invalid status transition')) return '当前生命周期状态不允许执行此动作'
    return blocker
  }
  return `缺少“${STATUS_ACTION_LABELS[capability.status] || capability.status}”权限`
}

export default function DocumentDetailPage({ params }: DocumentDetailPageProps) {
  const { projectId, docId } = use(params)
  const router = useRouter()
  const [newComment, setNewComment] = useState('')
  const [commentAnchor, setCommentAnchor] = useState('')
  const [commentFilter, setCommentFilter] = useState<'all' | 'unresolved' | 'resolved'>('all')
  const [replyingToCommentId, setReplyingToCommentId] = useState<string | null>(null)
  const [replyContent, setReplyContent] = useState('')
  const [activeContentTab, setActiveContentTab] = useState('content')
  const [locatedCommentAnchor, setLocatedCommentAnchor] = useState<string | null>(null)
  const [showVersionHistory, setShowVersionHistory] = useState(false)
  const [showEditDialog, setShowEditDialog] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editContent, setEditContent] = useState('')
  const [editSummary, setEditSummary] = useState('手动编辑文档')
  const [autoSaveStatus, setAutoSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [lastAutoSavedAt, setLastAutoSavedAt] = useState<string | null>(null)
  const [baselineName, setBaselineName] = useState('')
  const editDraftRef = useRef({ title: '', content: '' })
  const lastAutoSavedSignatureRef = useRef('')
  const autoSnapshotRunnerRef = useRef<(notify?: boolean) => void>(() => undefined)
  const closeAfterAutosaveRef = useRef(false)
  const queryClient = useQueryClient()
  const { addToast } = useToast()

  const { data: document, isLoading } = useQuery<Document>({
    queryKey: ['document', docId],
    queryFn: () => documentsApi.get(docId),
  })

  const { data: comments = [] } = useQuery<Comment[]>({
    queryKey: ['document-comments', docId],
    queryFn: () => collaborationApi.getComments(docId),
  })

  const { data: versions = [] } = useQuery<Version[]>({
    queryKey: ['document-versions', docId],
    queryFn: () => collaborationApi.getVersions(docId),
  })

  const { data: baselines = [] } = useQuery<DocumentBaseline[]>({
    queryKey: ['document-baselines', docId],
    queryFn: () => collaborationApi.getBaselines(docId),
  })

  const { data: snapshots = [] } = useQuery<DocumentSnapshot[]>({
    queryKey: ['document-snapshots', docId],
    queryFn: () => collaborationApi.getSnapshots(docId),
  })

  const { data: statusHistory = [] } = useQuery<DocumentStatusTransition[]>({
    queryKey: ['document-status-history', docId],
    queryFn: () => documentsApi.getStatusHistory(docId),
  })

  const { data: statusCapabilities } = useQuery<DocumentStatusCapabilities>({
    queryKey: ['document-status-capabilities', docId],
    queryFn: () => documentsApi.getStatusCapabilities(docId),
  })

  const addCommentMutation = useMutation({
    mutationFn: (data: { content: string; anchor?: string; parent_comment_id?: string }) =>
      collaborationApi.addComment(docId, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['document-comments', docId] })
      queryClient.invalidateQueries({ queryKey: ['document-status-capabilities', docId] })
      if (variables.parent_comment_id) {
        setReplyingToCommentId(null)
        setReplyContent('')
        addToast({ title: '回复已添加' })
      } else {
        setNewComment('')
        setCommentAnchor('')
        addToast({ title: '评论已添加' })
      }
    },
    onError: (error: Error) => {
      addToast({ title: '评论添加失败', description: error.message, variant: 'destructive' })
    },
  })

  const resolveCommentMutation = useMutation({
    mutationFn: (commentId: string) => collaborationApi.resolveComment(commentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['document-comments', docId] })
      queryClient.invalidateQueries({ queryKey: ['document-status-capabilities', docId] })
      addToast({ title: '评论已标记解决' })
    },
    onError: (error: Error) => {
      addToast({ title: '评论处理失败', description: error.message, variant: 'destructive' })
    },
  })

  const statusMutation = useMutation({
    mutationFn: (status: string) => documentsApi.updateStatus(docId, {
      status,
      reason: getStatusReason(status),
      action: `document_${status}`,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['document', docId] })
      queryClient.invalidateQueries({ queryKey: ['document-status-history', docId] })
      queryClient.invalidateQueries({ queryKey: ['document-status-capabilities', docId] })
      queryClient.invalidateQueries({ queryKey: ['project-documents', projectId] })
      addToast({ title: '流程状态已更新' })
    },
    onError: (error: Error) => {
      addToast({ title: '状态更新失败', description: error.message, variant: 'destructive' })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => documentsApi.delete(docId),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ['document', docId] })
      queryClient.invalidateQueries({ queryKey: ['project-documents', projectId] })
      addToast({ title: '文档已删除' })
      router.push(`/projects/${projectId}/documents`)
    },
    onError: (error: Error) => {
      addToast({ title: '删除文档失败', description: error.message, variant: 'destructive' })
    },
  })

  const editMutation = useMutation({
    mutationFn: async () => {
      if (!document) return null

      if (editContent !== document.content) {
        await collaborationApi.createVersion(docId, {
          content: editContent,
          changes_summary: editSummary.trim() || '手动编辑文档',
        })
      }

      if (editTitle.trim() && editTitle.trim() !== document.name) {
        await documentsApi.update(docId, { title: editTitle.trim() })
      }

      return documentsApi.get(docId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['document', docId] })
      queryClient.invalidateQueries({ queryKey: ['document-versions', docId] })
      queryClient.invalidateQueries({ queryKey: ['document-status-capabilities', docId] })
      queryClient.invalidateQueries({ queryKey: ['project-documents', projectId] })
      setShowEditDialog(false)
      addToast({ title: '文档已保存', description: '正文和版本历史已更新。' })
    },
    onError: (error: Error) => {
      addToast({ title: '保存失败', description: error.message, variant: 'destructive' })
    },
  })

  const createBaselineMutation = useMutation({
    mutationFn: () => {
      const version = versions[0]
      if (!version) {
        throw new Error('No persisted version is available for baseline creation')
      }

      return collaborationApi.createBaseline(docId, {
        version_id: version.id,
        baseline_name: baselineName.trim(),
        baseline_reason: 'Created from document lifecycle workbench',
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['document-baselines', docId] })
      setBaselineName('')
      addToast({ title: '基线已创建' })
    },
    onError: (error: Error) => {
      addToast({ title: '基线创建失败', description: error.message, variant: 'destructive' })
    },
  })

  const rollbackBaselineMutation = useMutation({
    mutationFn: (baselineId: string) => collaborationApi.rollbackBaseline(docId, baselineId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['document', docId] })
      queryClient.invalidateQueries({ queryKey: ['document-versions', docId] })
      queryClient.invalidateQueries({ queryKey: ['document-baselines', docId] })
      queryClient.invalidateQueries({ queryKey: ['document-status-capabilities', docId] })
      addToast({ title: '已从基线恢复' })
    },
    onError: (error: Error) => {
      addToast({ title: '基线恢复失败', description: error.message, variant: 'destructive' })
    },
  })

  const createSnapshotMutation = useMutation({
    mutationFn: () => collaborationApi.createSnapshot(docId, { snapshot_type: 'manual' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['document-snapshots', docId] })
      addToast({ title: '快照已创建' })
    },
    onError: (error: Error) => {
      addToast({ title: '快照创建失败', description: error.message, variant: 'destructive' })
    },
  })

  const autoSnapshotMutation = useMutation({
    mutationFn: (draft: { title: string; content: string; signature: string }) =>
      collaborationApi.createSnapshot(docId, {
        snapshot_type: 'auto',
        title: draft.title.trim(),
        content: draft.content,
      }),
    onMutate: () => {
      setAutoSaveStatus('saving')
    },
    onSuccess: (snapshot, draft) => {
      lastAutoSavedSignatureRef.current = draft.signature
      setLastAutoSavedAt(snapshot.createdAt || null)
      setAutoSaveStatus('saved')
      queryClient.invalidateQueries({ queryKey: ['document-snapshots', docId] })
      if (closeAfterAutosaveRef.current) {
        closeAfterAutosaveRef.current = false
        setShowEditDialog(false)
      }
    },
    onError: (error: Error) => {
      closeAfterAutosaveRef.current = false
      setAutoSaveStatus('error')
      addToast({
        title: '自动保存失败',
        description: `${error.message}。编辑窗口保持打开，草稿未丢失，可点击重试。`,
        variant: 'destructive',
      })
    },
  })

  const restoreSnapshotMutation = useMutation({
    mutationFn: (snapshotId: string) => collaborationApi.restoreSnapshot(snapshotId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['document', docId] })
      queryClient.invalidateQueries({ queryKey: ['document-versions', docId] })
      queryClient.invalidateQueries({ queryKey: ['document-snapshots', docId] })
      queryClient.invalidateQueries({ queryKey: ['document-status-capabilities', docId] })
      queryClient.invalidateQueries({ queryKey: ['project-documents', projectId] })
      addToast({ title: '已从快照恢复', description: '恢复前正文已写入版本历史，可继续追溯。' })
    },
    onError: (error: Error) => {
      addToast({ title: '快照恢复失败', description: error.message, variant: 'destructive' })
    },
  })

  editDraftRef.current = { title: editTitle, content: editContent }
  autoSnapshotRunnerRef.current = (notify = false) => {
    const draft = editDraftRef.current
    const signature = draftSignature(draft.title, draft.content)
    if (signature === lastAutoSavedSignatureRef.current || autoSnapshotMutation.isPending) {
      if (notify && signature === lastAutoSavedSignatureRef.current) {
        addToast({ title: '草稿已是最新状态' })
      }
      return
    }
    autoSnapshotMutation.mutate({
      ...draft,
      title: draft.title.trim() || document?.name || '未命名文档',
      signature,
    })
  }

  useEffect(() => {
    if (!showEditDialog) return
    const timer = window.setInterval(() => autoSnapshotRunnerRef.current(false), DOCUMENT_AUTOSAVE_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [showEditDialog, docId])

  const handleAddComment = () => {
    if (newComment.trim()) {
      addCommentMutation.mutate({ content: newComment, anchor: commentAnchor || undefined })
    }
  }

  const handleReply = (commentId: string) => {
    if (!replyContent.trim()) return
    addCommentMutation.mutate({ content: replyContent, parent_comment_id: commentId })
  }

  const handleLocateComment = (anchor: string) => {
    setLocatedCommentAnchor(anchor)
    setActiveContentTab('content')
    window.setTimeout(() => {
      const target = Array.from(window.document.querySelectorAll<HTMLElement>('[data-comment-anchor]'))
        .find((element) => element.dataset.commentAnchor === anchor)
      target?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 0)
  }

  const handleStatusChange = (newStatus: string) => {
    statusMutation.mutate(newStatus)
  }

  const unresolvedComments = comments.filter((comment) => !comment.resolved).length
  const commentAnchors = getDocumentCommentAnchors(document?.content || '')
  const rootComments = comments.filter((comment) => !comment.parentCommentId)
  const repliesByParent = comments.reduce<Record<string, Comment[]>>((groups, comment) => {
    if (comment.parentCommentId) {
      groups[comment.parentCommentId] = [...(groups[comment.parentCommentId] || []), comment]
    }
    return groups
  }, {})
  const filteredRootComments = rootComments.filter((comment) => {
    const thread = [comment, ...(repliesByParent[comment.id] || [])]
    if (commentFilter === 'unresolved') return thread.some((item) => !item.resolved)
    if (commentFilter === 'resolved') return thread.every((item) => item.resolved)
    return true
  })
  const currentDocumentStatus = document?.status || 'draft'
  const statusCapabilityMap = new Map(
    (statusCapabilities?.capabilities || []).map((capability) => [capability.status, capability])
  )
  const canTransitionTo = (status: string) => statusCapabilityMap.get(status)?.allowed === true
  const unresolvedTemplatePlaceholders = document ? getUnresolvedTemplatePlaceholders(document) : []
  const unresolvedTemplateSummary = document ? templatePlaceholderSummary(document) : ''
  const canApprove = canTransitionTo('approved')
  const canPublish = canTransitionTo('published')
  const canArchive = canTransitionTo('archived')
  const latestStatusHistory = [...statusHistory].reverse()
  const governedCapabilities = ['approved', 'published', 'archived'].map((status) => ({
    status,
    label: statusCapabilityMap.get(status)?.label || STATUS_ACTION_LABELS[status],
    capability: statusCapabilityMap.get(status),
  }))

  const handleDeleteDocument = () => {
    if (!document) return
    if (window.confirm(`确认删除文档“${document.name}”？删除后无法恢复。`)) {
      deleteMutation.mutate()
    }
  }

  const openEditDialog = () => {
    if (!document) return
    setEditTitle(document.name)
    setEditContent(document.content || '')
    setEditSummary('手动编辑文档')
    lastAutoSavedSignatureRef.current = draftSignature(document.name, document.content || '')
    const latestAutoSnapshot = snapshots.find((snapshot) => snapshot.snapshotType === 'auto')
    setLastAutoSavedAt(latestAutoSnapshot?.createdAt || null)
    setAutoSaveStatus(latestAutoSnapshot ? 'saved' : 'idle')
    closeAfterAutosaveRef.current = false
    setShowEditDialog(true)
  }

  const handleEditDialogOpenChange = (open: boolean) => {
    if (open) {
      setShowEditDialog(true)
      return
    }
    const draft = editDraftRef.current
    const hasUnsavedDraft = draftSignature(draft.title, draft.content) !== lastAutoSavedSignatureRef.current
    if (hasUnsavedDraft) {
      closeAfterAutosaveRef.current = true
      autoSnapshotRunnerRef.current(false)
      return
    }
    setShowEditDialog(false)
  }

  const handleRestoreSnapshot = (snapshot: DocumentSnapshot) => {
    const label = snapshot.snapshotType === 'auto' ? '自动保存草稿' : '人工快照'
    if (window.confirm(`确认恢复${label}？当前正文会先写入版本历史，然后替换为所选快照内容。`)) {
      restoreSnapshotMutation.mutate(snapshot.id)
    }
  }

  const handleExport = async () => {
    if (!document) return
    if (hasUnresolvedTemplatePlaceholders(document)) {
      addToast({
        title: '模板变量未补齐',
        description: `请先补齐：${templatePlaceholderSummary(document)}`,
        variant: 'destructive',
      })
      return
    }
    try {
      addToast({ title: '正在提交导出任务...' })
      await exportsApi.createMarkdown({
        document_id: document.id,
        title: document.name,
      })
      addToast({
        title: '导出任务已提交',
        description: '正在跳转到导出中心查看进度...',
      })
      setTimeout(() => {
        router.push('/exports')
      }, 1000)
    } catch (error: any) {
      addToast({
        title: '提交导出任务失败',
        description: error.message || '未知错误',
        variant: 'destructive',
      })
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-slate-500 dark:text-slate-400">正在加载文档...</div>
      </div>
    )
  }

  if (!document) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <div className="text-red-500">未找到文档</div>
        <Button variant="outline" onClick={() => router.push(`/projects/${projectId}/documents`)}>
          <ArrowLeft className="mr-2 h-4 w-4" />
          返回文档列表
        </Button>
      </div>
    )
  }

  
  const getStatusBadge = (status?: string) => {
    switch (status) {
      case 'published':
        return <Badge className="bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200">已发布</Badge>
      case 'draft':
        return <Badge variant="secondary">草稿</Badge>
      case 'writing':
        return <Badge className="bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200">编写中</Badge>
      case 'pending_review':
        return <Badge className="bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200">待评审</Badge>
      case 'review':
      case 'in_review':
        return <Badge className="bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200">评审中</Badge>
      case 'revision_required':
        return <Badge className="bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200">待修订</Badge>
      case 'rejected':
        return <Badge className="bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200">已退回</Badge>
      case 'approved':
        return <Badge className="bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200">已批准</Badge>
      case 'archived':
        return <Badge variant="secondary">已归档</Badge>
      default:
        return <Badge variant="secondary">草稿</Badge>
    }
  }

  const currentVersion: Version = {
    id: `${document.id}-current`,
    documentId: document.id,
    versionNumber: (document as any).version ?? Math.max(1, versions.length + 1),
    description: '当前版本',
    content: document.content || '',
    createdBy: (document as any).created_by ?? '当前用户',
    createdAt: document.updatedAt,
  }
  const versionTimeline = versions.length > 0 ? [currentVersion, ...versions] : [currentVersion]
  const isArchived = (document.metadata?.status || document.status) === 'archived'
  const deliveryMeta = document.metadata?.delivery || (document as any).metadata_json?.delivery || {}
  const deliveryQuality = deliveryMeta.quality_summary || {}
  const deliveryCompletion = Math.round((deliveryMeta.completion_ratio ?? 0) * 100)
  const deliveryPendingConfirmations = Array.isArray(deliveryMeta.pending_confirmations)
    ? deliveryMeta.pending_confirmations
    : []
  const deliveryUpstreamDependencies = Array.isArray(deliveryMeta.upstream_dependencies)
    ? deliveryMeta.upstream_dependencies
    : []
  const releaseBlockers = [
    ...(unresolvedTemplateSummary ? [`未填模板变量：${unresolvedTemplateSummary}`] : []),
    ...((['approved', 'published'].includes(currentDocumentStatus)) ? [] : ['文档尚未批准或发布']),
    ...(unresolvedComments > 0 ? [`${unresolvedComments} 条评论未解决`] : []),
    ...(deliveryPendingConfirmations.length > 0 ? [`${deliveryPendingConfirmations.length} 个生成确认项未关闭`] : []),
  ]
  const exportReady = releaseBlockers.length === 0
  const traceabilityReady = deliveryUpstreamDependencies.length > 0 && deliveryPendingConfirmations.length === 0
  const collaborationActionCount = unresolvedComments + (canApprove ? 1 : 0) + (exportReady ? 0 : 1)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="sm" onClick={() => router.push(`/projects/${projectId}/documents`)}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">{document.name}</h1>
            {getStatusBadge(document.status)}
          </div>
          <p className="text-sm text-slate-500 mt-1">
            {getDocumentTypeLabel(document.type)} • 更新于 {formatDistanceToNow(document.updatedAt)}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setShowVersionHistory(true)}>
            <History className="mr-2 h-4 w-4" />
            版本历史
          </Button>
          <Button variant="outline" onClick={handleExport} disabled={!exportReady} data-testid="document-export-action">
            <Download className="mr-2 h-4 w-4" />
            导出
          </Button>
          <Button
            variant="outline"
            onClick={() => handleStatusChange('archived')}
            disabled={isArchived || !canArchive || statusMutation.isPending}
            data-testid="document-archive-action"
          >
            <Archive className="mr-2 h-4 w-4" />
            归档
          </Button>
          <Button
            variant="destructive"
            onClick={handleDeleteDocument}
            disabled={deleteMutation.isPending}
            data-testid="document-delete-action"
          >
            <Trash2 className="mr-2 h-4 w-4" />
            删除
          </Button>
          <Button data-testid="open-edit-document" onClick={openEditDialog} disabled={isArchived}>
            <Edit className="mr-2 h-4 w-4" />
            编辑
          </Button>
        </div>
      </div>

      {unresolvedTemplatePlaceholders.length > 0 && (
        <Card data-testid="document-template-placeholder-panel" className="border-red-200 bg-red-50/70 dark:border-red-900 dark:bg-red-950/30">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-red-900 dark:text-red-100">
              <AlertTriangle className="h-5 w-5" />
              模板变量未补齐
            </CardTitle>
            <CardDescription className="text-red-800 dark:text-red-200">
              当前文档仍包含模板变量，必须补齐后才能发布、导出或纳入正式交付包。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div data-testid="document-template-placeholder-release-blocker" className="text-sm font-medium text-red-900 dark:text-red-100">
              未填模板变量：{unresolvedTemplatePlaceholders.join('、')}
            </div>
            <div className="flex flex-wrap gap-2">
              {unresolvedTemplatePlaceholders.map((placeholder) => (
                <Badge key={placeholder} className="bg-white text-red-800 dark:bg-red-950 dark:text-red-100">
                  {placeholder}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <Card data-testid="document-delivery-readiness">
        <CardHeader>
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <PackageCheck className="h-5 w-5 text-indigo-500" />
                交付证据与发布准备度
              </CardTitle>
              <CardDescription>
                汇总对话式写入、质量摘要、上游依赖、评论和发布阻塞，避免只看正文就进入导出。
              </CardDescription>
            </div>
            <Badge variant={releaseBlockers.length === 0 ? 'secondary' : 'destructive'}>
              {releaseBlockers.length === 0 ? '可发布/导出' : `${releaseBlockers.length} 个阻塞`}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-4">
            <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <CheckCircle className="h-4 w-4 text-emerald-500" />
                完成度
              </div>
              <p className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{deliveryCompletion || 0}%</p>
            </div>
            <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <ShieldCheck className="h-4 w-4 text-indigo-500" />
                质量等级
              </div>
              <p className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">
                {deliveryQuality.sufficiency_level || deliveryQuality.level || '未评估'}
              </p>
            </div>
            <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <GitBranch className="h-4 w-4 text-indigo-500" />
                上游依赖
              </div>
              <p className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{deliveryUpstreamDependencies.length}</p>
            </div>
            <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <MessageSquare className="h-4 w-4 text-indigo-500" />
                未解决评论
              </div>
              <p className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{unresolvedComments}</p>
            </div>
          </div>

          {releaseBlockers.length > 0 ? (
            <div className="space-y-2">
              {releaseBlockers.map((blocker) => (
                <div key={blocker} className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
                  <AlertTriangle className="h-4 w-4" />
                  {blocker}
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-100">
              当前文档没有发布阻塞，可以进入导出或交付包流程。
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => router.push(`/projects/${projectId}/traceability`)}>
              <GitBranch className="mr-2 h-4 w-4" />
              查看追溯
            </Button>
            <Button variant="outline" size="sm" onClick={handleExport} disabled={!exportReady}>
              <Download className="mr-2 h-4 w-4" />
              提交导出
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card data-testid="document-delivery-review-panel">
        <CardHeader>
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Workflow className="h-5 w-5 text-indigo-500" />
                交付/评审作战面板
              </CardTitle>
              <CardDescription>
                将生命周期、评论/版本、交付包、追溯和协同动作收拢到一个面板，作为发布或导出前的操作检查单。
              </CardDescription>
            </div>
            <Badge variant={exportReady ? 'secondary' : 'destructive'}>
              {exportReady ? '交付包可纳入' : `${releaseBlockers.length} 个交付阻塞`}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
              <p className="text-sm font-medium text-slate-900 dark:text-white">生命周期</p>
              <p className="mt-2 text-lg font-semibold text-slate-900 dark:text-white">
                {getDocumentStatusLabel(currentDocumentStatus)}
              </p>
              <p className="mt-1 text-xs text-slate-500">当前状态：{currentDocumentStatus}</p>
            </div>
            <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
              <p className="text-sm font-medium text-slate-900 dark:text-white">评论/版本</p>
              <p className="mt-2 text-lg font-semibold text-slate-900 dark:text-white">
                {unresolvedComments}/{comments.length} · {versionTimeline.length} 版
              </p>
              <p className="mt-1 text-xs text-slate-500">评论关闭后再进入批准和发布</p>
            </div>
            <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
              <p className="text-sm font-medium text-slate-900 dark:text-white">交付包</p>
              <p className="mt-2 text-lg font-semibold text-slate-900 dark:text-white">
                {exportReady ? '可打包' : '待处理'}
              </p>
              <p className="mt-1 text-xs text-slate-500">导出前校验发布状态和评论清单</p>
            </div>
            <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
              <p className="text-sm font-medium text-slate-900 dark:text-white">追溯</p>
              <p className="mt-2 text-lg font-semibold text-slate-900 dark:text-white">
                {deliveryUpstreamDependencies.length} 上游
              </p>
              <p className="mt-1 text-xs text-slate-500">{traceabilityReady ? '依赖已记录' : '需确认依赖或生成确认项'}</p>
            </div>
            <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
              <p className="text-sm font-medium text-slate-900 dark:text-white">协同动作</p>
              <p className="mt-2 text-lg font-semibold text-slate-900 dark:text-white">{collaborationActionCount}</p>
              <p className="mt-1 text-xs text-slate-500">评审、评论、版本和导出动作统一处理</p>
            </div>
          </div>

          <div className="grid gap-3 lg:grid-cols-[1fr_1fr]">
            <div className="space-y-2">
              <p className="text-xs font-medium uppercase text-slate-500">阻塞与证据</p>
              {releaseBlockers.length === 0 ? (
                <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-100">
                  生命周期、评论和交付包前置条件已满足。
                </div>
              ) : (
                releaseBlockers.map((blocker) => (
                  <div key={blocker} className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
                    {blocker}
                  </div>
                ))
              )}
              <div className="grid gap-2 sm:grid-cols-3">
                <div className="rounded-md bg-slate-50 p-3 text-xs text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                  基线 {baselines.length}
                </div>
                <div className="rounded-md bg-slate-50 p-3 text-xs text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                  快照 {snapshots.length}
                </div>
                <div className="rounded-md bg-slate-50 p-3 text-xs text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                  状态记录 {latestStatusHistory.length}
                </div>
              </div>
            </div>

            <div className="space-y-2">
              <p className="text-xs font-medium uppercase text-slate-500">协同动作入口</p>
              <div className="grid gap-2 sm:grid-cols-2">
                <Button variant="outline" size="sm" className="justify-start" onClick={() => handleStatusChange('review')} disabled={isArchived || !canTransitionTo('review') || statusMutation.isPending}>
                  <ShieldCheck className="mr-2 h-4 w-4" />
                  提交评审
                </Button>
                <Button variant="outline" size="sm" className="justify-start" onClick={() => setShowVersionHistory(true)}>
                  <History className="mr-2 h-4 w-4" />
                  查看版本
                </Button>
                <Button variant="outline" size="sm" className="justify-start" onClick={() => router.push(`/projects/${projectId}/traceability`)}>
                  <GitBranch className="mr-2 h-4 w-4" />
                  查看追溯
                </Button>
                <Button variant="outline" size="sm" className="justify-start" onClick={handleExport} disabled={!exportReady}>
                  <PackageCheck className="mr-2 h-4 w-4" />
                  提交导出
                </Button>
                <Button variant="outline" size="sm" className="justify-start sm:col-span-2" onClick={() => router.push('/collaboration')}>
                  <Users className="mr-2 h-4 w-4" />
                  打开协同评审
                </Button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div>
              <CardTitle data-testid="document-lifecycle-heading">文档生命周期</CardTitle>
              <CardDescription>
                汇总正文、评审评论、版本、基线和快照，发布前必须处理所有未解决评论。
              </CardDescription>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline" data-testid="document-status-current">
                {document.status || 'draft'} · {getDocumentStatusLabel(document.status || 'draft')}
              </Badge>
              <Badge variant="outline">版本：{(document as any).version ?? Math.max(1, versions.length)}</Badge>
              {statusCapabilities?.policy_revision ? (
                <Badge variant="outline">流程修订：{statusCapabilities.policy_revision}</Badge>
              ) : null}
              <Badge variant={canPublish ? 'secondary' : 'destructive'}>
                未解决评论 <span data-testid="unresolved-comments-count" className="ml-1">{unresolvedComments}</span>
              </Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div
            data-testid="document-status-governance"
            className="grid gap-3 md:grid-cols-3"
          >
            {governedCapabilities.map(({ status, label, capability }) => (
              <div
                key={status}
                data-testid={`document-status-capability-${status}`}
                className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-slate-900 dark:text-white">{label}</span>
                  <Badge variant={capability?.allowed ? 'secondary' : 'outline'}>
                    {capability?.allowed ? '可执行' : '受限'}
                  </Badge>
                </div>
                <p
                  className="mt-2 text-xs text-slate-500"
                  data-testid={`document-status-capability-message-${status}`}
                >
                  {getStatusCapabilityMessage(capability)}
                </p>
              </div>
            ))}
          </div>

          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="text-sm text-slate-600 dark:text-slate-300">
              {canPublish ? '评审阻塞已清除，可以发布。' : '发布需要文档已批准且没有未解决评论。'}
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onClick={() => handleStatusChange('draft')} disabled={isArchived || !canTransitionTo('draft') || statusMutation.isPending}>
                退回草稿
              </Button>
              <Button variant="outline" size="sm" onClick={() => handleStatusChange('review')} disabled={isArchived || !canTransitionTo('review') || statusMutation.isPending}>
                提交评审
              </Button>
              <Button
                data-testid="document-approve-action"
                variant="outline"
                size="sm"
                onClick={() => handleStatusChange('approved')}
                disabled={isArchived || !canApprove || statusMutation.isPending}
              >
                批准
              </Button>
              <Button
                data-testid="document-publish-action"
                size="sm"
                onClick={() => handleStatusChange('published')}
                disabled={isArchived || !canPublish || statusMutation.isPending}
              >
                <CheckCircle className="mr-2 h-4 w-4" />
                发布
              </Button>
            </div>
          </div>

          <div className="border-t border-slate-200 pt-4 dark:border-slate-700">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div data-testid="document-review-flow-heading" className="text-sm font-medium text-slate-900 dark:text-white">
                  评审轨迹
                </div>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  记录状态跳转、操作原因和发布门禁结果。
                </p>
              </div>
              <Badge variant="outline">最近 {latestStatusHistory.length} 条</Badge>
            </div>
            <div data-testid="status-history-list" className="mt-3 space-y-2">
              {latestStatusHistory.length === 0 ? (
                <div className="rounded-md border border-dashed border-slate-300 p-3 text-sm text-slate-500 dark:border-slate-700">
                  暂无状态变更记录
                </div>
              ) : (
                latestStatusHistory.map((item) => {
                  const transitionKey = statusTransitionKey(item)
                  return (
                  <div
                    key={transitionKey}
                    data-testid={`status-history-item-${transitionKey}`}
                    className="rounded-md border border-slate-200 p-3 text-sm dark:border-slate-700"
                  >
                    <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                      <div className="font-medium text-slate-900 dark:text-white">
                        {item.from_status} → {item.to_status}
                      </div>
                      <span className="text-xs text-slate-500">{formatDistanceToNow(item.changed_at)}</span>
                    </div>
                    {item.reason && (
                      <p className="mt-2 text-slate-600 dark:text-slate-300">{item.reason}</p>
                    )}
                    <p className="mt-1 text-xs text-slate-500">
                      操作：{item.action} · 未解决评论：{item.unresolved_comment_count}
                    </p>
                  </div>
                  )
                })
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Content Tabs */}
      <Tabs value={activeContentTab} onValueChange={setActiveContentTab} className="space-y-4">
        <TabsList>
          <TabsTrigger data-testid="document-tab-content" value="content">正文</TabsTrigger>
          <TabsTrigger data-testid="document-tab-comments" value="comments">
            <MessageSquare className="mr-2 h-4 w-4" />
            评论 ({comments.length})
          </TabsTrigger>
          <TabsTrigger data-testid="document-tab-versions" value="versions">版本</TabsTrigger>
          <TabsTrigger data-testid="document-tab-baselines" value="baselines">基线</TabsTrigger>
          <TabsTrigger data-testid="document-tab-snapshots" value="snapshots">快照</TabsTrigger>
        </TabsList>

        <TabsContent value="content">
          <Card>
            <CardContent className="py-6">
              <div className="prose dark:prose-invert max-w-none">
                {document.content ? (
                  <div data-testid="document-content-preview" className="text-slate-700 dark:text-slate-300">
                    {getDocumentContentPreviewLines(document.content).map(({ line, anchor, key }) => {
                      const isLocated = Boolean(anchor && locatedCommentAnchor === anchor)
                      return (
                        <div
                          key={key}
                          data-comment-anchor={anchor || undefined}
                          className={isLocated
                            ? 'rounded border-l-4 border-indigo-500 bg-indigo-50 px-3 py-1 text-indigo-950 dark:bg-indigo-950/40 dark:text-indigo-100'
                            : 'min-h-6 whitespace-pre-wrap'}
                        >
                          {line || '\u00a0'}
                        </div>
                      )
                    })}
                  </div>
                ) : (
                  <div className="text-center py-12 text-slate-500">
                    <FileText className="mx-auto h-12 w-12 text-slate-300" />
                    <p className="mt-4">暂无正文内容</p>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="comments">
          <Card>
            <CardHeader>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <CardTitle>评论评审</CardTitle>
                  <CardDescription>将评论定位到章节或段落，在线程中回复并关闭评审项。</CardDescription>
                </div>
                <Select
                  data-testid="comment-status-filter"
                  value={commentFilter}
                  onValueChange={(value) => setCommentFilter(value as typeof commentFilter)}
                  className="w-full sm:w-40"
                >
                  <SelectOption value="all">全部评论</SelectOption>
                  <SelectOption value="unresolved">仅未解决</SelectOption>
                  <SelectOption value="resolved">仅已解决</SelectOption>
                </Select>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Comments List */}
              {filteredRootComments.length === 0 ? (
                <div className="text-center py-8 text-slate-500">
                  <MessageSquare className="mx-auto h-10 w-10 text-slate-300" />
                  <p className="mt-2">{comments.length === 0 ? '暂无评论' : '当前筛选条件下暂无评论'}</p>
                </div>
              ) : (
                <div className="space-y-4">
                  {filteredRootComments.map((comment) => {
                    const replies = repliesByParent[comment.id] || []
                    return (
                      <div key={comment.id} data-testid={`comment-thread-${comment.id}`} className="rounded-lg border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-800">
                        <div className="flex gap-3">
                          <Avatar className="h-8 w-8">
                            <div className="flex h-full w-full items-center justify-center bg-indigo-100 text-xs font-medium text-indigo-600">
                              {comment.authorId?.charAt(0) || 'U'}
                            </div>
                          </Avatar>
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-sm font-medium text-slate-900 dark:text-white">
                                用户 {comment.authorId?.slice(0, 8) || '未知'}
                              </span>
                              <span className="text-xs text-slate-500">{formatDistanceToNow(comment.createdAt)}</span>
                              <Badge variant={comment.resolved ? 'secondary' : 'destructive'} className="text-xs">
                                {comment.resolved ? '已解决' : '待处理'}
                              </Badge>
                            </div>
                            {comment.anchor && (
                              <button
                                type="button"
                                data-testid={`locate-comment-${comment.id}`}
                                className="mt-2 flex max-w-full items-center gap-1 text-left text-xs text-indigo-600 hover:underline dark:text-indigo-300"
                                onClick={() => handleLocateComment(comment.anchor!)}
                              >
                                <MapPin className="h-3.5 w-3.5 shrink-0" />
                                <span className="truncate">{comment.anchor.replace(/^#{1,6}\s+/, '')}</span>
                              </button>
                            )}
                            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{comment.content}</p>
                            <div className="mt-3 flex flex-wrap gap-2">
                              <Button
                                data-testid={`reply-comment-${comment.id}`}
                                variant="outline"
                                size="sm"
                                onClick={() => {
                                  setReplyingToCommentId(replyingToCommentId === comment.id ? null : comment.id)
                                  setReplyContent('')
                                }}
                              >
                                <Reply className="mr-1 h-4 w-4" />
                                回复
                              </Button>
                              {!comment.resolved && (
                                <Button
                                  data-testid={`resolve-comment-${comment.id}`}
                                  variant="outline"
                                  size="sm"
                                  onClick={() => resolveCommentMutation.mutate(comment.id)}
                                  disabled={resolveCommentMutation.isPending}
                                >
                                  标记解决
                                </Button>
                              )}
                            </div>
                          </div>
                        </div>

                        {replies.length > 0 && (
                          <div className="mt-4 space-y-3 border-l-2 border-slate-200 pl-4 dark:border-slate-700">
                            {replies.map((reply) => (
                              <div key={reply.id} data-testid={`comment-reply-${reply.id}`} className="rounded-md bg-white p-3 dark:bg-slate-900">
                                <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                                  <span className="font-medium text-slate-700 dark:text-slate-200">
                                    用户 {reply.authorId?.slice(0, 8) || '未知'}
                                  </span>
                                  <span>{formatDistanceToNow(reply.createdAt)}</span>
                                  {reply.resolved && <Badge variant="secondary" className="text-xs">已关闭</Badge>}
                                </div>
                                <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{reply.content}</p>
                              </div>
                            ))}
                          </div>
                        )}

                        {replyingToCommentId === comment.id && (
                          <div className="mt-4 flex gap-2 border-t border-slate-200 pt-3 dark:border-slate-700">
                            <Input
                              data-testid={`reply-input-${comment.id}`}
                              placeholder="回复此评审线程..."
                              value={replyContent}
                              onChange={(event) => setReplyContent(event.target.value)}
                            />
                            <Button
                              data-testid={`submit-reply-${comment.id}`}
                              onClick={() => handleReply(comment.id)}
                              disabled={!replyContent.trim() || addCommentMutation.isPending}
                            >
                              <Send className="h-4 w-4" />
                            </Button>
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}

              {/* Add Comment */}
              <div className="space-y-3 border-t border-slate-200 pt-4 dark:border-slate-700">
                <Select
                  data-testid="comment-anchor-select"
                  value={commentAnchor}
                  onValueChange={setCommentAnchor}
                >
                  <SelectOption value="">整篇文档</SelectOption>
                  {commentAnchors.map((anchor) => (
                    <SelectOption key={anchor.value} value={anchor.value}>
                      {anchor.type}：{anchor.label}
                    </SelectOption>
                  ))}
                </Select>
                <div className="flex gap-3">
                  <Input
                    data-testid="new-comment-input"
                    placeholder="添加评审评论..."
                    value={newComment}
                    onChange={(e) => setNewComment(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault()
                        handleAddComment()
                      }
                    }}
                  />
                  <Button data-testid="add-comment-action" onClick={handleAddComment} disabled={!newComment.trim() || addCommentMutation.isPending}>
                    <Send className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="versions">
          <Card>
            <CardHeader>
              <CardTitle>版本时间线</CardTitle>
              <CardDescription>查看当前正文和历史版本内容，编辑保存会自动写入新版本。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {versionTimeline.map((version) => (
                <div
                  key={version.id}
                  data-testid={`version-item-${version.id}`}
                  className="rounded-lg border border-slate-200 p-4 dark:border-slate-700"
                >
                  <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                    <div className="font-medium text-slate-900 dark:text-white">
                      版本 {version.versionNumber}
                    </div>
                    <span className="text-xs text-slate-500">{formatDistanceToNow(version.createdAt)}</span>
                  </div>
                  <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{version.description}</p>
                  {version.content && (
                    <pre className="mt-3 max-h-48 overflow-auto whitespace-pre-wrap rounded-md bg-slate-50 p-3 text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                      {version.content.slice(0, 2400)}
                    </pre>
                  )}
                </div>
              ))}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="baselines">
          <Card>
            <CardHeader>
              <CardTitle>基线管理</CardTitle>
              <CardDescription>将已保存版本固化为评审基线，并可按需回滚正文。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-col gap-3 md:flex-row">
                <Input
                  data-testid="baseline-name-input"
                  placeholder="基线名称"
                  value={baselineName}
                  onChange={(event) => setBaselineName(event.target.value)}
                />
                <Button
                  data-testid="create-baseline-action"
                  onClick={() => createBaselineMutation.mutate()}
                  disabled={!baselineName.trim() || versions.length === 0 || createBaselineMutation.isPending}
                >
                  创建基线
                </Button>
              </div>
              {versions.length === 0 && (
                <p className="text-sm text-amber-600 dark:text-amber-300">
                  需要先保存至少一个历史版本，才能创建基线。
                </p>
              )}
              <div className="space-y-3">
                {baselines.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-slate-700">
                    暂无基线
                  </div>
                ) : (
                  baselines.map((baseline) => (
                    <div
                      key={baseline.id}
                      data-testid={`baseline-item-${baseline.id}`}
                      className="flex flex-col gap-3 rounded-lg border border-slate-200 p-4 dark:border-slate-700 md:flex-row md:items-center md:justify-between"
                    >
                      <div>
                        <div className="font-medium text-slate-900 dark:text-white">{baseline.name}</div>
                        <p className="text-xs text-slate-500">
                          版本 {baseline.versionId.slice(0, 8)} · {formatDistanceToNow(baseline.createdAt)}
                        </p>
                      </div>
                      <Button
                        data-testid={`rollback-baseline-${baseline.id}`}
                        variant="outline"
                        size="sm"
                        onClick={() => rollbackBaselineMutation.mutate(baseline.id)}
                        disabled={rollbackBaselineMutation.isPending}
                      >
                        回滚
                      </Button>
                    </div>
                  ))
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="snapshots">
          <Card>
            <CardHeader>
              <CardTitle>快照恢复</CardTitle>
              <CardDescription>查看自动保存草稿或创建人工快照，并安全恢复可追溯的正文状态。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <Button
                data-testid="create-snapshot-action"
                onClick={() => createSnapshotMutation.mutate()}
                disabled={createSnapshotMutation.isPending}
              >
                创建快照
              </Button>
              <div className="space-y-3">
                {snapshots.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-slate-700">
                    暂无快照
                  </div>
                ) : (
                  snapshots.map((snapshot) => (
                    <div
                      key={snapshot.id}
                      data-testid={`snapshot-item-${snapshot.id}`}
                      className="flex flex-col gap-3 rounded-lg border border-slate-200 p-4 dark:border-slate-700 md:flex-row md:items-center md:justify-between"
                    >
                      <div>
                        <div className="font-medium text-slate-900 dark:text-white">
                          {snapshot.snapshotType === 'auto' ? '自动保存草稿' : '人工快照'} · 正式版本 {snapshot.version}
                        </div>
                        <p className="text-xs text-slate-500">{formatDistanceToNow(snapshot.createdAt)}</p>
                        <p className="mt-1 line-clamp-2 text-xs text-slate-500">
                          {String(snapshot.snapshotData?.content || '无正文内容').slice(0, 160)}
                        </p>
                      </div>
                      <Button
                        data-testid={`restore-snapshot-${snapshot.id}`}
                        variant="outline"
                        size="sm"
                        onClick={() => handleRestoreSnapshot(snapshot)}
                        disabled={restoreSnapshotMutation.isPending}
                      >
                        恢复
                      </Button>
                    </div>
                  ))
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Version History Dialog */}
      <Dialog open={showVersionHistory} onOpenChange={setShowVersionHistory}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>版本历史</DialogTitle>
            <DialogDescription>文档版本时间线</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4 max-h-96 overflow-y-auto">
            {versions.length === 0 && (
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300">
                当前只有一个可见版本。点击“编辑”并保存正文变更后，系统会自动生成新的历史版本。
              </div>
            )}
            <div className="space-y-3">
                {versionTimeline.map((version) => (
                  <div
                    key={version.id}
                    className="flex items-start gap-3 p-3 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800"
                  >
                    <div className="rounded-full bg-indigo-100 p-2 dark:bg-indigo-900">
                      <History className="h-4 w-4 text-indigo-600 dark:text-indigo-400" />
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium text-slate-900 dark:text-white">
                          版本 {version.versionNumber}
                        </span>
                        <span className="text-xs text-slate-500">
                          {formatDistanceToNow(version.createdAt)}
                        </span>
                      </div>
                      <p className="text-sm text-slate-600 dark:text-slate-400 mt-1">
                        {version.description}
                      </p>
                      <p className="text-xs text-slate-500 mt-1">
                        创建人 {version.createdBy}
                      </p>
                      {version.content && (
                        <details className="mt-2 rounded-md border border-slate-200 bg-white p-2 text-xs dark:border-slate-700 dark:bg-slate-900">
                          <summary className="cursor-pointer text-slate-700 dark:text-slate-200">查看版本内容</summary>
                          <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap text-slate-600 dark:text-slate-300">
                            {version.content.slice(0, 2000)}
                            {version.content.length > 2000 ? '\n\n...内容较长，已截断预览' : ''}
                          </pre>
                        </details>
                      )}
                    </div>
                  </div>
                ))}
              </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowVersionHistory(false)}>
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showEditDialog} onOpenChange={handleEditDialogOpenChange}>
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>编辑文档</DialogTitle>
            <DialogDescription>每 5 分钟自动保存未提交草稿；正式保存正文时写入版本历史。</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="document-title">标题</Label>
              <Input
                id="document-title"
                value={editTitle}
                onChange={(event) => setEditTitle(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="document-summary">版本说明</Label>
              <Input
                id="document-summary"
                data-testid="edit-document-summary"
                value={editSummary}
                onChange={(event) => setEditSummary(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="document-content">正文</Label>
              <textarea
                id="document-content"
                data-testid="edit-document-content"
                className="min-h-[360px] w-full rounded-md border border-slate-200 bg-white p-3 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 dark:placeholder:text-slate-500"
                value={editContent}
                onChange={(event) => setEditContent(event.target.value)}
              />
            </div>
            <div
              data-testid="document-autosave-status"
              className="flex flex-col gap-3 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm dark:border-slate-700 dark:bg-slate-900 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300">
                {autoSaveStatus === 'saving' ? (
                  <Loader2 className="h-4 w-4 animate-spin text-indigo-500" />
                ) : autoSaveStatus === 'error' ? (
                  <CloudOff className="h-4 w-4 text-red-500" />
                ) : (
                  <Cloud className="h-4 w-4 text-emerald-500" />
                )}
                <span>
                  {autoSaveStatus === 'saving'
                    ? '正在自动保存草稿...'
                    : autoSaveStatus === 'error'
                      ? '自动保存失败，请重试'
                      : lastAutoSavedAt
                        ? `已自动保存 · ${formatDistanceToNow(lastAutoSavedAt)}`
                        : autoSaveStatus === 'saved'
                          ? '已自动保存 · 未提供时间'
                          : '尚无自动保存草稿'}
                </span>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                data-testid="autosave-document-draft"
                onClick={() => autoSnapshotRunnerRef.current(true)}
                disabled={
                  autoSnapshotMutation.isPending
                  || draftSignature(editTitle, editContent) === lastAutoSavedSignatureRef.current
                }
              >
                立即保存草稿
              </Button>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => handleEditDialogOpenChange(false)}>取消</Button>
            <Button
              data-testid="save-document-action"
              onClick={() => editMutation.mutate()}
              disabled={!editTitle.trim() || editMutation.isPending}
            >
              {editMutation.isPending ? '保存中...' : '保存文档'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function FileText({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
      <polyline points="10 9 9 9 8 9" />
    </svg>
  )
}
