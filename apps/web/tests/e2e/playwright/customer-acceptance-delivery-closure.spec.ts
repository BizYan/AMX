import { expect, test } from '@playwright/test'

import { setupApiMocks } from './fixtures/api-mocks'

test('records customer acceptance and closes formal delivery', async ({ page }) => {
  await setupApiMocks(page)
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef'))
  await page.goto('/projects/project-e2e-001/acceptance', { waitUntil: 'domcontentloaded' })

  await expect(page.getByRole('heading', { name: '客户验收与正式交付' })).toBeVisible()
  await expect(page.getByTestId('acceptance-gate')).toContainText('客户尚未给出可交付的验收结论')
  await expect(page.getByTestId('close-formal-delivery')).toBeDisabled()

  await page.getByTestId('acceptance-customer-name').fill('示例客户')
  await page.getByTestId('acceptance-contact-name').fill('业务负责人')
  await page.getByTestId('acceptance-decision').selectOption('accepted')
  await page.getByRole('button', { name: '添加验收项' }).click()
  const item = page.getByTestId('acceptance-items').locator('.grid').first()
  await item.getByPlaceholder('验收项').fill('范围与成果符合合同')
  await item.locator('select').selectOption('accepted')
  await item.getByPlaceholder('证据或会议纪要').fill('验收会议纪要 2026-06-14')
  await page.getByTestId('save-acceptance').click()

  await expect(page.getByTestId('acceptance-summary')).toContainText('可正式关闭')
  await expect(page.getByTestId('close-formal-delivery')).toBeEnabled()
  await page.getByTestId('close-formal-delivery').click()
  await expect(page.getByTestId('acceptance-summary')).toContainText('已关闭')
})
