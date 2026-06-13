import { expect, Page, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'

async function gotoAppPage(page: Page, path: string) {
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => {
    localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
  })
  await page.goto(path, { waitUntil: 'domcontentloaded' })
}

test.describe('P3 structured template section workbench', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
  })

  test('configures template sections and binds section skills', async ({ page }) => {
    await gotoAppPage(page, '/templates')

    const body = page.locator('body')
    await expect(body).toContainText('模板中心', { timeout: 8000 })
    await expect(body).toContainText('章节配置', { timeout: 8000 })

    await page.getByTestId('template-sections-open-template-e2e-001').click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText('章节结构')
    await expect(dialog).toContainText('业务愿景')
    await expect(dialog).toContainText('DocumentReviewer')

    await page.getByTestId('template-sections-seed').click()
    await expect(body).toContainText('标准章节已生成', { timeout: 8000 })
    await expect(dialog).toContainText('用户需求')

    await page.getByTestId('template-section-title').fill('验收标准')
    await page.getByTestId('template-section-key').fill('urs.acceptance')
    await page.getByTestId('template-section-requirement').fill('列出可验证的验收标准和评审口径。')
    await page.getByTestId('template-section-prompt').fill('请生成结构化验收标准。')
    await page.getByTestId('template-section-create').click()

    await expect(dialog).toContainText('验收标准')
    await page.getByTestId('template-section-select-section-e2e-001').click()
    await page.getByTestId('template-section-skill-skill-e2e-reviewer').check()
    await page.getByTestId('template-section-save-skills').click()

    await expect(body).toContainText('章节 Skill 绑定已更新', { timeout: 8000 })
  })
})
