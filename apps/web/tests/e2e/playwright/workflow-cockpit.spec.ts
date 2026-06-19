import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, Page, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'

const repoRoot = join(__dirname, '..', '..', '..', '..', '..')

async function gotoAppPage(page: Page, path: string) {
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => {
    localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
  })
  await page.goto(path, { waitUntil: 'domcontentloaded' })
}

test.describe('智能编排工作台与编辑器', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
  })

  test('展示生产闭环驾驶舱、模板库，并支持从模板创建工作流', async ({ page }) => {
    await gotoAppPage(page, '/workflows')

    await expect(page.getByRole('heading', { name: '智能编排工作台' })).toBeVisible()
    await expect(page.getByTestId('orchestration-readiness-band')).toContainText('生产就绪度')
    await expect(page.getByTestId('orchestration-maturity-links')).toContainText('项目文档联动')
    await expect(page.getByTestId('workflow-template-library')).toContainText('BRD 文档生成流水线')

    await page.getByTestId('workflow-template-create-change-impact-governance').click()
    await expect(page.locator('body')).toContainText('已从模板创建工作流', { timeout: 8000 })
    await expect(page.getByTestId('workflow-card-workflow-from-template-change-impact-governance')).toContainText('变更影响治理流水线')
  })

  test('工作流工作台展示可执行工作流并触发运行', async ({ page }) => {
    await gotoAppPage(page, '/workflows')

    await expect(page.getByTestId('workflow-ops-summary')).toContainText('工作流总数')
    await expect(page.getByTestId('workflow-card-workflow-e2e-prd')).toContainText('PRD')
    await expect(page.getByTestId('workflow-ops-detail')).toContainText('执行视图')
    await expect(page.getByTestId('workflow-production-preflight')).toContainText('生产预检')
    await expect(page.getByTestId('workflow-production-preflight')).toContainText('DAG 校验通过')
    await expect(page.getByTestId('workflow-preflight-gate')).toBeVisible()

    await page.getByTestId('workflow-run-workflow-e2e-prd').click()
    await expect(page.locator('body')).toContainText('工作流已进入执行队列', { timeout: 8000 })
    await expect(page).toHaveURL(/\/agent-ops/)
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('export_package')
    await expect(dialog).toContainText('node_provider_or_tool_reference')
    await expect(dialog).toContainText('artifact-e2e-new')
  })

  test('workflow detail links recent runs to the operations center', async ({ page }) => {
    await gotoAppPage(page, '/workflows')

    await expect(page.getByTestId('workflow-recent-runs')).toBeVisible()
    await page.getByTestId('workflow-recent-run-run-e2e-running').click()

    await expect(page).toHaveURL(/\/agent-ops\?runId=run-e2e-running/)
    await expect(page.getByRole('dialog')).toContainText('run-e2e-running')
  })

  test('工作流编辑器支持添加节点、校验和发布', async ({ page }) => {
    await gotoAppPage(page, '/workflows/new/editor')

    await expect(page.getByRole('button', { name: '发布', exact: true })).toBeDisabled()
    await page.getByRole('button', { name: '需求澄清' }).click()
    await expect(page.getByTestId('workflow-visual-canvas')).toContainText('需求澄清')

    await page.getByRole('button', { name: '校验' }).click()
    await expect(page.locator('body')).toContainText('工作流校验通过', { timeout: 8000 })

    await page.getByRole('button', { name: '发布', exact: true }).click()
    await expect(page.locator('body')).toContainText('工作流已发布', { timeout: 8000 })
  })

  test('成熟版编辑器支持控制节点和运行计划预览', async ({ page }) => {
    await gotoAppPage(page, '/workflows/new/editor')

    await page.getByRole('button', { name: '需求澄清' }).click()
    await page.getByRole('button', { name: '条件分支' }).click()
    await page.getByRole('button', { name: '人工审批' }).click()

    await expect(page.getByTestId('workflow-visual-canvas')).toBeVisible()
    await expect(page.getByTestId('workflow-visual-canvas')).toContainText('条件分支')
    await expect(page.getByTestId('workflow-visual-canvas')).toContainText('人工审批')

    await page.getByRole('button', { name: '运行计划' }).click()
    await expect(page.locator('body')).toContainText('运行计划已生成', { timeout: 8000 })
    await expect(page.locator('body')).toContainText('门禁摘要')
  })

  test('workflow node previews avoid list-index identity', () => {
    const source = readFileSync(join(repoRoot, 'apps/web/src/app/(app)/workflows/page.tsx'), 'utf8')

    expect(source).toContain('function workflowNodeKey')
    expect(source).toContain('key={workflowNodeKey(node)}')
    expect(source).not.toContain('key={node.id || index}')
  })
})
