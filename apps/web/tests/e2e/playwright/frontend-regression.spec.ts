import { expect, test } from '@playwright/test'

const smokeEmail = process.env.E2E_USER_EMAIL
const smokePassword = process.env.E2E_PASSWORD
const apiUrl = process.env.E2E_API_URL || `${process.env.E2E_BASE_URL || 'http://localhost:3000'}/api/v1`

test.describe('ConsultantAIP Frontend Quality HARDENING & Regression', () => {
  test.setTimeout(120000)

  // If credentials are not set, we skip authenticated tests
  test.skip(!smokeEmail || !smokePassword, 'Set E2E_USER_EMAIL and E2E_PASSWORD to run regression tests')

  test.beforeEach(async ({ page, request }) => {
    // Inject auth token to skip visual login
    const loginResponse = await request.post(`${apiUrl}/identity/auth/login`, {
      data: { email: smokeEmail, password: smokePassword },
    })
    expect(loginResponse.ok(), `API Login failed: ${loginResponse.status()}`).toBeTruthy()
    const loginJson = await loginResponse.json()
    expect(loginJson.access_token).toBeTruthy()

    await page.goto('/login', { waitUntil: 'domcontentloaded' })
    await page.evaluate((token) => {
      localStorage.setItem('auth_token', token)
    }, loginJson.access_token)
  })

  test('R.1: Traverse all global and config pages without crash or white-screen', async ({ page }) => {
    const consoleErrors: string[] = []
    page.on('console', (message) => {
      if (message.type() === 'error') {
        const text = message.text()
        // Filter known non-critical noises
        if (text.includes('favicon')) return
        if (text.includes('Failed to fetch RSC payload') && text.includes('Falling back to browser navigation')) return
        consoleErrors.push(text)
      }
    })

    const globalPages = [
      { path: '/', titleCheck: /工作台|项目文档|首页/i }, // Root redirect page
      { path: '/dashboard', titleCheck: /工作台|交付总控台|首页/i },
      { path: '/projects', titleCheck: /项目文档|项目列表/i },
      { path: '/documents', titleCheck: /全局文档注册表|文档资产清单/i },
      { path: '/knowledge/graph', titleCheck: /知识图谱|图谱/i },
      { path: '/agents', titleCheck: /智能体/i },
      { path: '/templates', titleCheck: /模板/i },
      { path: '/system-health', titleCheck: /健康状态|服务监控/i },
      { path: '/documents/contradictions', titleCheck: /冲突检测|可追溯性/i },
      { path: '/exports', titleCheck: /导出/i },
      { path: '/collaboration', titleCheck: /协同|协作/i },
      { path: '/settings', titleCheck: /设置|配置/i },
      // Admin Ops Pages
      { path: '/providers', titleCheck: /供应商/i },
      { path: '/quotas', titleCheck: /配额与监控|API配额/i },
      { path: '/agent-ops', titleCheck: /智能体运行|运行记录/i },
      { path: '/workflows', titleCheck: /工作流/i },
    ]

    for (const pageInfo of globalPages) {
      console.log(`Navigating to: ${pageInfo.path}`)
      await page.goto(pageInfo.path, { waitUntil: 'domcontentloaded' })
      await page.locator('body').waitFor({ state: 'visible' })

      // Assert basic rendering and no white-screen / Next errors
      const bodyText = await page.locator('body').innerText()
      expect(bodyText).not.toContain('Application error')
      expect(bodyText).not.toContain('client-side exception')
      expect(bodyText).not.toContain('This page could not be found')
      expect(bodyText).not.toContain('ChunkLoadError')

      // Assert key rendering area or main component is visible to user
      const mainArea = page.locator('main, #main-content, .container, h1, h2').first()
      await expect(mainArea).toBeVisible({ timeout: 5000 })

      // Verify the page contains something matching the titleCheck
      expect(bodyText).toMatch(pageInfo.titleCheck)

      // Ensure body is not completely empty
      await expect(page.locator('body')).not.toBeEmpty()
    }

    // Assert no severe console errors
    expect(consoleErrors).toEqual([])
  })

  test('R.2: Settings invitation form invalid inputs check', async ({ page }) => {
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await page.locator('body').waitFor({ state: 'visible' })

    // Find user management tab
    const userTab = page.locator('button[role="tab"]:has-text("用户"), button[role="tab"]:has-text("成员")').first()
    if (await userTab.isVisible().catch(() => false)) {
      await userTab.click()

      const inviteBtn = page.locator('button:has-text("邀请用户"), button:has-text("添加用户")').first()
      if (await inviteBtn.isVisible().catch(() => false)) {
        await inviteBtn.click()

        // Assert the modal/dialog pops up
        const dialog = page.getByRole('dialog').first()
        await expect(dialog).toBeVisible()

        // Test form submission disabled when empty/invalid
        const submitBtn = dialog.locator('button:has-text("发送邀请"), button:has-text("创建")').first()
        await expect(submitBtn).toBeDisabled()

        // Fill an invalid email format
        const emailInput = dialog.locator('input[type="email"]').first()
        if (await emailInput.isVisible().catch(() => false)) {
          await emailInput.fill('invalid-email-address')
          // Button should still be disabled or an error should prompt
          const isDisabled = await submitBtn.isDisabled()
          if (!isDisabled) {
            // Trigger check if submit fails or prompts error
            await submitBtn.click()
            await expect(page.locator('body')).toContainText(/格式错误|邮箱无效|invalid|失败|422/i)
          }
        }
      }
    }
  })

  test('R.3: Dynamic project routing and adaptive subpage checklist', async ({ page }) => {
    console.log("Navigating to: /projects")
    await page.goto('/projects', { waitUntil: 'domcontentloaded' })
    await page.locator('body').waitFor({ state: 'visible' })

    // Capture first project card's URL
    const firstProjectLink = page.locator('a[href^="/projects/"]').first()
    const hasProjects = await firstProjectLink.isVisible().catch(() => false)

    if (!hasProjects) {
      console.log('  No projects found on E2E server. Checking creation form only.')
      const createProjectBtn = page.locator('button:has-text("创建项目"), button:has-text("新建项目")').first()
      await expect(createProjectBtn).toBeVisible()
      await createProjectBtn.click()

      // Verify Dialog appears and validates empty input
      const dialog = page.getByRole('dialog').first()
      await expect(dialog).toBeVisible()
      const confirmBtn = dialog.locator('button:has-text("创建")').first()
      await expect(confirmBtn).toBeDisabled()
      return
    }

    // Adaptively grab projectId
    const projectHref = await firstProjectLink.getAttribute('href')
    expect(projectHref).toBeTruthy()
    const projectId = projectHref!.split('/').pop()
    expect(projectId).toBeTruthy()

    console.log(`  Adaptive E2E matched projectId: ${projectId}`)

    const projectSubpages = [
      { subPath: '', keyword: /概览|项目/ },
      { subPath: '/files', keyword: /文件|资料/ },
      { subPath: '/documents', keyword: /文档/ },
      { subPath: '/documents/generate', keyword: /生成|配置/ },
      { subPath: '/knowledge', keyword: /知识/ },
      { subPath: '/members', keyword: /成员|用户/ },
      { subPath: '/settings', keyword: /设置|基础/ },
      { subPath: '/traceability', keyword: /可追溯|矩阵/ },
      { subPath: '/changes', keyword: /变更|历史/ },
    ]

    for (const sub of projectSubpages) {
      const fullPath = `/projects/${projectId}${sub.subPath}`
      console.log(`Navigating to: ${fullPath}`)
      await page.goto(fullPath, { waitUntil: 'domcontentloaded' })
      await page.locator('body').waitFor({ state: 'visible' })

      const bodyText = await page.locator('body').innerText()
      expect(bodyText).not.toContain('Application error')
      expect(bodyText).not.toContain('client-side exception')
      expect(bodyText).not.toContain('This page could not be found')
      expect(bodyText).not.toContain('ChunkLoadError')

      // Assert key rendering area or main component is visible to user
      const mainArea = page.locator('main, #main-content, .container, h1, h2').first()
      await expect(mainArea).toBeVisible({ timeout: 5000 })

      // Assert specific keyword matching in visibility check
      expect(bodyText).toMatch(sub.keyword)

      // Assert it loads correctly and not a blank page
      await expect(page.locator('body')).not.toBeEmpty()
    }

    // Check document-specific routing if a document is present in the list
    await page.goto(`/projects/${projectId}/documents`, { waitUntil: 'domcontentloaded' })
    await page.locator('body').waitFor({ state: 'visible' })

    const firstDocLink = page.locator(`a[href^="/projects/${projectId}/documents/"]`).filter({ hasNotText: /generate/i }).first()
    const hasDoc = await firstDocLink.isVisible().catch(() => false)
    if (hasDoc) {
      const docHref = await firstDocLink.getAttribute('href')
      if (docHref && !docHref.endsWith('/generate')) {
        await page.goto(docHref, { waitUntil: 'domcontentloaded' })
        await page.locator('body').waitFor({ state: 'visible' })
        const detailText = await page.locator('body').innerText()
        expect(detailText).not.toContain('Application error')
        expect(detailText).not.toContain('client-side exception')
        expect(detailText).not.toContain('This page could not be found')
        expect(detailText).not.toContain('ChunkLoadError')

        const mainArea = page.locator('main, #main-content, .container, h1, h2').first()
        await expect(mainArea).toBeVisible({ timeout: 5000 })
        console.log(`  Adaptive document E2E traversed successfully: ${docHref}`)
      }
    } else {
      console.log('  No documents found for this project in E2E. Skipping document detail test.')
    }
  })
})
