import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, Page, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'

const repoRoot = join(__dirname, '..', '..', '..', '..', '..')

async function prepareAuthenticatedPage(page: Page) {
  await setupApiMocks(page)
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => {
    localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
  })
}

test.describe('Document contradiction resolution center', () => {
  test.beforeEach(async ({ page }) => {
    await prepareAuthenticatedPage(page)
  })

  test('detects document conflicts and records review decisions', async ({ page }) => {
    await page.goto('/documents/contradictions', { waitUntil: 'domcontentloaded' })

    await expect(page.getByTestId('contradiction-resolution-center')).toBeVisible()
    await expect(page.getByRole('heading', { name: '冲突解析中心' })).toBeVisible()
    await expect(page.getByTestId('contradiction-summary')).not.toContainText('0')
    await expect(page.getByTestId('contradiction-detail-panel')).toContainText('处置详情')
    await expect(page.getByTestId('contradiction-detail-panel')).toContainText(/建议动作|证据/)

    await page.getByTestId('contradiction-generate-analysis').click()
    await expect(page.getByTestId('contradiction-detail-panel')).toContainText('已生成分析')
    await expect(page.locator('body')).toContainText('等待负责人确认')

    await page.getByTestId('contradiction-accept-revision').click()
    await expect(page.getByTestId('contradiction-detail-panel')).toContainText('已接受修订')
    await expect(page.getByTestId('contradiction-history')).toContainText('已接受修订')

    await page.getByTestId('contradiction-state-filter').selectOption('accepted')
    await expect(page.getByTestId('contradiction-resolution-center')).toContainText('已接受修订')

    await page.getByTestId('contradiction-search').fill('缺少')
    await expect(page.getByTestId('contradiction-resolution-center')).toContainText(/缺少|当前筛选下没有冲突/)
  })

  test('surfaces persisted governance conflicts and records backend decisions', async ({ page }) => {
    await page.goto('/documents/contradictions', { waitUntil: 'domcontentloaded' })

    await expect(page.getByTestId('persisted-conflict-governance')).toContainText('Persisted conflict governance')
    await expect(page.getByTestId('persisted-conflict-governance')).toContainText('High-severity downstream document mismatch')
    await expect(page.getByTestId('persisted-conflict-governance')).toContainText('unassigned')
    await expect(page.getByTestId('persisted-conflict-history-conflict-e2e-001')).toContainText('Conflict decision history')
    await expect(page.getByTestId('persisted-conflict-history-conflict-e2e-001')).toContainText('assign')

    let acceptRiskPayload: Record<string, unknown> | undefined
    await page.route(/\/api\/v1\/change\/conflicts\/[^/]+\/accept-risk$/, async (route) => {
      acceptRiskPayload = JSON.parse(route.request().postData() || '{}')
      await route.fallback()
    })

    await page.getByTestId('persisted-conflict-accept-risk-conflict-e2e-001').click()

    expect(acceptRiskPayload).toBeDefined()
    expect(acceptRiskPayload).not.toHaveProperty('accepted_until')
    await expect(page.getByTestId('persisted-conflict-governance')).toContainText('risk_accepted')
    await expect(page.getByTestId('persisted-conflict-governance')).toContainText('Risk accepted until')
    await expect(page.getByTestId('persisted-conflict-history-conflict-e2e-001')).toContainText('accept_risk')
  })

  test('runs persisted scans and lets the current operator claim conflicts', async ({ page }) => {
    await page.goto('/documents/contradictions', { waitUntil: 'domcontentloaded' })

    await page.getByTestId('persisted-conflict-scan').click()

    await expect(page.getByTestId('persisted-conflict-governance')).toContainText('Scan detected 2 persisted conflicts')
    await expect(page.getByTestId('persisted-conflict-governance')).toContainText('New scan-generated downstream mismatch')

    await page.getByTestId('persisted-conflict-claim-conflict-e2e-001').click()

    await expect(page.getByTestId('persisted-conflict-governance')).toContainText('Assigned to me')
  })

  test('local contradiction decisions use conflict evidence time', () => {
    const source = readFileSync(join(repoRoot, 'apps/web/src/app/(app)/documents/contradictions/page.tsx'), 'utf8')

    expect(source).toContain('function getConflictEvidenceTimestamp')
    expect(source).toContain('decidedAt: getConflictEvidenceTimestamp(conflict)')
    expect(source).not.toContain('decidedAt: new Date().toISOString()')
  })
})
