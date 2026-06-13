import { expect, Page, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'

async function gotoAppPage(page: Page, path: string) {
  await page.addInitScript(() => {
    localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
  })
  await page.goto(path, { waitUntil: 'domcontentloaded' })
}

test.describe('project traceability and change disposition board', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
  })

  test('reviews upstream impact proposals and records sync decisions', async ({ page }) => {
    await gotoAppPage(page, '/projects/project-e2e-001/traceability')

    await expect(page.getByRole('heading', { name: '追溯与变更处置台' })).toBeVisible()
    await expect(page.getByTestId('trace-coverage-rate')).toContainText('67%')
    await expect(page.getByTestId('trace-matrix')).toContainText('URS')
    await expect(page.getByTestId('trace-matrix')).toContainText('PRD')
    await expect(page.getByTestId('trace-gap-list')).toContainText('测试用例缺失')
    await expect(page.getByTestId('impact-summary')).toContainText('URS 变更影响 PRD')
    await expect(page.getByTestId('impact-summary')).toContainText('人工确认节点')

    await page.getByTestId('trace-search').fill('PRD')
    await expect(page.getByTestId('trace-gap-list')).toContainText('PRD')

    await page.getByTestId('trace-run-analysis').click()
    await page.getByTestId('sync-proposal-select-proposal-e2e-001').click()
    await expect(page.getByTestId('sync-proposal-detail')).toContainText('P0')
    await expect(page.getByTestId('sync-proposal-detail')).toContainText('确认同步到 PRD')

    await page.getByTestId('sync-proposal-confirm-proposal-e2e-001').click()
    await expect(page.getByTestId('trace-feedback')).toContainText('已确认同步')
    await expect(page.getByTestId('sync-proposal-detail')).toContainText('已确认同步')

    await page.getByTestId('trace-search').fill('')
    await page.getByTestId('sync-proposal-select-proposal-e2e-002').click()
    await page.getByTestId('sync-proposal-ignore-proposal-e2e-002').click()
    await expect(page.getByTestId('trace-feedback')).toContainText('已忽略建议')
  })

  test('filters change queue, inspects affected documents, and marks disposition', async ({ page }) => {
    await gotoAppPage(page, '/projects/project-e2e-001/changes')

    await expect(page.getByRole('heading', { name: '变更请求处置台' })).toBeVisible()
    await expect(page.getByTestId('change-queue')).toContainText('URS 变更影响 PRD')
    await expect(page.getByTestId('change-queue')).toContainText('P0')
    await expect(page.getByTestId('change-queue')).toContainText('P1')
    await expect(page.getByTestId('change-queue')).toContainText('P2')
    await expect(page.getByTestId('change-queue')).toContainText('P3')

    await page.getByTestId('change-status-filter').selectOption('triage')
    await expect(page.getByTestId('change-count')).toContainText('1')

    await page.getByTestId('change-search').fill('测试用例缺失')
    await expect(page.getByTestId('change-count')).toContainText('1')
    await page.getByTestId('change-select-change-e2e-002').click()
    await expect(page.getByTestId('change-detail')).toContainText('测试用例缺失')
    await expect(page.getByTestId('change-detail')).toContainText('人工确认节点')

    await page.getByTestId('change-mark-resolved-change-e2e-002').click()
    await expect(page.getByTestId('change-feedback')).toContainText('已标记处置')
    await expect(page.getByTestId('change-recent-records')).toContainText('已标记处置')
  })
})
