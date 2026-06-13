'use client'

import { useEffect, useMemo, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  agentApi,
  documentsApi,
  knowledgeApi,
  templatesApi,
  type DocumentGenerationTurnResult,
  type DocumentGenerationSection,
  type DocumentGenerationSession,
  type AgentProfile,
  type SkillCatalogEntry,
  type SkillCatalogTestResult,
  type Template,
} from '@/lib/api-client'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Label } from '@/components/ui/label'
import { useToast } from '@/components/ui/toast'
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle,
  ClipboardCopy,
  Clock3,
  FileText,
  FileCheck2,
  Gauge,
  ListChecks,
  Loader2,
  MessageSquare,
  RotateCcw,
  Send,
  ShieldCheck,
  SkipForward,
  Sparkles,
  XCircle,
} from 'lucide-react'

interface GenerateDocumentPageProps {
  params: { projectId: string }
}

const DOCUMENT_TYPES = [
  {
    value: 'urs',
    badge: 'URS',
    label: '用户需求规格说明书',
    description: '定义用户需求、业务约束和系统能力边界',
  },
  {
    value: 'brd',
    badge: 'BRD',
    label: '业务需求文档',
    description: '梳理业务目标、流程、角色和成功标准',
  },
  {
    value: 'prd',
    badge: 'PRD',
    label: '产品需求文档',
    description: '描述产品功能、交互逻辑和验收范围',
  },
  {
    value: 'user_story',
    badge: 'USER STORY',
    label: '用户故事',
    description: '按角色、目标和价值组织需求条目',
  },
  {
    value: 'detailed_design',
    badge: 'DESIGN',
    label: '详细设计说明',
    description: '沉淀技术设计、架构方案和接口约束',
  },
  {
    value: 'interface',
    badge: 'API',
    label: '接口说明',
    description: '定义接口契约、端点、请求响应、错误码和限流策略',
  },
  {
    value: 'test_case',
    badge: 'TEST',
    label: '测试用例',
    description: '生成测试场景、步骤、预期结果和验收条件',
  },
  {
    value: 'data_dictionary',
    badge: 'DATA',
    label: '数据字典',
    description: '整理数据结构、字段含义和校验规则',
  },
]

const INTERACTIVE_DOC_TYPES = new Set(DOCUMENT_TYPES.map((type) => type.value))

const STATUS_LABELS: Record<string, string> = {
  active: '进行中',
  finalized: '已完成',
  cancelled: '已取消',
}

const SECTION_STATUS_LABELS: Record<string, string> = {
  pending: '待处理',
  drafted: '草稿',
  confirmed: '已确认',
  skipped: '已跳过',
}

const UPSTREAM_DEPENDENCIES: Record<string, string[]> = {
  urs: [],
  brd: ['urs'],
  prd: ['urs', 'brd'],
  user_story: ['prd'],
  detailed_design: ['prd', 'user_story'],
  interface: ['prd', 'detailed_design'],
  data_dictionary: ['detailed_design', 'interface'],
  test_case: ['prd', 'detailed_design', 'interface'],
}

function getDocumentTypeLabel(docType: string) {
  return DOCUMENT_TYPES.find((type) => type.value === docType)?.label || docType.toUpperCase()
}

function getStatusLabel(status: string) {
  return STATUS_LABELS[status] || status
}

function getSectionStatusLabel(status: string) {
  return SECTION_STATUS_LABELS[status] || status
}

function getCurrentSection(session: DocumentGenerationSession | null): DocumentGenerationSection | undefined {
  if (!session) return undefined
  return session.sections.find((section) => section.section_key === session.current_section_key) || session.sections[0]
}

function getSessionProgress(session: DocumentGenerationSession) {
  const total = session.sections.length
  const completed = session.sections.filter((section) => ['confirmed', 'skipped'].includes(section.status)).length
  return {
    completed,
    total,
    percent: total > 0 ? Math.round((completed / total) * 100) : 0,
  }
}

function getSessionEntityState(session: DocumentGenerationSession | null) {
  return (session?.context_json?.entity_state || {}) as Record<string, any>
}

function getSessionWriteLog(session: DocumentGenerationSession | null, lastTurn: DocumentGenerationTurnResult | null) {
  const turnLog = lastTurn?.write_log || []
  if (turnLog.length > 0) return turnLog
  return ((session?.stash_json || {}).write_log || []) as Record<string, any>[]
}

function getSessionQualityGate(session: DocumentGenerationSession | null, lastTurn: DocumentGenerationTurnResult | null) {
  return lastTurn?.quality_gate || session?.quality_summary_json?.delivery_readiness || {}
}

function getPendingConfirmations(session: DocumentGenerationSession | null, lastTurn: DocumentGenerationTurnResult | null) {
  if (lastTurn?.pending_confirmations) return lastTurn.pending_confirmations
  return (getSessionEntityState(session).pending_confirmations || []) as Record<string, any>[]
}

function getPendingConfirmationText(item: Record<string, any>) {
  return item.question || item.message || '请先人工确认该事项，再进入正式交付。'
}

function getSectionPrimaryQuestion(section: DocumentGenerationSection | undefined) {
  if (!section) return ''
  return section.pending_questions_json[0] || section.content_requirement || ''
}

function getSectionQualityRule(section: DocumentGenerationSection | undefined) {
  if (!section) return ''
  return section.quality_rules[0]?.rule || section.content_requirement || '内容完整且可追溯'
}

function getSectionDraftLength(section: DocumentGenerationSection | undefined) {
  return (section?.content || '').trim().length
}

function getSessionSkillTrace(session: DocumentGenerationSession | null, lastTurn: DocumentGenerationTurnResult | null) {
  const stashTrace = ((session?.stash_json || {}).skill_trace || []) as Record<string, any>[]
  const turnTrace = lastTurn?.skill_trace || []
  const seen = new Set<string>()
  return [...stashTrace, ...turnTrace].filter((item, index) => {
    const key = [
      item.label || item.skill_label || item.name || item.skill_name || `skill-${index}`,
      item.section_key || item.sectionKey || 'global',
      item.action || item.status || 'trace',
    ].join(':')
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function getSkillTraceLabel(item: Record<string, any>) {
  return String(item.label || item.skill_label || item.name || item.skill_name || item.skill_id || 'Skill')
}

function getSkillTypeLabel(skill: SkillCatalogEntry) {
  const marker = `${skill.skill_type || ''} ${skill.category || ''}`.toLowerCase()
  if (marker.includes('clar') || marker.includes('requirement')) return '需求澄清'
  if (marker.includes('quality') || marker.includes('review')) return '质量评审'
  if (marker.includes('trace') || marker.includes('audit')) return '证据追溯'
  if (marker.includes('write') || marker.includes('generation')) return '结构化写入'
  return '专项能力'
}

function traceMatchesSkill(skill: SkillCatalogEntry, trace: Record<string, any>) {
  const label = getSkillTraceLabel(trace)
  const displayName = getSkillDisplayName(skill)
  const typeLabel = getSkillTypeLabel(skill)
  return label.includes(displayName) ||
    displayName.includes(label) ||
    label.includes(typeLabel.replace('需求', '').replace('结构化', '')) ||
    (skill.skill_type === 'clarification' && label.includes('澄清')) ||
    (skill.skill_type === 'quality' && (label.includes('质量') || label.includes('评审')))
}

function getSkillSectionReason(skill: SkillCatalogEntry, section: DocumentGenerationSection) {
  const typeLabel = getSkillTypeLabel(skill)
  if (typeLabel === '需求澄清') {
    return section.confirmed_facts_json.length > 0 ? '用于核对已确认事实边界' : '用于补齐本节关键事实'
  }
  if (typeLabel === '质量评审') {
    return getSectionDraftLength(section) > 0 ? '用于复核草稿质量门禁' : '用于预置本节验收标准'
  }
  if (typeLabel === '证据追溯') return '用于串联写入记录、事实和质量证据'
  if (typeLabel === '结构化写入') return '用于将回答整理为章节草稿'
  return '用于本节专项处理'
}

function buildSkillPrompt(skill: SkillCatalogEntry, section: DocumentGenerationSection, templateName?: string) {
  const skillName = getSkillDisplayName(skill)
  const qualityRule = getSectionQualityRule(section)
  return [
    `【仅准备提示，不触发后台 Skill 执行】请围绕「${section.title}」应用 Skill「${skillName}」。`,
    `目标：${getSkillSectionReason(skill, section)}。`,
    `推荐模板：${templateName || '当前文档标准模板'}。`,
    `质量门禁：${qualityRule}。`,
    '请补充可写入本节的事实、边界、验收口径或待确认问题，并保留证据来源。',
  ].join('\n')
}

function buildSkillExecutionInput(skill: SkillCatalogEntry, section: DocumentGenerationSection, session: DocumentGenerationSession) {
  return {
    doc_type: session.doc_type,
    session_id: session.id,
    section_key: section.section_key,
    section_title: section.title,
    section_status: section.status,
    content_requirement: section.content_requirement,
    current_draft: section.content,
    pending_questions: section.pending_questions_json,
    confirmed_facts: section.confirmed_facts_json,
    quality_rules: section.quality_rules,
    skill_name: skill.name,
    skill_display_name: getSkillDisplayName(skill),
  }
}

function buildSkillExecutionContext(section: DocumentGenerationSection, session: DocumentGenerationSession, templateName?: string) {
  return {
    project_id: session.project_id,
    document_id: session.document_id,
    session_title: session.title,
    template_name: templateName || null,
    language: session.context_json?.language || 'zh-CN',
    requirements: session.context_json?.requirements || '',
    entity_state: session.context_json?.entity_state || {},
    section_position: section.position,
  }
}

function formatSkillExecutionResult(result: SkillCatalogTestResult, section: DocumentGenerationSection) {
  const output = result.output_data || {}
  const summary = String(output.summary || output.recommendation || output.message || '')
  const nextActions = Array.isArray(output.next_actions) ? output.next_actions : []
  const evidence = Array.isArray(output.evidence) ? output.evidence : []
  const lines = [
    `【Skill 执行结果】${result.skill_name}`,
    `适用章节：${section.title}`,
    summary ? `摘要：${summary}` : '',
    result.execution_time_ms !== null && result.execution_time_ms !== undefined ? `耗时：${result.execution_time_ms}ms` : '',
    nextActions.length ? `下一步：${nextActions.join('；')}` : '',
    evidence.length ? `证据：${evidence.join('；')}` : '',
    !summary && !nextActions.length && !evidence.length ? `输出：${JSON.stringify(output)}` : '',
  ].filter(Boolean)
  return lines.join('\n')
}

function getAgentDisplayName(agent: AgentProfile) {
  return agent.name || '未命名 Agent'
}

function getSectionParagraphs(section: DocumentGenerationSection) {
  const content = section.content.trim()
  if (!content) return []
  const blocks = content.split(/\n{2,}/).map((block) => block.trim()).filter(Boolean)
  return (blocks.length > 1 ? blocks : content.split('\n').map((line) => line.trim()).filter(Boolean)).slice(0, 8)
}

function getSectionEvidence(section: DocumentGenerationSection, writeLog: Record<string, any>[], skillTrace: Record<string, any>[]) {
  const sectionWriteLog = writeLog.filter((entry) => entry.section_key === section.section_key || entry.sectionKey === section.section_key)
  const sectionSkillTrace = skillTrace.filter((item) => item.section_key === section.section_key || item.sectionKey === section.section_key)
  const skillLabels = Array.from(new Set([
    ...sectionSkillTrace.map(getSkillTraceLabel),
    ...sectionWriteLog.flatMap((entry) => (entry.skill_labels || entry.skillLabels || []) as string[]),
  ].filter(Boolean)))
  const qualityScore = section.quality_json?.score
  const sufficiencyLevel = section.quality_json?.sufficiency_level || section.quality_json?.level
  const paragraphs = getSectionParagraphs(section)

  return {
    summary: [
      {
        label: '已确认事实',
        value: `${section.confirmed_facts_json.length} 条`,
        detail: section.confirmed_facts_json[0] || '本节尚未沉淀已确认事实',
      },
      {
        label: '写入记录',
        value: `${sectionWriteLog.length} 条`,
        detail: sectionWriteLog.length ? `最近写入：${sectionWriteLog[sectionWriteLog.length - 1].patch_type || 'patch'}` : '暂无写入记录',
      },
      {
        label: '活跃 Skill',
        value: `${skillLabels.length} 个`,
        detail: skillLabels.length ? skillLabels.slice(0, 3).join('、') : '暂无本节调用轨迹',
      },
      {
        label: '质量评分',
        value: qualityScore === undefined ? '未评分' : `${qualityScore}`,
        detail: sufficiencyLevel ? `充分性：${sufficiencyLevel}` : getSectionQualityRule(section),
      },
    ],
    paragraphs: paragraphs.map((paragraph, index) => {
      const heading = paragraph.replace(/^#+\s*/, '').slice(0, 36)
      const writeEntry = sectionWriteLog.slice().reverse().find((entry) => String(entry.new_text || '').includes(paragraph)) || sectionWriteLog[sectionWriteLog.length - 1]
      const fact = section.confirmed_facts_json[index] || section.confirmed_facts_json[0]
      const evidenceParts = [
        fact ? `已确认事实：${fact}` : '',
        writeEntry ? `写入记录 #${writeEntry.index || sectionWriteLog.length}（${writeEntry.verified ? '已验证' : '待核对'}）` : '',
        skillLabels.length ? `Skill：${skillLabels.slice(0, 2).join('、')}` : '',
        qualityScore !== undefined ? `质量评分：${qualityScore}` : '',
      ].filter(Boolean)
      return {
        id: `${section.section_key}-${index}`,
        title: heading || `段落 ${index + 1}`,
        detail: paragraph,
        evidence: evidenceParts,
        status: evidenceParts.length >= 2 ? '证据较完整' : '待补证据',
      }
    }),
  }
}

function sectionStatusTone(status: string) {
  if (status === 'confirmed') return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100'
  if (status === 'drafted') return 'bg-sky-100 text-sky-800 dark:bg-sky-900 dark:text-sky-100'
  if (status === 'skipped') return 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-100'
  return ''
}

const SECTION_BLUEPRINTS: Record<string, Array<{ title: string; gate: string }>> = {
  urs: [
    { title: '业务愿景', gate: '目标、范围和成功口径明确' },
    { title: '用户需求', gate: '每项需求可追溯到角色或场景' },
    { title: '验收标准', gate: '验收条件可测试、可审计' },
  ],
  brd: [
    { title: '背景与目标', gate: '业务痛点、目标和指标明确' },
    { title: '干系人与业务角色', gate: '角色、职责和确认人明确' },
    { title: '现状与目标业务流程', gate: '流程节点、异常和审批明确' },
    { title: '核心需求模块', gate: '需求边界和优先级明确' },
    { title: '非功能需求', gate: '安全、审计、性能和可用性明确' },
  ],
  prd: [
    { title: '产品目标与范围', gate: '承接 BRD 目标且范围清晰' },
    { title: '功能清单与规则', gate: '功能、状态和异常规则完整' },
    { title: '交互与数据', gate: '输入输出、字段和权限明确' },
    { title: '验收标准', gate: '每项功能有可验证标准' },
  ],
  user_story: [
    { title: '角色与目标', gate: '角色、目标和价值完整' },
    { title: '故事列表', gate: '每条故事可拆分和估算' },
    { title: '验收条件', gate: 'Given/When/Then 可执行' },
  ],
  detailed_design: [
    { title: '方案概览', gate: '架构边界和依赖明确' },
    { title: '接口与数据', gate: '接口、字段和状态流转明确' },
    { title: '风险与回滚', gate: '风险、监控和回滚路径明确' },
  ],
  test_case: [
    { title: '测试范围', gate: '覆盖范围和排除范围明确' },
    { title: '测试场景', gate: '正常、异常和权限路径完整' },
    { title: '验收口径', gate: '预期结果可执行' },
  ],
}

function getSectionBlueprint(docType: string) {
  return SECTION_BLUEPRINTS[docType] || [
    { title: '背景与范围', gate: '目标、范围和上下文明确' },
    { title: '主体内容', gate: '内容结构完整' },
    { title: '验收与待确认', gate: '验收标准和待确认问题明确' },
  ]
}

function hasAny(text: string, keywords: string[]) {
  return keywords.some((keyword) => text.includes(keyword))
}

function getContextReadiness(context: string) {
  const normalized = context.trim()
  return [
    {
      key: 'requirements',
      title: '需求背景',
      description: '说明业务目标、问题和约束',
      covered: normalized.length >= 30,
      evidence: normalized.length >= 30 ? '已提供足够背景' : '至少补充 30 字以上业务背景',
    },
    {
      key: 'stakeholders',
      title: '干系人',
      description: '明确角色、职责和评审人',
      covered: hasAny(normalized, ['角色', '干系人', '用户', '客户', '主管', '顾问', '评审人', '业务方']),
      evidence: '建议包含角色、职责和确认人',
    },
    {
      key: 'process',
      title: '业务流程',
      description: '描述流程节点、状态和异常',
      covered: hasAny(normalized, ['流程', '步骤', '节点', '审批', '状态', '异常', '收货', '上架', '拣货', '复核', '发运']),
      evidence: '建议包含端到端流程和异常路径',
    },
    {
      key: 'acceptance',
      title: '验收标准',
      description: '给出指标、质量门禁或验收条件',
      covered: hasAny(normalized, ['验收', '标准', '指标', 'KPI', '质量', '下降', '提升', '可追溯']),
      evidence: '建议包含可验证指标或验收条件',
    },
  ]
}

function buildSourceKnowledgeContext(entries: Array<{ content?: string; metadata?: Record<string, any> | null }>) {
  const usableEntries = entries
    .map((entry, index) => {
      const title = entry.metadata?.title || entry.metadata?.heading || `资料知识 ${index + 1}`
      const source = entry.metadata?.filename || entry.metadata?.source_file_name || entry.metadata?.source || '项目资料'
      const content = (entry.content || '').trim()
      if (!content) return ''
      return `【${title}｜来源：${source}】\n${content}`
    })
    .filter(Boolean)

  if (usableEntries.length === 0) return ''

  return [
    '以下内容来自已摄取的项目资料，可作为本文档的需求与背景：',
    '',
    ...usableEntries.slice(0, 8),
  ].join('\n\n')
}

function getSkillDisplayName(skill: SkillCatalogEntry) {
  return skill.effective_display_name || skill.display_name || skill.name
}

function getTemplatesArray(response: { items: Template[]; total: number } | Template[] | undefined) {
  if (!response) return []
  return Array.isArray(response) ? response : response.items || []
}

function isTemplatePublished(template: Template) {
  const status = String((template as any).lifecycle_status || (template as any).status || template.is_active || '').toLowerCase()
  return ['published', 'active', 'true', '1', 'yes'].includes(status)
}

function formatUpdatedAt(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

async function withTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T> {
  return Promise.race([
    promise,
    new Promise<T>((_, reject) => {
      window.setTimeout(() => reject(new Error('生成服务响应超时')), timeoutMs)
    }),
  ])
}

export default function GenerateDocumentPage({ params }: GenerateDocumentPageProps) {
  const { projectId } = params
  const router = useRouter()
  const searchParams = useSearchParams()
  const sourceFileId = searchParams.get('sourceFileId')
  const queryClient = useQueryClient()
  const { addToast } = useToast()
  const [selectedType, setSelectedType] = useState('urs')
  const [context, setContext] = useState('')
  const [generatedDocumentId, setGeneratedDocumentId] = useState<string | null>(null)
  const [generationSession, setGenerationSession] = useState<DocumentGenerationSession | null>(null)
  const [sessionInput, setSessionInput] = useState('')
  const [selectedSectionKey, setSelectedSectionKey] = useState<string | null>(null)
  const [restoredSessionId, setRestoredSessionId] = useState<string | null>(null)
  const [lastTurn, setLastTurn] = useState<DocumentGenerationTurnResult | null>(null)
  const [lastSkillExecution, setLastSkillExecution] = useState<{
    skill: SkillCatalogEntry
    section: DocumentGenerationSection
    result: SkillCatalogTestResult
  } | null>(null)

  const selectedDocType = useMemo(
    () => DOCUMENT_TYPES.find((type) => type.value === selectedType),
    [selectedType],
  )
  const supportsInteractiveGeneration = INTERACTIVE_DOC_TYPES.has(selectedType)
  const currentSection = useMemo(() => getCurrentSection(generationSession), [generationSession])
  const sourceKnowledgeQuery = useQuery({
    queryKey: ['source-knowledge-context', projectId, sourceFileId],
    queryFn: () => knowledgeApi.getEntries({ projectId, sourceFileId: sourceFileId || undefined, pageSize: 20 }),
    enabled: Boolean(sourceFileId),
  })
  useEffect(() => {
    if (!sourceFileId || context.trim() || !sourceKnowledgeQuery.data?.items?.length) return
    const sourceContext = buildSourceKnowledgeContext(sourceKnowledgeQuery.data.items)
    if (sourceContext) setContext(sourceContext)
  }, [context, sourceFileId, sourceKnowledgeQuery.data?.items])
  const focusedSection = useMemo(() => {
    if (!generationSession) return undefined
    return generationSession.sections.find((section) => section.section_key === selectedSectionKey) || currentSection
  }, [currentSection, generationSession, selectedSectionKey])
  const contextReadiness = useMemo(() => getContextReadiness(context), [context])
  const readinessScore = Math.round((contextReadiness.filter((item) => item.covered).length / contextReadiness.length) * 100)
  const sectionBlueprint = useMemo(
    () => generationSession
      ? generationSession.sections.map((section) => ({
        title: section.title,
        gate: section.quality_rules[0]?.rule || section.content_requirement || '质量门禁：内容完整且可追溯',
      }))
      : getSectionBlueprint(selectedType),
    [generationSession, selectedType],
  )
  const sessionProgress = useMemo(
    () => generationSession ? getSessionProgress(generationSession) : null,
    [generationSession],
  )
  const sessionEntityState = useMemo(
    () => getSessionEntityState(generationSession),
    [generationSession],
  )
  const sessionWriteLog = useMemo(
    () => getSessionWriteLog(generationSession, lastTurn),
    [generationSession, lastTurn],
  )
  const sessionQualityGate = useMemo(
    () => getSessionQualityGate(generationSession, lastTurn),
    [generationSession, lastTurn],
  )
  const sessionQualityBlockers = useMemo(
    () => ((sessionQualityGate.blockers || []) as string[]).filter(Boolean),
    [sessionQualityGate],
  )
  const sessionPendingConfirmations = useMemo(
    () => getPendingConfirmations(generationSession, lastTurn),
    [generationSession, lastTurn],
  )
  const upstreamDependencies = useMemo(
    () => {
      const docType = generationSession?.doc_type || selectedType
      const sessionDependencies = (sessionEntityState.upstream_dependencies || []) as string[]
      return sessionDependencies.length ? sessionDependencies : (UPSTREAM_DEPENDENCIES[docType] || [])
    },
    [generationSession?.doc_type, selectedType, sessionEntityState],
  )
  const canFinalizeSession = Boolean(
    generationSession &&
    (sessionProgress?.completed || 0) > 0 &&
    sessionPendingConfirmations.length === 0 &&
    sessionQualityBlockers.length === 0,
  )
  const focusedSectionIndex = useMemo(
    () => generationSession?.sections.findIndex((section) => section.section_key === focusedSection?.section_key) ?? -1,
    [focusedSection?.section_key, generationSession],
  )
  const sessionShareUrl = useMemo(() => {
    if (!generationSession || typeof window === 'undefined') return ''
    return `${window.location.origin}/projects/${projectId}/documents/generate?sessionId=${generationSession.id}`
  }, [generationSession, projectId])
  const sessionOperationItems = useMemo(() => {
    if (!generationSession) return []
    const sectionQuestions = generationSession.sections
      .filter((section) => !['confirmed', 'skipped'].includes(section.status))
      .flatMap((section) =>
        (section.pending_questions_json || []).slice(0, 1).map((question) => ({
          id: `question-${section.section_key}`,
          type: '待补问题',
          title: section.title,
          sectionKey: section.section_key,
          message: question || section.content_requirement,
        })),
      )
    const confirmations = sessionPendingConfirmations.map((item, index) => ({
      id: `confirmation-${item.section_key || index}`,
      type: '待确认',
      title: item.section_title || item.section_key || '待确认项',
      sectionKey: item.section_key,
      message: getPendingConfirmationText(item),
    }))
    const blockers = sessionQualityBlockers.map((blocker, index) => ({
      id: `blocker-${index}`,
      type: '门禁阻塞',
      title: '交付门禁',
      sectionKey: generationSession.current_section_key,
      message: blocker,
    }))
    return [...confirmations, ...blockers, ...sectionQuestions].slice(0, 8)
  }, [generationSession, sessionPendingConfirmations, sessionQualityBlockers])
  const finalizationChecks = useMemo(() => {
    if (!generationSession) return []
    return [
      {
        label: '至少一个章节已确认或跳过',
        passed: (sessionProgress?.completed || 0) > 0,
        detail: `${sessionProgress?.completed || 0}/${sessionProgress?.total || 0}`,
      },
      {
        label: '没有待确认项',
        passed: sessionPendingConfirmations.length === 0,
        detail: `${sessionPendingConfirmations.length} 项`,
      },
      {
        label: '质量门禁无阻塞',
        passed: sessionQualityBlockers.length === 0,
        detail: sessionQualityBlockers.length ? `${sessionQualityBlockers.length} 个阻塞` : '通过',
      },
      {
        label: '当前章节已有草稿或已处理',
        passed: Boolean(currentSection && (getSectionDraftLength(currentSection) > 0 || ['confirmed', 'skipped'].includes(currentSection.status))),
        detail: currentSection ? getSectionStatusLabel(currentSection.status) : '无章节',
      },
    ]
  }, [currentSection, generationSession, sessionPendingConfirmations.length, sessionProgress, sessionQualityBlockers.length])

  const sessionsQuery = useQuery({
    queryKey: ['document-generation-sessions', projectId],
    queryFn: () => documentsApi.listGenerationSessions({ projectId }),
  })

  const templatesQuery = useQuery({
    queryKey: ['generation-template-plan', selectedType],
    queryFn: () => templatesApi.list({ docType: selectedType, limit: 20 }),
  })

  const skillsQuery = useQuery({
    queryKey: ['generation-skill-plan', selectedType],
    queryFn: () => agentApi.listSkillCatalog({ status: 'published', pageSize: 100 }),
  })

  const agentProfilesQuery = useQuery({
    queryKey: ['generation-agent-plan', selectedType],
    queryFn: () => agentApi.listAgentProfiles({ status: 'active', docType: selectedType, pageSize: 100 }),
  })

  const agentRunsQuery = useQuery({
    queryKey: ['generation-agent-runs', projectId],
    queryFn: () => agentApi.listRuns({ projectId, pageSize: 5 }),
  })

  const recommendedTemplate = useMemo(() => {
    const templates = getTemplatesArray(templatesQuery.data)
    return templates.find((template) => template.doc_type === selectedType && isTemplatePublished(template)) ||
      templates.find((template) => template.doc_type === selectedType) ||
      templates[0]
  }, [selectedType, templatesQuery.data])

  const recommendedSkills = useMemo(() => {
    const skills = skillsQuery.data?.items || []
    const clarificationSkills = skills.filter((skill) =>
      skill.status === 'published' &&
      (skill.skill_type === 'clarification' || skill.category === 'requirements')
    )
    const docTypeSkills = skills
      .filter((skill) => skill.status === 'published')
      .filter((skill) => skill.supported_doc_types.length === 0 || skill.supported_doc_types.includes(selectedType))
    return Array.from(new Map([...clarificationSkills, ...docTypeSkills].map((skill) => [skill.id, skill])).values()).slice(0, 4)
  }, [selectedType, skillsQuery.data])
  const recommendedAgents = useMemo(() => {
    const agents = agentProfilesQuery.data?.items || []
    return agents
      .filter((agent) => agent.status === 'active')
      .filter((agent) => agent.applicable_doc_types.length === 0 || agent.applicable_doc_types.includes(selectedType))
      .slice(0, 3)
  }, [agentProfilesQuery.data, selectedType])
  const recentAgentRuns = useMemo(
    () => (agentRunsQuery.data?.items || []).slice(0, 3),
    [agentRunsQuery.data],
  )
  const sessionSkillTrace = useMemo(
    () => getSessionSkillTrace(generationSession, lastTurn),
    [generationSession, lastTurn],
  )
  const focusedSectionEvidence = useMemo(
    () => focusedSection ? getSectionEvidence(focusedSection, sessionWriteLog, sessionSkillTrace) : null,
    [focusedSection, sessionSkillTrace, sessionWriteLog],
  )
  const skillSectionPlan = useMemo(() => {
    if (!generationSession) return []
    return generationSession.sections.flatMap((section) =>
      recommendedSkills.slice(0, 3).map((skill) => {
        const trace = sessionSkillTrace.find((item) =>
          (item.section_key === section.section_key || item.sectionKey === section.section_key) &&
          traceMatchesSkill(skill, item)
        )
        return {
          id: `${section.section_key}-${skill.id}`,
          section,
          skill,
          activeTrace: trace,
          reason: getSkillSectionReason(skill, section),
          prompt: buildSkillPrompt(skill, section, recommendedTemplate?.name),
        }
      }),
    )
  }, [generationSession, recommendedSkills, recommendedTemplate?.name, sessionSkillTrace])

  const recentSessions = useMemo(
    () => (sessionsQuery.data || []).slice(0, 5),
    [sessionsQuery.data],
  )

  const replaceGenerateUrl = (next: { sessionId?: string | null; docType?: string }) => {
    const params = new URLSearchParams()
    if (next.sessionId) {
      params.set('sessionId', next.sessionId)
    } else if (next.docType) {
      params.set('docType', next.docType)
    }
    const query = params.toString()
    router.replace(`/projects/${projectId}/documents/generate${query ? `?${query}` : ''}`)
  }

  const restoreSessionMutation = useMutation({
    mutationFn: async (sessionId: string) => {
      const session = await documentsApi.getGenerationSession(sessionId)
      if (session.project_id !== projectId) {
        throw new Error('会话不属于当前项目')
      }
      return session
    },
    onSuccess: (session) => {
      if (session.status !== 'active') {
        addToast({
          title: '恢复生成会话失败',
          description: `该会话当前状态为${getStatusLabel(session.status)}，不能继续编辑。`,
          variant: 'destructive',
        })
        return
      }

      setSelectedType(session.doc_type)
      setGenerationSession(session)
      setSelectedSectionKey(session.current_section_key)
      setSessionInput('')
      setLastTurn(null)
      setRestoredSessionId(session.id)
      replaceGenerateUrl({ sessionId: session.id })
      const requirements = typeof session.context_json?.requirements === 'string' ? session.context_json.requirements : ''
      if (requirements) {
        setContext(requirements)
      }
      addToast({ title: '已恢复生成会话', description: session.title })
    },
    onError: (error: Error) => {
      addToast({ title: '恢复生成会话失败', description: error.message, variant: 'destructive' })
    },
  })

  useEffect(() => {
    const docType = searchParams.get('docType')
    if (docType && INTERACTIVE_DOC_TYPES.has(docType) && !generationSession) {
      setSelectedType(docType)
    }
  }, [generationSession, searchParams])

  useEffect(() => {
    const sessionId = searchParams.get('sessionId')
    if (!sessionId || sessionId === restoredSessionId) return
    setRestoredSessionId(sessionId)
    restoreSessionMutation.mutate(sessionId)
  }, [restoreSessionMutation, restoredSessionId, searchParams])

  useEffect(() => {
    if (!generationSession) {
      setSelectedSectionKey(null)
      return
    }
    const hasSelectedSection = generationSession.sections.some((section) => section.section_key === selectedSectionKey)
    if (!selectedSectionKey || !hasSelectedSection) {
      setSelectedSectionKey(generationSession.current_section_key)
    }
  }, [generationSession, selectedSectionKey])

  const generateMutation = useMutation({
    mutationFn: async () => {
      const requirements = context.trim()
      const title = `${selectedDocType?.label || '项目文档'} - ${new Date().toLocaleDateString('zh-CN')}`
      const payload = {
        project_id: projectId,
        doc_type: selectedType,
        title,
        context: {
          requirements,
          language: 'zh-CN',
        },
      }

      return await withTimeout(documentsApi.generate(payload), 20000)
    },
    onSuccess: (result) => {
      setGeneratedDocumentId(result.document_id)
      queryClient.invalidateQueries({ queryKey: ['project-documents', projectId] })
      addToast({ title: '文档已生成', description: '已创建文档，可进入详情页查看内容。' })
    },
    onError: (error: Error) => {
      addToast({ title: '生成文档失败', description: error.message, variant: 'destructive' })
    },
  })

  const startSessionMutation = useMutation({
    mutationFn: async () => {
      const requirements = context.trim()
      const title = `${selectedDocType?.label || '项目文档'} - ${new Date().toLocaleDateString('zh-CN')}`
      return documentsApi.startGenerationSession({
        project_id: projectId,
        doc_type: selectedType,
        title,
        context: {
          requirements,
          language: 'zh-CN',
        },
      })
    },
    onSuccess: (session) => {
      setGenerationSession(session)
      setSelectedSectionKey(session.current_section_key)
      setSessionInput('')
      setLastTurn(null)
      setRestoredSessionId(session.id)
      replaceGenerateUrl({ sessionId: session.id })
      queryClient.invalidateQueries({ queryKey: ['document-generation-sessions', projectId] })
      addToast({ title: '交互式生成已开始', description: '系统已创建章节化生成会话。' })
    },
    onError: (error: Error) => {
      addToast({ title: '启动交互式生成失败', description: error.message, variant: 'destructive' })
    },
  })

  const cancelSessionMutation = useMutation({
    mutationFn: (sessionId: string) => documentsApi.cancelGenerationSession(sessionId),
    onSuccess: (session) => {
      if (generationSession?.id === session.id) {
        setGenerationSession(null)
        setSelectedSectionKey(null)
        setSessionInput('')
        setLastTurn(null)
        setRestoredSessionId(null)
        replaceGenerateUrl({ docType: session.doc_type || selectedType })
      }
      queryClient.invalidateQueries({ queryKey: ['document-generation-sessions', projectId] })
      addToast({ title: '生成会话已取消', description: session.title })
    },
    onError: (error: Error) => {
      addToast({ title: '取消生成会话失败', description: error.message, variant: 'destructive' })
    },
  })

  const sessionMessageMutation = useMutation({
    mutationFn: async ({ action, message }: { action: string; message: string }) => {
      if (!generationSession) throw new Error('请先启动交互式生成会话')
      return documentsApi.continueGenerationSession(generationSession.id, { action, message })
    },
    onSuccess: (result) => {
      setGenerationSession(result.session)
      setSelectedSectionKey(result.session.current_section_key)
      setSessionInput('')
      setLastTurn(result)
      queryClient.invalidateQueries({ queryKey: ['document-generation-sessions', projectId] })
      addToast({ title: '章节已更新', description: result.assistant_message })
    },
    onError: (error: Error) => {
      addToast({ title: '更新生成会话失败', description: error.message, variant: 'destructive' })
    },
  })

  const skillExecutionMutation = useMutation({
    mutationFn: async ({ skill, section }: { skill: SkillCatalogEntry; section: DocumentGenerationSection }) => {
      if (!generationSession) throw new Error('请先启动交互式生成会话')
      return agentApi.testSkillCatalogEntry(skill.id, {
        input_data: buildSkillExecutionInput(skill, section, generationSession),
        context: buildSkillExecutionContext(section, generationSession, recommendedTemplate?.name),
      })
    },
    onSuccess: (result, variables) => {
      setLastSkillExecution({
        skill: variables.skill,
        section: variables.section,
        result,
      })
      setSelectedSectionKey(variables.section.section_key)
      setSessionInput(formatSkillExecutionResult(result, variables.section))
      queryClient.invalidateQueries({ queryKey: ['generation-agent-runs', projectId] })
      addToast({
        title: result.success ? 'Skill 已执行' : 'Skill 执行失败',
        description: result.success ? `${getSkillDisplayName(variables.skill)} 的结果已回填到当前输入框。` : result.error_message || '请检查 Skill 配置。',
        variant: result.success ? 'default' : 'destructive',
      })
    },
    onError: (error: Error) => {
      addToast({ title: 'Skill 执行失败', description: error.message, variant: 'destructive' })
    },
  })

  const finalizeSessionMutation = useMutation({
    mutationFn: async () => {
      if (!generationSession) throw new Error('请先启动交互式生成会话')
      return documentsApi.finalizeGenerationSession(generationSession.id)
    },
    onSuccess: (result) => {
      setGeneratedDocumentId(result.document_id)
      setGenerationSession(null)
      setSelectedSectionKey(null)
      setLastTurn(null)
      setRestoredSessionId(null)
      replaceGenerateUrl({ docType: selectedType })
      queryClient.invalidateQueries({ queryKey: ['project-documents', projectId] })
      queryClient.invalidateQueries({ queryKey: ['document-generation-sessions', projectId] })
      addToast({ title: '交互式文档已生成', description: '章节草稿和待确认项已写入文档。' })
    },
    onError: (error: Error) => {
      addToast({ title: '生成文档失败', description: error.message, variant: 'destructive' })
    },
  })

  const submitSessionMessage = (action: 'answer' | 'confirm' | 'skip' | 'revise') => {
    const message = action === 'answer' || action === 'revise'
      ? sessionInput.trim()
      : action === 'confirm'
        ? '确认'
        : '跳过'
    if ((action === 'answer' || action === 'revise') && !message) return
    sessionMessageMutation.mutate({ action, message })
  }

  const copySessionLink = async () => {
    if (!sessionShareUrl) return
    try {
      await navigator.clipboard.writeText(sessionShareUrl)
      addToast({ title: '会话链接已复制', description: '可用该链接恢复当前编写驾驶舱。' })
    } catch {
      addToast({ title: '复制失败', description: '浏览器未允许访问剪贴板。', variant: 'destructive' })
    }
  }

  if (generatedDocumentId) {
    return (
      <div className="space-y-6">
        <Card className="max-w-2xl mx-auto">
          <CardContent className="py-12">
            <div className="flex flex-col items-center text-center">
              <div className="rounded-full bg-green-100 p-4 dark:bg-green-900">
                <CheckCircle className="h-12 w-12 text-green-600 dark:text-green-400" />
              </div>
              <h2 className="mt-6 text-2xl font-semibold text-slate-900 dark:text-white">文档生成成功</h2>
              <p className="mt-2 text-slate-500 dark:text-slate-400">
                {selectedDocType?.label || '文档'}已创建，可进入详情页查看和继续编辑。
              </p>
              <div className="flex gap-3 mt-6">
                <Button variant="outline" onClick={() => setGeneratedDocumentId(null)}>
                  继续生成
                </Button>
                <Button
                  variant="outline"
                  data-testid="back-to-document-workbench"
                  onClick={() => router.push(`/projects/${projectId}/documents`)}
                >
                  返回项目文档
                </Button>
                <Button onClick={() => router.push(`/projects/${projectId}/documents/${generatedDocumentId}`)}>
                  查看文档
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="sm" onClick={() => router.push(`/projects/${projectId}/documents`)}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">生成文档</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">根据项目背景和需求生成结构化文档</p>
        </div>
      </div>

      <Card data-testid="generation-session-center">
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Clock3 className="h-5 w-5 text-indigo-500" />
                生成会话
              </CardTitle>
              <CardDescription>恢复进行中的章节化生成，或打开已完成会话生成的文档</CardDescription>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => sessionsQuery.refetch()}
              disabled={sessionsQuery.isFetching}
            >
              {sessionsQuery.isFetching ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RotateCcw className="mr-2 h-4 w-4" />}
              刷新
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {sessionsQuery.isLoading ? (
            <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
              <Loader2 className="h-4 w-4 animate-spin" />
              正在加载生成会话...
            </div>
          ) : recentSessions.length === 0 ? (
            <p className="text-sm text-slate-500 dark:text-slate-400">暂无生成会话。启动 BRD/PRD 交互式生成后，会在这里保留恢复入口。</p>
          ) : (
            <div className="space-y-3">
              {recentSessions.map((session) => {
                const progress = getSessionProgress(session)
                const current = getCurrentSection(session)
                const isActive = session.status === 'active'
                const isFinalized = session.status === 'finalized'

                return (
                  <div
                    key={session.id}
                    data-testid={`generation-session-${session.id}`}
                    className="rounded-md border border-slate-200 p-4 dark:border-slate-700"
                  >
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant="secondary">{getDocumentTypeLabel(session.doc_type)}</Badge>
                          <Badge
                            variant={isActive ? 'default' : 'outline'}
                            className={session.status === 'cancelled' ? 'border-slate-300 text-slate-500 dark:border-slate-600' : ''}
                          >
                            {getStatusLabel(session.status)}
                          </Badge>
                          <span className="text-xs text-slate-500 dark:text-slate-400">更新于 {formatUpdatedAt(session.updated_at)}</span>
                        </div>
                        <h3 className="mt-2 truncate text-sm font-semibold text-slate-900 dark:text-white">{session.title}</h3>
                        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                          当前章节：{current?.title || '无'} · 进度 {progress.completed}/{progress.total}
                        </p>
                        <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                          <div className="h-full rounded-full bg-indigo-500" style={{ width: `${progress.percent}%` }} />
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2 lg:justify-end">
                        {isActive && (
                          <Button
                            size="sm"
                            onClick={() => restoreSessionMutation.mutate(session.id)}
                            disabled={restoreSessionMutation.isPending}
                            data-testid={`restore-generation-session-${session.id}`}
                          >
                            <RotateCcw className="mr-2 h-4 w-4" />
                            恢复
                          </Button>
                        )}
                        {isActive && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => cancelSessionMutation.mutate(session.id)}
                            disabled={cancelSessionMutation.isPending}
                            data-testid={`cancel-generation-session-${session.id}`}
                          >
                            <XCircle className="mr-2 h-4 w-4" />
                            取消
                          </Button>
                        )}
                        {isFinalized && session.document_id && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => router.push(`/projects/${projectId}/documents/${session.document_id}`)}
                            data-testid={`open-generation-session-document-${session.id}`}
                          >
                            查看文档
                            <ArrowRight className="ml-2 h-4 w-4" />
                          </Button>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <Card data-testid="generation-command-flow">
        <CardHeader>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Gauge className="h-5 w-5 text-indigo-500" />
                文档生成指挥流
              </CardTitle>
              <CardDescription>在启动生成前检查上下文、模板、Skill 和章节质量门禁。</CardDescription>
            </div>
            <Badge variant={readinessScore >= 75 ? 'default' : 'secondary'}>
              上下文准备度 {readinessScore}%
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-5">
          <section>
            <div className="mb-3 flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold text-slate-900 dark:text-white">上下文准备度</h2>
              <span className="text-xs text-slate-500 dark:text-slate-400">
                {readinessScore >= 75 ? '可启动生成' : '建议补充后生成'}
              </span>
            </div>
            <div className="grid gap-3 md:grid-cols-4">
              {contextReadiness.map((item) => (
                <div
                  key={item.key}
                  data-testid={`generation-readiness-${item.key}`}
                  className="rounded-md border border-slate-200 p-3 dark:border-slate-700"
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium text-slate-900 dark:text-white">{item.title}</p>
                    <Badge
                      variant={item.covered ? 'secondary' : 'outline'}
                      className={item.covered ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-100' : ''}
                    >
                      {item.covered ? '已覆盖' : '待补充'}
                    </Badge>
                  </div>
                  <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{item.description}</p>
                  <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{item.evidence}</p>
                </div>
              ))}
            </div>
          </section>

          <div className="grid gap-4 lg:grid-cols-[0.85fr_1.15fr]">
            <section
              data-testid="generation-template-plan"
              className="rounded-md border border-slate-200 p-4 dark:border-slate-700"
            >
              <div className="flex items-center gap-2">
                <FileCheck2 className="h-4 w-4 text-indigo-500" />
                <h2 className="text-sm font-semibold text-slate-900 dark:text-white">模板与交付配置</h2>
              </div>
              <div className="mt-3 space-y-3">
                <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
                  <p className="text-xs text-slate-500">推荐模板</p>
                  <p className="mt-1 text-sm font-medium text-slate-900 dark:text-white">
                    {templatesQuery.isLoading ? '正在匹配模板...' : recommendedTemplate?.name || `${selectedDocType?.label || '文档'}标准模板`}
                  </p>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    {recommendedTemplate?.description || '未匹配到已发布模板，将使用默认章节结构。'}
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
                    <p className="text-slate-500">生成模式</p>
                    <p className="mt-1 font-medium text-slate-900 dark:text-white">
                      {supportsInteractiveGeneration ? '章节化交互式' : '直接生成'}
                    </p>
                  </div>
                  <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
                    <p className="text-slate-500">输出状态</p>
                    <p className="mt-1 font-medium text-slate-900 dark:text-white">草稿，待人工确认</p>
                  </div>
                </div>
              </div>
            </section>

            <section
              data-testid="generation-agent-skill-plan"
              className="rounded-md border border-slate-200 p-4 dark:border-slate-700"
            >
              <div className="flex items-center gap-2">
                <ShieldCheck className="h-4 w-4 text-indigo-500" />
                <h2 className="text-sm font-semibold text-slate-900 dark:text-white">Agent 与 Skill 编排</h2>
              </div>
              <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                用 Skill 约束澄清、生成、评审和追溯，不让生成结果直接进入正式交付。
              </p>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {skillsQuery.isLoading ? (
                  <p className="text-sm text-slate-500">正在加载可用 Skill...</p>
                ) : recommendedSkills.length === 0 ? (
                  <p className="text-sm text-slate-500">暂无匹配 Skill，将使用通用生成流程。</p>
                ) : (
                  recommendedSkills.map((skill) => (
                    <div key={skill.id} className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
                      <p className="text-sm font-medium text-slate-900 dark:text-white">{getSkillDisplayName(skill)}</p>
                      <p className="mt-1 line-clamp-2 text-xs text-slate-500 dark:text-slate-400">
                        {skill.description || skill.category}
                      </p>
                    </div>
                  ))
                )}
              </div>
            </section>
          </div>

          <section
            data-testid="generation-section-roadmap"
            className="rounded-md border border-slate-200 p-4 dark:border-slate-700"
          >
            <div className="flex items-center gap-2">
              <ListChecks className="h-4 w-4 text-indigo-500" />
              <h2 className="text-sm font-semibold text-slate-900 dark:text-white">章节路线图与质量门禁</h2>
            </div>
            <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
              {sectionBlueprint.map((section, index) => (
                <div key={`${section.title}-${index}`} className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-xs">{index + 1}</Badge>
                    <p className="text-sm font-medium text-slate-900 dark:text-white">{section.title}</p>
                  </div>
                  <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">质量门禁：{section.gate}</p>
                </div>
              ))}
            </div>
          </section>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>选择文档类型</CardTitle>
            <CardDescription>选择本次需要生成的交付物类型</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {DOCUMENT_TYPES.map((type) => (
              <button
                key={type.value}
                type="button"
                className={`w-full text-left p-4 rounded-lg border-2 cursor-pointer transition-colors ${
                  selectedType === type.value
                    ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20'
                    : 'border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600'
                }`}
                onClick={() => {
                  setSelectedType(type.value)
                  setGenerationSession(null)
                  setSelectedSectionKey(null)
                  setSessionInput('')
                  setLastTurn(null)
                  setRestoredSessionId(null)
                  replaceGenerateUrl({ docType: type.value })
                }}
              >
                <div className="flex items-start gap-3">
                  <div className="rounded-lg bg-indigo-100 p-2 dark:bg-indigo-900">
                    <FileText className="h-5 w-5 text-indigo-600 dark:text-indigo-400" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-slate-900 dark:text-white">{type.label}</span>
                      <Badge variant="secondary" className="text-xs">{type.badge}</Badge>
                    </div>
                    <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">{type.description}</p>
                  </div>
                </div>
              </button>
            ))}
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>文档上下文</CardTitle>
              <CardDescription>输入需求、背景、干系人、约束和需要覆盖的重点</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {sourceFileId && (
                <div className="rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-sm text-indigo-900 dark:border-indigo-900/60 dark:bg-indigo-950/40 dark:text-indigo-100">
                  {sourceKnowledgeQuery.isLoading
                    ? '正在读取所选资料的知识条目...'
                    : sourceKnowledgeQuery.data?.items?.length
                      ? `已从所选资料载入 ${sourceKnowledgeQuery.data.items.length} 条知识，可继续编辑后生成文档。`
                      : '所选资料尚未产生知识条目，请先完成资料摄取或手动补充背景。'}
                </div>
              )}
              <div className="space-y-2">
                <Label htmlFor="context">需求与背景</Label>
                <textarea
                  id="context"
                  className="w-full min-h-[260px] p-3 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 placeholder:text-slate-400 dark:placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
                  placeholder="例如：项目目标、业务范围、关键角色、功能需求、非功能要求、边界条件、验收标准等..."
                  value={context}
                  onChange={(e) => setContext(e.target.value)}
                />
              </div>
            </CardContent>
          </Card>

          {generationSession ? (
            <>
              <Card data-testid="interactive-generation-session">
                <CardHeader>
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                      <CardTitle>交互式生成会话</CardTitle>
                      <CardDescription>{generationSession.title}</CardDescription>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        data-testid="copy-generation-session-link"
                        onClick={copySessionLink}
                        disabled={!sessionShareUrl}
                      >
                        <ClipboardCopy className="mr-2 h-4 w-4" />
                        复制会话链接
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => cancelSessionMutation.mutate(generationSession.id)}
                        disabled={cancelSessionMutation.isPending}
                      >
                        {cancelSessionMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <XCircle className="mr-2 h-4 w-4" />}
                        取消会话
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex flex-wrap gap-2">
                    {generationSession.sections.map((section) => (
                      <Badge
                        key={section.id}
                        variant="secondary"
                        className={section.section_key === generationSession.current_section_key ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-100' : ''}
                      >
                        {section.position + 1}. {section.title} · {getSectionStatusLabel(section.status)}
                      </Badge>
                    ))}
                  </div>
                  {currentSection && (
                    <div className="rounded-md border border-slate-200 p-4 dark:border-slate-700">
                      <div className="flex items-center gap-2">
                        <MessageSquare className="h-4 w-4 text-indigo-500" />
                        <h3 className="text-sm font-semibold text-slate-900 dark:text-white">{currentSection.title}</h3>
                      </div>
                      <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                        {currentSection.pending_questions_json[0] || currentSection.content_requirement}
                      </p>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          data-testid="use-current-section-question"
                          onClick={() => setSessionInput(getSectionPrimaryQuestion(currentSection))}
                          disabled={!getSectionPrimaryQuestion(currentSection)}
                        >
                          带入本节问题
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          data-testid="use-current-section-gate"
                          onClick={() => setSessionInput(`按质量门禁补充：${getSectionQualityRule(currentSection)}`)}
                        >
                          带入质量门禁
                        </Button>
                      </div>
                      <textarea
                        className="mt-3 w-full min-h-28 resize-none rounded-md border border-slate-200 bg-white p-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                        data-testid="authoring-message-input"
                        value={sessionInput}
                        onChange={(event) => setSessionInput(event.target.value)}
                        placeholder="补充本节业务事实、角色、流程、指标或例外条件..."
                      />
                      <div className="mt-3 flex flex-wrap gap-2">
                        <Button
                          data-testid="authoring-answer-action"
                          onClick={() => submitSessionMessage('answer')}
                          disabled={!sessionInput.trim() || sessionMessageMutation.isPending}
                        >
                          {sessionMessageMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}
                          写入本节
                        </Button>
                        <Button
                          variant="outline"
                          data-testid="authoring-confirm-action"
                          onClick={() => submitSessionMessage('confirm')}
                          disabled={sessionMessageMutation.isPending || !currentSection.content.trim()}
                        >
                          <CheckCircle className="mr-2 h-4 w-4" />
                          确认本节
                        </Button>
                        <Button
                          variant="outline"
                          data-testid="authoring-skip-action"
                          onClick={() => submitSessionMessage('skip')}
                          disabled={sessionMessageMutation.isPending}
                        >
                          <SkipForward className="mr-2 h-4 w-4" />
                          跳过本节
                        </Button>
                        <Button
                          variant="outline"
                          data-testid="authoring-revise-action"
                          onClick={() => submitSessionMessage('revise')}
                          disabled={!sessionInput.trim() || sessionMessageMutation.isPending}
                        >
                          <RotateCcw className="mr-2 h-4 w-4" />
                          修订本节
                        </Button>
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>

              <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
                <Card data-testid="authoring-session-cockpit">
                  <CardHeader>
                    <CardTitle className="text-base">编写驾驶舱</CardTitle>
                    <CardDescription>恢复会话后仍可看到上游依据、章节进度、待确认项和最终生成门禁。</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="grid grid-cols-2 gap-3 text-sm">
                      <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
                        <p className="text-xs text-slate-500">章节进度</p>
                        <p className="mt-1 text-lg font-semibold text-slate-900 dark:text-white">
                          {sessionProgress?.completed || 0}/{sessionProgress?.total || 0}
                        </p>
                      </div>
                      <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
                        <p className="text-xs text-slate-500">写入证据</p>
                        <p className="mt-1 text-lg font-semibold text-slate-900 dark:text-white">{sessionWriteLog.length}</p>
                      </div>
                      <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
                        <p className="text-xs text-slate-500">待确认项</p>
                        <p className="mt-1 text-lg font-semibold text-slate-900 dark:text-white">{sessionPendingConfirmations.length}</p>
                      </div>
                      <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
                        <p className="text-xs text-slate-500">生成门禁</p>
                        <p className="mt-1 text-lg font-semibold text-slate-900 dark:text-white">
                          {sessionQualityGate.ready ? '通过' : '未通过'}
                        </p>
                      </div>
                    </div>

                    <div>
                      <p className="text-xs font-medium text-slate-500">上游依据</p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {upstreamDependencies.length ? upstreamDependencies.map((dependency) => (
                          <Badge key={dependency} variant="outline">{getDocumentTypeLabel(dependency)}</Badge>
                        )) : <Badge variant="secondary">无上游依赖</Badge>}
                      </div>
                    </div>

                    {(sessionQualityGate.blockers || []).length ? (
                      <div className="space-y-2">
                        {(sessionQualityGate.blockers || []).map((blocker: string) => (
                          <div key={blocker} className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
                            {blocker}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-100">
                        当前会话没有质量门禁阻塞。
                      </div>
                    )}
                  </CardContent>
                </Card>

                <Card data-testid="authoring-skill-agent-plan">
                  <CardHeader>
                    <CardTitle className="text-base">Skill/Agent 执行编排</CardTitle>
                    <CardDescription>
                      驾驶舱会推荐模板、Agent、Skill 和章节适用关系；可直接执行 Skill，并把结果回填为待写入证据。
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="grid gap-3 md:grid-cols-4">
                      <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
                        <p className="text-xs text-slate-500">推荐模板</p>
                        <p className="mt-1 text-sm font-medium text-slate-900 dark:text-white">
                          {recommendedTemplate?.name || `${getDocumentTypeLabel(generationSession.doc_type)}标准模板`}
                        </p>
                        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                          {recommendedTemplate?.description || '未匹配到发布模板，使用当前章节结构。'}
                        </p>
                      </div>
                      <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
                        <p className="text-xs text-slate-500">推荐 Skill</p>
                        <p className="mt-1 text-sm font-medium text-slate-900 dark:text-white">{recommendedSkills.length} 个</p>
                        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                          {recommendedSkills.length ? recommendedSkills.map(getSkillDisplayName).slice(0, 3).join('、') : '暂无可用 Skill，使用通用编写流程。'}
                        </p>
                      </div>
                      <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
                        <p className="text-xs text-slate-500">推荐 Agent</p>
                        <p className="mt-1 text-sm font-medium text-slate-900 dark:text-white">{recommendedAgents.length} 个</p>
                        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                          {recommendedAgents.length ? recommendedAgents.map(getAgentDisplayName).slice(0, 2).join('、') : '暂无适用 Agent，优先使用 Skill 编排。'}
                        </p>
                      </div>
                      <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
                        <p className="text-xs text-slate-500">活跃调用轨迹</p>
                        <p className="mt-1 text-sm font-medium text-slate-900 dark:text-white">{sessionSkillTrace.length} 条</p>
                        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                          {sessionSkillTrace.length ? sessionSkillTrace.slice(-3).map(getSkillTraceLabel).join('、') : '暂无调用轨迹。'}
                        </p>
                      </div>
                    </div>

                    <div className="grid gap-3 lg:grid-cols-2">
                      <div className="rounded-md border border-slate-200 p-3 dark:border-slate-800" data-testid="authoring-skill-execution-result">
                        <p className="text-xs font-medium text-slate-500">最近 Skill 执行</p>
                        {lastSkillExecution ? (
                          <div className="mt-2 space-y-2 text-sm">
                            <div className="flex flex-wrap items-center gap-2">
                              <Badge variant={lastSkillExecution.result.success ? 'default' : 'destructive'}>
                                {lastSkillExecution.result.success ? '成功' : '失败'}
                              </Badge>
                              <span className="font-medium text-slate-900 dark:text-white">{getSkillDisplayName(lastSkillExecution.skill)}</span>
                              <span className="text-xs text-slate-500">{lastSkillExecution.section.title}</span>
                            </div>
                            <p className="line-clamp-3 text-xs text-slate-500 dark:text-slate-400">
                              {lastSkillExecution.result.error_message || lastSkillExecution.result.output_data?.summary || lastSkillExecution.result.output_data?.recommendation || '结果已回填到输入框，可继续写入章节。'}
                            </p>
                          </div>
                        ) : (
                          <p className="mt-2 text-sm text-slate-500">尚未在本会话中执行 Skill。</p>
                        )}
                      </div>
                      <div className="rounded-md border border-slate-200 p-3 dark:border-slate-800" data-testid="authoring-agent-run-summary">
                        <p className="text-xs font-medium text-slate-500">最近编排运行</p>
                        {agentRunsQuery.isLoading ? (
                          <p className="mt-2 text-sm text-slate-500">正在加载运行记录...</p>
                        ) : recentAgentRuns.length ? (
                          <div className="mt-2 space-y-2">
                            {recentAgentRuns.map((run) => (
                              <div key={run.id} className="flex items-center justify-between gap-3 text-xs">
                                <span className="truncate text-slate-600 dark:text-slate-300">{run.id}</span>
                                <Badge variant={run.status === 'completed' ? 'default' : run.status === 'failed' ? 'destructive' : 'secondary'}>
                                  {run.status}
                                </Badge>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="mt-2 text-sm text-slate-500">暂无项目运行记录。执行 Skill 后会在后端运行闭环中留下证据。</p>
                        )}
                      </div>
                    </div>

                    <div className="overflow-x-auto">
                      <table className="w-full min-w-[760px] text-left text-sm">
                        <thead className="text-xs text-slate-500">
                          <tr className="border-b border-slate-200 dark:border-slate-800">
                            <th className="py-2 pr-3 font-medium">适用章节</th>
                            <th className="py-2 pr-3 font-medium">推荐 Skill</th>
                            <th className="py-2 pr-3 font-medium">规划目的</th>
                            <th className="py-2 pr-3 font-medium">轨迹状态</th>
                            <th className="py-2 pr-3 font-medium">快捷操作</th>
                          </tr>
                        </thead>
                        <tbody>
                          {skillSectionPlan.length ? skillSectionPlan.slice(0, 9).map((item) => (
                            <tr key={item.id} className="border-b border-slate-100 align-top dark:border-slate-900">
                              <td className="py-3 pr-3">
                                <p className="font-medium text-slate-900 dark:text-white">{item.section.position + 1}. {item.section.title}</p>
                                <p className="mt-1 text-xs text-slate-500">{getSectionStatusLabel(item.section.status)}</p>
                              </td>
                              <td className="py-3 pr-3">
                                <p className="font-medium text-slate-900 dark:text-white">{getSkillDisplayName(item.skill)}</p>
                                <p className="mt-1 text-xs text-slate-500">{getSkillTypeLabel(item.skill)}</p>
                              </td>
                              <td className="py-3 pr-3 text-xs text-slate-500">{item.reason}</td>
                              <td className="py-3 pr-3">
                                <Badge variant={item.activeTrace ? 'default' : 'secondary'}>
                                  {item.activeTrace ? `已记录：${getSkillTraceLabel(item.activeTrace)}` : '计划中'}
                                </Badge>
                              </td>
                              <td className="py-3 pr-3">
                                <div className="flex flex-wrap gap-2">
                                  <Button
                                    type="button"
                                    variant="outline"
                                    size="sm"
                                    data-testid="apply-recommended-skill-prompt"
                                    onClick={() => {
                                      setSelectedSectionKey(item.section.section_key)
                                      setSessionInput(item.prompt)
                                    }}
                                  >
                                    仅准备提示
                                  </Button>
                                  <Button
                                    type="button"
                                    size="sm"
                                    data-testid="execute-recommended-skill"
                                    onClick={() => skillExecutionMutation.mutate({ skill: item.skill, section: item.section })}
                                    disabled={skillExecutionMutation.isPending}
                                  >
                                    {skillExecutionMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Sparkles className="mr-2 h-4 w-4" />}
                                    执行 Skill
                                  </Button>
                                </div>
                              </td>
                            </tr>
                          )) : (
                            <tr>
                              <td className="py-4 text-sm text-slate-500" colSpan={5}>
                                暂无可规划 Skill。请先在 Skill 目录发布适用于该文档类型的能力，当前仍可使用章节问题继续编写。
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </CardContent>
                </Card>

                <Card data-testid="authoring-section-matrix">
                  <CardHeader>
                    <CardTitle className="text-base">章节执行矩阵</CardTitle>
                    <CardDescription>每个章节的状态、输入要求、质量规则和草稿长度。</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="overflow-x-auto">
                      <table className="w-full min-w-[680px] text-left text-sm">
                        <thead className="text-xs text-slate-500">
                          <tr className="border-b border-slate-200 dark:border-slate-800">
                            <th className="py-2 pr-3 font-medium">章节</th>
                            <th className="py-2 pr-3 font-medium">状态</th>
                            <th className="py-2 pr-3 font-medium">输入</th>
                            <th className="py-2 pr-3 font-medium">质量规则</th>
                            <th className="py-2 pr-3 font-medium">草稿</th>
                            <th className="py-2 pr-3 font-medium">操作</th>
                          </tr>
                        </thead>
                        <tbody>
                          {generationSession.sections.map((section) => {
                            const isFocused = focusedSection?.section_key === section.section_key
                            const isCurrent = generationSession.current_section_key === section.section_key
                            return (
                              <tr
                                key={section.id}
                                className={`border-b border-slate-100 align-top dark:border-slate-900 ${isFocused ? 'bg-indigo-50/60 dark:bg-indigo-950/30' : ''}`}
                              >
                                <td className="py-3 pr-3">
                                  <p className="font-medium text-slate-900 dark:text-white">{section.position + 1}. {section.title}</p>
                                  <p className="mt-1 max-w-[240px] text-xs text-slate-500">{section.content_requirement}</p>
                                  {isCurrent && <Badge variant="outline" className="mt-2">当前编写</Badge>}
                                </td>
                                <td className="py-3 pr-3">
                                  <Badge variant="secondary" className={sectionStatusTone(section.status)}>
                                    {getSectionStatusLabel(section.status)}
                                  </Badge>
                                </td>
                                <td className="py-3 pr-3 text-xs text-slate-500">
                                  {section.required_inputs.length ? section.required_inputs.slice(0, 2).join('、') : '通用上下文'}
                                </td>
                                <td className="py-3 pr-3 text-xs text-slate-500">
                                  {section.quality_rules.length ? (section.quality_rules[0].rule || '结构完整') : '内容完整且可追溯'}
                                </td>
                                <td className="py-3 pr-3 text-xs text-slate-500">
                                  {section.content.trim().length} 字
                                </td>
                                <td className="py-3 pr-3">
                                  <Button
                                    type="button"
                                    variant={isFocused ? 'default' : 'outline'}
                                    size="sm"
                                    data-testid="authoring-section-focus"
                                    onClick={() => setSelectedSectionKey(section.section_key)}
                                  >
                                    聚焦
                                  </Button>
                                </td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>
                  </CardContent>
                </Card>
              </div>

              <Card data-testid="authoring-operation-queue">
                <CardHeader>
                  <CardTitle className="text-base">编写待办队列</CardTitle>
                  <CardDescription>把待确认、门禁阻塞和各章节待补问题集中到一个可操作列表。</CardDescription>
                </CardHeader>
                <CardContent className="space-y-2">
                  {sessionOperationItems.length === 0 ? (
                    <div className="rounded-md border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-100">
                      当前没有待办项，可以进入最终交付检查。
                    </div>
                  ) : (
                    sessionOperationItems.map((item) => (
                      <div key={item.id} className="flex flex-col gap-3 rounded-md border border-slate-200 p-3 text-sm dark:border-slate-700 sm:flex-row sm:items-start sm:justify-between">
                        <div>
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant={item.type === '门禁阻塞' ? 'destructive' : 'secondary'}>{item.type}</Badge>
                            <span className="font-medium text-slate-900 dark:text-white">{item.title}</span>
                          </div>
                          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{item.message}</p>
                        </div>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          data-testid="use-operation-queue-item"
                          onClick={() => {
                            if (item.sectionKey) {
                              setSelectedSectionKey(item.sectionKey)
                            }
                            setSessionInput(item.message)
                          }}
                        >
                          带入处理
                        </Button>
                      </div>
                    ))
                  )}
                </CardContent>
              </Card>

              {focusedSection && (
                <>
                  <Card data-testid="authoring-section-detail">
                    <CardHeader>
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                        <div>
                          <CardTitle className="text-base">章节聚焦：{focusedSection.title}</CardTitle>
                          <CardDescription>
                            集中查看本节问题、已确认事实、待补输入和质量门禁；操作仍以当前编写章节为准。
                          </CardDescription>
                        </div>
                        <Badge variant="secondary" className={sectionStatusTone(focusedSection.status)}>
                          {getSectionStatusLabel(focusedSection.status)}
                        </Badge>
                      </div>
                    </CardHeader>
                    <CardContent className="grid gap-4 lg:grid-cols-3">
                      <div className="space-y-2 rounded-md border border-slate-200 p-3 dark:border-slate-700">
                        <p className="text-xs font-medium text-slate-500">本节问题</p>
                        <p className="text-sm text-slate-700 dark:text-slate-200">
                          {getSectionPrimaryQuestion(focusedSection) || '本节暂无待回答问题。'}
                        </p>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          data-testid="use-focused-section-question"
                          onClick={() => setSessionInput(getSectionPrimaryQuestion(focusedSection))}
                          disabled={!getSectionPrimaryQuestion(focusedSection)}
                        >
                          带入输入框
                        </Button>
                      </div>
                      <div className="space-y-2 rounded-md border border-slate-200 p-3 dark:border-slate-700">
                        <p className="text-xs font-medium text-slate-500">已确认事实</p>
                        {focusedSection.confirmed_facts_json.length ? (
                          focusedSection.confirmed_facts_json.slice(0, 3).map((fact) => (
                            <p key={fact} className="text-sm text-slate-700 dark:text-slate-200">{fact}</p>
                          ))
                        ) : (
                          <p className="text-sm text-slate-500">暂无已确认事实。</p>
                        )}
                      </div>
                      <div className="space-y-2 rounded-md border border-slate-200 p-3 dark:border-slate-700">
                        <p className="text-xs font-medium text-slate-500">质量门禁</p>
                        <p className="text-sm text-slate-700 dark:text-slate-200">{getSectionQualityRule(focusedSection)}</p>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          data-testid="use-focused-section-gate"
                          onClick={() => setSessionInput(`按质量门禁补充：${getSectionQualityRule(focusedSection)}`)}
                        >
                          按门禁补充
                        </Button>
                      </div>
                      <div className="space-y-3 rounded-md border border-slate-200 p-3 dark:border-slate-700 lg:col-span-3">
                        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                          <div>
                            <p className="text-xs font-medium text-slate-500">聚焦章节草稿</p>
                            <p className="mt-1 text-sm text-slate-700 dark:text-slate-200">
                              {getSectionDraftLength(focusedSection)} 字，位置 {focusedSection.position + 1}/{generationSession.sections.length}
                            </p>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              data-testid="focus-previous-section"
                              onClick={() => {
                                const previous = generationSession.sections[Math.max(0, focusedSectionIndex - 1)]
                                if (previous) setSelectedSectionKey(previous.section_key)
                              }}
                              disabled={focusedSectionIndex <= 0}
                            >
                              上一节
                            </Button>
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              data-testid="focus-next-section"
                              onClick={() => {
                                const next = generationSession.sections[Math.min(generationSession.sections.length - 1, focusedSectionIndex + 1)]
                                if (next) setSelectedSectionKey(next.section_key)
                              }}
                              disabled={focusedSectionIndex < 0 || focusedSectionIndex >= generationSession.sections.length - 1}
                            >
                              下一节
                            </Button>
                          </div>
                        </div>
                        {focusedSection.content.trim() ? (
                          <pre data-testid="focused-section-draft-preview" className="max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-slate-950 p-4 text-xs text-slate-100">
                            {focusedSection.content}
                          </pre>
                        ) : (
                          <div className="rounded-md border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-slate-700">
                            本节还没有草稿。可以先带入本节问题，补充事实后写入。
                          </div>
                        )}
                      </div>
                    </CardContent>
                  </Card>

                  <Card data-testid="authoring-section-evidence">
                    <CardHeader>
                      <CardTitle className="text-base">段落/章节证据</CardTitle>
                      <CardDescription>
                        基于本节草稿、写入记录、Skill 轨迹、已确认事实和质量评分生成的前端证据视图。
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      <div className="grid gap-3 md:grid-cols-4">
                        {(focusedSectionEvidence?.summary || []).map((item) => (
                          <div key={item.label} className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
                            <p className="text-xs text-slate-500">{item.label}</p>
                            <p className="mt-1 text-sm font-medium text-slate-900 dark:text-white">{item.value}</p>
                            <p className="mt-1 line-clamp-2 text-xs text-slate-500 dark:text-slate-400">{item.detail}</p>
                          </div>
                        ))}
                      </div>
                      {focusedSectionEvidence?.paragraphs.length ? (
                        <div className="space-y-2">
                          {focusedSectionEvidence.paragraphs.map((item) => (
                            <div key={item.id} className="rounded-md border border-slate-200 p-3 text-sm dark:border-slate-700">
                              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                                <div>
                                  <p className="font-medium text-slate-900 dark:text-white">{item.title}</p>
                                  <p className="mt-1 line-clamp-2 text-xs text-slate-500 dark:text-slate-400">{item.detail}</p>
                                </div>
                                <Badge variant={item.status === '证据较完整' ? 'default' : 'secondary'}>{item.status}</Badge>
                              </div>
                              <div className="mt-2 flex flex-wrap gap-2">
                                {item.evidence.length ? item.evidence.map((evidence) => (
                                  <Badge key={evidence} variant="outline" className="max-w-full truncate">{evidence}</Badge>
                                )) : <Badge variant="secondary">暂无段落证据</Badge>}
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="rounded-md border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-slate-700">
                          本节暂无可拆分段落。写入草稿后将显示段落级证据。
                        </div>
                      )}
                    </CardContent>
                  </Card>
                </>
              )}

              <Card data-testid="authoring-evidence-log">
                <CardHeader>
                  <CardTitle className="text-base">写入证据与待确认项</CardTitle>
                  <CardDescription>汇总本会话历史写入、能力调用和仍需人工确认的问题。</CardDescription>
                </CardHeader>
                <CardContent className="grid gap-4 lg:grid-cols-2">
                  <div className="space-y-2">
                    {sessionWriteLog.length === 0 ? (
                      <div className="rounded-md border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-slate-700">
                        尚无写入记录。回答当前章节问题后会自动形成写入证据。
                      </div>
                    ) : (
                      sessionWriteLog.slice(-5).map((entry) => (
                        <div key={entry.index} className="rounded-md border border-slate-200 p-3 text-sm dark:border-slate-700">
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-medium text-slate-900 dark:text-white">{entry.section_title || entry.section_key}</span>
                            <Badge variant={entry.verified ? 'default' : 'secondary'}>{entry.verified ? '已验证' : '待核对'}</Badge>
                          </div>
                          <p className="mt-1 text-xs text-slate-500">{entry.patch_type || 'patch'} · {entry.action || 'answer'}</p>
                          {(entry.skill_labels || []).length ? (
                            <p className="mt-1 text-xs text-slate-500">能力：{entry.skill_labels.join('、')}</p>
                          ) : null}
                        </div>
                      ))
                    )}
                  </div>
                  <div className="space-y-2">
                    {sessionPendingConfirmations.length === 0 ? (
                      <div className="rounded-md border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-100">
                        当前没有待确认项。
                      </div>
                    ) : (
                      sessionPendingConfirmations.map((item, index) => (
                        <div key={`${item.section_key || 'pending'}-${index}`} className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
                          <p className="font-medium">{item.section_title || item.section_key || '待确认项'}</p>
                          <p className="mt-1 text-xs">{getPendingConfirmationText(item)}</p>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="mt-3 border-amber-300 bg-white/70 text-amber-900 hover:bg-white dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100"
                            data-testid="use-pending-confirmation"
                            onClick={() => setSessionInput(getPendingConfirmationText(item))}
                          >
                            带入输入框
                          </Button>
                        </div>
                      ))
                    )}
                  </div>
                </CardContent>
              </Card>

              {lastTurn && (
                <div className="grid gap-4 lg:grid-cols-3">
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">写入与验证</CardTitle>
                      <CardDescription>最近一次对话写入的 patch 和验证结果</CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-2 text-sm">
                      {(lastTurn.write_log || []).slice(-3).map((entry) => (
                        <div key={entry.index} className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-medium">{entry.section_title || entry.section_key}</span>
                            <Badge variant={entry.verified ? 'default' : 'secondary'}>{entry.verified ? '已验证' : '待核对'}</Badge>
                          </div>
                          <p className="mt-1 text-xs text-slate-500">{entry.patch_type} · {entry.action}</p>
                        </div>
                      ))}
                    </CardContent>
                  </Card>

                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">能力调用</CardTitle>
                      <CardDescription>本轮使用的中文业务能力</CardDescription>
                    </CardHeader>
                    <CardContent className="flex flex-wrap gap-2">
                      {(lastTurn.skill_trace || []).map((item, index) => (
                        <Badge key={`${item.label}-${index}`} variant="secondary">
                          {item.label}
                        </Badge>
                      ))}
                    </CardContent>
                  </Card>

                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">质量门禁</CardTitle>
                      <CardDescription>确认、评审和导出准备度</CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-2 text-sm text-slate-600 dark:text-slate-300">
                      <div>评审：{lastTurn.quality_gate?.review_ready ? '可进入评审' : '仍需补齐'}</div>
                      <div>导出：{lastTurn.quality_gate?.export_ready ? '可导出' : '暂不可导出'}</div>
                      {(lastTurn.quality_gate?.blockers || []).map((blocker: string) => (
                        <div key={blocker} className="text-amber-600 dark:text-amber-300">阻塞：{blocker}</div>
                      ))}
                    </CardContent>
                  </Card>
                </div>
              )}

              {currentSection?.content && (
                <Card>
                  <CardHeader>
                    <CardTitle>当前章节草稿</CardTitle>
                    <CardDescription>确认后会进入下一章节，未确认内容会保留待确认标记</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-md bg-slate-950 p-4 text-xs text-slate-100">
                      {currentSection.content}
                    </pre>
                  </CardContent>
                </Card>
              )}

              <Card>
                <CardHeader>
                  <CardTitle className="text-base">最终交付检查</CardTitle>
                  <CardDescription>生成正式文档前必须完成的章节、确认项和质量门禁检查。</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4 py-6">
                  <div className="grid gap-3 md:grid-cols-2" data-testid="authoring-finalization-checklist">
                    {finalizationChecks.map((check) => (
                      <div
                        key={check.label}
                        className={`rounded-md border p-3 text-sm ${
                          check.passed
                            ? 'border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-100'
                            : 'border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100'
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          {check.passed ? <CheckCircle className="h-4 w-4" /> : <Clock3 className="h-4 w-4" />}
                          <span className="font-medium">{check.label}</span>
                        </div>
                        <p className="mt-1 text-xs opacity-80">{check.detail}</p>
                      </div>
                    ))}
                  </div>
                  <Button
                    className="w-full"
                    size="lg"
                    onClick={() => finalizeSessionMutation.mutate()}
                    disabled={finalizeSessionMutation.isPending || !canFinalizeSession}
                  >
                    {finalizeSessionMutation.isPending ? <Loader2 className="mr-2 h-5 w-5 animate-spin" /> : <Sparkles className="mr-2 h-5 w-5" />}
                    {canFinalizeSession ? '生成交互式文档' : '先确认至少一个章节并关闭待确认项'}
                  </Button>
                </CardContent>
              </Card>
            </>
          ) : (
            <Card>
              <CardContent className="py-6">
                <div className="flex flex-col items-center text-center">
                  <Sparkles className="h-10 w-10 text-indigo-500" />
                  <h3 className="mt-4 text-lg font-medium text-slate-900 dark:text-white">AI 辅助生成</h3>
                  <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                    所有核心项目文档都使用章节化对话式编写，写入、验证、评审和导出状态会保留在交付链路中。
                  </p>
                  <div className="mt-6 grid w-full gap-3">
                    {supportsInteractiveGeneration && (
                      <Button
                        size="lg"
                        data-testid="start-interactive-generation"
                        onClick={() => startSessionMutation.mutate()}
                        disabled={!selectedType || !context.trim() || startSessionMutation.isPending}
                      >
                        {startSessionMutation.isPending ? <Loader2 className="mr-2 h-5 w-5 animate-spin" /> : <MessageSquare className="mr-2 h-5 w-5" />}
                        开始交互式生成
                      </Button>
                    )}
                    <Button
                      variant={supportsInteractiveGeneration ? 'outline' : 'default'}
                      size="lg"
                      onClick={() => generateMutation.mutate()}
                      disabled={!selectedType || !context.trim() || generateMutation.isPending}
                    >
                      {generateMutation.isPending ? (
                        <>
                          <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                          正在生成...
                        </>
                      ) : (
                        <>
                          <Sparkles className="mr-2 h-5 w-5" />
                          直接生成文档
                        </>
                      )}
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
