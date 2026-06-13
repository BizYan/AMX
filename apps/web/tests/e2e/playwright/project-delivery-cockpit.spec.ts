import { expect, Page, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'

async function gotoAppPage(page: Page, path: string) {
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => {
    localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
  })
  await page.goto(path, { waitUntil: 'domcontentloaded' })
}

test.describe('P1 project delivery cockpit', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
  })

  test('summarizes delivery readiness, risks, and next actions on project overview', async ({ page }) => {
    await gotoAppPage(page, '/projects/project-e2e-001')

    await expect(page.getByTestId('project-delivery-cockpit')).toBeVisible({ timeout: 8000 })
    await expect(page.getByTestId('delivery-kpi-documents')).toHaveText('3')
    await expect(page.getByTestId('delivery-kpi-knowledge')).toHaveText('2')
    await expect(page.getByTestId('delivery-kpi-pending-sync')).toHaveText('1')
    await expect(page.getByTestId('delivery-status-matrix')).toContainText('草稿')
    await expect(page.getByTestId('delivery-status-draft')).toContainText('1')
    await expect(page.getByTestId('delivery-source-ready')).toContainText('1')
    await expect(page.getByTestId('delivery-traceability-health')).toContainText('待同步 1')

    await expect(page.getByTestId('delivery-chain-urs')).toContainText('已发布')
    await expect(page.getByTestId('delivery-chain-brd')).toContainText('待生成')
    await expect(page.getByTestId('delivery-chain-prd')).toContainText('草稿')
    await expect(page.getByTestId('delivery-chain-test_case')).toContainText('待生成')
    await expect(page.getByTestId('delivery-stage-brd')).toContainText('缺口')

    await expect(page.getByTestId('review-queue-list')).toContainText('产品需求文档')
    await expect(page.getByTestId('delivery-risk-list')).toContainText('有待处理的影响同步提案')
    await expect(page.getByTestId('delivery-risk-list')).toContainText('交付链路缺少关键文档')
    await expect(page.getByTestId('delivery-action-plan')).toContainText('处理影响同步')
    await expect(page.getByTestId('next-action-review_traceability_sync')).toContainText('处理影响同步')
  })
})
