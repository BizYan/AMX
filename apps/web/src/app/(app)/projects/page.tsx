'use client'

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import {
  Archive,
  CheckCircle2,
  Clock,
  FileText,
  FolderKanban,
  MoreVertical,
  Network,
  Plus,
  RotateCcw,
  Settings,
  Trash2,
  Upload,
  Users,
} from 'lucide-react'

import {
  identityApi,
  Project,
  ProjectLaunchBlueprint,
  ProjectLaunchPayload,
  projectsApi,
} from '@/lib/api-client'
import { formatDistanceToNow } from '@/lib/utils'
import { useToast } from '@/components/ui/toast'
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const DOCUMENT_LABELS: Record<string, string> = {
  urs: '用户需求规格说明书',
  brd: '业务需求文档',
  prd: '产品需求文档',
  detailed_design: '详细设计说明',
  interface: '接口说明',
  data_dictionary: '数据字典',
  test_case: '测试用例',
}

const WORKFLOW_LABELS: Record<string, string> = {
  'brd-document-generation': 'BRD 对话式生成',
  'document-quality-assessment': '文档质量评审',
  'human-approval-delivery-pipeline': '人工审批交付',
  'change-impact-governance': '变更影响治理',
  'parallel-quality-review': '并行质量评审',
}

function getProjectDate(project: Project, key: 'created' | 'updated') {
  return key === 'created'
    ? project.createdAt || project.created_at || new Date().toISOString()
    : project.updatedAt || project.updated_at || project.createdAt || project.created_at || new Date().toISOString()
}

function getProjectDocumentCount(project: Project) {
  return project.documentCount ?? project.document_count ?? 0
}

function toggleValue(values: string[], value: string) {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value]
}

export default function ProjectsPage() {
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [projectView, setProjectView] = useState<'active' | 'archived'>('active')
  const [step, setStep] = useState(1)
  const [launchData, setLaunchData] = useState<ProjectLaunchPayload>({
    blueprint_key: '',
    name: '',
    description: '',
    member_ids: [],
    document_types: [],
    workflow_template_ids: [],
  })
  const queryClient = useQueryClient()
  const { addToast } = useToast()

  const { data, isLoading, error } = useQuery({
    queryKey: ['projects', projectView],
    queryFn: () => projectsApi.list({ status: projectView }),
  })
  const { data: blueprints = [] } = useQuery({
    queryKey: ['project-launch-blueprints'],
    queryFn: projectsApi.listLaunchBlueprints,
    enabled: isCreateOpen,
  })
  const { data: users } = useQuery({
    queryKey: ['tenant-users', 'project-launch'],
    queryFn: () => identityApi.listUsers({ pageSize: 100 }),
    enabled: isCreateOpen,
  })

  const selectedBlueprint = blueprints.find((item) => item.key === launchData.blueprint_key)

  const launchMutation = useMutation({
    mutationFn: (payload: ProjectLaunchPayload) => projectsApi.launch(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      setIsCreateOpen(false)
      setStep(1)
      setLaunchData({
        blueprint_key: '',
        name: '',
        description: '',
        member_ids: [],
        document_types: [],
        workflow_template_ids: [],
      })
      addToast({ title: '项目已启动', description: '交付文档、工作流和协作配置已初始化。' })
    },
    onError: (mutationError: Error) => {
      addToast({ title: '项目启动失败', description: mutationError.message, variant: 'destructive' })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => projectsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      addToast({ title: '项目已删除' })
    },
    onError: (mutationError: Error) => {
      addToast({ title: '删除项目失败', description: mutationError.message, variant: 'destructive' })
    },
  })
  const archiveMutation = useMutation({
    mutationFn: (id: string) => projectsApi.archive(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      addToast({ title: '项目已归档' })
    },
    onError: (mutationError: Error) => {
      addToast({ title: '归档项目失败', description: mutationError.message, variant: 'destructive' })
    },
  })
  const restoreMutation = useMutation({
    mutationFn: (id: string) => projectsApi.restore(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      addToast({ title: '项目已恢复', description: '项目已返回活跃工作区。' })
    },
    onError: (mutationError: Error) => {
      addToast({ title: '恢复项目失败', description: mutationError.message, variant: 'destructive' })
    },
  })

  const selectBlueprint = (blueprint: ProjectLaunchBlueprint) => {
    setLaunchData((current) => ({
      ...current,
      blueprint_key: blueprint.key,
      document_types: [...blueprint.document_types],
      workflow_template_ids: [...blueprint.workflow_template_ids],
    }))
  }

  const canContinue =
    (step === 1 && Boolean(selectedBlueprint)) ||
    (step === 2 && Boolean(launchData.name.trim())) ||
    (step === 3 && launchData.document_types.length > 0)

  const submitLaunch = () => {
    const name = launchData.name.trim()
    launchMutation.mutate({
      ...launchData,
      name,
      description: launchData.description?.trim(),
    })
  }

  if (isLoading) {
    return <div className="flex h-64 items-center justify-center text-slate-500">正在加载项目...</div>
  }
  if (error) {
    return <div className="flex h-64 items-center justify-center text-red-500">项目加载失败</div>
  }

  const projects = data?.items || []

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">项目文档</h1>
          <p className="mt-1 text-sm text-slate-500">按交付蓝图启动项目，管理资料、知识、文档和追溯关系</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" asChild>
            <Link href="/knowledge/graph">
              <Network className="mr-2 h-4 w-4" />
              知识总览
            </Link>
          </Button>
          <Button data-testid="open-project-launch" onClick={() => setIsCreateOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            启动项目
          </Button>
        </div>
      </div>

      <div className="flex w-fit rounded-md border border-slate-200 p-1 dark:border-slate-700" aria-label="项目生命周期视图">
        <Button
          data-testid="project-view-active"
          variant={projectView === 'active' ? 'secondary' : 'ghost'}
          size="sm"
          onClick={() => setProjectView('active')}
        >
          活跃项目
        </Button>
        <Button
          data-testid="project-view-archived"
          variant={projectView === 'archived' ? 'secondary' : 'ghost'}
          size="sm"
          onClick={() => setProjectView('archived')}
        >
          已归档
        </Button>
      </div>

      {projects.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <FolderKanban className="h-12 w-12 text-slate-300" />
            <h3 className="mt-4 text-lg font-medium">{projectView === 'archived' ? '暂无已归档项目' : '暂无项目'}</h3>
            <p className="mt-2 text-sm text-slate-500">
              {projectView === 'archived' ? '归档项目会保留交付证据，并可随时恢复。' : '选择交付蓝图启动第一个项目'}
            </p>
            {projectView === 'active' && (
              <Button className="mt-4" onClick={() => setIsCreateOpen(true)}>
                <Plus className="mr-2 h-4 w-4" />
                启动项目
              </Button>
            )}
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {projects.map((project) => (
            <Card key={project.id} className="transition-shadow hover:shadow-md" data-testid={`project-card-${project.id}`}>
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="rounded-md bg-indigo-100 p-2 dark:bg-indigo-900">
                      <FolderKanban className="h-5 w-5 text-indigo-600 dark:text-indigo-400" />
                    </div>
                    <div>
                      <CardTitle className="text-base">
                        <Link href={`/projects/${project.id}`} className="hover:text-indigo-600">
                          {project.name}
                        </Link>
                      </CardTitle>
                      <CardDescription className="mt-1 text-xs">
                        更新于 {formatDistanceToNow(getProjectDate(project, 'updated'))}
                      </CardDescription>
                      {project.status === 'archived' && <Badge className="mt-2" variant="secondary">已归档</Badge>}
                    </div>
                  </div>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 w-8 p-0"
                        data-testid={`project-actions-${project.id}`}
                      >
                        <span className="sr-only">打开项目操作菜单</span>
                        <MoreVertical className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem asChild><Link href={`/projects/${project.id}`}><FolderKanban className="mr-2 h-4 w-4" />打开项目</Link></DropdownMenuItem>
                      <DropdownMenuItem asChild><Link href={`/projects/${project.id}/documents`}><FileText className="mr-2 h-4 w-4" />项目文档</Link></DropdownMenuItem>
                      <DropdownMenuItem asChild><Link href={`/projects/${project.id}/files`}><Upload className="mr-2 h-4 w-4" />项目资料</Link></DropdownMenuItem>
                      <DropdownMenuItem asChild><Link href={`/projects/${project.id}/knowledge`}><Network className="mr-2 h-4 w-4" />项目知识</Link></DropdownMenuItem>
                      <DropdownMenuItem asChild><Link href={`/projects/${project.id}/settings`}><Settings className="mr-2 h-4 w-4" />项目设置</Link></DropdownMenuItem>
                      <DropdownMenuItem asChild><Link href={`/projects/${project.id}/members`}><Users className="mr-2 h-4 w-4" />项目成员</Link></DropdownMenuItem>
                      {project.status === 'archived' ? (
                        <DropdownMenuItem
                          data-testid={`project-restore-${project.id}`}
                          disabled={restoreMutation.isPending}
                          onClick={() => restoreMutation.mutate(project.id)}
                        >
                          <RotateCcw className="mr-2 h-4 w-4" />恢复项目
                        </DropdownMenuItem>
                      ) : (
                        <DropdownMenuItem
                          data-testid={`project-archive-${project.id}`}
                          disabled={archiveMutation.isPending}
                          onClick={() => archiveMutation.mutate(project.id)}
                        >
                          <Archive className="mr-2 h-4 w-4" />归档项目
                        </DropdownMenuItem>
                      )}
                      <DropdownMenuItem
                        className="text-red-600"
                        disabled={deleteMutation.isPending}
                        data-testid={`project-delete-${project.id}`}
                        onClick={() => window.confirm(`确认删除项目“${project.name}”？`) && deleteMutation.mutate(project.id)}
                      >
                        <Trash2 className="mr-2 h-4 w-4" />删除项目
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              </CardHeader>
              <CardContent>
                <p className="line-clamp-2 text-sm text-slate-600 dark:text-slate-400">{project.description || '暂无描述'}</p>
                <div className="mt-4 flex items-center gap-4 border-t pt-4">
                  <Badge variant="secondary">{getProjectDocumentCount(project)} 个文档</Badge>
                  <div className="flex items-center gap-1 text-xs text-slate-500">
                    <Clock className="h-3 w-3" />
                    {formatDistanceToNow(getProjectDate(project, 'created'))}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
        <DialogContent className="max-w-3xl" data-testid="project-launch-wizard">
          <DialogHeader>
            <DialogTitle>项目启动与交付蓝图</DialogTitle>
            <DialogDescription>一次配置交付文档、推荐工作流和协作成员，系统将生成可重试的启动计划。</DialogDescription>
          </DialogHeader>

          <div className="flex gap-2 border-b pb-3">
            {['选择蓝图', '项目信息', '配置资产', '确认启动'].map((label, index) => (
              <div key={label} className={`flex-1 text-xs ${step === index + 1 ? 'font-semibold text-indigo-600' : 'text-slate-500'}`}>
                {index + 1}. {label}
              </div>
            ))}
          </div>

          <div className="max-h-[58vh] min-h-80 overflow-y-auto py-2">
            {step === 1 && (
              <div className="grid gap-3 md:grid-cols-3">
                {blueprints.map((blueprint) => (
                  <button
                    key={blueprint.key}
                    type="button"
                    data-testid={`launch-blueprint-${blueprint.key}`}
                    onClick={() => selectBlueprint(blueprint)}
                    className={`rounded-md border p-4 text-left transition-colors ${
                      launchData.blueprint_key === blueprint.key
                        ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-950'
                        : 'border-slate-200 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-900'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <h3 className="font-semibold">{blueprint.name}</h3>
                      {launchData.blueprint_key === blueprint.key && <CheckCircle2 className="h-4 w-4 text-indigo-600" />}
                    </div>
                    <p className="mt-2 text-xs text-slate-500">{blueprint.description}</p>
                    <div className="mt-3 flex flex-wrap gap-1">
                      {blueprint.scenarios.map((scenario) => <Badge key={scenario} variant="outline">{scenario}</Badge>)}
                    </div>
                  </button>
                ))}
              </div>
            )}

            {step === 2 && (
              <div className="space-y-5">
                <div className="space-y-2">
                  <Label htmlFor="launch-project-name">项目名称</Label>
                  <Input
                    id="launch-project-name"
                    data-testid="launch-project-name"
                    value={launchData.name}
                    onChange={(event) => setLaunchData({ ...launchData, name: event.target.value })}
                    placeholder="例如：会员平台升级"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="launch-project-description">项目目标与范围</Label>
                  <Input
                    id="launch-project-description"
                    data-testid="launch-project-description"
                    value={launchData.description}
                    onChange={(event) => setLaunchData({ ...launchData, description: event.target.value })}
                    placeholder="描述业务目标、交付范围和关键约束"
                  />
                </div>
              </div>
            )}

            {step === 3 && (
              <div className="grid gap-5 lg:grid-cols-3">
                <section data-testid="launch-document-options">
                  <h3 className="text-sm font-semibold">初始交付文档</h3>
                  <div className="mt-3 space-y-2">
                    {selectedBlueprint?.document_types.map((docType) => (
                      <label key={docType} className="flex cursor-pointer items-center gap-2 rounded-md border p-2 text-sm">
                        <input
                          type="checkbox"
                          checked={launchData.document_types.includes(docType)}
                          onChange={() => setLaunchData({ ...launchData, document_types: toggleValue(launchData.document_types, docType) })}
                        />
                        {DOCUMENT_LABELS[docType] || docType}
                      </label>
                    ))}
                  </div>
                </section>
                <section>
                  <h3 className="text-sm font-semibold">推荐工作流</h3>
                  <div className="mt-3 space-y-2">
                    {selectedBlueprint?.workflow_template_ids.map((workflowId) => (
                      <label key={workflowId} className="flex cursor-pointer items-center gap-2 rounded-md border p-2 text-sm">
                        <input
                          type="checkbox"
                          checked={launchData.workflow_template_ids.includes(workflowId)}
                          onChange={() => setLaunchData({ ...launchData, workflow_template_ids: toggleValue(launchData.workflow_template_ids, workflowId) })}
                        />
                        {WORKFLOW_LABELS[workflowId] || workflowId}
                      </label>
                    ))}
                  </div>
                </section>
                <section>
                  <h3 className="text-sm font-semibold">协作成员</h3>
                  <div className="mt-3 space-y-2">
                    {(users?.items || []).filter((user) => user.is_active !== false).map((user) => (
                      <label
                        key={user.id}
                        data-testid={`launch-member-${user.id}`}
                        className="flex cursor-pointer items-center gap-2 rounded-md border p-2 text-sm"
                      >
                        <input
                          type="checkbox"
                          checked={launchData.member_ids.includes(user.id)}
                          onChange={() => setLaunchData({ ...launchData, member_ids: toggleValue(launchData.member_ids, user.id) })}
                        />
                        {user.full_name || user.email}
                      </label>
                    ))}
                  </div>
                </section>
              </div>
            )}

            {step === 4 && selectedBlueprint && (
              <div className="space-y-4" data-testid="launch-summary">
                <div>
                  <p className="text-xs text-slate-500">交付蓝图</p>
                  <h3 className="text-lg font-semibold">{selectedBlueprint.name}</h3>
                  <p className="mt-1 text-sm text-slate-500">{selectedBlueprint.description}</p>
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-md border p-3"><p className="text-2xl font-semibold">{launchData.document_types.length}</p><p className="text-xs text-slate-500">初始文档</p></div>
                  <div className="rounded-md border p-3"><p className="text-2xl font-semibold">{launchData.workflow_template_ids.length}</p><p className="text-xs text-slate-500">推荐工作流</p></div>
                  <div className="rounded-md border p-3"><p className="text-2xl font-semibold">{launchData.member_ids.length}</p><p className="text-xs text-slate-500">协作成员</p></div>
                </div>
                <div className="rounded-md border border-indigo-200 bg-indigo-50 p-4 text-sm text-indigo-900 dark:border-indigo-900 dark:bg-indigo-950 dark:text-indigo-100">
                  启动后将创建草稿文档、初始化工作流和项目设置。所有步骤都有执行证据，失败后可在项目页重试补齐。
                </div>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => step === 1 ? setIsCreateOpen(false) : setStep(step - 1)}>
              {step === 1 ? '取消' : '上一步'}
            </Button>
            {step < 4 ? (
              <Button data-testid="launch-next" disabled={!canContinue} onClick={() => setStep(step + 1)}>下一步</Button>
            ) : (
              <Button data-testid="submit-project-launch" disabled={launchMutation.isPending} onClick={submitLaunch}>
                {launchMutation.isPending ? '正在启动...' : '确认启动'}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
