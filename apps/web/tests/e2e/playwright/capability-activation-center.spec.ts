import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, Page, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'

const repoRoot = join(__dirname, '..', '..', '..', '..', '..')

async function gotoAppPage(page: Page, path: string) {
  try {
    await page.goto(path, { waitUntil: 'domcontentloaded' })
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    if (!message.includes('net::ERR_ABORTED')) {
      throw error
    }
    await page.goto(path, { waitUntil: 'domcontentloaded' })
  }
}

test.describe('core capability operations center', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
    await gotoAppPage(page, '/login')
    await page.evaluate(() => {
      localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
    })
  })

  test('surfaces real operations metrics, quotas, rate limits, and audit events', async ({ page }) => {
    await gotoAppPage(page, '/system-health')

    const body = page.locator('body')
    await expect(page.getByTestId('production-ops-command-center')).toContainText('生产运维指挥台')
    await expect(page.getByTestId('production-ops-release-gate')).toContainText('发布前必须完成处置')
    await expect(page.getByTestId('production-ops-command-center')).toContainText('来源知识图谱校准')
    await expect(page.getByTestId('production-ops-command-center').getByRole('link', { name: /补齐项目资料/ }).first()).toHaveAttribute('href', '/projects')
    await expect(body).toContainText('1,284')
    await expect(body).toContainText('当前租户本月 2,400 次调用')
    await expect(body).toContainText('8,420 / 10,000')
    await expect(body).toContainText('租户请求成功率')
    await expect(body).toContainText('95%')
    await expect(body).toContainText('最紧张限流')
    await expect(body).toContainText('/providers/provider-e2e-001/test')
    await expect(body).toContainText('为系统管理员分配管理员角色')
    await expect(body).not.toContainText('暂无配额数据')
  })

  test('generates an activation plan and executes safe actions only', async ({ page }) => {
    await gotoAppPage(page, '/system-health')

    const panel = page.getByTestId('capability-activation-panel')
    await expect(panel).toBeVisible()
    await expect(panel).toContainText('核心能力激活中心')
    await expect(panel).toContainText('尚未生成计划')

    await page.getByRole('button', { name: /生成激活计划/ }).click()
    await expect(panel).toContainText('初始化核心文档模板')
    await expect(panel).toContainText('初始化 Agent/Skill/Workflow')
    await expect(panel).toContainText('初始化外部同步证据')
    await expect(panel).toContainText('初始化协同执行证据')
    await expect(panel).toContainText('初始化通知告警证据')
    await expect(panel).toContainText('需人工')

    await page.getByRole('button', { name: /执行安全激活/ }).click()
    await expect(panel).toContainText('已完成')
    await expect(panel).toContainText('配置外部系统集成')
  })

  test('runs production commissioning checks and exposes remediation links', async ({ page }) => {
    await gotoAppPage(page, '/system-health')

    const panel = page.getByTestId('capability-commissioning-panel')
    await expect(panel).toBeVisible()
    await expect(panel).toContainText('核心能力投产校准中心')
    await expect(panel).toContainText('尚未生成校准清单')

    await page.getByRole('button', { name: /生成校准清单/ }).click()
    await expect(panel).toContainText('真实 LLM Provider 校准')
    await expect(panel).toContainText('来源知识图谱校准')
    await expect(panel).toContainText('外部同步项目写入校准')
    await expect(panel).toContainText('协同责任执行校准')
    await expect(panel).toContainText('通知确认与告警投递校准')
    await expect(panel).toContainText('待处理')
    await expect(panel.getByRole('link', { name: /处理/ }).first()).toHaveAttribute('href', '/providers')

    await page.getByRole('button', { name: /运行校准检查/ }).click()
    await expect(panel).toContainText('已通过')
    await expect(panel).toContainText('未通过')
  })

  test('health metrics fallback does not synthesize current timestamps', () => {
    const source = readFileSync(join(repoRoot, 'apps/web/src/app/(app)/health/page.tsx'), 'utf8')
    const apiClient = readFileSync(join(repoRoot, 'apps/web/src/lib/api-client.ts'), 'utf8')

    expect(source).toContain('timestamp: null')
    expect(source).not.toContain('timestamp: new Date().toISOString()')
    expect(apiClient).toContain('timestamp: string | null')
  })
})
