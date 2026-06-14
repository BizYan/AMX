import { expect, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'

test.describe('Account security lifecycle', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
    await page.goto('/login')
    await page.evaluate(() => localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef'))
  })

  test('shows security evidence and validates password change locally', async ({ page }) => {
    await page.goto('/settings')
    await page.getByRole('tab', { name: '账户安全' }).click()

    await expect(page.getByTestId('account-security-panel')).toBeVisible()
    await expect(page.getByText('auth.login')).toBeVisible()
    await expect(page.getByTestId('change-password')).toBeDisabled()

    await page.getByLabel('当前密码').fill('OldPassword-2026')
    await page.getByLabel('新密码', { exact: true }).fill('NewPassword-2026')
    await page.getByLabel('确认新密码').fill('different')
    await expect(page.getByTestId('change-password')).toBeDisabled()

    await page.getByLabel('确认新密码').fill('NewPassword-2026')
    await expect(page.getByTestId('change-password')).toBeEnabled()
  })

  test('revokes all sessions and returns to login', async ({ page }) => {
    await page.goto('/settings')
    await page.getByRole('tab', { name: '账户安全' }).click()
    await page.getByTestId('revoke-all-sessions').click()
    await expect(page).toHaveURL(/\/login$/)
  })
})
