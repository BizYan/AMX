import { expect, test } from '@playwright/test'

const runRealTest = process.env.RUN_REAL_API_TEST === 'true'
const apiUrl = process.env.E2E_API_URL || 'http://localhost:18000/api/v1'
const testEmail = process.env.E2E_USER_EMAIL || 'admin@example.com'
const testPassword = process.env.E2E_PASSWORD || 'admin123'

test.describe('AMX Real Backend Capability Integration Hardening', () => {
  // 仅在设置 RUN_REAL_API_TEST=true 时执行本组集成测试，不破坏普通的纯前端 mock 测试
  test.skip(!runRealTest, 'Skipping real API integration tests. Set RUN_REAL_API_TEST=true to enable.')

  let authToken = ''

  test.beforeAll(async ({ request }) => {
    // 在测试执行前，尝试向真实的后端获取 JWT Token
    try {
      const loginRes = await request.post(`${apiUrl}/identity/auth/login`, {
        data: { email: testEmail, password: testPassword },
      })
      if (loginRes.ok()) {
        const json = await loginRes.json()
        authToken = json.access_token
        console.log('[E2E Test] Successfully logged in to real backend. Token acquired.')
      } else {
        // 如果登录失败（例如是本地 SQLite 全新初始化没有账号），我们尝试快速注册一个默认管理员账号
        console.log('[E2E Test] Default credentials not found. Attempting to seed or register a default admin user...')
        const registerRes = await request.post(`${apiUrl}/identity/users`, {
          data: {
            email: testEmail,
            password: testPassword,
            full_name: 'System Admin',
          },
        }).catch(() => null)

        if (registerRes && registerRes.ok()) {
          console.log('[E2E Test] Successfully registered a default admin user. Retrying login...')
          const retryRes = await request.post(`${apiUrl}/identity/auth/login`, {
            data: { email: testEmail, password: testPassword },
          })
          if (retryRes.ok()) {
            const json = await retryRes.json()
            authToken = json.access_token
          }
        }
      }
    } catch (e) {
      console.error('[E2E Test] Error establishing initial auth token:', e)
    }

    expect(authToken, 'An active authenticated token is strictly required for real API tests').toBeTruthy()
  })

  test.beforeEach(async ({ page }) => {
    // 注入真实的 JWT auth_token 绕过登录页并同步状态
    await page.goto('/')
    await page.evaluate((token) => {
      localStorage.setItem('auth_token', token)
    }, authToken)
  })

  // ==================== 1. 真实 UI 路由加载与健康验证 ====================
  test('Test 1: Global pages loading under authenticated state', async ({ page }) => {
    test.setTimeout(90000)
    const pages = [
      { path: '/dashboard', label: '工作台' },
      { path: '/projects', label: '项目' },
      { path: '/exports', label: '导出中心' },
      { path: '/providers', label: '供应商' },
      { path: '/quotas', label: '配额' },
    ]

    for (const p of pages) {
      await page.goto(p.path)

      // 等待核心容器加载完毕，解决首次路由加载 Next 异步编译白屏竞态问题
      const mainArea = page.locator('main, #main-content, .container, h1, h2, form').first()
      await expect(mainArea).toBeVisible({ timeout: 15000 })

      const body = page.locator('body')
      await expect(body).not.toContainText('Application error', { timeout: 4000 })
      await expect(body).not.toContainText('client-side exception', { timeout: 4000 })
      await expect(body).not.toContainText('This page could not be found', { timeout: 4000 })

      // 确认界面能渲染出包含核心中文名词的内容，避免白屏
      await expect(body).toContainText(new RegExp(p.label, 'i'), { timeout: 15000 })
    }
  })

  // ==================== 2. 全链路后端物理表持久化与真实 API 契约集成测试 ====================
  test('Test 2: Full-chain contract and physical database integration checks', async ({ request }) => {
    const authHeaders = { 'Authorization': `Bearer ${authToken}` }

    // (A) 验证 Ops 配额接口 GET /ops/quota
    console.log('[E2E Chain] 1. Validating GET /ops/quota API contract...')
    const quotaRes = await request.get(`${apiUrl}/ops/quota`, { headers: authHeaders })
    expect(quotaRes.status()).toBe(200)
    const quota = await quotaRes.json()
    expect(quota).toHaveProperty('used')
    expect(quota).toHaveProperty('limit')
    expect(quota).toHaveProperty('resetAt')

    // (B) 验证 LLM Provider 注册与连接测试 POST /providers 和 POST /providers/{id}/test
    console.log('[E2E Chain] 2. Registering LLM Provider & testing connection (Sandbox Fallback)...')
    const providerCreateRes = await request.post(`${apiUrl}/providers`, {
      headers: authHeaders,
      data: {
        name: `E2E Sandbox Provider ${Date.now()}`,
        provider_type: 'llm',
        config: { api_key: 'sandbox-mock-key' },
        capabilities: {}
      }
    })
    expect(providerCreateRes.status()).toBe(201)
    const provider = await providerCreateRes.json()
    expect(provider.id).toBeTruthy()
    const providerId = provider.id

    const providerTestRes = await request.post(`${apiUrl}/providers/${providerId}/test`, {
      headers: authHeaders,
      data: { capability_type: 'text_generation', params: {} }
    })
    expect(providerTestRes.status()).toBe(200)
    const providerTest = await providerTestRes.json()
    expect(providerTest.success).toBe(true)
    expect(providerTest.message).toContain('Sandbox')

    // (C) 真实项目创建与物理库存储校验 POST /projects
    console.log('[E2E Chain] 3. Validating project creation and retrieval...')
    const uniqueSlug = `int-proj-${Date.now()}`
    const projectCreateRes = await request.post(`${apiUrl}/projects`, {
      headers: authHeaders,
      data: {
        name: `Integration Test Project ${Date.now()}`,
        description: 'An automated physical capability testing project',
        slug: uniqueSlug,
      }
    })
    expect(projectCreateRes.status()).toBe(201)
    const project = await projectCreateRes.json()
    expect(project.id).toBeTruthy()
    const projectId = project.id

    // (D) 验证项目成员邀请物理表存储 POST /projects/{id}/invitations
    console.log('[E2E Chain] 4. Validating project member invitation database persistence...')
    const inviteEmail = `test-invitation-${Date.now()}@example.com`
    const inviteRes = await request.post(`${apiUrl}/projects/${projectId}/invitations?email=${encodeURIComponent(inviteEmail)}`, {
      headers: authHeaders
    })
    expect(inviteRes.status()).toBe(201)
    const invitation = await inviteRes.json()
    expect(invitation.token).toBeTruthy()
    expect(invitation.expires_at).toBeTruthy()

    // (E) 创建临时文档以支持导出测试
    console.log('[E2E Chain] 5. Creating a document draft for export tests...')
    const docRes = await request.post(`${apiUrl}/documents`, {
      headers: authHeaders,
      data: {
        project_id: projectId,
        title: 'E2E Test Specs',
        name: 'E2E Test Specs',
        doc_type: 'urs',
        content: '# E2E System Tests\nThis is a real integration document content.',
        status: 'draft'
      }
    })
    expect(docRes.status()).toBe(201)
    const doc = await docRes.json()
    const documentId = doc.id

    // (F) 真实文档导出异步任务创建 POST /exports/markdown
    console.log('[E2E Chain] 6. Creating Markdown asynchronous export job...')
    const exportJobRes = await request.post(`${apiUrl}/exports/markdown`, {
      headers: authHeaders,
      data: {
        document_id: documentId,
        title: 'E2E Integrated Markdown Export',
      }
    })
    expect(exportJobRes.status()).toBe(201)
    const exportJob = await exportJobRes.json()
    expect(exportJob.job_id).toBeTruthy()
    const jobId = exportJob.job_id

    // (G) 智能进度轮询直至编译成功 GET /exports/jobs/{id}
    console.log('[E2E Chain] 7. Polling export job compilation status...')
    let jobStatus = 'pending'
    let pollAttempts = 0
    while ((jobStatus === 'pending' || jobStatus === 'processing') && pollAttempts < 10) {
      await new Promise((resolve) => setTimeout(resolve, 800))
      const statusCheckRes = await request.get(`${apiUrl}/exports/jobs/${jobId}`, { headers: authHeaders })
      expect(statusCheckRes.status()).toBe(200)
      const statusData = await statusCheckRes.json()
      jobStatus = statusData.status
      pollAttempts++
      console.log(`[E2E Polling] Attempt ${pollAttempts}: Job state = ${jobStatus}`)
    }
    expect(jobStatus).toBe('completed')

    // (H) 获取导出列表，确认当前租户任务历史中包含本条记录 GET /exports
    console.log('[E2E Chain] 8. Confirming tenant export history...')
    const historyRes = await request.get(`${apiUrl}/exports`, { headers: authHeaders })
    expect(historyRes.status()).toBe(200)
    const historyList = await historyRes.json()
    const foundJob = historyList.find((job: any) => job.id === jobId)
    expect(foundJob).toBeTruthy()
    expect(foundJob.status).toBe('completed')

    // (H2) 获取该 job 的产物列表 GET /exports/jobs/{id}/artifacts
    console.log('[E2E Chain] 8b. Fetching job artifacts...')
    const artifactsRes = await request.get(`${apiUrl}/exports/jobs/${jobId}/artifacts`, { headers: authHeaders })
    expect(artifactsRes.status()).toBe(200)
    const artifacts = await artifactsRes.json()
    expect(artifacts.length > 0).toBeTruthy()
    const artifactId = artifacts[0].id

    // (I) 物理下载导出产物并验证内容 GET /exports/artifacts/{id}/download
    console.log('[E2E Chain] 9. Verifying physical download of compile artifact...')
    const downloadRes = await request.get(`${apiUrl}/exports/artifacts/${artifactId}/download`, { headers: authHeaders })
    expect(downloadRes.status()).toBe(200)
    const fileContent = await downloadRes.text()
    expect(fileContent).toContain('E2E System Tests')

    // (J) 验证项目归档 PATCH /projects/{id}
    console.log('[E2E Chain] 10. Archiving project through PATCH...')
    const patchRes = await request.patch(`${apiUrl}/projects/${projectId}`, {
      headers: authHeaders,
      data: { status: 'archived' }
    })
    expect(patchRes.status()).toBe(200)
    const patchedProject = await patchRes.json()
    expect(patchedProject.status).toBe('archived')
  })
})
