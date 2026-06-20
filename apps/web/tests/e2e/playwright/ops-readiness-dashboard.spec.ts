import { expect, Page, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'

async function gotoAppPage(page: Page, path: string) {
  try {
    await page.goto(path, { waitUntil: 'domcontentloaded' })
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    if (!message.includes('net::ERR_ABORTED')) {
      throw error
    }
    await page.goto(path, { waitUntil: 'domcontentloaded' })
  }
}

test.describe('ops readiness dashboard evidence', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
    await gotoAppPage(page, '/login')
    await page.evaluate(() => {
      localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
    })
  })

  test('shows sanitized production readiness evidence and export boundary', async ({ page }) => {
    await gotoAppPage(page, '/system-health')

    const dashboard = page.getByTestId('ops-readiness-dashboard')
    await expect(dashboard).toBeVisible()
    await expect(dashboard).toContainText('Provider readiness')
    await expect(dashboard).toContainText('67%')
    await expect(dashboard).toContainText('Capability readiness')
    await expect(dashboard).toContainText('Quota')
    await expect(dashboard).toContainText('v1.0.1')
    await expect(dashboard).toContainText('Smoke')
    await expect(dashboard).toContainText('passed')
    await expect(dashboard).toContainText('GitNexus')
    await expect(dashboard).toContainText('Agent health')
    await expect(dashboard).toContainText('Latest critical failures')
    await expect(dashboard).toContainText('error:provider_timeout')
    await expect(dashboard).toContainText('sanitized')
    await expect(dashboard).not.toContainText(/api[_-]?key|token|secret/i)
  })
})
