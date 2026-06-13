'use client'

import { use, useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import {
  projectsApi,
  type ProjectDocumentLifecyclePolicy,
  type ProjectDocumentLifecyclePolicyUpdate,
} from '@/lib/api-client'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/components/ui/toast'
import { ArrowLeft, GitBranch, Loader2, Save, ShieldCheck } from 'lucide-react'

interface ProjectSettingsPageProps {
  params: Promise<{ projectId: string }>
}

const STATUS_CATALOG = [
  { key: 'draft', label: '草稿' },
  { key: 'writing', label: '编写中' },
  { key: 'pending_review', label: '待评审' },
  { key: 'review', label: '评审' },
  { key: 'in_review', label: '评审中' },
  { key: 'revision_required', label: '待修订' },
  { key: 'approved', label: '已批准' },
  { key: 'published', label: '已发布' },
  { key: 'archived', label: '已归档' },
]

const clonePolicy = (policy: ProjectDocumentLifecyclePolicy): ProjectDocumentLifecyclePolicy =>
  JSON.parse(JSON.stringify(policy))

export default function ProjectSettingsPage({ params }: ProjectSettingsPageProps) {
  const { projectId } = use(params)
  const router = useRouter()
  const queryClient = useQueryClient()
  const { addToast } = useToast()
  const [form, setForm] = useState({ name: '', description: '' })
  const [lifecycleForm, setLifecycleForm] = useState<ProjectDocumentLifecyclePolicy | null>(null)

  const { data: project, isLoading } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => projectsApi.get(projectId),
  })
  const lifecycleQuery = useQuery({
    queryKey: ['project-document-lifecycle-policy', projectId],
    queryFn: () => projectsApi.getDocumentLifecyclePolicy(projectId),
  })

  useEffect(() => {
    if (project) {
      setForm({
        name: project.name || '',
        description: project.description || '',
      })
    }
  }, [project])

  useEffect(() => {
    if (lifecycleQuery.data) setLifecycleForm(clonePolicy(lifecycleQuery.data))
  }, [lifecycleQuery.data])

  const updateMutation = useMutation({
    mutationFn: () =>
      projectsApi.update(projectId, {
        name: form.name.trim(),
        description: form.description.trim(),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project', projectId] })
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      addToast({ title: '项目设置已保存' })
    },
    onError: (error: Error) => {
      addToast({ title: '保存失败', description: error.message, variant: 'destructive' })
    },
  })

  const policyIssues = useMemo(() => {
    if (!lifecycleForm) return []
    const enabled = new Set(lifecycleForm.statuses.map((status) => status.key))
    const inbound = new Set(lifecycleForm.transitions.map((transition) => transition.to_status))
    const outbound = new Set(lifecycleForm.transitions.map((transition) => transition.from_status))
    const issues: string[] = []
    lifecycleForm.statuses.forEach((status) => {
      if (status.key !== 'draft' && !inbound.has(status.key)) {
        issues.push(`“${status.label}”没有入口流转`)
      }
      if (!status.label.trim()) issues.push(`状态 ${status.key} 缺少显示名称`)
      if (status.key !== 'archived' && !outbound.has(status.key)) {
        issues.push(`“${status.label}”没有出口流转`)
      }
    })
    lifecycleForm.transitions.forEach((transition) => {
      if (!enabled.has(transition.from_status) || !enabled.has(transition.to_status)) {
        issues.push('流转矩阵包含未启用状态')
      }
    })
    if (
      lifecycleForm.publish_gates.require_approved &&
      lifecycleForm.transitions.some(
        (transition) => transition.to_status === 'published' && transition.from_status !== 'approved'
      )
    ) {
      issues.push('启用批准门禁时，只能从“已批准”流转到“已发布”')
    }
    return [...new Set(issues)]
  }, [lifecycleForm])

  const lifecycleMutation = useMutation({
    mutationFn: () => {
      if (!lifecycleForm) throw new Error('生命周期策略尚未加载')
      const payload: ProjectDocumentLifecyclePolicyUpdate = {
        statuses: lifecycleForm.statuses,
        transitions: lifecycleForm.transitions,
        require_reason_for: lifecycleForm.require_reason_for,
        publish_gates: lifecycleForm.publish_gates,
      }
      return projectsApi.updateDocumentLifecyclePolicy(projectId, payload)
    },
    onSuccess: (policy) => {
      setLifecycleForm(clonePolicy(policy))
      queryClient.setQueryData(['project-document-lifecycle-policy', projectId], policy)
      queryClient.invalidateQueries({ queryKey: ['document-status-capabilities'] })
      addToast({ title: '生命周期策略已保存', description: `当前生效修订：${policy.revision}` })
    },
    onError: (error: Error) => {
      addToast({ title: '生命周期策略保存失败', description: error.message, variant: 'destructive' })
    },
  })

  const setStatusEnabled = (key: string, enabled: boolean) => {
    if (!lifecycleForm || key === 'draft') return
    setLifecycleForm((current) => {
      if (!current) return current
      if (enabled) {
        const catalog = STATUS_CATALOG.find((status) => status.key === key)
        if (!catalog || current.statuses.some((status) => status.key === key)) return current
        return { ...current, statuses: [...current.statuses, catalog] }
      }
      return {
        ...current,
        statuses: current.statuses.filter((status) => status.key !== key),
        transitions: current.transitions.filter(
          (transition) => transition.from_status !== key && transition.to_status !== key
        ),
        require_reason_for: current.require_reason_for.filter((status) => status !== key),
      }
    })
  }

  const setStatusLabel = (key: string, label: string) => {
    setLifecycleForm((current) =>
      current
        ? {
            ...current,
            statuses: current.statuses.map((status) => (status.key === key ? { ...status, label } : status)),
          }
        : current
    )
  }

  const setReasonRequired = (key: string, required: boolean) => {
    setLifecycleForm((current) => {
      if (!current) return current
      const next = new Set(current.require_reason_for)
      if (required) next.add(key)
      else next.delete(key)
      return { ...current, require_reason_for: [...next] }
    })
  }

  const hasTransition = (fromStatus: string, toStatus: string) =>
    lifecycleForm?.transitions.some(
      (transition) => transition.from_status === fromStatus && transition.to_status === toStatus
    ) === true

  const setTransition = (fromStatus: string, toStatus: string, enabled: boolean) => {
    setLifecycleForm((current) => {
      if (!current) return current
      const transitions = current.transitions.filter(
        (transition) => !(transition.from_status === fromStatus && transition.to_status === toStatus)
      )
      if (enabled) transitions.push({ from_status: fromStatus, to_status: toStatus })
      return { ...current, transitions }
    })
  }

  const setPublishGate = (
    key: keyof ProjectDocumentLifecyclePolicy['publish_gates'],
    enabled: boolean
  ) => {
    setLifecycleForm((current) => {
      if (!current) return current
      let transitions = current.transitions
      if (key === 'require_approved' && enabled) {
        transitions = transitions.filter(
          (transition) => transition.to_status !== 'published' || transition.from_status === 'approved'
        )
      }
      return {
        ...current,
        transitions,
        publish_gates: { ...current.publish_gates, [key]: enabled },
      }
    })
  }

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="text-slate-500 dark:text-slate-400">正在加载项目设置...</div>
      </div>
    )
  }

  if (!project) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-4">
        <div className="text-red-500">未找到项目</div>
        <Button variant="outline" onClick={() => router.push('/projects')}>
          <ArrowLeft className="mr-2 h-4 w-4" />
          返回项目
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-4">
        <Button variant="ghost" size="sm" onClick={() => router.push(`/projects/${projectId}`)} aria-label="返回项目">
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">项目设置</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">维护项目基础信息与文档交付治理流程</p>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>基础信息</CardTitle>
          <CardDescription>项目名称和描述会显示在项目列表、概览和面包屑中。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="project-name">项目名称</Label>
            <Input
              id="project-name"
              value={form.name}
              onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
              placeholder="输入项目名称"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="project-description">项目描述</Label>
            <textarea
              id="project-description"
              className="min-h-[120px] w-full resize-none rounded-md border border-slate-200 bg-white p-3 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 dark:placeholder:text-slate-500"
              value={form.description}
              onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
              placeholder="输入项目描述"
            />
          </div>
          <div className="flex justify-end gap-3">
            <Button variant="outline" onClick={() => router.push(`/projects/${projectId}`)}>取消</Button>
            <Button onClick={() => updateMutation.mutate()} disabled={!form.name.trim() || updateMutation.isPending}>
              {updateMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
              保存基础信息
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card data-testid="project-lifecycle-policy-panel">
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2">
                <GitBranch className="h-5 w-5" />
                文档生命周期
              </CardTitle>
              <CardDescription className="mt-2">
                配置本项目实际生效的状态、流转和发布门禁。批准、发布和归档权限仍由平台统一控制。
              </CardDescription>
            </div>
            <Badge variant="outline">策略修订 {lifecycleForm?.revision ?? '-'}</Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-7">
          {lifecycleQuery.isLoading || !lifecycleForm ? (
            <div className="flex items-center justify-center py-12 text-sm text-slate-500">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              正在加载生命周期策略...
            </div>
          ) : (
            <>
              <section className="space-y-3">
                <div>
                  <h2 className="font-semibold text-slate-900 dark:text-white">状态目录</h2>
                  <p className="mt-1 text-sm text-slate-500">启用项目所需状态，并设置面向项目成员的中文名称。</p>
                </div>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {STATUS_CATALOG.map((catalog) => {
                    const status = lifecycleForm.statuses.find((item) => item.key === catalog.key)
                    const enabled = Boolean(status)
                    return (
                      <div key={catalog.key} className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
                        <div className="flex items-center justify-between gap-3">
                          <label className="flex items-center gap-2 text-sm font-medium text-slate-900 dark:text-white">
                            <input
                              type="checkbox"
                              checked={enabled}
                              disabled={catalog.key === 'draft'}
                              onChange={(event) => setStatusEnabled(catalog.key, event.target.checked)}
                              data-testid={`lifecycle-status-enabled-${catalog.key}`}
                            />
                            {catalog.label}
                          </label>
                          <code className="text-xs text-slate-500">{catalog.key}</code>
                        </div>
                        <Input
                          className="mt-3"
                          value={status?.label ?? catalog.label}
                          disabled={!enabled}
                          onChange={(event) => setStatusLabel(catalog.key, event.target.value)}
                          data-testid={`lifecycle-status-label-${catalog.key}`}
                          aria-label={`${catalog.label}显示名称`}
                        />
                        <label className="mt-3 flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
                          <input
                            type="checkbox"
                            checked={lifecycleForm.require_reason_for.includes(catalog.key)}
                            disabled={!enabled}
                            onChange={(event) => setReasonRequired(catalog.key, event.target.checked)}
                            data-testid={`lifecycle-require-reason-${catalog.key}`}
                          />
                          流转到此状态时必须填写原因
                        </label>
                      </div>
                    )
                  })}
                </div>
              </section>

              <section className="space-y-3">
                <div>
                  <h2 className="font-semibold text-slate-900 dark:text-white">流转矩阵</h2>
                  <p className="mt-1 text-sm text-slate-500">勾选允许的定向流转。每个启用状态都必须至少有一个入口。</p>
                </div>
                <div className="overflow-x-auto rounded-md border border-slate-200 dark:border-slate-800">
                  <table className="w-full min-w-[760px] text-sm">
                    <thead className="bg-slate-50 dark:bg-slate-900">
                      <tr>
                        <th className="px-3 py-3 text-left font-medium">从 / 到</th>
                        {lifecycleForm.statuses.map((status) => (
                          <th key={status.key} className="px-2 py-3 text-center font-medium">{status.label}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {lifecycleForm.statuses.map((source) => (
                        <tr key={source.key} className="border-t border-slate-200 dark:border-slate-800">
                          <th className="px-3 py-3 text-left font-medium">{source.label}</th>
                          {lifecycleForm.statuses.map((target) => {
                            const approvalLocked =
                              lifecycleForm.publish_gates.require_approved &&
                              target.key === 'published' &&
                              source.key !== 'approved'
                            return (
                              <td key={target.key} className="px-2 py-3 text-center">
                                <input
                                  type="checkbox"
                                  checked={hasTransition(source.key, target.key)}
                                  disabled={source.key === target.key || approvalLocked}
                                  onChange={(event) => setTransition(source.key, target.key, event.target.checked)}
                                  aria-label={`${source.label}到${target.label}`}
                                />
                              </td>
                            )
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <section className="space-y-3">
                <div>
                  <h2 className="flex items-center gap-2 font-semibold text-slate-900 dark:text-white">
                    <ShieldCheck className="h-4 w-4" />
                    发布门禁
                  </h2>
                  <p className="mt-1 text-sm text-slate-500">门禁决定发布前必须满足的交付条件，不影响平台权限判定。</p>
                </div>
                <div className="grid gap-3 lg:grid-cols-3">
                  {[
                    ['require_approved', '必须先批准', '只允许从已批准状态进入已发布。'],
                    ['require_resolved_comments', '评论全部解决', '存在未解决评审评论时禁止发布。'],
                    ['require_resolved_placeholders', '模板变量全部补齐', '存在未替换模板变量时禁止发布。'],
                  ].map(([key, title, description]) => (
                    <label key={key} className="flex gap-3 rounded-md border border-slate-200 p-4 dark:border-slate-800">
                      <input
                        type="checkbox"
                        className="mt-1"
                        checked={lifecycleForm.publish_gates[key as keyof ProjectDocumentLifecyclePolicy['publish_gates']]}
                        onChange={(event) => setPublishGate(key as keyof ProjectDocumentLifecyclePolicy['publish_gates'], event.target.checked)}
                        data-testid={`lifecycle-publish-gate-${key.replace('require_', '').replace('resolved_', '')}`}
                      />
                      <span>
                        <span className="block font-medium text-slate-900 dark:text-white">{title}</span>
                        <span className="mt-1 block text-xs text-slate-500">{description}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </section>

              {policyIssues.length > 0 ? (
                <div className="rounded-md border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
                  <p className="font-semibold">策略尚不能保存</p>
                  <ul className="mt-2 list-disc space-y-1 pl-5">
                    {policyIssues.map((issue) => <li key={issue}>{issue}</li>)}
                  </ul>
                </div>
              ) : (
                <div className="flex items-center gap-2 rounded-md border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-100">
                  <ShieldCheck className="h-4 w-4" />
                  当前策略结构完整，可提交后端进行最终校验并立即生效。
                </div>
              )}

              <div className="flex justify-end gap-3">
                <Button variant="outline" onClick={() => lifecycleQuery.data && setLifecycleForm(clonePolicy(lifecycleQuery.data))}>
                  放弃修改
                </Button>
                <Button
                  onClick={() => lifecycleMutation.mutate()}
                  disabled={policyIssues.length > 0 || lifecycleMutation.isPending}
                  data-testid="save-lifecycle-policy"
                >
                  {lifecycleMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
                  保存生命周期策略
                </Button>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
