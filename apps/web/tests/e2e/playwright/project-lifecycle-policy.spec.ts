import { expect, Page, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'

async function gotoAppPage(page: Page, path: string) {
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => {
    localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
  })
  await page.goto(path, { waitUntil: 'domcontentloaded' })
}

test.describe('project document lifecycle policy', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
  })

  test('loads, edits, validates, and saves the effective project lifecycle', async ({ page }) => {
    await gotoAppPage(page, '/projects/project-e2e-001/settings')

    const panel = page.getByTestId('project-lifecycle-policy-panel')
    await expect(panel).toContainText('文档生命周期')
    await expect(panel).toContainText('策略修订 1')
    await expect(panel).toContainText('草稿')
    await expect(panel).toContainText('已发布')

    await page.getByTestId('lifecycle-status-label-review').fill('客户评审')
    await page.getByTestId('lifecycle-require-reason-review').check()
    await page.getByTestId('lifecycle-publish-gate-comments').uncheck()
    await page.getByTestId('save-lifecycle-policy').click()

    await expect(panel).toContainText('策略修订 2')
    await expect(page.locator('body')).toContainText('生命周期策略已保存')
    await expect(page.getByTestId('lifecycle-status-label-review')).toHaveValue('客户评审')
    await expect(page.getByTestId('lifecycle-require-reason-review')).toBeChecked()
    await expect(page.getByTestId('lifecycle-publish-gate-comments')).not.toBeChecked()
  })
})
