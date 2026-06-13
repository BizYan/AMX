import { expect, Page, test } from '@playwright/test'

import { setupApiMocks } from './fixtures/api-mocks'

async function gotoAppPage(page: Page, path: string) {
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => {
    localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
  })
  await page.goto(path, { waitUntil: 'domcontentloaded' })
}

test.describe('Sidebar navigation taxonomy', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
  })

  test('uses project-document-centered navigation routes', async ({ page }) => {
    await gotoAppPage(page, '/dashboard')

    await expect(page.locator('a[href="/dashboard"]')).toBeVisible()
    const mainHrefs = await page.locator('nav a').evaluateAll((links) =>
      links.map((link) => link.getAttribute('href'))
    )
    expect(mainHrefs).toEqual([
      '/dashboard',
      '/projects',
      '/knowledge/graph',
      '/agents',
      '/agent-ops',
      '/workflows',
      '/templates',
      '/documents/contradictions',
      '/exports',
      '/collaboration',
      '/team',
      '/notifications',
      '/system-health',
      '/providers',
      '/quotas',
      '/audit',
    ])

    await expect(page.locator('nav')).toContainText('运行记录')
    await expect(page.locator('nav')).toContainText('工作流')
    await expect(page.locator('nav')).toContainText('通知中心')
    await expect(page.locator('nav')).toContainText('供应商')
    await expect(page.locator('nav')).toContainText('资源配额')
    await expect(page.locator('nav')).toContainText('审计')
    await expect(page.locator('a[href="/settings"]')).toHaveCount(1)
    await expect(page.locator('nav a[href="/documents"]')).toHaveCount(0)
  })
})
