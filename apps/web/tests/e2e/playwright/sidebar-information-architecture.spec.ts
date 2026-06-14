import { expect, test } from '@playwright/test'

import { setupApiMocks } from './fixtures/api-mocks'

test.describe('Sidebar information architecture', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
    await page.goto('/login', { waitUntil: 'domcontentloaded' })
    await page.evaluate(() => {
      localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
    })
    await page.goto('/dashboard', { waitUntil: 'domcontentloaded' })
  })

  test('groups primary navigation by delivery workflow and removes duplicate entries', async ({ page }) => {
    const sidebar = page.locator('nav').first()

    await expect(page.getByTestId('primary-sidebar')).toHaveCSS('width', '220px')

    await expect(page.getByTestId('sidebar-section-sectionOverview')).toContainText('总览')
    await expect(page.getByTestId('sidebar-section-sectionDelivery')).toContainText('项目交付')
    await expect(page.getByTestId('sidebar-section-sectionIntelligence')).toContainText('智能能力')
    await expect(page.getByTestId('sidebar-section-sectionGovernance')).toContainText('平台治理')

    const expectedLinks = [
      ['个人工作台', '/dashboard'],
      ['交付总览', '/delivery'],
      ['项目文档', '/projects'],
      ['协同评审', '/collaboration'],
      ['变更追溯', '/documents/contradictions'],
      ['交付导出', '/exports'],
      ['智能编排', '/agents'],
      ['模板中心', '/templates'],
      ['团队权限', '/team'],
      ['平台运维', '/system-health'],
      ['审计日志', '/audit'],
      ['系统设置', '/settings'],
    ]

    for (const [name, href] of expectedLinks) {
      await expect(sidebar.getByRole('link', { name, exact: true })).toHaveAttribute('href', href)
    }

    await expect(sidebar.getByRole('link')).toHaveCount(12)
    await expect(sidebar.getByRole('link', { name: '知识图谱', exact: true })).toHaveCount(0)
    await expect(sidebar.getByRole('link', { name: '运行记录', exact: true })).toHaveCount(0)
    await expect(sidebar.getByRole('link', { name: '工作流', exact: true })).toHaveCount(0)
    await expect(sidebar.getByRole('link', { name: '通知中心', exact: true })).toHaveCount(0)
    await expect(sidebar.getByRole('link', { name: '供应商', exact: true })).toHaveCount(0)
    await expect(sidebar.getByRole('link', { name: '资源配额', exact: true })).toHaveCount(0)

    await page.goto('/projects', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('link', { name: '知识总览', exact: true })).toHaveAttribute('href', '/knowledge/graph')
  })

  test('keeps consolidated child routes accessible and highlights their parent entry', async ({ page }) => {
    await page.goto('/agents', { waitUntil: 'domcontentloaded' })
    await page.getByRole('tab', { name: '工作流', exact: true }).click()
    await expect(page.getByRole('link', { name: '打开工作流工作台', exact: true })).toHaveAttribute('href', '/workflows')

    await page.goto('/workflows', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('nav').first().getByRole('link', { name: '智能编排', exact: true })).toHaveAttribute('aria-current', 'page')

    await page.goto('/providers', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('nav').first().getByRole('link', { name: '平台运维', exact: true })).toHaveAttribute('aria-current', 'page')

    await page.goto('/system-health', { waitUntil: 'domcontentloaded' })
    const operationsNavigation = page.getByTestId('platform-operations-navigation')
    await expect(operationsNavigation.getByRole('link', { name: '模型服务' })).toHaveAttribute('href', '/providers')
    await expect(operationsNavigation.getByRole('link', { name: '资源配额' })).toHaveAttribute('href', '/quotas')
  })
})
