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

test.describe('integration operations center', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
    await gotoAppPage(page, '/login')
    await page.evaluate(() => {
      localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
    })
  })

  test('closes the external integration operations loop', async ({ page }) => {
    await gotoAppPage(page, '/integrations')

    const body = page.locator('body')
    await expect(page.getByTestId('integration-operations-center')).toBeVisible()
    await expect(body).toContainText('集成中心')
    await expect(page.getByTestId('integration-production-command-center')).toContainText('生产联调指挥台')
    await expect(page.getByTestId('integration-release-gate')).toContainText('联调阻断')
    await expect(page.getByTestId('integration-production-command-center')).toContainText('清理 Webhook 与 Outbox 阻断')
    await expect(page.getByTestId('integration-production-command-center')).toContainText('Outbox 事件待发布')
    await expect(body).toContainText('禅道需求同步')
    await expect(body).toContainText('Confluence 知识库')
    await expect(page.getByTestId('integration-summary-score')).toContainText('76')
    await expect(page.getByTestId('integration-evidence-project_binding_count')).toContainText('2')

    await page.getByTestId('integration-test-integration-e2e-zentao').click()
    await expect(page.getByTestId('integration-action-result')).toContainText('连接成功')

    await page.getByTestId('integration-sync-integration-e2e-zentao').click()
    await expect(page.getByTestId('integration-action-result')).toContainText('同步完成')

    await page.getByTestId('integration-select-integration-e2e-zentao').click()
    await expect(page.getByTestId('integration-binding-panel')).toContainText('WMS 项目需求同步')
    await page.getByTestId('integration-preview-binding-e2e-001').click()
    await expect(page.getByTestId('integration-preview-panel')).toContainText('登录异常处理规则')
    await page.getByTestId('integration-sync-binding-e2e-001').click()
    await expect(page.getByTestId('integration-action-result')).toContainText('项目同步完成')

    await page.getByRole('tab', { name: 'Webhook' }).click()
    await page.getByTestId('integration-webhook-panel').getByText('交付系统 Webhook').waitFor()
    await page.getByRole('tab', { name: 'Outbox' }).click()
    await page.getByTestId('integration-publish-outbox').click()
    await expect(page.getByTestId('integration-action-result')).toContainText('已发布 2 个事件')
  })

  test('can create a configured integration without leaving the page', async ({ page }) => {
    await gotoAppPage(page, '/integrations')

    await page.getByTestId('integration-open-create').click()
    await page.getByTestId('integration-create-name').fill('Jira 研发事项')
    await page.getByTestId('integration-create-provider').fill('jira')
    await page.getByTestId('integration-create-base-url').fill('https://jira.example.com')
    await page.getByTestId('integration-create-api-key').fill('jira-token')
    await page.getByTestId('integration-submit-create').click()

    await expect(page.locator('body')).toContainText('Jira 研发事项')
    await expect(page.getByTestId('integration-action-result')).toContainText('集成已创建')
  })
})
