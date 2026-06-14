import { expect, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'

test.describe('Project invitation delivery governance', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
    await page.goto('/login')
    await page.evaluate(() => localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef'))
    await page.goto('/projects/project-e2e-001/members')
  })

  test('records failed and successful delivery evidence', async ({ page }) => {
    await expect(page.getByTestId('invitation-delivery-summary')).toContainText('待确认投递')
    await expect(page.getByTestId('invitation-delivery-summary')).toContainText('1')

    await page.getByTestId('invitation-delivery-failed-invitation-e2e-001').click()
    await expect(page.getByText('收件人未确认收到邀请')).toBeVisible()

    await page.getByTestId('invitation-delivery-sent-invitation-e2e-001').click()
    await expect(page.getByText('投递：已送达')).toBeVisible()
    await expect(page.getByText(/尝试 2 次/)).toBeVisible()
  })
})
