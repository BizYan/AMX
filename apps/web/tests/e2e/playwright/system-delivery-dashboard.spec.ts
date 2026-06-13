import { expect, test } from '@playwright/test'

import { setupApiMocks } from './fixtures/api-mocks'
import { MOCK_PROJECT } from './fixtures/mock-data'

test.describe('System delivery command center', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
    await page.goto('/login', { waitUntil: 'domcontentloaded' })
    await page.evaluate(() => {
      localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
    })
  })

  test('renders delivery phases, release gates, operating plan, and project queue', async ({ page }) => {
    await page.goto('/dashboard', { waitUntil: 'domcontentloaded' })

    const body = page.locator('body')
    await expect(page.getByRole('heading', { name: '交付总控台' })).toBeVisible()
    await expect(body).toContainText('系统就绪度')
    await expect(body).toContainText('核心模块健康')
    await expect(body).toContainText('交付阶段作战图')
    await expect(body).toContainText('发布门禁')
    await expect(body).toContainText('执行计划')
    await expect(body).toContainText('项目交付队列')
    await expect(body).toContainText('评审追溯')
    await expect(body).toContainText('项目资料就绪')
    await expect(body).toContainText('交付包可导出')
    await expect(body).toContainText(MOCK_PROJECT.name)
    await expect(body).toContainText('知识图谱')
    await expect(body).toContainText('智能编排')
    await expect(body).toContainText('导出中心')
    await expect(body).toContainText('团队与权限')
    await expect(body).toContainText('运维监控与审计')
    await expect(page.getByTestId('milestone-portfolio')).toContainText('评审与追溯')
    await expect(page.getByTestId('milestone-portfolio')).toContainText('逾期 1')
    await expect(page.getByTestId('milestone-owner-load')).toContainText('项目负责人')
    await expect(body).not.toContainText('Application error')
    await expect(body).not.toContainText('This page could not be found')

    const main = page.locator('main')
    await expect(page.getByTestId('production-gate')).toBeVisible()
    await expect(page.getByTestId('production-gate')).toContainText('通知确认与告警处置')
    await expect(body).toContainText('外部集成同步闭环')
    await expect(body).toContainText('协同责任与评审处置')
    await expect(page.getByTestId('production-gate').getByRole('link', { name: /处理通知与告警/ })).toHaveAttribute('href', '/notifications')
    await expect(page.getByTestId('production-gate').getByRole('link', { name: /管理外部集成/ })).toHaveAttribute('href', '/settings?tab=integrations')
    await expect(main.getByRole('link', { name: /知识图谱/ }).first()).toHaveAttribute('href', '/knowledge/graph')
    await expect(main.getByRole('link', { name: /智能编排/ }).first()).toHaveAttribute('href', '/workflows')
    await expect(main.getByRole('link', { name: /导出中心/ }).first()).toHaveAttribute('href', '/exports')
    await expect(main.getByRole('link', { name: /交付包可导出/ }).first()).toHaveAttribute('href', '/exports')
    await expect(main.getByRole('link', { name: /团队与权限/ }).first()).toHaveAttribute('href', '/team')
    await expect(main.getByRole('link', { name: /运维监控与审计/ }).first()).toHaveAttribute('href', '/system-health')
  })
})
