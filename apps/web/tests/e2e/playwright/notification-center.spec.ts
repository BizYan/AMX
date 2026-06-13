import { expect, Page, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'

async function gotoAppPage(page: Page, path: string) {
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => {
    localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
  })
  await page.goto(path, { waitUntil: 'domcontentloaded' })
}

test.describe('in-app notification center', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
  })

  test('shows real unread count and supports inbox processing', async ({ page }) => {
    await gotoAppPage(page, '/dashboard')

    await expect(page.getByTestId('notification-unread-count')).toHaveText('2')
    await page.getByTestId('notification-trigger').click()
    await expect(page.getByTestId('notification-dropdown')).toContainText('文档待评审')
    await expect(page.getByTestId('notification-dropdown')).toContainText('需求评审工作流失败')
    await page.getByTestId('notification-view-all').click()

    await expect(page).toHaveURL(/\/notifications$/)
    await expect(page.getByTestId('notification-center')).toContainText('文档待评审')
    await expect(page.getByTestId('notification-center')).toContainText('需求评审工作流失败')

    await page.getByTestId('notification-read-all').click()
    await expect(page.getByTestId('notification-unread-kpi')).toContainText('0')

    await page.getByTestId('notification-archive-notification-review-001').click()
    await expect(page.getByTestId('notification-center')).not.toContainText('文档待评审')

    await page.locator('select').first().selectOption('archived')
    await expect(page.getByTestId('notification-center')).toContainText('文档待评审')
  })
})
