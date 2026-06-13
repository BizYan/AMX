import { expect, Page, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'

async function gotoAppPage(page: Page, path: string) {
  try {
    await page.goto(path, { waitUntil: 'domcontentloaded' })
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    if (!message.includes('net::ERR_ABORTED')) {
      throw error
    }
    await page.goto(path, { waitUntil: 'domcontentloaded' })
  }
}

test.describe('P3 Template version lifecycle center', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
    await gotoAppPage(page, '/login')
    await page.evaluate(() => {
      localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
    })
  })

  test('shows version lineage and activates a historical template version', async ({ page }) => {
    await gotoAppPage(page, '/templates')

    await expect(page.getByTestId('template-lifecycle-heading')).toBeVisible()
    await expect(page.getByTestId('template-card-template-e2e-001')).toContainText('2 个版本')

    await page.getByTestId('template-version-history-template-e2e-001').click()

    await expect(page.getByTestId('template-version-version-e2e-002')).toContainText('当前版本')
    await expect(page.getByTestId('template-version-version-e2e-001')).not.toContainText('当前版本')

    await page.getByTestId('activate-template-version-version-e2e-001').click()

    await expect(page.locator('body')).toContainText('模板版本已设为当前版本')
    await expect(page.getByTestId('template-version-version-e2e-001')).toContainText('当前版本')
    await expect(page.getByTestId('activate-template-version-version-e2e-001')).toBeDisabled()
  })

  test('shows governed template library and section delivery workbench', async ({ page }) => {
    await gotoAppPage(page, '/templates')

    const body = page.locator('body')
    await expect(page.getByTestId('template-governance-summary')).toContainText('平台级')
    await expect(page.getByTestId('template-governance-summary')).toContainText('项目级')
    await expect(page.getByTestId('template-production-loop')).toBeVisible()
    await expect(page.getByTestId('template-production-evidence-template_count')).toContainText('5')
    await expect(page.getByTestId('template-production-evidence-published_template_count')).toContainText('4')
    await expect(page.getByTestId('template-production-evidence-template_section_count')).toContainText('12')
    await expect(page.getByTestId('template-production-evidence-skill_binding_count')).toContainText('14')
    await expect(page.getByTestId('template-production-evidence-core_coverage_count')).toContainText('4/5')
    await expect(page.getByTestId('template-core-coverage-urs')).toContainText('已覆盖')
    await expect(page.getByTestId('template-core-coverage-acceptance_report')).toContainText('待补齐')
    await expect(page.getByTestId('template-production-open-workbench')).toBeEnabled()
    await expect(page.getByTestId('template-production-seed-sections')).toBeEnabled()
    await page.getByTestId('template-production-seed-sections').click()
    await expect(page.locator('body')).toContainText('标准章节已生成')
    await expect(page.getByTestId('template-card-template-e2e-brd')).toContainText('BRD 商业需求文档')
    await expect(page.getByTestId('template-card-template-e2e-prd')).toContainText('PRD 产品需求文档')
    await expect(page.getByTestId('template-workbench')).toContainText('章节交付物定义')
    await expect(page.getByTestId('template-workbench')).toContainText('业务愿景')
    await expect(page.getByTestId('template-workbench')).toContainText('文档评审器')

    await page.getByTestId('template-governance-filter').selectOption('project')
    await expect(body).toContainText('项目实施方案模板', { timeout: 8000 })
    await expect(body).not.toContainText('BRD 商业需求文档')

    await page.getByTestId('template-governance-filter').selectOption('all')
    await page.getByTestId('template-status-filter').selectOption('draft')
    await expect(body).toContainText('项目验收报告模板', { timeout: 8000 })
  })

  test('preflights uploaded Office templates with Chinese placeholders before saving', async ({ page }) => {
    await gotoAppPage(page, '/templates')

    await page.getByRole('button', { name: '新建模板' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('创建新模板')

    await page.getByTestId('template-upload-file-input').setInputFiles({
      name: '客户汇报模板.pptx',
      mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
      buffer: Buffer.from('mock office bytes with {{项目名称}} and {{客户名称}}'),
    })

    const evidence = page.getByTestId('template-parse-evidence')
    await expect(evidence).toContainText('模板预检结果')
    await expect(evidence).toContainText('可上传')
    await expect(evidence).toContainText('PPTX')
    await expect(evidence).toContainText('{{项目名称}}')
    await expect(evidence).toContainText('{{客户名称}} x2')
    await expect(evidence).toContainText('重复占位符：客户名称')
    await expect(dialog.getByRole('button', { name: '创建模板' })).toBeEnabled()
  })
})
