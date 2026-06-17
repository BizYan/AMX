import { expect, Page, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { setupApiMocks } from './fixtures/api-mocks'

const repoRoot = join(__dirname, '..', '..', '..', '..', '..')

async function prepareAuthenticatedPage(page: Page) {
  await setupApiMocks(page)
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => {
    localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
  })
}

test('collaboration review hub supports filtering, detail selection, and review actions', async ({ page }) => {
  await prepareAuthenticatedPage(page)

  await page.goto('/collaboration', { waitUntil: 'domcontentloaded' })

  await expect(page.getByRole('heading', { name: '协同验收中心' })).toBeVisible()
  await expect(page.getByTestId('collaboration-acceptance-command-center')).toContainText('协同验收指挥台')
  await expect(page.getByTestId('collaboration-acceptance-gate')).toContainText('验收阻断')
  await expect(page.getByTestId('collaboration-acceptance-command-center')).toContainText('关闭评审与评论阻断')
  await expect(page.getByTestId('collaboration-acceptance-command-center')).toContainText('评论待办未关闭')
  await expect(page.getByTestId('collaboration-member-collab-member-pm')).toContainText('项目经理')
  await expect(page.getByTestId('collaboration-member-collab-member-business')).toContainText('业务顾问')
  await expect(page.getByTestId('collaboration-member-collab-member-tech')).toContainText('技术顾问')
  await expect(page.getByTestId('collaboration-member-collab-member-customer')).toContainText('客户评审人')
  await expect(page.getByTestId('review-status-PASSED')).toContainText('通过验收')
  await expect(page.getByTestId('review-status-BLOCKED')).toContainText('退回修订')
  await expect(page.getByTestId('review-status-PASSED_WITH_FOLLOW_UPS')).toContainText('带跟进项通过')

  await page.getByTestId('collaboration-member-search').fill('客户')
  await expect(page.getByTestId('collaboration-member-collab-member-customer')).toBeVisible()
  await expect(page.getByTestId('collaboration-member-collab-member-tech')).not.toBeVisible()

  await page.getByTestId('collaboration-member-search').fill('')
  await page.getByTestId('collaboration-role-filter').selectOption('技术顾问')
  await expect(page.getByTestId('collaboration-member-collab-member-tech')).toBeVisible()
  await expect(page.getByTestId('collaboration-member-collab-member-business')).not.toBeVisible()

  await page.getByTestId('collaboration-role-filter').selectOption('')
  await page.getByTestId('collaboration-status-filter').selectOption('pending')
  await expect(page.getByTestId('collaboration-member-collab-member-business')).toBeVisible()
  await expect(page.getByTestId('collaboration-member-collab-member-customer')).toBeVisible()
  await expect(page.getByTestId('collaboration-member-collab-member-pm')).not.toBeVisible()

  await page.getByTestId('collaboration-status-filter').selectOption('')
  await page.getByTestId('collaboration-document-search').fill('PRD')
  await expect(page.getByTestId('collaboration-review-review-prd-001')).toBeVisible()
  await expect(page.getByTestId('collaboration-review-review-brd-001')).not.toBeVisible()

  await page.getByTestId('collaboration-document-search').fill('')
  await page.getByTestId('collaboration-review-review-prd-001').click()
  await expect(page.getByTestId('collaboration-review-detail')).toContainText('履约监控 PRD 评审')
  await expect(page.getByTestId('collaboration-review-detail')).toContainText('接口超时策略和追溯字段未确认')
  await expect(page.getByTestId('collaboration-review-detail')).toContainText('快照')
  await expect(page.getByTestId('collaboration-review-detail')).toContainText('基线')

  await page.getByTestId('collaboration-assign-me').click()
  await expect(page.getByText('已领取评审')).toBeVisible()

  await page.getByTestId('collaboration-mark-read').click()
  await expect(page.getByText('已标记已读')).toBeVisible()

  await page.getByTestId('collaboration-pass-acceptance').click()
  await expect(page.getByText('验收已通过')).toBeVisible()
  await expect(page.getByTestId('collaboration-review-detail')).toContainText('通过验收')

  await page.getByTestId('collaboration-return-revision').click()
  await expect(page.getByText('已退回修订')).toBeVisible()
  await expect(page.getByTestId('collaboration-review-detail')).toContainText('退回修订')
})

test('collaboration freshness banner does not synthesize review timestamps', () => {
  const source = readFileSync(join(repoRoot, 'apps/web/src/app/(app)/collaboration/page.tsx'), 'utf8')

  expect(source).not.toContain("reviews[0]?.updated_at || new Date().toISOString()")
  expect(source).toContain("reviews[0]?.updated_at ? formatTime(reviews[0].updated_at) :")
})
