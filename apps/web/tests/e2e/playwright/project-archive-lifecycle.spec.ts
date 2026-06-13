import { expect, Page, test } from '@playwright/test'

import { setupApiMocks } from './fixtures/api-mocks'
import { MOCK_PROJECT } from './fixtures/mock-data'

async function prepareAuthenticatedPage(page: Page) {
  await setupApiMocks(page)
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef'))
}

test('archives and restores projects from separate lifecycle views', async ({ page }) => {
  await prepareAuthenticatedPage(page)

  let status = 'active'
  await page.route(/\/api\/v1\/projects(?:\?.*)?$/, async (route) => {
    const requestedStatus = new URL(route.request().url()).searchParams.get('status') || 'active'
    const items = requestedStatus === status ? [{ ...MOCK_PROJECT, status }] : []
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items, total: items.length, page: 1, page_size: 20, has_more: false }),
    })
  })
  await page.route(/\/api\/v1\/projects\/project-e2e-001\/(archive|restore)$/, async (route) => {
    status = route.request().url().endsWith('/archive') ? 'archived' : 'active'
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...MOCK_PROJECT, status }),
    })
  })

  await page.goto('/projects', { waitUntil: 'domcontentloaded' })
  await expect(page.getByTestId('project-card-project-e2e-001')).toBeVisible()
  await page.getByTestId('project-actions-project-e2e-001').click()
  await page.getByTestId('project-archive-project-e2e-001').click()
  await expect(page.getByTestId('project-card-project-e2e-001')).toHaveCount(0)

  await page.getByTestId('project-view-archived').click()
  await expect(page.getByTestId('project-card-project-e2e-001')).toContainText('已归档')
  await page.getByTestId('project-actions-project-e2e-001').click()
  await page.getByTestId('project-restore-project-e2e-001').click()
  await expect(page.getByTestId('project-card-project-e2e-001')).toHaveCount(0)

  await page.getByTestId('project-view-active').click()
  await expect(page.getByTestId('project-card-project-e2e-001')).toBeVisible()
})
