import { expect, test } from '@playwright/test'

import { setupApiMocks } from './fixtures/api-mocks'

test.describe('Team permission control center', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
    await page.goto('/login', { waitUntil: 'domcontentloaded' })
    await page.evaluate(() => {
      localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
    })
  })

  test('shows the tenant member list by default', async ({ page }) => {
    await page.goto('/team', { waitUntil: 'domcontentloaded' })

    await expect(page.getByRole('tab', { name: '成员' })).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByRole('heading', { name: '租户成员列表', exact: true })).toBeVisible()
    await expect(page.getByText('业务验收负责人', { exact: true })).toBeVisible()
  })

  test('renders member, role, policy, field permission, and audit workflows', async ({ page }) => {
    await page.route('**/api/v1/identity/permission-diagnostics*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          generated_at: '2026-06-04T13:30:00Z',
          tenant_id: 'tenant-e2e-001',
          user_id: 'user-e2e-001',
          summary: { total: 4, allowed: 3, denied: 1, field_restricted: 1 },
          checks: [
            { key: 'projects.read', label: '项目资料读取', resource: 'projects', action: 'read', allowed: true, reason: 'rbac' },
            { key: 'documents.export', label: '导出交付包', resource: 'documents', action: 'export', allowed: false, reason: 'deny_policy' },
            { key: 'team.read', label: '团队权限读取', resource: 'team', action: 'read', allowed: true, reason: 'rbac' },
            { key: 'agents.manage', label: '智能编排管理', resource: 'agents', action: 'manage', allowed: true, reason: 'rbac' },
          ],
          field_controls: [
            { role_id: 'role-member', role_name: '普通成员', resource_type: 'document', field_name: 'commercial_terms', permission: 'none' },
          ],
          policy_evidence: [
            { id: 'policy-export-deny', name: '非批准文档禁止导出', effect: 'deny', actions: ['export'], resources: ['documents'] },
          ],
        }),
      })
    })

    await page.goto('/team', { waitUntil: 'domcontentloaded' })
    await page.getByRole('tab', { name: '总览' }).click()

    const body = page.locator('body')
    await expect(page.getByRole('heading', { name: '团队权限', exact: true })).toBeVisible()
    await expect(page.getByTestId('team-permission-command-center')).toContainText('权限治理指挥台')
    await expect(page.getByTestId('team-permission-release-gate')).toContainText('权限阻断')
    await expect(page.getByTestId('team-permission-command-center')).toContainText('复核权限自检拒绝项')
    await expect(page.getByTestId('team-permission-command-center')).toContainText('字段级权限限制生效')
    await expect(body).toContainText('租户成员')
    await expect(body).toContainText('角色授权覆盖')
    await expect(body).toContainText('权限风险队列')
    await expect(body).toContainText('权限自检')
    await expect(body).toContainText('导出交付包')
    await expect(body).toContainText('拒绝')
    await expect(body).toContainText('字段管控')
    await expect(page.getByTestId('team-production-evidence-grid')).toBeVisible()
    await expect(page.getByTestId('team-production-evidence-policy_count')).toContainText('2')
    await expect(page.getByTestId('team-production-evidence-field_permission_count')).toContainText('5')
    await expect(page.getByTestId('team-activation-action-seed_team_permission_evidence')).toBeEnabled()
    await page.getByTestId('team-activation-action-seed_team_permission_evidence').click()
    await expect(page.getByTestId('team-role-template-panel')).toContainText('标准角色模板')
    await expect(page.getByTestId('team-create-role-template-consultant')).toBeEnabled()
    await page.getByTestId('team-create-role-template-consultant').click()
    await expect(body).toContainText('角色模板已创建')
    await expect(page.getByRole('main').getByRole('link', { name: '审计日志', exact: true })).toHaveAttribute('href', '/audit')

    await page.getByRole('tab', { name: '成员' }).click()
    await expect(body).toContainText('租户成员列表')
    await expect(body).toContainText('业务验收负责人')
    await page.getByRole('button', { name: '新增成员' }).first().click()
    await expect(page.getByRole('dialog')).toContainText('新增成员')
    await page.getByLabel('姓名').fill('交付顾问')
    await page.getByLabel('邮箱').fill('consultant@example.com')
    await page.getByRole('button', { name: '创建成员' }).click()
    await expect(body).toContainText('成员已创建')
    await page.getByRole('button', { name: '撤销 管理员' }).click()
    await expect(body).toContainText('角色已撤销')

    await page.getByRole('tab', { name: '角色矩阵' }).click()
    await expect(body).toContainText('角色权限矩阵')
    await page.getByRole('button', { name: '编辑' }).first().click()
    await expect(page.getByRole('dialog')).toContainText('编辑角色')
    await page.getByLabel('说明').fill('系统全部操作权限，按月复核。')
    await page.getByRole('button', { name: '保存角色' }).click()
    await expect(body).toContainText('角色已更新')
    await page.getByRole('button', { name: '新建角色' }).click()
    await expect(page.getByRole('dialog')).toContainText('新建角色')
    await page.getByLabel('角色名称').fill('文档评审负责人')
    await page.getByLabel('说明').fill('负责文档评审和批准前检查')
    await page.getByRole('button', { name: '创建角色' }).click()
    await expect(body).toContainText('角色已创建')

    await page.getByRole('tab', { name: '策略' }).click()
    await expect(body).toContainText('ABAC 策略')
    await expect(body).toContainText('非批准文档禁止导出')
    await page.getByRole('button', { name: '编辑' }).first().click()
    await expect(page.getByRole('dialog')).toContainText('编辑策略')
    await page.getByLabel('说明').fill('仅允许访问当前租户下的项目、文档和编排记录，按发布前复核。')
    await page.getByRole('button', { name: '保存策略' }).click()
    await expect(body).toContainText('策略已更新')
    await page.getByRole('button', { name: '新建策略' }).click()
    await expect(page.getByRole('dialog')).toContainText('新建策略')
    await page.getByLabel('策略名称').fill('项目内成员访问策略')
    await page.getByRole('button', { name: '创建策略' }).click()
    await expect(body).toContainText('策略已创建')
    await page.getByRole('button', { name: '删除' }).first().click()
    await expect(body).toContainText('策略已删除')

    await page.getByRole('tab', { name: '字段权限' }).click()
    await expect(body).toContainText('字段级权限')
    await expect(body).toContainText('商务条款')
    await page.getByRole('combobox').last().selectOption('none')
    await expect(body).toContainText('字段权限已保存')

    await page.getByRole('tab', { name: '权限模拟' }).click()
    await expect(page.getByTestId('team-permission-simulation-panel')).toContainText('权限模拟器')
    await page.getByTestId('team-run-permission-simulation').click()
    await expect(page.getByTestId('team-permission-simulation-result')).toContainText('后端判定拒绝')
    await expect(page.getByTestId('team-permission-simulation-result')).toContainText('非批准文档禁止导出')
    await expect(page.getByTestId('team-permission-simulation-result')).toContainText('商务条款')

    await page.getByRole('tab', { name: '审计' }).click()
    await expect(body).toContainText('权限审计')
    await expect(body).toContainText('为系统管理员分配管理员角色')
    await expect(page.getByRole('link', { name: '打开审计中心' })).toHaveAttribute('href', '/audit')
  })
})
