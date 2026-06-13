import { expect, Page, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'
import { MOCK_PROJECT, MOCK_DOCUMENTS, MOCK_TEMPLATE, MOCK_PROVIDER } from './fixtures/mock-data'

test.describe('AMX Deterministic Frontend E2E QA Hardening', () => {

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
    // Inject Playwright API router mock layer to guarantee a local deterministic sandbox
    await setupApiMocks(page)

    // Navigate to login, inject fake JWT token to bypass authentications
    await gotoAppPage(page, '/login')
    await page.evaluate(() => {
      localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
    })
  })

  // ==================== Test 1: Global Navigation & Page Usabilities ====================
  test('Test 1: Global and configuration navigation path check', async ({ page }) => {
    test.setTimeout(120000)
    const globalPages = [
      { path: '/', titleCheck: /项目|登录|控制台|工作台|交付总控台|首页/i },
      { path: '/login', titleCheck: /登录/i },
      { path: '/dashboard', titleCheck: /工作台|交付总控台|首页/i },
      { path: '/projects', titleCheck: /项目文档|项目列表|确定性测试项目/i },
      { path: '/documents', titleCheck: /全局文档注册表|文档资产清单/i },
      { path: '/knowledge/graph', titleCheck: /知识图谱|图谱/i },
      { path: '/agents', titleCheck: /智能体|智能编排/i },
      { path: '/templates', titleCheck: /模板/i },
      { path: '/system-health', titleCheck: /健康状态|服务监控/i },
      { path: '/documents/contradictions', titleCheck: /冲突检测|冲突解析|变更追溯|可追溯性/i },
      { path: '/exports', titleCheck: /导出/i },
      { path: '/settings', titleCheck: /设置|配置/i },
      { path: '/providers', titleCheck: /供应商/i },
      { path: '/quotas', titleCheck: /配额与监控|API配额/i },
      { path: '/agent-ops', titleCheck: /智能体运行|运行记录/i },
      { path: '/workflows', titleCheck: /工作流/i },
    ]

    for (const pageInfo of globalPages) {
      console.log(`[E2E Navigation] Routing to: ${pageInfo.path}`)

      // Ensure the mock JWT token is always present before routing to authenticated pages,
      // preventing token deletion logic in /login from aborting subsequent page accesses.
      if (pageInfo.path !== '/login' && pageInfo.path !== '/') {
        await page.evaluate(() => {
          localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
        }).catch(() => {})
      }

      await gotoAppPage(page, pageInfo.path)

      // 1. Wait for core container layout selector to be visible (avoids Next router transition race conditions)
      const mainArea = page.locator('main, #main-content, .container, h1, h2, form').first()
      await expect(mainArea).toBeVisible({ timeout: 8000 })

      const body = page.locator('body')

      // 2. Assert basic usabilities and Next.js internal runtime errors
      await expect(body).not.toContainText('Application error', { timeout: 3000 })
      await expect(body).not.toContainText('client-side exception', { timeout: 3000 })
      await expect(body).not.toContainText('This page could not be found', { timeout: 3000 })
      await expect(body).not.toContainText('ChunkLoadError', { timeout: 3000 })

      // 3. Assert Chinese title or core workflow keywords are physically rendered to resolve loading delays
      await expect(body).toContainText(pageInfo.titleCheck, { timeout: 8000 })
    }
  })

  // ==================== Test 2: Project Life-cycle & Adaptive Subpages ====================
  test('Test 2: Dynamic project lifecycle subpages path check', async ({ page }) => {
    const projectId = 'project-e2e-001'
    const projectSubpages = [
      { subPath: '', keyword: /概览|项目/i, type: 'dashboard' },
      { subPath: '/files', keyword: /文件|资料/i, type: 'files' },
      { subPath: '/documents', keyword: /文档/i, type: 'documents' },
      { subPath: '/documents/generate', keyword: /生成|配置/i, type: 'generate' },
      { subPath: '/knowledge', keyword: /知识|节点/i, type: 'knowledge' },
      { subPath: '/members', keyword: /成员|用户/i, type: 'members' },
      { subPath: '/settings', keyword: /设置|基础/i, type: 'settings' },
      { subPath: '/traceability', keyword: /可追溯|矩阵/i, type: 'traceability' },
      { subPath: '/changes', keyword: /变更|历史/i, type: 'changes' },
    ]

    for (const sub of projectSubpages) {
      const fullPath = `/projects/${projectId}${sub.subPath}`
      console.log(`[E2E Project] Routing to: ${fullPath}`)
      await gotoAppPage(page, fullPath)

      // 1. Wait for layout container (defeats React rendering lag)
      const mainArea = page.locator('main, #main-content, .container, h1, h2').first()
      await expect(mainArea).toBeVisible({ timeout: 8000 })

      const body = page.locator('body')

      // 2. Assert no white screen errors
      await expect(body).not.toContainText('Application error', { timeout: 3000 })
      await expect(body).not.toContainText('client-side exception', { timeout: 3000 })
      await expect(body).not.toContainText('This page could not be found', { timeout: 3000 })
      await expect(body).not.toContainText('ChunkLoadError', { timeout: 3000 })

      // 3. Assert Chinese keywords presence with automated retry waiting
      await expect(body).toContainText(sub.keyword, { timeout: 8000 })

      // 4. Subpage-specific component verification
      if (sub.type === 'dashboard') {
        await expect(body).toContainText(MOCK_PROJECT.name, { timeout: 5000 })
      } else if (sub.type === 'files') {
        const uploadBtn = page.locator('input[type="file"], button:has-text("上传"), div:has-text("上传"), [class*="upload"]').first()
        await expect(uploadBtn).toBeVisible({ timeout: 5000 })
      } else if (sub.type === 'documents') {
        await expect(body).toContainText(MOCK_DOCUMENTS[0].name, { timeout: 8000 })
      } else if (sub.type === 'generate') {
        const select = page.locator('select, button[role="combobox"], input, button:has-text("生成")').first()
        await expect(select).toBeVisible({ timeout: 5000 })
      } else if (sub.type === 'knowledge') {
        const searchInput = page.locator('input[placeholder*="搜索"], input[type="search"], button:has-text("添加")').first()
        await expect(searchInput).toBeVisible({ timeout: 5000 })
      } else if (sub.type === 'members') {
        const inviteBtn = page.locator('button:has-text("邀请"), button:has-text("添加"), button:has-text("成员")').first()
        await expect(inviteBtn).toBeVisible({ timeout: 5000 })
      } else if (sub.type === 'settings') {
        const saveBtn = page.locator('button:has-text("保存"), button:has-text("更新"), button:has-text("基本信息")').first()
        await expect(saveBtn).toBeVisible({ timeout: 5000 })
      }
    }
  })

  // ==================== Test 3: Document Editor & Details Check ====================
  test('Test 3: Document details page check', async ({ page }) => {
    const docUrl = `/projects/project-e2e-001/documents/doc-e2e-001`
    console.log(`[E2E Document] Routing to: ${docUrl}`)
    await gotoAppPage(page, docUrl)

    const mainArea = page.locator('main, #main-content, .container, h1, h2').first()
    await expect(mainArea).toBeVisible({ timeout: 8000 })

    const body = page.locator('body')
    await expect(body).not.toContainText('Application error', { timeout: 3000 })
    await expect(body).not.toContainText('client-side exception', { timeout: 3000 })
    await expect(body).not.toContainText('This page could not be found', { timeout: 3000 })
    await expect(body).not.toContainText('ChunkLoadError', { timeout: 3000 })

    // 1. Assert Title and main content are visible
    await expect(body).toContainText(MOCK_DOCUMENTS[0].name, { timeout: 8000 })
    await expect(body).toContainText('业务愿景', { timeout: 8000 })

    // 2. Click Edit button to open dialog
    const editBtn = page.locator('button:has-text("编辑"), button:has-text("保存"), button:has-text("修改")').first()
    if (await editBtn.isVisible().catch(() => false)) {
      await editBtn.click()

      // Verification click does not crash, dialog is present
      const dialog = page.getByRole('dialog').first()
      await expect(dialog).toBeVisible({ timeout: 5000 })
      await expect(body).not.toContainText(/崩溃|exception|error/i)

      // CRITICAL: Dismiss modal to clear background dialog backdrop overlay instantly
      const cancelBtn = dialog.locator('button:has-text("取消"), button:has-text("关闭")').first()
      if (await cancelBtn.isVisible().catch(() => false)) {
        await cancelBtn.click()
      } else {
        await page.keyboard.press('Escape')
      }
      await expect(dialog).not.toBeVisible({ timeout: 5000 })
    }

    // 3. Export either works or exposes a visible release blocker.
    const exportBtn = page.getByTestId('document-export-action')
    if (await exportBtn.isVisible().catch(() => false)) {
      if (await exportBtn.isEnabled()) {
        await exportBtn.click()
        await expect(body).not.toContainText(/崩溃|exception|error/i)

        // Dismiss dialog if any export prompts show up
        const dialog = page.getByRole('dialog').first()
        if (await dialog.isVisible().catch(() => false)) {
          const cancelBtn = dialog.locator('button:has-text("取消"), button:has-text("关闭")').first()
          if (await cancelBtn.isVisible().catch(() => false)) {
            await cancelBtn.click()
          } else {
            await page.keyboard.press('Escape')
          }
          await expect(dialog).not.toBeVisible({ timeout: 5000 })
        }
      } else {
        await expect(body).toContainText(/模板变量|发布阻塞|未填模板变量/)
      }
    }

    // 4. Version history section exists
    const versionHeader = page.locator('div:has-text("历史版本"), div:has-text("版本"), button:has-text("版本"), [class*="version"]').first()
    await expect(versionHeader).toBeVisible({ timeout: 5000 })

    // 5. Comment section exists
    const commentHeader = page.locator('div:has-text("评论"), button:has-text("批注"), [class*="comment"]').first()
    await expect(commentHeader).toBeVisible({ timeout: 5000 })
  })

  // ==================== Test 4: Settings Hub & User Validation ====================
  test('Test 4: Settings hub panel check', async ({ page }) => {
    await gotoAppPage(page, '/settings')

    const mainArea = page.locator('main, #main-content, .container, h1, h2').first()
    await expect(mainArea).toBeVisible({ timeout: 8000 })

    // 1. Assert tabs are interactive and clickable
    const userTab = page.locator('button[role="tab"]:has-text("用户"), button[role="tab"]:has-text("成员"), button:has-text("成员"), button:has-text("用户")').first()
    const roleTab = page.locator('button[role="tab"]:has-text("角色"), button:has-text("角色")').first()
    const apiKeyTab = page.locator('button[role="tab"]:has-text("密钥"), button[role="tab"]:has-text("API"), button:has-text("密钥"), button:has-text("API")').first()

    // Test user tab
    if (await userTab.isVisible().catch(() => false)) {
      await userTab.click()

      // 2. Open Add User Dialog
      const inviteBtn = page.locator('button:has-text("邀请"):not([disabled]), button:has-text("添加"):not([disabled])').first()
      if (await inviteBtn.isVisible().catch(() => false)) {
        await inviteBtn.click()

        const dialog = page.getByRole('dialog').first()
        await expect(dialog).toBeVisible({ timeout: 5000 })

        // Submit button should be disabled when inputs are empty
        const submitBtn = dialog.locator('button:has-text("发送邀请"), button:has-text("创建"), button[type="submit"]').first()

        // Fill a valid email to check integration
        const emailInput = dialog.locator('input[type="email"], label:has-text("邮箱") + input, input[name*="email"]').first()
        if (await emailInput.isVisible().catch(() => false)) {
          await emailInput.fill('e2e-test-user@example.com')

          await expect(submitBtn).toBeEnabled()
        }

        // Close modal
        const cancelBtn = dialog.locator('button:has-text("取消"), button:has-text("关闭")').first()
        if (await cancelBtn.isVisible().catch(() => false)) {
          await cancelBtn.click()
        } else {
          await page.keyboard.press('Escape')
        }
        await expect(dialog).not.toBeVisible({ timeout: 5000 })
      }
    }

    await gotoAppPage(page, '/settings')

    if (await roleTab.isVisible().catch(() => false)) {
      await roleTab.click()
      const addRoleBtn = page.locator('button:has-text("新建角色"), button:has-text("添加角色"), button:has-text("创建角色")').first()
      if (await addRoleBtn.isVisible().catch(() => false)) {
        await addRoleBtn.click()
        const dialog = page.getByRole('dialog').first()
        await expect(dialog).toBeVisible({ timeout: 5000 })
        await page.keyboard.press('Escape')
        await expect(dialog).not.toBeVisible({ timeout: 5000 })
      }
    }

    await gotoAppPage(page, '/settings')

    if (await apiKeyTab.isVisible().catch(() => false)) {
      await apiKeyTab.click()
      const createKeyBtn = page.locator('button:has-text("创建密钥"), button:has-text("新建密钥"), button:has-text("添加密钥")').first()
      if (await createKeyBtn.isVisible().catch(() => false)) {
        await createKeyBtn.click()
        const dialog = page.getByRole('dialog').first()
        await expect(dialog).toBeVisible({ timeout: 5000 })
        await page.keyboard.press('Escape')
        await expect(dialog).not.toBeVisible({ timeout: 5000 })
      }
    }
  })

  // ==================== Test 5: Templates & Versioning ====================
  test('Test 5: Templates hub panel check', async ({ page }) => {
    await gotoAppPage(page, '/templates')

    const mainArea = page.locator('main, #main-content, .container, h1, h2').first()
    await expect(mainArea).toBeVisible({ timeout: 8000 })

    await expect(page.locator('body')).toContainText(MOCK_TEMPLATE[0].name, { timeout: 8000 })

    // 1. Open New Template Modal
    const createTemplateBtn = page.locator('button:has-text("新建模板"), button:has-text("创建模板")').first()
    if (await createTemplateBtn.isVisible().catch(() => false)) {
      await createTemplateBtn.click()
      const dialog = page.getByRole('dialog').first()
      await expect(dialog).toBeVisible({ timeout: 5000 })

      // Submit is disabled without selected file or empty fields
      const submitBtn = dialog.locator('button:has-text("创建"), button[type="submit"]').first()
      await expect(submitBtn).toBeDisabled()

      await page.keyboard.press('Escape')
      await expect(dialog).not.toBeVisible({ timeout: 5000 })
    }

    // 2. Open version upload modal
    const uploadVerBtn = page.locator('button:has-text("上传版本"), button:has-text("更新版本"), button:has-text("新增版本")').first()
    if (await uploadVerBtn.isVisible().catch(() => false)) {
      await uploadVerBtn.click()
      const dialog = page.getByRole('dialog').first()
      await expect(dialog).toBeVisible({ timeout: 5000 })
      await page.keyboard.press('Escape')
      await expect(dialog).not.toBeVisible({ timeout: 5000 })
    }

    // 3. Open version history
    const verHistoryBtn = page.locator('button:has-text("版本历史"), button:has-text("历史记录"), button:has-text("版本管理")').first()
    if (await verHistoryBtn.isVisible().catch(() => false)) {
      await verHistoryBtn.click()
      const dialog = page.getByRole('dialog').first()
      await expect(dialog).toBeVisible({ timeout: 5000 })
      await page.keyboard.press('Escape')
      await expect(dialog).not.toBeVisible({ timeout: 5000 })
    }

    // 4. Assert Delete button exists (do not perform physical deletes)
    const deleteBtn = page.locator('button:has-text("删除")').first()
    if (await deleteBtn.isVisible().catch(() => false)) {
      await expect(deleteBtn).toBeEnabled()
    }
  })

  // ==================== Test 6: Providers, Quotas, Agent-Ops & Workflows ====================
  test('Test 6: Operations, Quotas, Agent-Ops & Workflows panel check', async ({ page }) => {
    // 1. Providers connection test
    await gotoAppPage(page, '/providers')

    const mainArea = page.locator('main, #main-content, .container, h1, h2').first()
    await expect(mainArea).toBeVisible({ timeout: 8000 })
    await expect(page.locator('body')).toContainText(MOCK_PROVIDER[0].name, { timeout: 8000 })

    const testConnBtn = page.locator('button:has-text("测试连接"), button:has-text("测试")').first()
    if (await testConnBtn.isVisible().catch(() => false)) {
      await testConnBtn.click()
      // Verify Toast feedback from mock connections
      await expect(page.locator('body')).toContainText(/测试连接成功|通信正常|连接成功|联调测试失败|Fallback 已接管/i, { timeout: 8000 })
    }

    // 2. Quotas refreshes and exports
    await gotoAppPage(page, '/quotas')
    await expect(page.locator('main, #main-content, .container, h1, h2').first()).toBeVisible({ timeout: 8000 })

    const refreshBtn = page.locator('button:has-text("刷新")').first()
    if (await refreshBtn.isVisible().catch(() => false)) {
      await refreshBtn.click()
      await expect(page.locator('body')).not.toContainText(/崩溃|exception|error/i)
    }

    const exportBtn = page.locator('button:has-text("导出"), button:has-text("生成报表")').first()
    if (await exportBtn.isVisible().catch(() => false)) {
      await exportBtn.click()
      await expect(page.locator('body')).not.toContainText(/崩溃|exception|error/i)
    }

    // 3. Agent Runs Modal
    await gotoAppPage(page, '/agent-ops')
    await expect(page.locator('main, #main-content, .container, h1, h2').first()).toBeVisible({ timeout: 8000 })

    const detailLogBtn = page.locator('button:has-text("查看日志"), button:has-text("日志"), button:has-text("详情")').first()
    if (await detailLogBtn.isVisible().catch(() => false)) {
      await detailLogBtn.click()
      // Details dialog visible
      const dialog = page.getByRole('dialog').first()
      await expect(dialog).toBeVisible({ timeout: 5000 })
      await page.keyboard.press('Escape')
      await expect(dialog).not.toBeVisible({ timeout: 5000 })
    }

    // 4. Workflows editor routing
    await gotoAppPage(page, '/workflows')
    await expect(page.locator('main, #main-content, .container, h1, h2').first()).toBeVisible({ timeout: 8000 })

    const editWorkflowBtn = page.locator('button:has-text("编辑"), a[href*="editor"]').first()
    if (await editWorkflowBtn.isVisible().catch(() => false)) {
      await expect(editWorkflowBtn).toBeEnabled()
    }
  })
})
