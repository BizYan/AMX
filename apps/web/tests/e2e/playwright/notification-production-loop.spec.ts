import { expect, Page, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'

async function gotoAppPage(page: Page, path: string) {
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => {
    localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
  })
  await page.goto(path, { waitUntil: 'domcontentloaded' })
}

test.describe('notification and alert production loop', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
  })

  test('saves preferences and acknowledges an escalated notification', async ({ page }) => {
    await gotoAppPage(page, '/notifications')

    await expect(page.getByTestId('notification-preferences')).toContainText('通知偏好与确认时限')
    await page.getByTestId('notification-preferences-save').click()
    await expect(page.getByText('通知偏好已保存')).toBeVisible()

    await expect(page.getByTestId('notification-center')).toContainText('已升级')
    await page.getByTestId('notification-acknowledge-notification-review-001').click()
    await expect(page.getByText('关键通知已确认')).toBeVisible()
    await expect(page.getByTestId('notification-acknowledge-notification-review-001')).toHaveCount(0)
  })

  test('retries a failed delivery from operations monitoring', async ({ page }) => {
    await gotoAppPage(page, '/system-health')

    await expect(page.getByTestId('notification-delivery-operations')).toContainText('告警邮件投递失败')
    await page.getByTestId('retry-notification-delivery-delivery-failed-001').click()
    await expect(page.getByTestId('notification-delivery-operations')).toContainText('sent')
    await expect(page.getByTestId('retry-notification-delivery-delivery-failed-001')).toHaveCount(0)
  })
})
