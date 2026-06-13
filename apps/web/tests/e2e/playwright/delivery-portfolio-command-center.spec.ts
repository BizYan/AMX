import { expect, test } from '@playwright/test'

import { setupApiMocks } from './fixtures/api-mocks'

test('operates the complete cross-project delivery portfolio', async ({ page }) => {
  await setupApiMocks(page)
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef'))
  await page.goto('/delivery', { waitUntil: 'domcontentloaded' })

  await expect(page.getByRole('heading', { name: '跨项目交付组合' })).toBeVisible()
  await expect(page.getByTestId('delivery-portfolio-summary')).toContainText('逾期')
  await expect(page.getByTestId('delivery-portfolio-table')).toContainText('评审与追溯')

  await page.getByTestId('portfolio-status-filter').selectOption('blocked')
  await expect(page.getByTestId('delivery-portfolio-table')).toContainText('评审与追溯')
  await expect(page.getByTestId('delivery-portfolio-table')).not.toContainText('核心文档编写')

  await page.getByTestId('edit-portfolio-milestone-review-traceability').click()
  await page.getByTestId('portfolio-milestone-priority').selectOption('critical')
  await page.getByTestId('save-portfolio-milestone').click()
  await page.getByTestId('portfolio-status-filter').selectOption('all')
  await expect(page.getByTestId('delivery-portfolio-table')).toContainText('紧急')
})
