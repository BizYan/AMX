'use client'

import Link from 'next/link'
import { use, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { sourceFilesApi, SourceFile, SourceIngestionJob } from '@/lib/api-client'
import { createClientId } from '@/lib/client-id'
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
import { useToast } from '@/components/ui/toast'
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle,
  Clock,
  Download,
  FileText,
  Loader2,
  Network,
  PlusCircle,
  RefreshCw,
  RotateCcw,
  Play,
  Upload,
  X,
} from 'lucide-react'

interface FilesPageProps {
  params: Promise<{ projectId: string }>
}

interface UploadingFile {
  id: string
  name: string
  size: number
  status: 'reading' | 'uploading' | 'queued' | 'error'
  progress: number
  error?: string
}

const statusCopy: Record<SourceFile['status'], { label: string; tone: string; stage: string }> = {
  pending: { label: '等待摄取', tone: 'bg-slate-100 text-slate-700', stage: '排队等待解析' },
  processing: { label: '处理中', tone: 'bg-amber-100 text-amber-800', stage: '解析与知识抽取中' },
  ready: { label: '可用于生成', tone: 'bg-emerald-100 text-emerald-800', stage: '已完成知识抽取' },
  failed: { label: '需补充', tone: 'bg-red-100 text-red-800', stage: '摄取失败或证据不足' },
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  if (typeof error === 'string') return error
  return ''
}

function translateError(error: unknown): string {
  const msg = getErrorMessage(error).toLowerCase()
  if (msg.includes('403') || msg.includes('access denied') || msg.includes('permission')) {
    return '权限不足：您没有在此项目上传资料的权限，请联系项目管理员。'
  }
  if (msg.includes('400') || msg.includes('unsupported')) {
    return '格式错误：暂不支持此文件类型，请上传 PDF、Word、Excel、CSV 或文本资料。'
  }
  if (msg.includes('413') || msg.includes('too large')) {
    return '文件过大：上传的文件超过大小限制，请压缩后重试。'
  }
  if (msg.includes('failed to fetch') || msg.includes('network') || msg.includes('timeout')) {
    return '网络异常：无法连接服务器，请检查网络后重试。'
  }
  return `上传失败：${getErrorMessage(error) || '未知错误，请重试。'}`
}

function formatFileSize(bytes: number) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

function buildFileSummary(file: SourceFile) {
  if (file.ingestionSummary) return file.ingestionSummary
  if (file.status === 'ready') return '已完成正文解析、要点归纳和知识条目抽取，可直接加入文档生成上下文。'
  if (file.status === 'processing') return '系统正在解析正文、识别结构化事实，并准备写入知识库。'
  if (file.status === 'failed') return file.errorMessage || '资料解析未完成，需要补充更清晰的文件或人工确认关键信息。'
  return '资料已进入摄取队列，等待解析服务处理。'
}

export default function FilesPage({ params }: FilesPageProps) {
  const { projectId } = use(params)
  const [isUploadOpen, setIsUploadOpen] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const [uploadingFiles, setUploadingFiles] = useState<UploadingFile[]>([])
  const [lastUploadSummary, setLastUploadSummary] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const dialogFileInputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()
  const { addToast } = useToast()

  const { data: filesData, isLoading } = useQuery({
    queryKey: ['project-files', projectId],
    queryFn: () => sourceFilesApi.list(projectId, { pageSize: 100 }),
  })
  const { data: ingestionJobsData } = useQuery({
    queryKey: ['source-ingestion-jobs', projectId],
    queryFn: () => sourceFilesApi.listIngestionJobs(projectId),
    refetchInterval: (query) => {
      const jobs = query.state.data?.items ?? []
      return jobs.some((job) => job.status === 'pending' || job.status === 'running') ? 3000 : false
    },
  })

  const files = useMemo(() => filesData?.items ?? [], [filesData?.items])
  const latestJobsByFile = useMemo(() => {
    const jobs = ingestionJobsData?.items ?? []
    return jobs.reduce<Record<string, SourceIngestionJob>>((latest, job) => {
      if (!latest[job.source_file_id]) latest[job.source_file_id] = job
      return latest
    }, {})
  }, [ingestionJobsData?.items])
  const refreshIngestionState = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['project-files', projectId] }),
      queryClient.invalidateQueries({ queryKey: ['source-ingestion-jobs', projectId] }),
    ])
  }
  const ingestionAction = useMutation({
    mutationFn: async (action: { type: 'execute' | 'retry' | 'reingest'; id: string }) => {
      if (action.type === 'execute') return sourceFilesApi.executeIngestionJob(projectId, action.id)
      if (action.type === 'retry') return sourceFilesApi.retryIngestionJob(projectId, action.id)
      return sourceFilesApi.reingest(projectId, action.id)
    },
    onSuccess: async () => {
      await refreshIngestionState()
      addToast({ title: '摄取任务已更新', description: '最新任务状态和知识入库结果已同步。' })
    },
    onError: (error) => {
      addToast({ title: '摄取任务操作失败', description: getErrorMessage(error), variant: 'destructive' })
    },
  })
  const summary = useMemo(
    () => ({
      uploaded: files.length,
      processing: files.filter((file) => file.status === 'pending' || file.status === 'processing').length,
      ready: files.filter((file) => file.status === 'ready').length,
      needsInput: files.filter((file) => file.status === 'failed').length,
    }),
    [files]
  )

  const uploadFiles = async (selectedFiles: File[]) => {
    if (selectedFiles.length === 0) return

    const newUploadingFiles = selectedFiles.map((file) => ({
      id: createClientId(`upload-${file.name}`),
      name: file.name,
      size: file.size,
      status: 'reading' as const,
      progress: 20,
    }))

    setUploadingFiles((prev) => [...prev, ...newUploadingFiles])
    setLastUploadSummary(null)

    let successCount = 0
    let failureCount = 0
    const uploadedNames: string[] = []

    for (let i = 0; i < selectedFiles.length; i++) {
      const file = selectedFiles[i]
      const queueItem = newUploadingFiles[i]

      try {
        setUploadingFiles((prev) =>
          prev.map((item) => (item.id === queueItem.id ? { ...item, status: 'uploading', progress: 60 } : item))
        )
        const formData = new FormData()
        formData.append('file', file)
        const uploadedFile = await sourceFilesApi.upload(projectId, formData)

        setUploadingFiles((prev) =>
          prev.map((item) => (item.id === queueItem.id ? { ...item, status: 'queued', progress: 100 } : item))
        )
        successCount++
        uploadedNames.push(uploadedFile.name || file.name)
      } catch (error) {
        const friendlyError = translateError(error)
        setUploadingFiles((prev) =>
          prev.map((item) =>
            item.id === queueItem.id ? { ...item, status: 'error', progress: 100, error: friendlyError } : item
          )
        )
        failureCount++
      }
    }

    queryClient.invalidateQueries({ queryKey: ['project-files', projectId] })

    if (successCount > 0) {
      const description = `已保存 ${successCount} 个文件，资料将自动进入解析、抽取和知识入库流程。`
      addToast({ title: '文件上传成功', description })
      setLastUploadSummary(`已进入知识摄取队列，可在本页跟踪解析和抽取结果。`)
      setIsUploadOpen(false)
    }

    if (failureCount > 0) {
      addToast({
        title: '部分文件上传失败',
        description: `有 ${failureCount} 个文件未上传成功，请查看上传队列中的中文错误提示。`,
        variant: 'destructive',
      })
    }
  }

  const handleDrag = (event: React.DragEvent) => {
    event.preventDefault()
    event.stopPropagation()
    setDragActive(event.type === 'dragenter' || event.type === 'dragover')
  }

  const handleDrop = (event: React.DragEvent) => {
    event.preventDefault()
    event.stopPropagation()
    setDragActive(false)
    uploadFiles(event.dataTransfer.files ? Array.from(event.dataTransfer.files) : [])
  }

  const downloadFile = async (file: SourceFile) => {
    try {
      const response = await fetch(sourceFilesApi.downloadUrl(projectId, file.id), {
        headers: { Authorization: `Bearer ${localStorage.getItem('auth_token') || ''}` },
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = file.name
      link.click()
      URL.revokeObjectURL(url)
    } catch (error) {
      addToast({ title: '下载失败', description: translateError(error), variant: 'destructive' })
    }
  }

  const isUploading = uploadingFiles.some((file) => file.status === 'reading' || file.status === 'uploading')

  return (
    <div className="mx-auto max-w-7xl space-y-6 px-4 py-2 sm:px-6 lg:px-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-900 dark:text-white">资料摄取驾驶舱</h1>
          <p className="mt-1.5 text-sm text-slate-500 dark:text-slate-400">
            上传项目资料后，跟踪解析队列、知识抽取结果、缺口提示，并把可用资料推进到文档生成和知识图谱。
          </p>
        </div>
        <Button onClick={() => setIsUploadOpen(true)} className="bg-indigo-600 text-white hover:bg-indigo-500">
          <Upload className="mr-2 h-4 w-4" />
          上传资料
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          ['已上传', summary.uploaded, '当前项目资料总数'],
          ['处理中', summary.processing, '排队、解析或抽取中'],
          ['可用于生成', summary.ready, '可加入生成上下文'],
          ['失败/需补充', summary.needsInput, '需要重新上传或人工补证'],
        ].map(([label, value, hint]) => (
          <div key={label} className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900/40">
            <p className="text-sm font-medium text-slate-500 dark:text-slate-400">{label}</p>
            <p className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">
              {label} {value}
            </p>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{hint}</p>
          </div>
        ))}
      </div>

      <Card
        className={`cursor-pointer border-2 border-dashed transition-colors ${
          dragActive ? 'border-indigo-500 bg-indigo-50/60' : 'border-slate-200 bg-white hover:border-slate-300'
        } dark:border-slate-800 dark:bg-slate-900/30`}
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        onClick={(event) => {
          const target = event.target as HTMLElement
          if (!target.closest('button') && !target.closest('a')) fileInputRef.current?.click()
        }}
      >
        <CardContent className="flex flex-col items-center justify-center px-6 py-12 text-center">
          <div className="rounded-full border border-slate-100 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-800">
            {isUploading ? <Loader2 className="h-9 w-9 animate-spin text-indigo-500" /> : <Upload className="h-9 w-9 text-slate-400" />}
          </div>
          <p className="mt-4 text-lg font-semibold text-slate-900 dark:text-white">
            {isUploading ? '资料正在上传并进入摄取队列' : '拖放资料到这里'}
          </p>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">支持 PDF、Word、PPTX、Excel、CSV、TXT 和代码文本</p>
          <Button variant="outline" className="mt-4" disabled={isUploading} onClick={() => fileInputRef.current?.click()}>
            选择本地资料
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(event) => uploadFiles(event.target.files ? Array.from(event.target.files) : [])}
          />
        </CardContent>
      </Card>

      {(uploadingFiles.length > 0 || lastUploadSummary) && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center justify-between text-base">
              <span>上传队列</span>
              {isUploading && <Loader2 className="h-4 w-4 animate-spin text-indigo-500" />}
            </CardTitle>
            <CardDescription>成功上传后会保留队列反馈，提示资料已经进入知识摄取流程。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {lastUploadSummary && (
              <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
                <CheckCircle className="h-4 w-4" />
                <span>{lastUploadSummary}</span>
              </div>
            )}
            {uploadingFiles.map((file) => (
              <div key={file.id} className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-sm font-medium text-slate-900 dark:text-white">{file.name}</p>
                    <p className="mt-1 text-xs text-slate-500">
                      {formatFileSize(file.size)} ·{' '}
                      {file.status === 'reading' && '正在读取本地文件'}
                      {file.status === 'uploading' && '正在安全上传'}
                      {file.status === 'queued' && '已进入知识摄取队列，可在本页跟踪解析和抽取结果。'}
                      {file.status === 'error' && <span className="text-red-600">{file.error}</span>}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {file.status === 'queued' && <CheckCircle className="h-4 w-4 text-emerald-600" />}
                    {file.status === 'error' && <AlertTriangle className="h-4 w-4 text-red-600" />}
                    {file.status === 'error' && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 w-7 p-0"
                        aria-label="清除失败项"
                        onClick={() => setUploadingFiles((prev) => prev.filter((item) => item.id !== file.id))}
                      >
                        <X className="h-4 w-4" />
                      </Button>
                    )}
                  </div>
                </div>
                <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100">
                  <div className="h-full bg-indigo-500 transition-all" style={{ width: `${file.progress}%` }} />
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {isLoading ? (
        <div className="flex h-64 items-center justify-center rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900/30">
          <Loader2 className="mr-2 h-5 w-5 animate-spin text-indigo-500" />
          <span className="text-sm text-slate-500">正在加载资料摄取状态...</span>
        </div>
      ) : files.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center px-4 py-16 text-center">
            <FileText className="h-10 w-10 text-slate-300" />
            <h2 className="mt-4 text-lg font-semibold text-slate-900 dark:text-white">暂无项目资料</h2>
            <p className="mt-1 max-w-md text-sm text-slate-500">上传第一份资料后，系统会展示解析阶段、抽取摘要和下一步动作。</p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {files.map((file) => {
            const status = statusCopy[file.status]
            const sourceFileId = encodeURIComponent(file.id)
            const latestJob = latestJobsByFile[file.id]
            return (
              <Card key={file.id}>
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <CardTitle className="truncate text-base">{file.name}</CardTitle>
                      <CardDescription>
                        {formatFileSize(file.size)} · {file.createdAt ? new Date(file.createdAt).toLocaleString('zh-CN') : '未提供时间'}
                      </CardDescription>
                    </div>
                    <Badge className={status.tone}>{status.label}</Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid gap-3 sm:grid-cols-3">
                    <div>
                      <p className="text-xs text-slate-500">处理阶段</p>
                      <p className="mt-1 text-sm font-medium text-slate-900 dark:text-white">{file.ingestionStage || status.stage}</p>
                    </div>
                    <div>
                      <p className="text-xs text-slate-500">知识条目</p>
                      <p className="mt-1 text-sm font-medium text-slate-900 dark:text-white">{file.extractedKnowledgeCount ?? 0} 条</p>
                    </div>
                    <div>
                      <p className="text-xs text-slate-500">待补充</p>
                      <p className="mt-1 text-sm font-medium text-slate-900 dark:text-white">{file.requiredAction || '暂无阻塞'}</p>
                    </div>
                  </div>

                  <div className="rounded-lg bg-slate-50 p-3 text-sm text-slate-700 dark:bg-slate-800/60 dark:text-slate-200">
                    <span className="font-medium">抽取摘要：</span>
                    {buildFileSummary(file)}
                  </div>

                  <div className="flex flex-wrap gap-2">
                    {latestJob?.status === 'pending' && (
                      <Button
                        size="sm"
                        data-testid={`execute-ingestion-${file.id}`}
                        disabled={ingestionAction.isPending}
                        onClick={() => ingestionAction.mutate({ type: 'execute', id: latestJob.id })}
                      >
                        <Play className="mr-2 h-4 w-4" />
                        执行摄取
                      </Button>
                    )}
                    {latestJob?.status === 'failed' && (
                      <Button
                        size="sm"
                        variant="outline"
                        data-testid={`retry-ingestion-${file.id}`}
                        disabled={ingestionAction.isPending}
                        onClick={() => ingestionAction.mutate({ type: 'retry', id: latestJob.id })}
                      >
                        <RotateCcw className="mr-2 h-4 w-4" />
                        重试摄取
                      </Button>
                    )}
                    {file.status === 'ready' && !latestJob?.status?.match(/pending|running/) && (
                      <Button
                        size="sm"
                        variant="outline"
                        data-testid={`reingest-source-${file.id}`}
                        disabled={ingestionAction.isPending}
                        onClick={() => ingestionAction.mutate({ type: 'reingest', id: file.id })}
                      >
                        <RefreshCw className="mr-2 h-4 w-4" />
                        重新摄取
                      </Button>
                    )}
                    <Button variant="outline" size="sm" onClick={() => downloadFile(file)}>
                      <Download className="mr-2 h-4 w-4" />
                      下载原件
                    </Button>
                    {file.status === 'ready' ? (
                      <Button asChild size="sm">
                        <Link href={`/projects/${projectId}/documents/generate?sourceFileId=${sourceFileId}`}>
                          <PlusCircle className="mr-2 h-4 w-4" />
                          加入生成上下文
                        </Link>
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        onClick={() =>
                          addToast({
                            title: '资料暂不可用于生成',
                            description: `${file.name} 当前状态为“${status.label}”，请等待解析完成或补充资料。`,
                          })
                        }
                      >
                        <PlusCircle className="mr-2 h-4 w-4" />
                        加入生成上下文
                      </Button>
                    )}
                    <Button asChild variant="outline" size="sm">
                      <Link href={`/knowledge/graph?projectId=${projectId}&sourceFileId=${sourceFileId}`}>
                        <Network className="mr-2 h-4 w-4" />
                        查看知识图谱
                      </Link>
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() =>
                        addToast({
                          title: '已标记补充资料',
                          description: `${file.name} 已加入待补充事项，生成前会提醒补齐证据。`,
                        })
                      }
                    >
                      <ArrowRight className="mr-2 h-4 w-4" />
                      标记补充资料
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}

      <Dialog open={isUploadOpen} onOpenChange={setIsUploadOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>上传项目资料</DialogTitle>
            <DialogDescription>资料上传后会进入知识摄取队列，页面会持续反馈解析、抽取和可用状态。</DialogDescription>
          </DialogHeader>
          <button
            type="button"
            className="flex w-full flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-200 p-8 text-center hover:border-slate-300 dark:border-slate-800"
            onClick={() => dialogFileInputRef.current?.click()}
            onDragEnter={handleDrag}
            onDragLeave={handleDrag}
            onDragOver={handleDrag}
            onDrop={handleDrop}
            disabled={isUploading}
          >
            {isUploading ? <Loader2 className="h-8 w-8 animate-spin text-indigo-500" /> : <Upload className="h-8 w-8 text-slate-400" />}
            <span className="mt-3 text-sm font-medium text-slate-900 dark:text-white">拖放资料或点击浏览</span>
            <span className="mt-1 text-xs text-slate-500">单次可上传多个文件</span>
            <input
              ref={dialogFileInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={(event) => uploadFiles(event.target.files ? Array.from(event.target.files) : [])}
            />
          </button>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsUploadOpen(false)} disabled={isUploading}>
              取消
            </Button>
            <Button onClick={() => dialogFileInputRef.current?.click()} disabled={isUploading}>
              {isUploading ? (
                <>
                  <Clock className="mr-2 h-4 w-4" />
                  正在上传
                </>
              ) : (
                '选择并上传'
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
