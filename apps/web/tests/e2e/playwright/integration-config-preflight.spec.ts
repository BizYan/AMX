import { expect, Page, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'

async function gotoAppPage(page: Page, path: string) {
  await page.goto(path, { waitUntil: 'domcontentloaded' })
}

test.describe('integration config preflight', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
    await gotoAppPage(page, '/login')
    await page.evaluate(() => {
      localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
    })
  })

  test('validates integration JSON before saving production configuration', async ({ page }) => {
    await gotoAppPage(page, '/settings')
    await page.getByRole('tab', { name: '外部集成' }).click()

    const workbench = page.getByTestId('integration-workbench')
    const preflight = page.getByTestId('integration-config-preflight')
    const configEditor = page.locator('#integration-config')
    const saveButton = workbench.locator('button').filter({ hasText: /保存集成/ }).first()

    await expect(preflight).toContainText('JSON 有效')
    await expect(preflight).toContainText('Endpoint 已识别')
    await expect(preflight).toContainText('认证字段 已识别')
    await expect(preflight).toContainText('api_key')

    await configEditor.fill('{ invalid json')
    await expect(preflight).toContainText('JSON 无效')
    await expect(preflight).toContainText('配置预检失败')
    await expect(saveButton).toBeDisabled()

    await configEditor.fill(JSON.stringify({ base_url: 'https://jira.example.com', health_path: '/rest/api/2/myself' }, null, 2))
    await expect(preflight).toContainText('JSON 有效')
    await expect(preflight).toContainText('Endpoint 已识别')
    await expect(preflight).toContainText('认证字段 缺失')
    await expect(saveButton).toBeDisabled()
  })
})
