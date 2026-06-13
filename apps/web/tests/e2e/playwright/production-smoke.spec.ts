import { expect, test } from '@playwright/test'

const smokeEmail = process.env.E2E_USER_EMAIL
const smokePassword = process.env.E2E_PASSWORD
const apiUrl = process.env.E2E_API_URL || `${process.env.E2E_BASE_URL || 'http://localhost:3000'}/api/v1`

test.describe('production smoke', () => {
  test.skip(!smokeEmail || !smokePassword, 'Set E2E_USER_EMAIL and E2E_PASSWORD to run authenticated smoke tests')

  test.beforeEach(async ({ page, request }) => {
    const loginResponse = await request.post(`${apiUrl}/identity/auth/login`, {
      data: { email: smokeEmail, password: smokePassword },
    })
    expect(loginResponse.ok(), `login status ${loginResponse.status()}`).toBeTruthy()
    const loginJson = await loginResponse.json()
    expect(loginJson.access_token).toBeTruthy()

    await page.goto('/login')
    await page.evaluate((token) => {
      localStorage.setItem('auth_token', token)
    }, loginJson.access_token)
  })

  test('major authenticated routes render Chinese UI without console errors', async ({ page }) => {
    const consoleErrors: string[] = []
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text())
    })

    const routes = [
      { path: '/dashboard', heading: '交付总控台' },
      { path: '/projects', heading: '项目文档' },
      { path: '/documents', heading: '全局文档注册表' },
      { path: '/knowledge/graph', heading: '知识图谱' },
      { path: '/templates', heading: '模板' },
      { path: '/system-health', heading: '健康状态' },
      { path: '/providers', heading: '供应商管理' },
      { path: '/quotas', heading: '配额与监控' },
      { path: '/agent-ops', heading: '智能体运行' },
      { path: '/workflows', heading: '工作流' },
      { path: '/settings', heading: '设置' },
    ]

    for (const route of routes) {
      await page.goto(route.path)
      await expect(page.getByRole('heading', { name: route.heading }).first()).toBeVisible()
      await expect(page.locator('body')).not.toContainText('Application error')
      await expect(page.locator('body')).not.toContainText('This page could not be found')
    }

    const relevantErrors = consoleErrors.filter((error) => {
      if (error.includes('favicon')) return false
      if (error.includes('Failed to fetch RSC payload') && error.includes('Falling back to browser navigation')) return false
      return true
    })
    expect(relevantErrors).toEqual([])
  })

  test('settings invitation and project upload controls expose usable feedback states', async ({ page }) => {
    await page.goto('/settings')
    await page.getByRole('tab', { name: /用户/ }).click()
    await page.getByRole('button', { name: /邀请用户|添加用户/ }).click()
    await expect(page.getByRole('heading', { name: /添加团队成员|邀请用户/ })).toBeVisible()
    await expect(page.getByRole('button', { name: /发送邀请|创建用户/ })).toBeDisabled()
    await page.getByLabel('邮箱').fill(`smoke-${Date.now()}@example.com`)
    await expect(page.getByRole('button', { name: /发送邀请|创建用户/ })).toBeEnabled()

    await page.goto('/projects')
    const firstProject = page.locator('a[href^="/projects/"], [data-testid="project-card"]').first()
    if (await firstProject.isVisible().catch(() => false)) {
      await firstProject.click()
      await page.waitForURL(/\/projects\/[^/]+/)
      await page.getByRole('link', { name: /上传文件|管理文件|文件/ }).first().click()
      await expect(page.getByRole('heading', { name: '项目资料' })).toBeVisible()
      await page.getByRole('button', { name: '上传文件' }).click()
      await expect(page.getByRole('dialog', { name: '上传文件' })).toBeVisible()
    }
  })
})
