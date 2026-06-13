import { expect, Page, test } from '@playwright/test'

import { setupApiMocks } from './fixtures/api-mocks'

async function prepare(page: Page) {
  await setupApiMocks(page)
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef'))
}

test('operates an executable project delivery plan', async ({ page }) => {
  await prepare(page)
  await page.goto('/projects/project-e2e-001/plan', { waitUntil: 'domcontentloaded' })

  await expect(page.getByTestId('delivery-plan-summary')).toContainText('25%')
  await expect(page.getByTestId('delivery-plan-milestones')).toContainText('评审与追溯')
  await expect(page.getByTestId('milestone-review-traceability')).toContainText('文档必须批准或发布')
  await page.getByTestId('start-milestone-core-authoring').click()
  await expect(page.getByText('里程碑已开始')).toBeVisible()
  await page.getByTestId('open-create-milestone').click()
  await page.getByTestId('milestone-title').fill('客户验收')
  await page.getByTestId('create-milestone').click()
  await expect(page.getByTestId('delivery-plan-milestones')).toContainText('客户验收')
})
