import { expect, Page, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'

async function gotoAppPage(page: Page, path: string) {
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => {
    localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
  })
  await page.goto(path, { waitUntil: 'domcontentloaded' })
}

test.describe('智能编排 / Agent 配置中心', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
  })

  test('agents page renders non-empty agents, skills, workflows, and recent runs', async ({ page }) => {
    await gotoAppPage(page, '/agents')

    await expect(page.getByRole('heading', { name: '智能编排中心' })).toBeVisible()
    await expect(page.getByTestId('agent-center-summary')).toContainText('活跃 Agent')
    await expect(page.getByTestId('agent-card-agent-profile-e2e-prd')).toContainText('PRD 产品方案顾问')
    await expect(page.getByTestId('agent-card-agent-profile-e2e-prd')).toContainText('文档评审器')
    await expect(page.getByTestId('agent-card-agent-profile-e2e-prd')).toContainText('PRD 审查流水线')
    await expect(page.getByTestId('skill-card-skill-e2e-reviewer')).toContainText('系统级')
    await expect(page.getByTestId('skill-card-skill-e2e-reviewer')).toContainText('适用文档')
    await expect(page.getByTestId('run-row-run-e2e-001')).toContainText('PRD 审查流水线')
  })

  test('skill marketplace supports search and displays test execution result', async ({ page }) => {
    await gotoAppPage(page, '/agents')

    await page.getByRole('tab', { name: 'Skill 市场' }).click()
    await page.getByTestId('skill-search-input').fill('评审')
    await expect(page.getByTestId('skill-card-skill-e2e-reviewer')).toContainText('文档评审器')

    await page.getByTestId('skill-test-skill-e2e-reviewer').click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('测试 Skill')
    await expect(page.getByTestId('skill-test-input-json')).toContainText('发运复核')
    await page.getByRole('button', { name: '运行测试' }).click()
    await expect(dialog).toContainText('测试输入满足 Skill 契约', { timeout: 8000 })
    await expect(dialog).toContainText('score')
  })

  test('agent cards can trigger a run through the mocked API', async ({ page }) => {
    await gotoAppPage(page, '/agents')

    await page.getByTestId('agent-run-agent-profile-e2e-prd').click()
    await expect(page.locator('body')).toContainText('Agent 已开始运行', { timeout: 8000 })
    await page.getByRole('tab', { name: '运行记录' }).click()
    await expect(page.getByTestId('run-row-run-new-001')).toContainText('PRD 产品方案顾问')
    await expect(page.getByTestId('run-row-run-new-001')).toContainText('run-new-001')
  })

  test('agent search and run filters remain usable with production empty states', async ({ page }) => {
    await gotoAppPage(page, '/agents')

    await page.getByRole('tab', { name: 'Agent' }).click()
    await page.getByTestId('agent-search-input').fill('不存在的 Agent')
    await expect(page.getByTestId('agent-empty-state')).toContainText('没有匹配的 Agent')

    await page.getByTestId('agent-search-input').fill('PRD')
    await expect(page.getByTestId('agent-card-agent-profile-e2e-prd')).toBeVisible()

    await page.getByRole('tab', { name: '运行记录' }).click()
    await page.getByTestId('run-status-filter').selectOption('failed')
    await expect(page.getByTestId('run-row-run-e2e-failed')).toContainText('失败')
    await page.getByTestId('run-search-input').fill('没有这个运行')
    await expect(page.getByTestId('run-empty-state')).toContainText('没有匹配的运行记录')
  })

  test('agents page exposes refresh feedback and governance permission status', async ({ page }) => {
    await gotoAppPage(page, '/agents')

    await page.getByTestId('agent-center-refresh').click()
    await expect(page.locator('body')).toContainText('智能编排数据已刷新', { timeout: 8000 })
    await expect(page.getByTestId('agent-card-agent-profile-e2e-prd')).toContainText('需要人工复核')
    await expect(page.getByTestId('agent-card-agent-profile-e2e-prd')).toContainText('权限状态')
    await expect(page.getByTestId('agent-card-agent-profile-e2e-change')).toContainText('草稿状态不可运行')
  })

  test('agents page can explicitly bootstrap orchestration defaults', async ({ page }) => {
    await gotoAppPage(page, '/agents')

    await page.getByTestId('agent-center-bootstrap').click()
    await expect(page.locator('body')).toContainText('智能编排已初始化', { timeout: 8000 })
    await expect(page.getByTestId('agent-card-agent-profile-e2e-prd')).toBeVisible()
    await expect(page.getByTestId('skill-card-skill-e2e-reviewer')).toBeVisible()
  })

  test('agent ops page shows run details with tasks, events, progress, and failure reason', async ({ page }) => {
    await gotoAppPage(page, '/agent-ops')

    await expect(page.getByRole('heading', { name: 'Agent 运行中心' })).toBeVisible()
    await expect(page.getByTestId('agent-ops-summary')).toContainText('可观测事件')
    await page.getByTestId('agent-run-view-run-e2e-failed').click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('运行详情')
    await expect(dialog).toContainText('变更影响分析顾问')
    await expect(dialog).toContainText('失败原因')
    await expect(dialog).toContainText('同步建议缺少引用证据')
    await expect(dialog).toContainText('任务进度')
    await expect(dialog).toContainText('impact_review')
    await expect(dialog).toContainText('node_failed')
  })

  test('agent ops retry and cancel actions call APIs and refresh state', async ({ page }) => {
    await gotoAppPage(page, '/agent-ops')

    await expect(page.getByTestId('agent-run-retry-run-e2e-001')).toBeDisabled()
    await expect(page.getByTestId('agent-run-retry-run-e2e-001')).toHaveAttribute('title', /仅失败运行可重试/)

    await page.getByTestId('agent-run-retry-run-e2e-failed').click()
    await expect(page.locator('body')).toContainText('已重新排队', { timeout: 8000 })
    await expect(page.getByTestId('agent-run-row-run-retry-001')).toContainText('等待执行')

    await page.getByTestId('agent-run-cancel-run-e2e-running').click()
    await expect(page.locator('body')).toContainText('运行已取消', { timeout: 8000 })
    await expect(page.getByTestId('agent-run-row-run-e2e-running')).toContainText('已取消')
  })

  test('agent ops can approve a paused workflow control gate and refresh evidence', async ({ page }) => {
    await gotoAppPage(page, '/agent-ops')

    await expect(page.getByTestId('agent-ops-summary')).toContainText('待控制处理')
    await expect(page.getByTestId('agent-run-row-run-e2e-approval')).toContainText('需人工处理')

    await page.getByTestId('agent-run-view-run-e2e-approval').click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('编排控制台')
    await expect(dialog).toContainText('人工审批')
    await expect(dialog).toContainText('workflow_paused_for_control')

    await page.getByTestId('agent-run-control-approve').click()
    await expect(page.locator('body')).toContainText('已通过控制节点', { timeout: 8000 })
    await expect(dialog).toContainText('control_approve', { timeout: 8000 })
    await expect(dialog).toContainText('恢复执行')
    await expect(dialog).not.toContainText('需人工处理')
  })

  test('agent ops can resume a delayed workflow control gate', async ({ page }) => {
    await gotoAppPage(page, '/agent-ops')

    await expect(page.getByTestId('agent-run-row-run-e2e-delay')).toContainText('待恢复')

    await page.getByTestId('agent-run-view-run-e2e-delay').click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('编排控制台')
    await expect(dialog).toContainText('延迟等待')
    await expect(dialog).toContainText('预计恢复')
    await expect(dialog).toContainText('workflow_paused_for_delay')

    await page.getByTestId('agent-run-control-resume').click()
    await expect(page.locator('body')).toContainText('已恢复运行', { timeout: 8000 })
    await expect(dialog).toContainText('control_resume', { timeout: 8000 })
  })

  test('agent ops has a deterministic empty state when filters match nothing', async ({ page }) => {
    await gotoAppPage(page, '/agent-ops')

    await page.getByTestId('agent-ops-search-input').fill('不存在的运行')
    await expect(page.getByTestId('agent-ops-empty-state')).toContainText('没有匹配的运行记录')
  })
})
