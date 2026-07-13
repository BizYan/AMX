import { expect, Page, test } from '@playwright/test'
import { Buffer } from 'node:buffer'
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

  test('uploads a source file and shows knowledge availability evidence after ingestion', async ({ page }) => {
    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'source-to-knowledge-marker.md',
      mimeType: 'text/markdown',
      buffer: Buffer.from('# Source evidence\n\nAMX-SOURCE-TO-KNOWLEDGE-UI-MARKER is ready for ingestion.'),
    })

    await expect(page.getByText('已进入知识摄取队列').first()).toBeVisible()
    await expect(page.getByText('new-source.txt')).toBeVisible()

    const executeButton = page.locator('[data-testid^="execute-ingestion-file-uploaded-"]').first()
    await expect(executeButton).toBeVisible()
    await executeButton.click()

    const evidence = page.locator('[data-testid^="source-knowledge-evidence-file-uploaded-"]').first()
    await expect(evidence).toContainText('知识可检索')
    await expect(evidence).toContainText('查看来源追溯')
  })

  test('shows searchable source lineage in the normal project knowledge route', async ({ page }) => {
    await gotoAppPage(page, '/projects/project-e2e-001/knowledge')
    await page.getByTestId('project-knowledge-search').fill('仓储批次分配规则')

    const entry = page.getByTestId('knowledge-entry-entry-source-ready-001')
    await expect(entry).toBeVisible()
    await expect(entry).toHaveAttribute('data-source-file-id', 'file-e2e-ready')
    await expect(page.getByTestId('knowledge-entry-lineage-entry-source-ready-001')).toContainText('仓储升级招标文件.pdf')
  })
})
