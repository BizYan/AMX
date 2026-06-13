import { expect, Page, test } from '@playwright/test'

import { setupApiMocks } from './fixtures/api-mocks'

async function prepareAuthenticatedPage(page: Page) {
  await setupApiMocks(page)
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef'))
}

test('launches a project from a configurable delivery blueprint', async ({ page }) => {
  await prepareAuthenticatedPage(page)
  await page.goto('/projects', { waitUntil: 'domcontentloaded' })

  await page.getByTestId('open-project-launch').click()
  await expect(page.getByTestId('project-launch-wizard')).toBeVisible()
  await page.getByTestId('launch-blueprint-product-delivery').click()
  await page.getByTestId('launch-next').click()
  await page.getByTestId('launch-project-name').fill('会员平台升级')
  await page.getByTestId('launch-project-description').fill('建立完整需求、设计与测试交付链。')
  await page.getByTestId('launch-next').click()
  await expect(page.getByTestId('launch-document-options')).toContainText('产品需求文档')
  await page.getByTestId('launch-member-user-reviewer-001').click()
  await page.getByTestId('launch-next').click()
  await expect(page.getByTestId('launch-summary')).toContainText('产品需求到交付')
  await page.getByTestId('submit-project-launch').click()

  await expect(page.getByText('项目已启动')).toBeVisible()
})

test('shows launch checks and retries project initialization', async ({ page }) => {
  await prepareAuthenticatedPage(page)
  await page.goto('/projects/project-e2e-001', { waitUntil: 'domcontentloaded' })

  await expect(page.getByTestId('project-launch-status')).toBeVisible()
  await expect(page.getByTestId('project-launch-status')).toContainText('产品需求到交付')
  await expect(page.getByTestId('project-launch-checks')).toContainText('初始交付文档已规划')
  await page.getByTestId('retry-project-launch').click()
  await expect(page.getByText('启动计划已重新检查')).toBeVisible()
})
