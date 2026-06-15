import { expect, test } from '@playwright/test'

import { setupApiMocks } from './fixtures/api-mocks'

test.describe('Audit evidence center', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
    await page.goto('/login', { waitUntil: 'domcontentloaded' })
    await page.evaluate(() => {
      localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
    })
  })

  test('renders audit risk queue, aggregations, timeline, table, and search', async ({ page }) => {
    await page.goto('/audit', { waitUntil: 'domcontentloaded' })

    const body = page.locator('body')
    await expect(page.getByRole('heading', { name: '审计证据中心' })).toBeVisible()
    await expect(body).toContainText('审计事件')
    await expect(body).toContainText('高风险事件')
    await expect(body).toContainText('风险事件队列')
    await expect(body).toContainText('实体影响聚合')
    await expect(body).toContainText('审计时间线')
    await expect(body).toContainText('明细表')
    await expect(page.getByTestId('change-audit-command-center')).toContainText('变更追溯指挥台')
    await expect(page.getByTestId('change-audit-release-gate')).toContainText('发布阻断')
    await expect(page.getByTestId('change-audit-command-center')).toContainText('处理文档追溯与同步建议')
    await expect(body).toContainText('为系统管理员分配管理员角色')
    await expect(body).toContainText('删除占位验收报告草稿')
    await expect(body).toContainText('生成项目交付包并保留导出证据')
    await expect(page.getByTestId('change-audit-command-center')).toContainText('Document conflicts')
    await expect(page.getByTestId('change-audit-command-center')).toContainText('Resolve document conflict governance queue')
    await expect(page.getByTestId('change-audit-command-center')).toContainText('High-severity document conflicts are unresolved')
    await expect(page.locator('[data-testid="audit-entry"]')).toHaveCount(5)
    await expect(page.locator('[data-testid="audit-table"]')).toBeVisible()

    await page.getByTestId('audit-search').fill('交付包')
    await expect(page.locator('[data-testid="audit-entry"]')).toHaveCount(1)
    await expect(body).toContainText('生成项目交付包并保留导出证据')
    await expect(body).not.toContainText('删除占位验收报告草稿')
  })
})
