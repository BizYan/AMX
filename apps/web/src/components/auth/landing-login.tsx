'use client'

import { useState } from 'react'
import { ArrowRight, CheckCircle2, FileText, GitBranch, Network, ShieldCheck, Sparkles } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { useAuth } from '@/lib/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

function ProductPreview() {
  const rows = [
    ['用户需求规格说明书', '已发布', '92%'],
    ['采购供应链流程', '评审中', '76%'],
    ['验收标准矩阵', '草稿', '48%'],
  ]

  return (
    <div className="rounded-lg border border-white/10 bg-slate-950/55 p-4 shadow-2xl shadow-slate-950/40 backdrop-blur">
      <div className="mb-4 flex items-center justify-between border-b border-white/10 pb-3">
        <div>
          <p className="text-sm font-semibold text-white">项目智能工作台</p>
          <p className="mt-1 text-xs text-slate-400">文档、知识、追溯一体化管理</p>
        </div>
        <div className="rounded-md bg-emerald-400/12 px-2.5 py-1 text-xs font-medium text-emerald-200">
          在线
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        {[
          ['项目', '12', FileText, 'text-cyan-200'],
          ['知识节点', '438', Network, 'text-emerald-200'],
          ['追溯关系', '86', GitBranch, 'text-amber-200'],
        ].map(([label, value, Icon, color]) => (
          <div key={label as string} className="rounded-md border border-white/10 bg-white/[0.04] p-3">
            <Icon className={`h-4 w-4 ${color}`} />
            <p className="mt-3 text-2xl font-semibold text-white">{value as string}</p>
            <p className="mt-1 text-xs text-slate-400">{label as string}</p>
          </div>
        ))}
      </div>

      <div className="mt-4 space-y-2">
        {rows.map(([name, status, score]) => (
          <div key={name} className="flex items-center justify-between rounded-md border border-white/10 bg-white/[0.04] px-3 py-2">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-slate-100">{name}</p>
              <p className="mt-0.5 text-xs text-slate-500">{status}</p>
            </div>
            <div className="ml-4 text-sm font-semibold text-cyan-100">{score}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

export function LandingLogin() {
  const { login } = useAuth()
  const tAuth = useTranslations('auth')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  const submitLogin = async () => {
    setError(null)
    setIsLoading(true)

    try {
      await login(email, password)
      window.location.assign('/dashboard')
    } catch (err) {
      setError(err instanceof Error ? err.message : tAuth('loginFailedDetail'))
    } finally {
      setIsLoading(false)
    }
  }

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    await submitLogin()
  }

  return (
    <main className="min-h-screen overflow-hidden bg-[#0b1020] text-white">
      <div className="mx-auto flex min-h-screen w-full max-w-7xl flex-col px-6 py-6 lg:px-8">
        <header className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-md bg-cyan-300 text-slate-950">
              <Sparkles className="h-5 w-5" />
            </div>
            <div>
              <p className="text-lg font-semibold tracking-normal">Avenir Matrix</p>
              <p className="text-xs text-slate-400">AI consulting operating system</p>
            </div>
          </div>
        </header>

        <section className="grid flex-1 items-start gap-10 py-12 lg:grid-cols-[1.18fr_0.82fr] lg:py-14">
          <div className="max-w-3xl pt-6 lg:pt-14">
            <h1 className="max-w-3xl text-4xl font-semibold leading-tight tracking-normal text-white sm:text-5xl lg:text-[4.6rem]">
              <span className="block">驾驭 AI 矩阵</span>
              <span className="block">锚定人类终极决策</span>
            </h1>
            <p className="mt-6 max-w-2xl text-base leading-8 text-slate-300 sm:text-lg">
              专为资深顾问与系统架构师打造的“人机协同（Human-in-the-Loop）”工业级交付引擎。
              基于双向结构化血缘图谱与 GraphRAG，一键构建、追踪并审计所有高价值交付件。
            </p>

            <div className="mt-8 grid gap-3 sm:grid-cols-3">
              {[
                ['文档生成', '从项目资料生成 URS、BRD、PRD'],
                ['知识追溯', '把需求、证据和变更关联起来'],
                ['团队协作', '角色、权限和审阅流程统一管理'],
              ].map(([title, desc]) => (
                <div key={title} className="rounded-md border border-white/10 bg-white/[0.04] p-4">
                  <CheckCircle2 className="h-5 w-5 text-emerald-300" />
                  <p className="mt-3 text-sm font-semibold text-white">{title}</p>
                  <p className="mt-2 text-xs leading-5 text-slate-400">{desc}</p>
                </div>
              ))}
            </div>

            <div className="mt-8 hidden lg:block">
              <ProductPreview />
            </div>
          </div>

          <div className="w-full lg:flex lg:justify-end lg:pt-8">
            <div className="mx-auto w-full max-w-sm rounded-lg border border-white/12 bg-slate-900/88 p-5 shadow-2xl shadow-slate-950/45 backdrop-blur lg:mx-0">
              <div className="mb-4">
                <p className="text-xl font-semibold text-white">{tAuth('signIn')}</p>
                <p className="mt-1.5 text-xs leading-5 text-slate-400">
                  使用您的账户进入 Avenir Matrix 工作台
                </p>
              </div>

              <form onSubmit={handleSubmit} className="space-y-3.5">
                {error && (
                  <div className="rounded-md border border-red-400/30 bg-red-500/10 p-3 text-sm text-red-100">
                    {error}
                  </div>
                )}
                <div className="space-y-2">
                  <Label htmlFor="email" className="text-slate-100">{tAuth('email')}</Label>
                  <Input
                    id="email"
                    type="email"
                    placeholder="you@company.com"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    required
                    disabled={isLoading}
                    className="h-10 border-white/10 bg-slate-950/55 text-sm text-white placeholder:text-slate-500 focus-visible:ring-cyan-300"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="password" className="text-slate-100">{tAuth('password')}</Label>
                  <Input
                    id="password"
                    type="password"
                    placeholder="••••••••"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    required
                    disabled={isLoading}
                    className="h-10 border-white/10 bg-slate-950/55 text-sm text-white placeholder:text-slate-500 focus-visible:ring-cyan-300"
                  />
                </div>
                <Button
                  type="submit"
                  className="h-10 w-full bg-cyan-200 text-sm font-semibold text-slate-950 hover:bg-cyan-100"
                  disabled={isLoading}
                >
                  {isLoading ? tAuth('signingIn') : tAuth('signIn')}
                  {!isLoading && <ArrowRight className="ml-2 h-4 w-4" />}
                </Button>
              </form>

              <div className="mt-4 flex items-center gap-2 text-xs text-slate-500">
                <ShieldCheck className="h-4 w-4 text-emerald-300" />
                <span>通过 HTTPS 安全连接访问企业工作台</span>
              </div>
            </div>

            <div className="mt-6 lg:hidden">
              <ProductPreview />
            </div>
          </div>
        </section>
      </div>
    </main>
  )
}
