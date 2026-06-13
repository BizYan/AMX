import { expect, Page, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'

test.describe('ConsultantAIP Project Files Upload UX & Dark Mode QA Spec', () => {

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

  test.beforeEach(async ({ page }) => {
    // 注入底层 Api Mock 层
    await setupApiMocks(page)

    // 登录注入 Mock 凭证
    await gotoAppPage(page, '/login')
    await page.evaluate(() => {
      localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
    })
  })

  test('Test files page layout and native picker accessibilities', async ({ page }) => {
    const filesUrl = '/projects/project-e2e-001/files'
    await gotoAppPage(page, filesUrl)

    // 验证核心标题
    await expect(page.locator('h1')).toContainText('项目资料')

    // 验证拖拽大框和上传按钮正常呈现
    const dragCard = page.locator('div:has-text("拖拽文件到这里")').first()
    await expect(dragCard).toBeVisible()

    const fileInput = page.locator('input[type="file"]').first()
    await expect(fileInput).not.toBeVisible() // 应该处于隐藏状态，防视觉干扰

    const uploadButton = page.locator('button:has-text("选择本地文件")').first()
    await expect(uploadButton).toBeVisible()
    await expect(uploadButton).toBeEnabled()
  })

  test('Test single file upload success and reactive Chinese Toast feedback', async ({ page }) => {
    const filesUrl = '/projects/project-e2e-001/files'
    await gotoAppPage(page, filesUrl)

    await page.route(/\/api\/v1\/documents(?:\?.*)?$/, async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({
            message: 'documentsApi must not be used for project file uploads',
          }),
        })
        return
      }
      await route.fallback()
    })

    // 拦截真实 source_files 上传接口，模拟秒级完成
    await page.route(/\/api\/v1\/projects\/project-e2e-001\/files(?:\?.*)?$/, async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 'mock-source-file-success-999',
            project_id: 'project-e2e-001',
            filename: 'stored-playwright-test.txt',
            original_filename: 'playwright-test.txt',
            content_type: 'text/plain',
            size: 200,
            hash: 'a'.repeat(64),
            storage_path: 'tenant/project/stored-playwright-test.txt',
            status: 'ready',
            metadata_json: {},
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          }),
        })
        return
      }
      await route.fallback()
    })

    // 模拟选择并触发本地文件输入事件
    const fileInput = page.locator('input[type="file"]').first()
    await fileInput.setInputFiles({
      name: 'playwright-test.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Mock content text.'),
    })

    // 验证上传队列出现
    await expect(page.locator('text=上传队列')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'playwright-test.txt' })).toBeVisible()

    // 验证上传成功 Toast 提示 (中文反馈)
    const toast = page.locator('text=文件上传成功')
    await expect(toast).toBeVisible({ timeout: 10000 })
  })

  test('Test file upload failure with localized friendly Chinese error', async ({ page }) => {
    const filesUrl = '/projects/project-e2e-001/files'
    await gotoAppPage(page, filesUrl)

    // 模拟真实 source_files 上传接口 403 错误 (例如权限不足)
    await page.route(/\/api\/v1\/projects\/project-e2e-001\/files(?:\?.*)?$/, async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 403,
          contentType: 'application/json',
          body: JSON.stringify({
            message: 'Permission denied for this workspace',
          }),
        })
        return
      }
      await route.fallback()
    })

    // 模拟选择并触发本地文件输入
    const fileInput = page.locator('input[type="file"]').first()
    await fileInput.setInputFiles({
      name: 'restricted-doc.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Restricted data.'),
    })

    // 验证上传队列展示错误
    await expect(page.locator('text=上传队列')).toBeVisible()

    // 验证错误被翻译为中文友好语意，包含 “权限不足”
    const errorText = page.locator('text=权限不足')
    await expect(errorText).toBeVisible({ timeout: 10000 })
  })

  test('Test Dark Mode accessibility states and layout reading contrast', async ({ page }) => {
    const filesUrl = '/projects/project-e2e-001/files'
    await gotoAppPage(page, filesUrl)

    // 切换至暗黑模式 (通过向 html 添加 dark 类)
    await page.evaluate(() => {
      document.documentElement.classList.add('dark')
    })

    // 确保暗黑模式下的核心文本可读
    const headerTitle = page.locator('h1')
    await expect(headerTitle).toHaveClass(/text-slate-900|text-white/)

    // 确保核心操作卡片在暗黑模式下仍可交互
    const browseBtn = page.locator('button:has-text("选择本地文件")').first()
    await expect(browseBtn).toBeVisible()
    await expect(browseBtn).toBeEnabled()
  })

})
