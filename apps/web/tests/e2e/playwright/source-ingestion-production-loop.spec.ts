import { expect, Page, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'

async function gotoAppPage(page: Page, path: string) {
  await page.goto(path, { waitUntil: 'domcontentloaded' })
}

test.describe('Source ingestion production loop', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
    await gotoAppPage(page, '/login')
    await page.evaluate(() => localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef'))
    await gotoAppPage(page, '/projects/project-e2e-001/files')
  })

  test('executes queued ingestion, retries failures, and reingests ready sources', async ({ page }) => {
    await expect(page.getByTestId('execute-ingestion-file-e2e-processing')).toBeVisible()
    await page.getByTestId('execute-ingestion-file-e2e-processing').click()
    await expect(page.getByTestId('reingest-source-file-e2e-processing')).toBeVisible()

    await expect(page.getByTestId('retry-ingestion-file-e2e-failed')).toBeVisible()
    await page.getByTestId('retry-ingestion-file-e2e-failed').click()
    await expect(page.getByTestId('execute-ingestion-file-e2e-failed')).toBeVisible()

    await expect(page.getByTestId('reingest-source-file-e2e-ready')).toBeVisible()
    await page.getByTestId('reingest-source-file-e2e-ready').click()
    await expect(page.getByTestId('execute-ingestion-file-e2e-ready')).toBeVisible()
  })
})
