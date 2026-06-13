import { expect, Page, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'

async function gotoAppPage(page: Page, path: string) {
  try {
    await page.goto(path, { waitUntil: 'domcontentloaded' })
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    if (!message.includes('net::ERR_ABORTED')) throw error
    await page.goto(path, { waitUntil: 'domcontentloaded' })
  }
}

test.describe('integration operations workbench', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
    await page.route('**/api/v1/integrations/operations/summary*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'degraded',
          score: 72,
          summary: '外部集成已配置，但仍存在 Webhook 投递失败和 Outbox 积压。',
          evidence: {
            integration_count: 2,
            enabled_integration_count: 2,
            configured_integration_count: 1,
            synced_integration_count: 1,
            webhook_count: 2,
            active_webhook_count: 1,
            successful_delivery_count: 4,
            failed_delivery_count: 1,
            pending_outbox_count: 1,
            failed_outbox_count: 0,
          },
          blockers: ['Webhook 投递失败 1 次，需要处理失败目标或重试。', 'Outbox 仍有 1 条待发布事件。'],
          recommended_actions: ['检查 Webhook 投递历史并重试失败事件。', '发布或排查 Outbox 积压事件。'],
        }),
      })
    })
    await gotoAppPage(page, '/login')
    await page.evaluate(() => {
      localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
    })
  })

  test('surfaces production operations evidence for integrations and webhooks', async ({ page }) => {
    await gotoAppPage(page, '/settings')
    await page.getByRole('tab', { name: '外部集成' }).click()

    const body = page.locator('body')
    await expect(page.getByTestId('integration-workbench')).toBeVisible()
    await expect(body).toContainText('集成投产总览')
    await expect(body).toContainText('Webhook 投递失败')
    await expect(body).toContainText('Outbox 积压')
    await expect(body).toContainText('72')
    await expect(body).toContainText('处理失败目标或重试')
    await expect(page.getByTestId('integration-activation-action-seed_integration_sync_evidence')).toBeEnabled()
    await page.getByTestId('integration-activation-action-seed_integration_sync_evidence').click()
    await expect(body).toContainText('外部同步证据已初始化')
  })
})
