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

  test('shows the read-only release evidence console and exports sanitized JSON', async ({ page }) => {
    await gotoAppPage(page, '/system-health')

    const dashboard = page.getByTestId('ops-readiness-dashboard')
    await expect(dashboard).toBeVisible()
    await expect(dashboard.getByRole('heading', { name: 'Release Evidence Console' })).toBeVisible()
    await expect(dashboard).toContainText('blocked')
    await expect(dashboard).toContainText('production')
    await expect(dashboard).toContainText('Runtime SHA')
    await expect(dashboard).toContainText('Expected SHA')
    await expect(dashboard).toContainText('SHA match')
    await expect(dashboard.getByRole('link', { name: 'Candidate verification' })).toHaveAttribute(
      'href',
      'https://github.com/BizYan/AMX/actions/runs/123456780',
    )
    await expect(dashboard.getByRole('link', { name: 'Production deployment' })).toHaveAttribute(
      'href',
      'https://github.com/BizYan/AMX/actions/runs/123456789',
    )
    await expect(dashboard).toContainText('Provenance')
    await expect(dashboard).toContainText('Latest evidence export')
    await expect(dashboard).toContainText('Provider readiness is not production-ready.')
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
    await expect(dashboard).toContainText('Operational metric failure recorded')
    await expect(dashboard).toContainText('sanitized')
    await expect(dashboard).not.toContainText(/api[_-]?key|token|secret/i)

    const downloadPromise = page.waitForEvent('download')
    await dashboard.getByRole('button', { name: 'Export sanitized evidence' }).click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toBe('amx-release-evidence.json')
  })
})
