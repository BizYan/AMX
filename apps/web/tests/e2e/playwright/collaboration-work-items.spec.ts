import { expect, Page, test } from '@playwright/test'

import { setupApiMocks } from './fixtures/api-mocks'

async function prepareAuthenticatedPage(page: Page) {
  await setupApiMocks(page)
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef'))
}

test('collaboration center manages persistent work items end to end', async ({ page }) => {
  await prepareAuthenticatedPage(page)
  await page.goto('/collaboration', { waitUntil: 'domcontentloaded' })

  await expect(page.getByTestId('collaboration-work-item-board')).toBeVisible()
  await expect(page.getByTestId('work-item-work-item-review')).toContainText('评审履约监控 PRD')

  await page.getByTestId('work-item-assignment-filter').selectOption('unassigned')
  await expect(page.getByTestId('work-item-work-item-unassigned')).toBeVisible()
  await page.getByTestId('work-item-work-item-unassigned').getByRole('button', { name: '领取' }).click()
  await expect(page.getByTestId('work-item-work-item-unassigned')).toContainText('处理中')

  await page.getByTestId('work-item-assignment-filter').selectOption('all')
  await page.getByTestId('work-item-work-item-review').getByRole('button', { name: '完成' }).click()
  await expect(page.getByTestId('work-item-work-item-review')).toContainText('已完成')
  await page.getByTestId('work-item-work-item-review').getByRole('button', { name: '重开' }).click()
  await expect(page.getByTestId('work-item-work-item-review')).toContainText('待处理')

  await page.getByTestId('create-work-item').click()
  await page.getByTestId('work-item-title').fill('组织验收决策会')
  await page.getByTestId('work-item-description').fill('协调业务、技术和客户完成验收决策。')
  await page.getByTestId('work-item-due-at').fill('2026-06-09T10:30')
  await page.getByTestId('work-item-project').selectOption('project-e2e-001')
  await page.getByTestId('work-item-assignee').selectOption('collab-member-tech')
  await page.getByTestId('submit-work-item').click()
  await expect(page.getByText('组织验收决策会')).toBeVisible()
  await expect(page.getByText(/协调业务、技术和客户完成验收决策/)).toBeVisible()
})
