'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Select, SelectOption } from '@/components/ui/select'
import { agentApi, apiClient, templatesApi, ParsedTemplate, SkillCatalogEntry, TemplatePageType, TemplatePlaceholder, TemplateSection } from '@/lib/api-client'
import { useToast } from '@/components/ui/toast'
import {
  FileText,
  Upload,
  Search,
  Plus,
  History,
  Trash2,
  FileUp,
  CheckCircle,
  AlertCircle,
  ListTree,
  Save,
  ShieldCheck,
  Settings,
} from 'lucide-react'

interface Template {
  id: string
  name: string
  description: string | null
  doc_type: string
  version_count: number
  is_active: string
  created_at: string
  updated_at: string
  governance_scope?: string | null
  visibility?: string | null
  lifecycle_status?: string | null
  status?: string | null
  is_builtin?: boolean
  section_count?: number
  skill_binding_count?: number
  active_version?: number | null
}

interface TemplateVersion {
  id: string
  version: number
  file_hash: string
  is_active: string
  placeholder_schema: TemplatePlaceholder[] | null
  page_types: TemplatePageType[] | null
  created_at: string
}

interface CapabilityReadinessItem {
  key: string
  label: string
  status: string
  score: number
  summary: string
  evidence: Record<string, any>
  blockers?: string[]
  recommended_actions?: string[]
}

interface CapabilityReadinessResponse {
  capabilities: CapabilityReadinessItem[]
}

const CORE_TEMPLATE_TYPES = [
  { docType: 'urs', label: 'URS' },
  { docType: 'brd', label: 'BRD' },
  { docType: 'prd', label: 'PRD' },
  { docType: 'implementation_plan', label: '实施方案' },
  { docType: 'acceptance_report', label: '验收报告' },
]

function evidenceNumber(evidence: Record<string, any> | undefined, keys: string[], fallback = 0) {
  if (!evidence) return fallback
  for (const key of keys) {
    const value = Number(evidence[key])
    if (Number.isFinite(value)) return value
  }
  return fallback
}

function templateValidationMessageKey(kind: 'error' | 'warning', message: string) {
  return `${kind}:${message}`
}

function templateValidationMessages(parsedPlaceholders: ParsedTemplate) {
  return [
    ...Array.from(new Set(parsedPlaceholders.errors)).map((message) => ({ kind: 'error' as const, message })),
    ...Array.from(new Set(parsedPlaceholders.warnings)).map((message) => ({ kind: 'warning' as const, message })),
  ]
}

export default function TemplatesPage() {
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const { addToast } = useToast()

  const [searchQuery, setSearchQuery] = useState('')
  const [filterDocType, setFilterDocType] = useState<string>('all')
  const [filterStatus, setFilterStatus] = useState<string>('all')
  const [filterGovernance, setFilterGovernance] = useState<string>('all')
  const [selectedWorkbenchTemplateId, setSelectedWorkbenchTemplateId] = useState<string | null>(null)
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null)
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false)
  const [previewDialogOpen, setPreviewDialogOpen] = useState(false)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadData, setUploadData] = useState({
    name: '',
    description: '',
    doc_type: 'urs',
  })
  const [parsedPlaceholders, setParsedPlaceholders] = useState<ParsedTemplate | null>(null)
  const [isParsingTemplate, setIsParsingTemplate] = useState(false)
  const [versionHistoryTemplate, setVersionHistoryTemplate] = useState<Template | null>(null)
  const [sectionDialogOpen, setSectionDialogOpen] = useState(false)
  const [sectionTemplate, setSectionTemplate] = useState<Template | null>(null)
  const [selectedSectionId, setSelectedSectionId] = useState<string | null>(null)
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([])
  const [sectionForm, setSectionForm] = useState({
    title: '',
    section_key: '',
    content_requirement: '',
    prompt: '',
  })

  // Fetch templates
  const { data: templatesData, isLoading } = useQuery({
    queryKey: ['templates'],
    queryFn: () => templatesApi.list(),
  })

  const templates: Template[] = Array.isArray(templatesData)
    ? templatesData
    : templatesData?.items || []

  const readinessQuery = useQuery({
    queryKey: ['template-production-readiness'],
    queryFn: () => apiClient.get<CapabilityReadinessResponse>('/ops/capabilities/readiness'),
  })

  // Create template mutation
  const createTemplateMutation = useMutation({
    mutationFn: async (data: { name: string; description: string; doc_type: string; file: File }) => {
      const template = await templatesApi.create({
        name: data.name,
        description: data.description,
        doc_type: data.doc_type,
      })

      const formData = new FormData()
      formData.append('file', data.file)
      formData.append('description', data.description || '初始版本')
      await templatesApi.uploadVersion(template.id, formData)

      return template
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['templates'] })
      setUploadDialogOpen(false)
      resetUploadForm()
      addToast({ title: '模板已创建', description: '模板文件已上传为初始版本。' })
    },
    onError: (error: Error) => {
      addToast({ title: '创建模板失败', description: error.message, variant: 'destructive' })
    },
  })

  // Upload version mutation
  const uploadVersionMutation = useMutation({
    mutationFn: ({ templateId, formData }: { templateId: string; formData: FormData }) => {
      return templatesApi.uploadVersion(templateId, formData)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['templates'] })
      queryClient.invalidateQueries({ queryKey: ['template-versions', selectedTemplate?.id] })
      setUploadDialogOpen(false)
      resetUploadForm()
      setSelectedTemplate(null)
      addToast({ title: '模板版本已上传' })
    },
    onError: (error: Error) => {
      addToast({ title: '上传模板版本失败', description: error.message, variant: 'destructive' })
    },
  })

  // Delete template mutation
  const deleteTemplateMutation = useMutation({
    mutationFn: (templateId: string) => templatesApi.delete(templateId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['templates'] })
      setSelectedTemplate(null)
      addToast({ title: '模板已删除' })
    },
    onError: (error: Error) => {
      addToast({ title: '删除模板失败', description: error.message, variant: 'destructive' })
    },
  })

  // Fetch version history for a template
  const { data: versionHistoryData } = useQuery({
    queryKey: ['template-versions', versionHistoryTemplate?.id],
    queryFn: () => templatesApi.getVersions(versionHistoryTemplate!.id),
    enabled: !!versionHistoryTemplate,
  })

  const { data: templateSections = [], isLoading: sectionsLoading } = useQuery({
    queryKey: ['template-sections', sectionTemplate?.id],
    queryFn: () => templatesApi.listSections(sectionTemplate!.id),
    enabled: sectionDialogOpen && !!sectionTemplate,
  })

  const { data: skillCatalogData } = useQuery({
    queryKey: ['template-section-skills'],
    queryFn: () => agentApi.listSkillCatalog({ status: 'published', pageSize: 100 }),
    enabled: sectionDialogOpen,
  })

  const skillCatalog: SkillCatalogEntry[] = skillCatalogData?.items || []
  const selectedSection = useMemo(
    () => templateSections.find((section) => section.id === selectedSectionId) || templateSections[0] || null,
    [selectedSectionId, templateSections]
  )

  useEffect(() => {
    if (!selectedSection && templateSections.length > 0) {
      setSelectedSectionId(templateSections[0].id)
    }
  }, [selectedSection, templateSections])

  useEffect(() => {
    if (!selectedSection) {
      setSelectedSkillIds([])
      return
    }
    setSelectedSkillIds(selectedSection.skill_bindings.map((binding) => binding.skill_id))
  }, [selectedSection])

  const seedSectionsMutation = useMutation({
    mutationFn: (templateId: string) => templatesApi.seedSections(templateId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['template-sections', sectionTemplate?.id] })
      queryClient.invalidateQueries({ queryKey: ['template-workbench-sections', selectedWorkbenchTemplate?.id] })
      queryClient.invalidateQueries({ queryKey: ['templates'] })
      addToast({ title: '标准章节已生成' })
    },
    onError: (error: Error) => {
      addToast({ title: '生成标准章节失败', description: error.message, variant: 'destructive' })
    },
  })

  const createSectionMutation = useMutation({
    mutationFn: (templateId: string) =>
      templatesApi.createSection(templateId, {
        section_key: sectionForm.section_key,
        title: sectionForm.title,
        level: 1,
        position: templateSections.length,
        content_requirement: sectionForm.content_requirement,
        prompt: sectionForm.prompt,
        required_inputs: [],
        quality_rules: [],
      }),
    onSuccess: (section) => {
      queryClient.invalidateQueries({ queryKey: ['template-sections', sectionTemplate?.id] })
      setSelectedSectionId(section.id)
      setSectionForm({ title: '', section_key: '', content_requirement: '', prompt: '' })
      addToast({ title: '章节已创建' })
    },
    onError: (error: Error) => {
      addToast({ title: '创建章节失败', description: error.message, variant: 'destructive' })
    },
  })

  const replaceSectionSkillsMutation = useMutation({
    mutationFn: ({ sectionId, skillIds }: { sectionId: string; skillIds: string[] }) =>
      templatesApi.replaceSectionSkills(sectionId, skillIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['template-sections', sectionTemplate?.id] })
      addToast({ title: '章节 Skill 绑定已更新' })
    },
    onError: (error: Error) => {
      addToast({ title: '保存章节 Skill 失败', description: error.message, variant: 'destructive' })
    },
  })

  const activateVersionMutation = useMutation({
    mutationFn: ({ templateId, versionId }: { templateId: string; versionId: string }) =>
      templatesApi.activateVersion(templateId, versionId),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['templates'] })
      queryClient.invalidateQueries({ queryKey: ['template-versions', variables.templateId] })
      addToast({ title: '模板版本已设为当前版本' })
    },
    onError: (error: Error) => {
      addToast({ title: '设置当前版本失败', description: error.message, variant: 'destructive' })
    },
  })

  const resetUploadForm = () => {
    setUploadFile(null)
    setUploadData({ name: '', description: '', doc_type: 'urs' })
    setParsedPlaceholders(null)
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    await handleSelectedFile(file)
  }

  const handleSelectedFile = async (file: File) => {
    if (!/\.(docx|pptx)$/i.test(file.name)) {
      addToast({
        title: '文件类型不支持',
        description: '模板文件仅支持 DOCX 或 PPTX 格式。',
        variant: 'destructive',
      })
      return
    }

    setUploadFile(file)
    setParsedPlaceholders(null)
    setIsParsingTemplate(true)

    try {
      const formData = new FormData()
      formData.append('file', file)
      const parsed = await templatesApi.parseUpload(formData, uploadData.doc_type)
      setParsedPlaceholders(parsed)
      if (parsed.is_valid) {
        addToast({
          title: '模板预检通过',
          description: `识别到 ${parsed.placeholders.length} 个占位符，${parsed.total_pages || 1} 个页面/文档单元。`,
        })
      } else {
        addToast({
          title: '模板预检发现问题',
          description: parsed.errors[0] || '请修复模板占位符后再上传。',
          variant: 'destructive',
        })
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setParsedPlaceholders({
        placeholders: [],
        page_types: [],
        total_pages: 0,
        is_valid: false,
        warnings: [],
        errors: [message],
        invalid_placeholders: [],
        duplicate_placeholders: [],
        content_format: 'unknown',
      })
      addToast({ title: '模板预检失败', description: message, variant: 'destructive' })
    } finally {
      setIsParsingTemplate(false)
    }
  }

  const handleUpload = async () => {
    if (!uploadFile) return

    if (!selectedTemplate) {
      // Create new template
      createTemplateMutation.mutate({
        name: uploadData.name || uploadFile.name.replace(/\.(docx|pptx)$/i, ''),
        description: uploadData.description,
        doc_type: uploadData.doc_type,
        file: uploadFile,
      })
    } else {
      // Upload version to existing template
      const formData = new FormData()
      formData.append('file', uploadFile)
      formData.append('description', uploadData.description)

      uploadVersionMutation.mutate({
        templateId: selectedTemplate.id,
        formData,
      })
    }
  }

  const getTemplateGovernance = (template: Template) => {
    if (template.governance_scope) return template.governance_scope
    if (template.is_builtin) return 'system'
    if (template.visibility === 'platform') return 'platform'
    return 'project'
  }

  const getTemplateLifecycleStatus = (template: Template) => {
    const status = String(template.lifecycle_status || template.status || template.is_active || '').toLowerCase()
    if (['published', 'active', 'true', '1', 'yes'].includes(status)) return 'published'
    if (['archived', 'disabled', 'deleted'].includes(status)) return 'archived'
    return 'draft'
  }

  const getDocTypeLabel = (docType: string) => {
    const labels: Record<string, string> = {
      urs: 'URS 用户需求',
      brd: 'BRD 商业需求',
      prd: 'PRD 产品需求',
      feasibility: '可研报告',
      implementation_plan: '实施方案',
      acceptance_report: '验收报告',
    }
    return labels[docType] || docType.toUpperCase()
  }

  const getGovernanceLabel = (scope: string) => {
    const labels: Record<string, string> = {
      system: '系统级',
      platform: '平台级',
      tenant: '租户级',
      project: '项目级',
      personal: '个人级',
    }
    return labels[scope] || scope
  }

  const getLifecycleStatusLabel = (status: string) => {
    const labels: Record<string, string> = {
      published: '已发布',
      draft: '草稿',
      archived: '已归档',
    }
    return labels[status] || status
  }

  const filteredTemplates = templates.filter(t => {
    const query = searchQuery.toLowerCase()
    const matchesSearch = t.name.toLowerCase().includes(query) ||
      (t.description || '').toLowerCase().includes(query) ||
      getDocTypeLabel(t.doc_type).toLowerCase().includes(query)
    const matchesType = filterDocType === 'all' || t.doc_type === filterDocType
    const matchesStatus = filterStatus === 'all' || getTemplateLifecycleStatus(t) === filterStatus
    const matchesGovernance = filterGovernance === 'all' || getTemplateGovernance(t) === filterGovernance
    return matchesSearch && matchesType && matchesStatus && matchesGovernance
  })

  const selectedWorkbenchTemplate =
    filteredTemplates.find((template) => template.id === selectedWorkbenchTemplateId) ||
    filteredTemplates[0] ||
    null

  useEffect(() => {
    if (!selectedWorkbenchTemplate) {
      setSelectedWorkbenchTemplateId(null)
      return
    }
    if (selectedWorkbenchTemplate.id !== selectedWorkbenchTemplateId) {
      setSelectedWorkbenchTemplateId(selectedWorkbenchTemplate.id)
    }
  }, [selectedWorkbenchTemplate, selectedWorkbenchTemplateId])

  const { data: workbenchSections = [] } = useQuery({
    queryKey: ['template-workbench-sections', selectedWorkbenchTemplate?.id],
    queryFn: () => templatesApi.listSections(selectedWorkbenchTemplate!.id),
    enabled: !!selectedWorkbenchTemplate,
  })

  const summary = {
    total: templates.length,
    platform: templates.filter((template) => ['system', 'platform'].includes(getTemplateGovernance(template))).length,
    project: templates.filter((template) => getTemplateGovernance(template) === 'project').length,
    published: templates.filter((template) => getTemplateLifecycleStatus(template) === 'published').length,
    draft: templates.filter((template) => getTemplateLifecycleStatus(template) === 'draft').length,
  }

  const templateProductionCapability = readinessQuery.data?.capabilities.find((capability) => capability.key === 'document_delivery')
  const totalSectionCount = templates.reduce((total, template) => total + Number(template.section_count ?? 0), 0)
  const totalSkillBindingCount = templates.reduce((total, template) => total + Number(template.skill_binding_count ?? 0), 0)
  const activeTemplateCount = templates.filter((template) => getTemplateLifecycleStatus(template) === 'published' && template.active_version !== null).length
  const coreTemplateCoverage = CORE_TEMPLATE_TYPES.map((item) => {
    const matched = templates.find((template) => template.doc_type === item.docType && getTemplateLifecycleStatus(template) === 'published')
    return { ...item, matched }
  })
  const coveredCoreTemplateCount = coreTemplateCoverage.filter((item) => item.matched).length
  const templateEvidence = templateProductionCapability?.evidence
  const productionEvidenceItems = [
    {
      key: 'template_count',
      label: '模板总数',
      value: evidenceNumber(templateEvidence, ['template_count'], summary.total),
    },
    {
      key: 'published_template_count',
      label: '已发布模板',
      value: summary.published,
    },
    {
      key: 'active_template_count',
      label: '当前版本',
      value: activeTemplateCount,
    },
    {
      key: 'template_section_count',
      label: '章节定义',
      value: evidenceNumber(templateEvidence, ['template_section_count'], totalSectionCount),
    },
    {
      key: 'skill_binding_count',
      label: 'Skill 绑定',
      value: totalSkillBindingCount,
    },
    {
      key: 'core_coverage_count',
      label: '核心模板覆盖',
      value: `${coveredCoreTemplateCount}/${CORE_TEMPLATE_TYPES.length}`,
    },
  ]

  const getDocTypeBadgeColor = (docType: string) => {
    switch (docType) {
      case 'urs':
        return 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-100'
      case 'brd':
        return 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-100'
      case 'prd':
        return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-100'
      default:
        return 'bg-slate-100 text-slate-800 dark:bg-slate-700 dark:text-slate-100'
    }
  }

  const openSectionWorkbench = (template: Template) => {
    setSectionTemplate(template)
    setSelectedSectionId(null)
    setSelectedSkillIds([])
    setSectionForm({ title: '', section_key: '', content_requirement: '', prompt: '' })
    setSectionDialogOpen(true)
  }

  const toggleSkillSelection = (skillId: string, checked: boolean) => {
    setSelectedSkillIds((current) =>
      checked
        ? Array.from(new Set([...current, skillId]))
        : current.filter((id) => id !== skillId)
    )
  }

  const sortedSections: TemplateSection[] = [...templateSections].sort((a, b) => {
    if (a.position !== b.position) return a.position - b.position
    return a.section_key.localeCompare(b.section_key)
  })

  const isActiveVersion = (version: TemplateVersion) =>
    ['true', 'active', '1', 'yes'].includes(String(version.is_active).toLowerCase())
  const canUploadTemplate =
    !!uploadFile &&
    !isParsingTemplate &&
    parsedPlaceholders?.is_valid !== false &&
    !createTemplateMutation.isPending &&
    !uploadVersionMutation.isPending

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1
            className="text-2xl font-semibold text-slate-900 dark:text-white"
            data-testid="template-lifecycle-heading"
          >
            模板中心
          </h1>
          <p className="text-sm text-slate-500 mt-1">管理带变量占位符的文档模板</p>
        </div>
        <Dialog
          open={uploadDialogOpen}
          onOpenChange={(open) => {
            setUploadDialogOpen(open)
            if (!open) {
              setSelectedTemplate(null)
              resetUploadForm()
            }
          }}
        >
          <DialogTrigger asChild>
            <Button onClick={() => {
              setSelectedTemplate(null)
              resetUploadForm()
            }}>
              <Plus className="mr-2 h-4 w-4" />
              新建模板
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-lg">
            <DialogHeader>
              <DialogTitle>
                {selectedTemplate ? `上传新版本 - ${selectedTemplate.name}` : '创建新模板'}
              </DialogTitle>
            </DialogHeader>
            <div className="space-y-4 py-4">
              {!selectedTemplate && (
                <>
                  <div className="space-y-2">
                    <Label htmlFor="name">模板名称</Label>
                    <Input
                      id="name"
                      value={uploadData.name}
                      onChange={(e) => setUploadData({ ...uploadData, name: e.target.value })}
                      placeholder="输入模板名称"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="description">描述</Label>
                    <Input
                      id="description"
                      value={uploadData.description}
                      onChange={(e) => setUploadData({ ...uploadData, description: e.target.value })}
                      placeholder="可选描述"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="docType">文档类型</Label>
                    <Select
                      id="docType"
                      value={uploadData.doc_type}
                      onValueChange={(value) => setUploadData({ ...uploadData, doc_type: value })}
                    >
                      <SelectOption value="urs">URS（用户需求）</SelectOption>
                      <SelectOption value="brd">BRD（业务需求）</SelectOption>
                      <SelectOption value="prd">PRD（产品需求）</SelectOption>
                    </Select>
                  </div>
                </>
              )}

              {selectedTemplate && (
                <div className="space-y-2">
                  <Label htmlFor="versionDescription">版本说明</Label>
                  <Input
                    id="versionDescription"
                    value={uploadData.description}
                    onChange={(e) => setUploadData({ ...uploadData, description: e.target.value })}
                    placeholder="描述此版本的变更"
                  />
                </div>
              )}

              <div className="space-y-2">
                <Label>模板文件</Label>
                <div
                  className="border-2 border-dashed border-slate-200 dark:border-slate-700 rounded-lg p-8 text-center hover:border-indigo-500 dark:hover:border-indigo-400 transition-colors cursor-pointer"
                  onClick={() => fileInputRef.current?.click()}
                  onDragOver={(event) => {
                    event.preventDefault()
                    event.stopPropagation()
                  }}
                  onDrop={(event) => {
                    event.preventDefault()
                    event.stopPropagation()
                    const file = event.dataTransfer.files?.[0]
                    if (file) {
                      handleSelectedFile(file)
                    }
                  }}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    data-testid="template-upload-file-input"
                    accept=".docx,.pptx"
                    className="hidden"
                    onChange={handleFileChange}
                  />
                  {uploadFile ? (
                    <div className="flex items-center justify-center gap-2 text-green-600">
                      <CheckCircle className="h-8 w-8" />
                      <span className="font-medium">{uploadFile.name}</span>
                    </div>
                  ) : (
                    <>
                      <FileUp className="mx-auto h-10 w-10 text-slate-400" />
                      <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
                        点击上传或拖放文件
                      </p>
                      <p className="mt-1 text-xs text-slate-500">包含 {'{{variable}}'} 占位符的 DOCX 或 PPTX 文件</p>
                    </>
                  )}
                </div>
              </div>

              {isParsingTemplate && (
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                  正在解析模板占位符、页面类型和质量规则...
                </div>
              )}

              {parsedPlaceholders && (
                <div className="space-y-2" data-testid="template-parse-evidence">
                  <Label>模板预检结果</Label>
                  <div
                    className={`rounded-lg border p-3 ${
                      parsedPlaceholders.is_valid
                        ? 'border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/20 dark:text-emerald-100'
                        : 'border-red-200 bg-red-50 text-red-900 dark:border-red-900 dark:bg-red-950/20 dark:text-red-100'
                    }`}
                  >
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <Badge variant={parsedPlaceholders.is_valid ? 'secondary' : 'destructive'}>
                        {parsedPlaceholders.is_valid ? '可上传' : '需修复'}
                      </Badge>
                      <span>格式：{parsedPlaceholders.content_format.toUpperCase()}</span>
                      <span>页面/文档单元：{parsedPlaceholders.total_pages || 1}</span>
                      <span>占位符：{parsedPlaceholders.placeholders.length}</span>
                    </div>

                    {parsedPlaceholders.placeholders.length > 0 ? (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {parsedPlaceholders.placeholders.map((p, idx) => (
                          <Badge key={`${p.name}-${idx}`} variant="secondary" className="font-mono text-xs">
                            {'{{'}{p.name}{'}}'}
                            {(p.occurrence_count || 1) > 1 ? ` x${p.occurrence_count}` : ''}
                          </Badge>
                        ))}
                      </div>
                    ) : (
                      <p className="mt-3 text-sm">未识别到符合规范的占位符。</p>
                    )}

                    {parsedPlaceholders.duplicate_placeholders.length > 0 && (
                      <p className="mt-3 text-xs">
                        重复占位符：{parsedPlaceholders.duplicate_placeholders.join('、')}。重复项允许上传，但会在导出映射中复用同一字段。
                      </p>
                    )}

                    {parsedPlaceholders.invalid_placeholders.length > 0 && (
                      <p className="mt-3 text-xs">
                        非法占位符：{parsedPlaceholders.invalid_placeholders.map((name) => `{{${name}}}`).join('、')}
                      </p>
                    )}

                    {templateValidationMessages(parsedPlaceholders).map(({ kind, message }) => (
                      <p key={templateValidationMessageKey(kind, message)} className="mt-2 text-xs">
                        {message}
                      </p>
                    ))}
                  </div>
                </div>
              )}

              <div className="flex justify-end gap-2 pt-4">
                <Button variant="outline" onClick={() => { setUploadDialogOpen(false); resetUploadForm(); }}>
                  取消
                </Button>
                <Button
                  onClick={handleUpload}
                  disabled={!canUploadTemplate}
                >
                  {isParsingTemplate
                    ? '预检中...'
                    : createTemplateMutation.isPending || uploadVersionMutation.isPending
                    ? '处理中...'
                    : selectedTemplate ? '上传版本' : '创建模板'}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      <div
        data-testid="template-governance-summary"
        className="grid grid-cols-2 gap-3 lg:grid-cols-5"
      >
        <Card>
          <CardContent className="pt-4">
            <p className="text-2xl font-semibold text-slate-900 dark:text-white">{summary.total}</p>
            <p className="mt-1 text-xs text-slate-500">模板总数</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-2xl font-semibold text-slate-900 dark:text-white">{summary.platform}</p>
            <p className="mt-1 text-xs text-slate-500">平台级/系统级</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-2xl font-semibold text-slate-900 dark:text-white">{summary.project}</p>
            <p className="mt-1 text-xs text-slate-500">项目级</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-2xl font-semibold text-slate-900 dark:text-white">{summary.published}</p>
            <p className="mt-1 text-xs text-slate-500">已发布</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-2xl font-semibold text-slate-900 dark:text-white">{summary.draft}</p>
            <p className="mt-1 text-xs text-slate-500">草稿</p>
          </CardContent>
        </Card>
      </div>

      <Card data-testid="template-production-loop">
        <CardHeader>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <CardTitle>模板生产闭环</CardTitle>
              <CardDescription>集中校验模板治理、当前版本、章节定义、Skill 绑定和核心文档类型覆盖。</CardDescription>
            </div>
            <Badge variant={templateProductionCapability?.status === 'ready' ? 'secondary' : templateProductionCapability?.status === 'blocked' ? 'destructive' : 'outline'}>
              {readinessQuery.isLoading ? '检查中' : templateProductionCapability?.status === 'ready' ? '已就绪' : templateProductionCapability?.status === 'degraded' ? '需补模板' : templateProductionCapability?.status === 'blocked' ? '阻塞' : '未校准'}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="space-y-4">
            <div>
              <p className="font-semibold text-slate-900 dark:text-white">{templateProductionCapability?.label || '项目文档交付闭环'}</p>
              <p className="mt-1 text-sm text-slate-500">{templateProductionCapability?.summary || '正在读取模板生产准备度。'}</p>
            </div>
            <div data-testid="template-production-evidence-grid" className="grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
              {productionEvidenceItems.map((item) => (
                <div key={item.key} data-testid={`template-production-evidence-${item.key}`} className="rounded-md border border-slate-200 px-3 py-2 dark:border-slate-800">
                  <p className="text-xs text-slate-500">{item.label}</p>
                  <p className="mt-1 text-lg font-semibold text-slate-900 dark:text-white">{item.value}</p>
                </div>
              ))}
            </div>
            <div data-testid="template-core-coverage" className="grid gap-2 md:grid-cols-5">
              {coreTemplateCoverage.map((item) => (
                <div key={item.docType} data-testid={`template-core-coverage-${item.docType}`} className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2 text-sm dark:bg-slate-900">
                  <span>{item.label}</span>
                  <Badge variant={item.matched ? 'secondary' : 'outline'}>{item.matched ? '已覆盖' : '待补齐'}</Badge>
                </div>
              ))}
            </div>
            {templateProductionCapability?.blockers?.length ? (
              <div className="rounded-md bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
                {templateProductionCapability.blockers[0]}
              </div>
            ) : null}
          </div>
          <div className="space-y-3 rounded-lg border border-slate-200 p-4 dark:border-slate-800">
            <div>
              <p className="font-semibold text-slate-900 dark:text-white">章节与 Skill 编排</p>
              <p className="mt-1 text-sm text-slate-500">
                当前模板：{selectedWorkbenchTemplate?.name || '暂无模板'}。
                先补齐章节，再绑定适配 Skill，保证对话式文档生成可追溯。
              </p>
            </div>
            <Button
              data-testid="template-production-open-workbench"
              className="w-full"
              disabled={!selectedWorkbenchTemplate}
              onClick={() => selectedWorkbenchTemplate && openSectionWorkbench(selectedWorkbenchTemplate)}
            >
              <Settings className="mr-2 h-4 w-4" />
              打开章节工作台
            </Button>
            <Button
              data-testid="template-production-seed-sections"
              variant="outline"
              className="w-full"
              disabled={!selectedWorkbenchTemplate || seedSectionsMutation.isPending}
              onClick={() => selectedWorkbenchTemplate && seedSectionsMutation.mutate(selectedWorkbenchTemplate.id)}
            >
              {seedSectionsMutation.isPending ? <ShieldCheck className="mr-2 h-4 w-4 animate-pulse" /> : <ListTree className="mr-2 h-4 w-4" />}
              {seedSectionsMutation.isPending ? '补齐中...' : '补齐标准章节'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Search and Filters */}
      <Card>
        <CardContent className="py-4">
          <div className="grid gap-3 lg:grid-cols-[1fr_160px_160px_180px]">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
              <Input
                placeholder="搜索模板名称、说明或文档类型..."
                className="pl-10"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
            <Select
              value={filterDocType}
              onValueChange={setFilterDocType}
              className="w-40"
            >
              <SelectOption value="all">全部类型</SelectOption>
              <SelectOption value="urs">URS</SelectOption>
              <SelectOption value="brd">BRD</SelectOption>
              <SelectOption value="prd">PRD</SelectOption>
              <SelectOption value="implementation_plan">实施方案</SelectOption>
              <SelectOption value="acceptance_report">验收报告</SelectOption>
            </Select>
            <Select
              value={filterStatus}
              onValueChange={setFilterStatus}
              className="w-full"
              data-testid="template-status-filter"
            >
              <SelectOption value="all">全部状态</SelectOption>
              <SelectOption value="published">已发布</SelectOption>
              <SelectOption value="draft">草稿</SelectOption>
              <SelectOption value="archived">已归档</SelectOption>
            </Select>
            <Select
              value={filterGovernance}
              onValueChange={setFilterGovernance}
              className="w-full"
              data-testid="template-governance-filter"
            >
              <SelectOption value="all">全部治理级别</SelectOption>
              <SelectOption value="system">系统级</SelectOption>
              <SelectOption value="platform">平台级</SelectOption>
              <SelectOption value="project">项目级</SelectOption>
              <SelectOption value="tenant">租户级</SelectOption>
            </Select>
          </div>
        </CardContent>
      </Card>

      {/* Templates Grid */}
      {isLoading ? (
        <div className="flex items-center justify-center h-64 text-slate-500">
          正在加载模板...
        </div>
      ) : filteredTemplates.length === 0 ? (
        <Card>
          <CardContent className="py-16 text-center text-slate-500">
            <FileText className="mx-auto h-16 w-16 text-slate-300" />
            <p className="mt-4 text-lg font-medium">未找到模板</p>
            <p className="mt-2 text-sm">
              {searchQuery || filterDocType !== 'all'
                ? '请调整搜索条件或筛选项'
                : '创建第一个模板开始使用'}
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredTemplates.map((template) => (
            <Card
              key={template.id}
              className={`hover:shadow-md transition-shadow ${
                selectedWorkbenchTemplate?.id === template.id ? 'border-indigo-500' : ''
              }`}
              data-testid={`template-card-${template.id}`}
            >
              <CardHeader className="pb-2">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2">
                    <FileText className="h-5 w-5 text-indigo-500" />
                    <CardTitle className="text-base">{template.name}</CardTitle>
                  </div>
                  <Badge className={getDocTypeBadgeColor(template.doc_type)}>
                    {getDocTypeLabel(template.doc_type)}
                  </Badge>
                </div>
                {template.description && (
                  <CardDescription className="line-clamp-2 mt-2">
                    {template.description}
                  </CardDescription>
                )}
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-2 text-sm text-slate-500">
                  <span>{template.version_count} 个版本</span>
                  <span>{template.section_count ?? 0} 个章节</span>
                  <span>{template.skill_binding_count ?? 0} 个 Skill</span>
                  <span>{new Date(template.updated_at).toLocaleDateString('zh-CN')}</span>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Badge variant="secondary" className="text-xs">
                    {getGovernanceLabel(getTemplateGovernance(template))}
                  </Badge>
                  <Badge variant="outline" className="text-xs">
                    {getLifecycleStatusLabel(getTemplateLifecycleStatus(template))}
                  </Badge>
                  {template.active_version && (
                    <Badge variant="outline" className="text-xs">当前 v{template.active_version}</Badge>
                  )}
                </div>
                <div className="flex flex-wrap gap-2 mt-4">
                  <Button
                    variant={selectedWorkbenchTemplate?.id === template.id ? 'secondary' : 'outline'}
                    size="sm"
                    onClick={() => setSelectedWorkbenchTemplateId(template.id)}
                  >
                    查看工作台
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="flex-1"
                    onClick={() => {
                      resetUploadForm()
                      setSelectedTemplate(template)
                      setUploadDialogOpen(true)
                    }}
                  >
                    <Upload className="mr-1 h-3 w-3" />
                    上传
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    data-testid={`template-sections-open-${template.id}`}
                    onClick={() => openSectionWorkbench(template)}
                  >
                    <Settings className="mr-1 h-3 w-3" />
                    章节配置
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    aria-label={`查看 ${template.name} 的版本历史`}
                    data-testid={`template-version-history-${template.id}`}
                    onClick={() => {
                      setVersionHistoryTemplate(template)
                      setPreviewDialogOpen(true)
                    }}
                  >
                    <History className="h-3 w-3" />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      if (window.confirm(`确认删除模板“${template.name}”？`)) {
                        deleteTemplateMutation.mutate(template.id)
                      }
                    }}
                    disabled={deleteTemplateMutation.isPending}
                  >
                    <Trash2 className="h-3 w-3 text-red-500" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {selectedWorkbenchTemplate && (
        <Card data-testid="template-workbench">
          <CardHeader>
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <CardTitle>模板治理工作台</CardTitle>
                <CardDescription>
                  {selectedWorkbenchTemplate.name} · {getDocTypeLabel(selectedWorkbenchTemplate.doc_type)}
                </CardDescription>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setVersionHistoryTemplate(selectedWorkbenchTemplate)
                    setPreviewDialogOpen(true)
                  }}
                >
                  <History className="mr-1 h-3 w-3" />
                  版本历史
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => openSectionWorkbench(selectedWorkbenchTemplate)}
                >
                  <Settings className="mr-1 h-3 w-3" />
                  章节配置
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="grid gap-3 md:grid-cols-4">
              <div className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
                <p className="text-xs text-slate-500">治理级别</p>
                <p className="mt-1 text-sm font-semibold text-slate-900 dark:text-white">
                  {getGovernanceLabel(getTemplateGovernance(selectedWorkbenchTemplate))}
                </p>
              </div>
              <div className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
                <p className="text-xs text-slate-500">生命周期</p>
                <p className="mt-1 text-sm font-semibold text-slate-900 dark:text-white">
                  {getLifecycleStatusLabel(getTemplateLifecycleStatus(selectedWorkbenchTemplate))}
                </p>
              </div>
              <div className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
                <p className="text-xs text-slate-500">当前版本</p>
                <p className="mt-1 text-sm font-semibold text-slate-900 dark:text-white">
                  v{selectedWorkbenchTemplate.active_version || selectedWorkbenchTemplate.version_count || 1}
                </p>
              </div>
              <div className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
                <p className="text-xs text-slate-500">章节/Skill</p>
                <p className="mt-1 text-sm font-semibold text-slate-900 dark:text-white">
                  {selectedWorkbenchTemplate.section_count ?? workbenchSections.length} 章 · {selectedWorkbenchTemplate.skill_binding_count ?? 0} Skill
                </p>
              </div>
            </div>

            <section>
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold text-slate-900 dark:text-white">章节交付物定义</h2>
                  <p className="mt-1 text-xs text-slate-500">
                    每个章节明确输入、提示词、质量规则和可调用 Skill。
                  </p>
                </div>
                <Badge variant="outline">{workbenchSections.length} 个章节</Badge>
              </div>
              {workbenchSections.length === 0 ? (
                <div className="rounded-md border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-slate-700">
                  当前模板还没有章节定义，可进入章节配置生成标准章节。
                </div>
              ) : (
                <div className="grid gap-3 lg:grid-cols-2">
                  {workbenchSections.slice(0, 6).map((section) => (
                    <div key={section.id} className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="text-sm font-semibold text-slate-900 dark:text-white">{section.title}</p>
                          <p className="mt-1 text-xs text-slate-500">{section.section_key}</p>
                        </div>
                        <Badge variant="outline" className="text-xs">L{section.level}</Badge>
                      </div>
                      <p className="mt-2 line-clamp-2 text-sm text-slate-600 dark:text-slate-300">
                        {section.content_requirement || '未配置内容要求'}
                      </p>
                      <div className="mt-3 flex flex-wrap gap-1">
                        {section.skill_bindings.length === 0 ? (
                          <Badge variant="secondary" className="text-xs">未绑定 Skill</Badge>
                        ) : (
                          section.skill_bindings.map((binding) => (
                            <Badge key={binding.id} variant="secondary" className="text-xs">
                              {binding.skill?.effective_display_name || binding.skill?.display_name || binding.skill?.name || binding.skill_id}
                            </Badge>
                          ))
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </CardContent>
        </Card>
      )}

      {/* Structured Sections Dialog */}
      <Dialog
        open={sectionDialogOpen}
        onOpenChange={(open) => {
          setSectionDialogOpen(open)
          if (!open) {
            setSectionTemplate(null)
            setSelectedSectionId(null)
            setSelectedSkillIds([])
          }
        }}
      >
        <DialogContent className="max-w-5xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>章节配置 - {sectionTemplate?.name}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-5 lg:grid-cols-[1fr_1.25fr] py-4">
            <section className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold text-slate-900 dark:text-white">章节结构</h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400">按模板版本维护目录、要求和提示词</p>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  data-testid="template-sections-seed"
                  onClick={() => sectionTemplate && seedSectionsMutation.mutate(sectionTemplate.id)}
                  disabled={!sectionTemplate || seedSectionsMutation.isPending}
                >
                  <ListTree className="mr-1 h-3 w-3" />
                  生成标准章节
                </Button>
              </div>

              <div className="space-y-2 rounded-md border border-slate-200 p-3 dark:border-slate-700">
                {sectionsLoading ? (
                  <p className="text-sm text-slate-500">正在加载章节...</p>
                ) : sortedSections.length === 0 ? (
                  <p className="text-sm text-slate-500">暂无章节，请先生成标准章节或手动新增。</p>
                ) : (
                  sortedSections.map((section) => (
                    <button
                      key={section.id}
                      type="button"
                      data-testid={`template-section-select-${section.id}`}
                      className={`w-full rounded-md border px-3 py-2 text-left text-sm transition-colors ${
                        selectedSection?.id === section.id
                          ? 'border-indigo-500 bg-indigo-50 text-indigo-900 dark:border-indigo-400 dark:bg-indigo-950 dark:text-indigo-100'
                          : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800'
                      }`}
                      onClick={() => setSelectedSectionId(section.id)}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium">{section.title}</span>
                        <Badge variant="outline" className="text-xs">
                          L{section.level}
                        </Badge>
                      </div>
                      <p className="mt-1 truncate text-xs text-slate-500 dark:text-slate-400">{section.section_key}</p>
                    </button>
                  ))
                )}
              </div>

              <div className="space-y-3 rounded-md border border-slate-200 p-3 dark:border-slate-700">
                <h4 className="text-sm font-semibold text-slate-900 dark:text-white">新增章节</h4>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-1">
                    <Label htmlFor="template-section-title">章节标题</Label>
                    <Input
                      id="template-section-title"
                      data-testid="template-section-title"
                      value={sectionForm.title}
                      onChange={(event) => setSectionForm({ ...sectionForm, title: event.target.value })}
                      placeholder="例如：验收标准"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="template-section-key">章节键</Label>
                    <Input
                      id="template-section-key"
                      data-testid="template-section-key"
                      value={sectionForm.section_key}
                      onChange={(event) => setSectionForm({ ...sectionForm, section_key: event.target.value })}
                      placeholder="urs.acceptance"
                    />
                  </div>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="template-section-requirement">内容要求</Label>
                  <textarea
                    id="template-section-requirement"
                    data-testid="template-section-requirement"
                    className="min-h-20 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                    value={sectionForm.content_requirement}
                    onChange={(event) => setSectionForm({ ...sectionForm, content_requirement: event.target.value })}
                    placeholder="说明该章节必须覆盖的业务内容"
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="template-section-prompt">默认提示词</Label>
                  <textarea
                    id="template-section-prompt"
                    data-testid="template-section-prompt"
                    className="min-h-20 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                    value={sectionForm.prompt}
                    onChange={(event) => setSectionForm({ ...sectionForm, prompt: event.target.value })}
                    placeholder="用于指导 Agent 生成或评审该章节"
                  />
                </div>
                <Button
                  data-testid="template-section-create"
                  onClick={() => sectionTemplate && createSectionMutation.mutate(sectionTemplate.id)}
                  disabled={!sectionTemplate || !sectionForm.title.trim() || !sectionForm.section_key.trim() || createSectionMutation.isPending}
                >
                  <Plus className="mr-2 h-4 w-4" />
                  添加章节
                </Button>
              </div>
            </section>

            <section className="space-y-4">
              <div className="rounded-md border border-slate-200 p-4 dark:border-slate-700">
                {selectedSection ? (
                  <div className="space-y-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <h3 className="text-base font-semibold text-slate-900 dark:text-white">{selectedSection.title}</h3>
                        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{selectedSection.section_key}</p>
                      </div>
                      <Badge className={getDocTypeBadgeColor(sectionTemplate?.doc_type || 'custom')}>
                        {sectionTemplate?.doc_type?.toUpperCase() || 'TEMPLATE'}
                      </Badge>
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div>
                        <p className="text-xs font-medium text-slate-500 dark:text-slate-400">内容要求</p>
                        <p className="mt-1 text-sm text-slate-700 dark:text-slate-200">{selectedSection.content_requirement || '未配置'}</p>
                      </div>
                      <div>
                        <p className="text-xs font-medium text-slate-500 dark:text-slate-400">必需输入</p>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {selectedSection.required_inputs.length > 0 ? (
                            selectedSection.required_inputs.map((input) => (
                              <Badge key={input} variant="secondary" className="text-xs">{input}</Badge>
                            ))
                          ) : (
                            <span className="text-sm text-slate-500">未配置</span>
                          )}
                        </div>
                      </div>
                    </div>
                    <div>
                      <p className="text-xs font-medium text-slate-500 dark:text-slate-400">默认提示词</p>
                      <p className="mt-1 rounded-md bg-slate-50 p-3 text-sm text-slate-700 dark:bg-slate-900 dark:text-slate-200">
                        {selectedSection.prompt || '未配置'}
                      </p>
                    </div>
                  </div>
                ) : (
                  <p className="text-sm text-slate-500">选择一个章节后配置 Skill。</p>
                )}
              </div>

              <div className="rounded-md border border-slate-200 p-4 dark:border-slate-700">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-900 dark:text-white">章节 Skill 绑定</h3>
                    <p className="text-xs text-slate-500 dark:text-slate-400">选择生成、澄清、评审或质量检查 Skill</p>
                  </div>
                  <Button
                    size="sm"
                    data-testid="template-section-save-skills"
                    onClick={() => selectedSection && replaceSectionSkillsMutation.mutate({ sectionId: selectedSection.id, skillIds: selectedSkillIds })}
                    disabled={!selectedSection || replaceSectionSkillsMutation.isPending}
                  >
                    <Save className="mr-1 h-3 w-3" />
                    保存绑定
                  </Button>
                </div>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  {skillCatalog.length === 0 ? (
                    <p className="text-sm text-slate-500">暂无可绑定 Skill。</p>
                  ) : (
                    skillCatalog.map((skill) => (
                      <label
                        key={skill.id}
                        className="flex min-h-20 items-start gap-3 rounded-md border border-slate-200 p-3 text-sm dark:border-slate-700"
                      >
                        <input
                          type="checkbox"
                          data-testid={`template-section-skill-${skill.id}`}
                          className="mt-1 h-4 w-4 rounded border-slate-300 text-indigo-600"
                          checked={selectedSkillIds.includes(skill.id)}
                          onChange={(event) => toggleSkillSelection(skill.id, event.target.checked)}
                        />
                        <span>
                          <span className="block font-medium text-slate-900 dark:text-white">{skill.name}</span>
                          <span className="mt-1 block text-xs text-slate-500 dark:text-slate-400">{skill.description || skill.category}</span>
                        </span>
                      </label>
                    ))
                  )}
                </div>
              </div>
            </section>
          </div>
        </DialogContent>
      </Dialog>

      {/* Version History Dialog */}
      <Dialog open={previewDialogOpen} onOpenChange={setPreviewDialogOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>版本历史 - {versionHistoryTemplate?.name}</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            {versionHistoryData && versionHistoryData.length > 0 ? (
              <div className="space-y-3">
                {versionHistoryData.map((version) => {
                  const active = isActiveVersion(version)

                  return (
                  <div
                    key={version.id}
                    data-testid={`template-version-${version.id}`}
                    className="flex items-start gap-4 p-4 rounded-lg border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800"
                  >
                    <div className="flex-shrink-0 w-10 h-10 rounded-full bg-indigo-100 dark:bg-indigo-900 flex items-center justify-center">
                      <span className="text-sm font-semibold text-indigo-600 dark:text-indigo-400">
                        v{version.version}
                      </span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="font-medium text-slate-900 dark:text-white">
                          版本 {version.version}
                        </p>
                        {active && (
                          <Badge variant="secondary" className="text-xs">当前</Badge>
                        )}
                      </div>
                      <p className="text-sm text-slate-500 mt-1">
                        {new Date(version.created_at).toLocaleString('zh-CN')}
                      </p>
                      {version.placeholder_schema && version.placeholder_schema.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1">
                          {version.placeholder_schema.slice(0, 5).map((p, pIdx) => (
                            <Badge key={pIdx} variant="outline" className="text-xs font-mono">
                              {'{{'}{p.name}{'}}'}
                            </Badge>
                          ))}
                          {version.placeholder_schema.length > 5 && (
                            <Badge variant="outline" className="text-xs">
                              +{version.placeholder_schema.length - 5} 个更多
                            </Badge>
                          )}
                        </div>
                      )}
                    </div>
                    <div className="flex-shrink-0">
                      <Button
                        variant={active ? 'secondary' : 'outline'}
                        size="sm"
                        disabled={active || activateVersionMutation.isPending}
                        data-testid={`activate-template-version-${version.id}`}
                        onClick={() => {
                          if (!versionHistoryTemplate) return
                          activateVersionMutation.mutate({
                            templateId: versionHistoryTemplate.id,
                            versionId: version.id,
                          })
                        }}
                      >
                        <CheckCircle className="mr-1 h-3 w-3" />
                        {active ? '当前版本' : '设为当前'}
                      </Button>
                    </div>
                  </div>
                  )
                })}
              </div>
            ) : (
              <div className="text-center py-8 text-slate-500">
                <AlertCircle className="mx-auto h-10 w-10 text-slate-300" />
                <p className="mt-2">暂无版本历史</p>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
