import { expect, Page, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'

async function gotoAppPage(page: Page, path: string) {
  try {
    await page.goto(path, { waitUntil: 'domcontentloaded' })
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    if (!message.includes('net::ERR_ABORTED')) throw error
    await page.goto(path, { waitUntil: 'domcontentloaded' })
  }
}

test.describe('Source knowledge cockpit', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
    await gotoAppPage(page, '/login')
    await page.evaluate(() => {
      localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
    })
  })

  test('shows source ingestion overview and actionable file cards', async ({ page }) => {
    await gotoAppPage(page, '/projects/project-e2e-001/files')

    await expect(page.getByRole('heading', { name: '资料摄取驾驶舱' })).toBeVisible()
    await expect(page.getByText('已上传 4')).toBeVisible()
    await expect(page.getByText('处理中 1')).toBeVisible()
    await expect(page.getByText('可用于生成 2')).toBeVisible()
    await expect(page.getByText('失败/需补充 1')).toBeVisible()

    await expect(page.getByText('仓储升级招标文件.pdf')).toBeVisible()
    await expect(page.getByText('抽取摘要：识别到仓储批次分配、人工复核和验收指标等 12 条可复用知识。')).toBeVisible()
    await expect(page.getByRole('link', { name: '加入生成上下文' }).first()).toHaveAttribute(
      'href',
      '/projects/project-e2e-001/documents/generate?sourceFileId=file-e2e-ready'
    )
    await expect(page.getByRole('link', { name: '查看知识图谱' }).first()).toHaveAttribute(
      'href',
      '/knowledge/graph?projectId=project-e2e-001&sourceFileId=file-e2e-ready'
    )
    await expect(page.getByRole('button', { name: '标记补充资料' }).first()).toBeVisible()
  })

  test('keeps upload queue visible with ingestion guidance after success and localized failure', async ({ page }) => {
    await gotoAppPage(page, '/projects/project-e2e-001/files')

    const fileInput = page.locator('input[type="file"]').first()
    await fileInput.setInputFiles({
      name: 'new-source.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('new source content'),
    })

    await expect(page.getByText('上传队列')).toBeVisible()
    await expect(page.getByText('new-source.txt')).toBeVisible()
    await expect(page.getByText('已进入知识摄取队列，可在本页跟踪解析和抽取结果。').first()).toBeVisible({
      timeout: 10000,
    })

    await page.route(/\/api\/v1\/projects\/project-e2e-001\/files(?:\?.*)?$/, async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 413,
          contentType: 'application/json',
          body: JSON.stringify({ message: 'too large' }),
        })
        return
      }
      await route.fallback()
    })

    await fileInput.setInputFiles({
      name: 'too-large.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('too large'),
    })

    await expect(page.getByText('文件过大：上传的文件超过大小限制，请压缩后重试。')).toBeVisible({
      timeout: 10000,
    })
  })

  test('shows knowledge extracted from sources with filters, gaps and feedback actions', async ({ page }) => {
    await gotoAppPage(page, '/projects/project-e2e-001/knowledge')

    await expect(page.getByRole('heading', { name: '项目知识工作台' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '项目知识条目' })).toBeVisible()
    await expect(page.getByText('仓储批次分配规则')).toBeVisible()
    await expect(page.getByText('来源：仓储升级招标文件.pdf')).toBeVisible()
    await expect(page.getByText('缺口/冲突提示')).toBeVisible()
    await expect(page.getByText('缺少验收签收日期，需要补充客户确认材料。').first()).toBeVisible()

    await page.getByPlaceholder('搜索知识、来源、证据或结论').fill('签收')
    await expect(page.getByRole('heading', { name: '验收证据缺口' })).toBeVisible()
    await expect(page.getByText('仓储批次分配规则')).not.toBeVisible()

    await page.getByRole('button', { name: '选择' }).click()
    await page.getByRole('button', { name: '加入生成上下文' }).click()
    await expect(page.getByText('已加入生成上下文')).toBeVisible()
    await page.getByRole('link', { name: '图谱定位' }).click()
    await expect(page).toHaveURL(/\/knowledge\/graph\?projectId=project-e2e-001/)
  })
})
