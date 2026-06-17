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

test.describe('Project export package center', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
  })

  test('configures a delivery package, creates an export job, and exposes artifacts and failures', async ({ page }) => {
    await gotoAppPage(page, '/exports')

    await expect(page.getByRole('heading', { name: '交付导出发布室' })).toBeVisible({ timeout: 8000 })
    await expect(page.getByTestId('export-readiness')).toContainText('76%')
    await expect(page.getByTestId('export-readiness')).toContainText('可正式导出 4')
    await expect(page.getByTestId('export-production-readiness')).toContainText('核心交付清单')
    await expect(page.getByTestId('export-production-readiness')).toContainText('测试用例')
    await expect(page.getByTestId('export-production-readiness')).toContainText('仍有阻塞')
    await expect(page.getByTestId('export-release-evidence-center')).toContainText('发布包证据中心')
    await expect(page.getByTestId('export-release-gate')).toContainText('发布阻断')
    await expect(page.getByTestId('export-release-evidence-center')).toContainText('补齐核心交付文档')
    await expect(page.getByTestId('export-release-evidence-center')).toContainText('客户评审交付包.docx')
    await expect(page.getByTestId('export-production-loop')).toBeVisible()
    await expect(page.getByTestId('export-production-evidence-export_job_count')).toContainText('2')
    await expect(page.getByTestId('export-production-evidence-completed_export_count')).toContainText('1')
    await expect(page.getByTestId('export-production-evidence-exportable_document_count')).toContainText('4')
    await expect(page.getByTestId('export-production-evidence-artifact_count')).toContainText('3')
    await expect(page.getByTestId('export-production-evidence-failed_export_count')).toContainText('1')
    await expect(page.getByTestId('export-format-coverage-word')).toContainText('已有产物')
    await expect(page.getByTestId('export-format-coverage-markdown')).toContainText('已有产物')
    await expect(page.getByTestId('export-format-coverage-pptx')).toContainText('已有产物')
    await expect(page.getByTestId('export-failure-triage')).toContainText('模板变量缺少客户签收日期')
    await expect(page.getByTestId('export-production-commissioning-run')).toBeEnabled()
    await page.getByTestId('export-production-commissioning-run').click()
    await expect(page.getByText('导出发布校准已完成')).toBeVisible()
    await page.getByTestId('export-production-history-link').click()
    await expect(page.getByRole('tab', { name: '任务历史' })).toHaveAttribute('aria-selected', 'true')
    await page.getByRole('tab', { name: '交付包配置' }).click()
    await expect(page.getByTestId('export-format-summary')).toContainText('Word')
    await expect(page.getByTestId('export-format-summary')).toContainText('Markdown')
    await expect(page.getByTestId('export-format-summary')).toContainText('PPTX')
    await expect(page.getByTestId('recent-export-summary')).toContainText('已完成')

    await page.getByLabel('搜索文档').fill('实施')
    await expect(page.getByTestId('export-document-list')).toContainText('实施方案')
    await expect(page.getByTestId('export-document-list')).not.toContainText('业务需求文档')

    await page.getByLabel('状态筛选').selectOption('draft')
    await expect(page.getByTestId('export-document-list')).toContainText('实施方案')
    await expect(page.getByTestId('export-blockers')).toContainText('验收报告')

    await page.getByLabel('状态筛选').selectOption('all')
    await page.getByLabel('搜索文档').fill('')
    await page.getByLabel('选择 业务需求文档').uncheck()
    await expect(page.getByTestId('package-selection-summary')).toContainText('已选择 3')

    await page.getByLabel('包名称').fill('WMS 一期交付包')
    await page.getByLabel('PPTX').check()
    await page.getByLabel('变量摘要').fill('项目经理=张三；发布日期=2026-05-31')
    await expect(page.getByTestId('export-variable-panel')).toContainText('模板变量映射')
    await page.getByTestId('export-variable-value-1').fill('远大客户')
    await page.getByTestId('export-variable-value-2').fill('2026-05-31')
    await page.getByTestId('add-export-variable').click()
    await page.getByTestId('export-variable-key-4').fill('验收负责人')
    await page.getByTestId('export-variable-value-4').fill('李四')
    await expect(page.getByTestId('export-variable-evidence')).toContainText('已配置 4 个变量')
    await page.getByLabel('水印').fill('客户评审版')
    await page.getByLabel('生成审计清单').check()

    const packageRequestPromise = page.waitForRequest((request) =>
      request.method() === 'POST' && request.url().endsWith('/api/v1/exports/project-package')
    )
    await page.getByRole('button', { name: '创建导出任务' }).click()
    const packageRequest = await packageRequestPromise
    const payload = packageRequest.postDataJSON()
    expect(payload.variables).toMatchObject({
      summary: '项目经理=张三；发布日期=2026-05-31',
      客户名称: '远大客户',
      发布日期: '2026-05-31',
      验收负责人: '李四',
    })

    await expect(page.getByText('导出任务已创建')).toBeVisible({ timeout: 8000 })
    await expect(page.getByRole('tab', { name: '任务历史' })).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByTestId('export-history')).toContainText('WMS 一期交付包')
    await expect(page.getByTestId('export-history')).toContainText('customer-review.docx')
    await expect(page.getByTestId('export-history')).toContainText('customer-review.md')
    await expect(page.getByTestId('export-history')).toContainText('customer-review.pptx')
    await expect(page.getByTestId('export-history')).toContainText('模板变量缺少客户签收日期')
  })

  test('export variable rows expose stable row identity', () => {
    const source = readFileSync(join(repoRoot, 'apps/web/src/app/(app)/exports/page.tsx'), 'utf8')

    expect(source).toContain('data-testid={`export-variable-row-${row.id}`}')
    expect(source).toContain('key={row.id}')
  })
})
