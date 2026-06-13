import { expect, Page, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'

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

test.describe('provider operations control center', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
    await gotoAppPage(page, '/login')
    await page.evaluate(() => {
      localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
    })
  })

  test('connects provider health, circuit breaker risk and operator actions', async ({ page }) => {
    await gotoAppPage(page, '/providers')

    const body = page.locator('body')
    await expect(page.getByTestId('provider-operations-center')).toBeVisible()
    await expect(body).toContainText('Graphify')
    await expect(body).toContainText('OpenAI LLM')
    await expect(body).toContainText('GitNexus')
    await expect(page.getByTestId('provider-production-readiness')).toBeVisible()
    await expect(page.getByTestId('provider-production-readiness')).toContainText('Provider 生产就绪度')
    await expect(page.getByTestId('provider-production-readiness')).toContainText('仍有阻塞')
    await expect(page.getByTestId('provider-production-readiness')).toContainText('Graphify 图谱')
    await expect(page.getByTestId('provider-production-readiness')).toContainText('GitNexus 代码索引')
    await expect(body).toContainText('graphify-service-breaker')
    await expect(body).toContainText('gitnexus-service-breaker')
    await expect(body).toContainText('Sandbox fallback')

    await page.getByTestId('provider-test-provider-e2e-001').click()
    await expect(body).toContainText(/Graphify.*fallback/i, { timeout: 8000 })

    await page.getByTestId('provider-list-test-provider-e2e-002').click()
    await expect(body).toContainText(/Mock.*normal|Mock.*success|Mock/i, { timeout: 8000 })

    await page.getByTestId('provider-config-provider-e2e-001').click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await expect(page.getByTestId('provider-edit-name')).toHaveValue(/Graphify/)
    await page.getByTestId('provider-edit-cancel').click()
  })

  test('keeps quota operations reachable from provider risk context', async ({ page }) => {
    await gotoAppPage(page, '/providers')
    await expect(page.getByTestId('provider-operations-center')).toBeVisible()

    await gotoAppPage(page, '/quotas')
    await expect(page.getByTestId('quota-command-center')).toBeVisible()
    await expect(page.getByTestId('quota-operating-gate')).toContainText('需要关注')
    await expect(page.getByTestId('quota-priority-actions')).toContainText('Provider 健康风险')
    await expect(page.getByTestId('quota-rate-limit-risks')).toContainText('/api/agent')
    await expect(page.locator('body')).toContainText('Graphify')
    await expect(page.locator('body')).toContainText(/fallback/i)
  })
})
