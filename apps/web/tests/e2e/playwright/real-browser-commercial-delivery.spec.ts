import { expect, test, type APIRequestContext, type BrowserContext, type Page } from '@playwright/test'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { randomUUID } from 'node:crypto'
import os from 'node:os'
import path from 'node:path'

const runRealBrowserDelivery = process.env.RUN_REAL_BROWSER_DELIVERY_TEST === 'true'
const target = process.env.E2E_TARGET || ''
const gitSha = process.env.E2E_GIT_SHA || ''
const webUrl = normalizeBaseUrl(process.env.E2E_WEB_URL || '')
const apiUrl = normalizeApiUrl(process.env.E2E_API_URL || '')
const bootstrapEmail = process.env.E2E_USER_EMAIL || ''
const bootstrapPassword = process.env.E2E_PASSWORD || ''

type ApiOptions = {
  data?: unknown
  headers?: Record<string, string>
  multipart?: Record<string, unknown>
  params?: Record<string, string>
}

type SyntheticMember = {
  roleId: string
  userId: string
  email: string
  password: string
}

type JourneyEvidence = {
  target: string
  git_sha: string
  marker: string
  project_id: string
  source_file_id: string
  ingestion_job_id: string
  knowledge_entry_id: string
  document_id: string
  version_id: string
  baseline_id: string
  export_job_id: string
  artifact_id: string
  portal_link_id: string
  acceptance_evidence: string
  audit_evidence_id: string
  blocked_paths: string[]
  screenshots: string[]
  application_cleanup: string
}

function normalizeBaseUrl(value: string) {
  return value.trim().replace(/\/+$/, '')
}

function normalizeApiUrl(value: string) {
  const normalized = normalizeBaseUrl(value)
  if (!normalized) return ''
  return normalized.endsWith('/api/v1') ? normalized : `${normalized}/api/v1`
}

function requireRealBrowserDeliveryEnv() {
  expect(['candidate', 'staging', 'production'], 'E2E_TARGET must identify the approved runtime').toContain(target)
  expect(gitSha, 'E2E_GIT_SHA is required when RUN_REAL_BROWSER_DELIVERY_TEST=true').toMatch(/^[0-9a-f]{40}$/)
  expect(webUrl, 'E2E_WEB_URL is required when RUN_REAL_BROWSER_DELIVERY_TEST=true').toBeTruthy()
  expect(apiUrl, 'E2E_API_URL is required when RUN_REAL_BROWSER_DELIVERY_TEST=true').toBeTruthy()
  expect(bootstrapEmail, 'E2E_USER_EMAIL is required when RUN_REAL_BROWSER_DELIVERY_TEST=true').toBeTruthy()
  expect(bootstrapPassword, 'E2E_PASSWORD is required when RUN_REAL_BROWSER_DELIVERY_TEST=true').toBeTruthy()
}

async function apiJson<T>(
  request: APIRequestContext,
  method: 'get' | 'post' | 'put' | 'delete',
  endpoint: string,
  token: string,
  options: ApiOptions = {},
): Promise<T> {
  const response = await request[method](`${apiUrl}${endpoint}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(options.headers || {}),
    },
  })
  const body = await response.text()
  expect(
    response.ok(),
    `${method.toUpperCase()} ${endpoint} failed with HTTP ${response.status()}: ${body.slice(0, 600)}`,
  ).toBeTruthy()
  return body ? JSON.parse(body) as T : undefined as T
}

async function loginViaApi(request: APIRequestContext, email: string, password: string) {
  const response = await request.post(`${apiUrl}/identity/auth/login`, {
    data: { email, password },
  })
  expect(response.ok(), `real API login failed with HTTP ${response.status()}`).toBeTruthy()
  const payload = await response.json()
  expect(payload.access_token, 'real API login must return an access token').toBeTruthy()
  return String(payload.access_token)
}

async function loginThroughBrowser(page: Page, email: string, password: string) {
  await page.goto(`${webUrl}/login`, { waitUntil: 'domcontentloaded' })
  await page.locator('#email').fill(email)
  await page.locator('#password').fill(password)
  await page.locator('button[type="submit"]').click()
  await page.waitForFunction(() => Boolean(window.localStorage.getItem('auth_token')), null, { timeout: 30000 })
  const token = await page.evaluate(() => window.localStorage.getItem('auth_token') || '')
  expect(token, 'browser login must store a real auth token').toBeTruthy()
  expect(token).not.toContain('mock-jwt')
  return token
}

async function createSyntheticMember(
  request: APIRequestContext,
  adminToken: string,
  marker: string,
  roleName: string,
  permissions: Record<string, string[]>,
): Promise<SyntheticMember> {
  const suffix = randomUUID()
  const password = `Amx-${suffix}!`
  const email = `${roleName.toLowerCase().replace(/[^a-z]+/g, '-')}-${suffix}@example.test`
  const role = await apiJson<any>(request, 'post', '/identity/roles', adminToken, {
    data: {
      name: `${roleName} ${marker}`.slice(0, 100),
      description: 'Synthetic staging role for the real commercial delivery journey.',
      permissions,
    },
  })
  const user = await apiJson<any>(request, 'post', '/identity/users', adminToken, {
    data: {
      email,
      password,
      full_name: `${roleName} Staging User`,
      is_active: true,
    },
  })
  await apiJson<void>(request, 'post', `/identity/roles/${role.id}/assign`, adminToken, {
    data: { role_id: role.id, user_id: user.id },
  })
  return { roleId: role.id, userId: user.id, email, password }
}

async function pollFor<T>(
  description: string,
  getter: () => Promise<T | null | undefined>,
  predicate: (value: T) => boolean,
  timeoutMs = 90000,
  intervalMs = 2000,
): Promise<T> {
  const startedAt = Date.now()
  let lastValue: T | null | undefined
  while (Date.now() - startedAt < timeoutMs) {
    lastValue = await getter()
    if (lastValue && predicate(lastValue)) return lastValue
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }
  throw new Error(`${description} did not become ready within ${timeoutMs}ms. Last value: ${JSON.stringify(lastValue)}`)
}

function responseItems<T>(value: any): T[] {
  if (Array.isArray(value)) return value
  return Array.isArray(value?.items) ? value.items : []
}

async function closeContext(context: BrowserContext | undefined) {
  await context?.close().catch(() => undefined)
}

test.describe('Real browser commercial delivery validation', () => {
  test.skip(
    !runRealBrowserDelivery,
    'Set RUN_REAL_BROWSER_DELIVERY_TEST=true plus the approved target, SHA, URLs, user, and password to run real browser delivery validation.',
  )

  test('completes the role-separated commercial journey without API mocks or fake JWTs', async ({ browser, page, request }, testInfo) => {
    test.setTimeout(720000)
    requireRealBrowserDeliveryEnv()

    const marker = `AMX-REAL-BROWSER-${Date.now()}`
    const customerEmail = `customer-${randomUUID()}@example.test`
    const revokedCustomerEmail = `revoked-${randomUUID()}@example.test`
    const tempDir = await mkdtemp(path.join(os.tmpdir(), 'amx-real-browser-delivery-'))
    const sourcePath = path.join(tempDir, 'real-browser-delivery-source.md')
    const evidence: JourneyEvidence = {
      target,
      git_sha: gitSha,
      marker,
      project_id: '',
      source_file_id: '',
      ingestion_job_id: '',
      knowledge_entry_id: '',
      document_id: '',
      version_id: '',
      baseline_id: '',
      export_job_id: '',
      artifact_id: '',
      portal_link_id: '',
      acceptance_evidence: '',
      audit_evidence_id: '',
      blocked_paths: [],
      screenshots: [],
      application_cleanup: 'pending',
    }
    let adminToken = ''
    let leadToken = ''
    let reviewerContext: BrowserContext | undefined
    let approverContext: BrowserContext | undefined
    let customerContext: BrowserContext | undefined
    let revokedContext: BrowserContext | undefined
    let adminContext: BrowserContext | undefined

    try {
      adminToken = await loginViaApi(request, bootstrapEmail, bootstrapPassword)
      const lead = await createSyntheticMember(request, adminToken, marker, 'Project Lead', {
        projects: ['read', 'write', 'manage'],
        documents: ['read', 'write', 'review', 'approve', 'export'],
        team: ['read'],
      })
      const reviewer = await createSyntheticMember(request, adminToken, marker, 'Reviewer', {
        projects: ['read'],
        documents: ['read', 'review'],
        team: ['read'],
      })
      const approver = await createSyntheticMember(request, adminToken, marker, 'Approver', {
        projects: ['read'],
        documents: ['read', 'review', 'approve', 'publish'],
        team: ['read'],
      })

      leadToken = await loginThroughBrowser(page, lead.email, lead.password)
      await page.goto(`${webUrl}/projects`, { waitUntil: 'domcontentloaded' })
      await page.getByTestId('open-project-launch').click()
      const blueprint = page.locator('[data-testid^="launch-blueprint-"]').first()
      await expect(blueprint).toBeVisible({ timeout: 30000 })
      await blueprint.click()
      await page.getByTestId('launch-next').click()
      await page.getByTestId('launch-project-name').fill(`Commercial Delivery ${marker}`)
      await page.getByTestId('launch-project-description').fill('Synthetic staging project for the complete delivery journey.')
      await page.getByTestId('launch-next').click()
      await page.getByTestId(`launch-member-${reviewer.userId}`).click()
      await page.getByTestId(`launch-member-${approver.userId}`).click()
      await page.getByTestId('launch-next').click()
      await page.getByTestId('submit-project-launch').click()

      const projectCard = page.locator('[data-testid^="project-card-"]').filter({ hasText: marker }).first()
      await expect(projectCard).toBeVisible({ timeout: 30000 })
      const projectTestId = await projectCard.getAttribute('data-testid')
      evidence.project_id = String(projectTestId || '').replace('project-card-', '')
      expect(evidence.project_id, 'project ID must be discoverable from the normal project UI').toBeTruthy()
      await projectCard.getByRole('link').first().click()
      await expect(page).toHaveURL(new RegExp(`/projects/${evidence.project_id}`))

      await writeFile(
        sourcePath,
        `# Real browser delivery source\n\nThe exact marker ${marker} must flow through ingestion, knowledge, generation, review, export, portal acceptance, and closeout evidence.\n`,
        'utf-8',
      )
      await page.goto(`${webUrl}/projects/${evidence.project_id}/files`, { waitUntil: 'domcontentloaded' })
      await page.getByTestId('source-file-input').setInputFiles(sourcePath)

      const sourceFile = await pollFor<any>(
        'uploaded source file',
        async () => {
          const files = await apiJson<any>(request, 'get', `/projects/${evidence.project_id}/files`, leadToken, {
            params: { page_size: '100' },
          })
          return responseItems<any>(files).find((item) => item.name === 'real-browser-delivery-source.md')
        },
        (item) => Boolean(item.id),
      )
      evidence.source_file_id = sourceFile.id

      const queuedJob = await pollFor<any>(
        'queued source ingestion job',
        async () => {
          const jobs = await apiJson<any>(request, 'get', `/projects/${evidence.project_id}/ingestion-jobs`, leadToken, {
            params: { source_file_id: evidence.source_file_id },
          })
          return responseItems<any>(jobs)[0]
        },
        (job) => Boolean(job.id && ['pending', 'running', 'completed'].includes(job.status)),
      )
      if (queuedJob.status === 'pending') {
        await page.getByTestId(`execute-ingestion-${evidence.source_file_id}`).click()
      }
      const completedJob = await pollFor<any>(
        'completed ingestion job',
        async () => {
          const jobs = await apiJson<any>(request, 'get', `/projects/${evidence.project_id}/ingestion-jobs`, leadToken, {
            params: { source_file_id: evidence.source_file_id },
          })
          return responseItems<any>(jobs)[0]
        },
        (job) => job.status === 'completed' && job.stage === 'knowledge_ready',
      )
      evidence.ingestion_job_id = completedJob.id
      await page.reload({ waitUntil: 'domcontentloaded' })
      await expect(page.getByTestId(`source-knowledge-evidence-${evidence.source_file_id}`)).toBeVisible({ timeout: 30000 })

      const search = await apiJson<any>(request, 'get', '/knowledge/search', leadToken, {
        params: { q: marker, type: 'fulltext', project_id: evidence.project_id },
      })
      const knowledgeEntry = search.results?.[0]?.entry
      expect(knowledgeEntry?.id, 'knowledge search must return the uploaded marker').toBeTruthy()
      expect(knowledgeEntry.source_file_id).toBe(evidence.source_file_id)
      evidence.knowledge_entry_id = knowledgeEntry.id
      const provenance = await apiJson<any[]>(request, 'get', `/knowledge/provenance/${knowledgeEntry.id}`, leadToken)
      expect(provenance.some((item) => item.raw_artifact_id === evidence.source_file_id)).toBeTruthy()

      await page.goto(`${webUrl}/projects/${evidence.project_id}/knowledge`, { waitUntil: 'domcontentloaded' })
      await page.getByTestId('project-knowledge-search').fill(marker)
      const knowledgeCard = page.getByTestId(`knowledge-entry-${evidence.knowledge_entry_id}`)
      await expect(knowledgeCard).toBeVisible({ timeout: 30000 })
      await expect(knowledgeCard).toHaveAttribute('data-source-file-id', evidence.source_file_id)
      await expect(page.getByTestId(`knowledge-entry-lineage-${evidence.knowledge_entry_id}`)).toContainText('real-browser-delivery-source.md')
      const knowledgeScreenshot = testInfo.outputPath('01-source-knowledge.png')
      await page.screenshot({ path: knowledgeScreenshot, fullPage: true })
      evidence.screenshots.push(path.basename(knowledgeScreenshot))

      const generationContext = [
        `Use the exact source-backed marker phrase ${marker}.`,
        'Generate a commercial-delivery PRD with source grounding, acceptance criteria, and export-ready language.',
        `Source file id: ${evidence.source_file_id}. Knowledge entry id: ${evidence.knowledge_entry_id}.`,
      ].join('\n')
      await page.goto(`${webUrl}/projects/${evidence.project_id}/documents/generate?sourceFileId=${evidence.source_file_id}&docType=prd`, {
        waitUntil: 'domcontentloaded',
      })
      await page.locator('#context').fill(generationContext)
      await expect(page.getByTestId('direct-generate-document-action')).toBeEnabled({ timeout: 30000 })
      await page.getByTestId('direct-generate-document-action').click()

      const generatedDocument = await pollFor<any>(
        'provider-generated document',
        async () => {
          const documents = await apiJson<any>(request, 'get', '/documents', leadToken, {
            params: { project_id: evidence.project_id, include_placeholders: 'true', page_size: '100' },
          })
          return responseItems<any>(documents).find((item) => String(item.content || '').includes(marker))
        },
        (document) => (document.metadata_json || document.metadata || {}).generation_status === 'generated',
        180000,
        3000,
      )
      evidence.document_id = generatedDocument.id
      const generationEvidence = (generatedDocument.metadata_json || generatedDocument.metadata || {}).generation_evidence || {}
      expect(generationEvidence.provider || generationEvidence.provider_run_id).toBeTruthy()
      expect(generationEvidence.usage || generationEvidence.model || generationEvidence.provider_run_id).toBeTruthy()

      await page.goto(`${webUrl}/projects/${evidence.project_id}/documents/${evidence.document_id}`, { waitUntil: 'domcontentloaded' })
      await expect(page.getByTestId('document-content-preview')).toContainText(marker, { timeout: 30000 })
      await page.getByTestId('open-edit-document').click()
      const contentEditor = page.getByTestId('edit-document-content')
      const generatedContent = await contentEditor.inputValue()
      await contentEditor.fill(`${generatedContent}\n\nVersion evidence: ${marker}`)
      await page.getByTestId('edit-document-summary').fill('Create immutable reviewed version for staging evidence.')
      await page.getByTestId('save-document-action').click()
      await expect(page.getByTestId('save-document-action')).toBeHidden({ timeout: 30000 })

      const versions = await pollFor<any[]>(
        'persisted document version',
        async () => responseItems<any>(await apiJson<any>(request, 'get', `/documents/${evidence.document_id}/versions`, leadToken)),
        (items) => items.length > 0,
      )
      evidence.version_id = versions[0].id
      await page.getByTestId('document-tab-versions').click()
      await expect(page.getByTestId(`version-item-${evidence.version_id}`)).toBeVisible()
      await page.getByTestId('document-tab-baselines').click()
      await page.getByTestId('baseline-name-input').fill(`Staging baseline ${marker}`)
      await page.getByTestId('create-baseline-action').click()
      const baselines = await pollFor<any[]>(
        'document baseline',
        async () => responseItems<any>(await apiJson<any>(request, 'get', `/documents/${evidence.document_id}/baselines`, leadToken)),
        (items) => items.length > 0,
      )
      evidence.baseline_id = baselines[0].id
      await expect(page.getByTestId(`baseline-item-${evidence.baseline_id}`)).toBeVisible({ timeout: 30000 })
      await page.getByTestId('document-submit-review-action').click()

      reviewerContext = await browser.newContext()
      const reviewerPage = await reviewerContext.newPage()
      await loginThroughBrowser(reviewerPage, reviewer.email, reviewer.password)
      await reviewerPage.goto(`${webUrl}/projects/${evidence.project_id}/documents/${evidence.document_id}`, { waitUntil: 'domcontentloaded' })
      await reviewerPage.getByTestId('document-tab-comments').click()
      await reviewerPage.getByTestId('new-comment-input').fill(`Review evidence for ${marker}`)
      await reviewerPage.getByTestId('add-comment-action').click()
      const comment = await pollFor<any>(
        'created review comment',
        async () => {
          const comments = await apiJson<any[]>(request, 'get', `/collaboration/documents/${evidence.document_id}/comments`, leadToken)
          return comments.find((item) => item.content === `Review evidence for ${marker}`)
        },
        (item) => Boolean(item.id && !item.resolved),
      )

      approverContext = await browser.newContext()
      const approverPage = await approverContext.newPage()
      await loginThroughBrowser(approverPage, approver.email, approver.password)
      await approverPage.goto(`${webUrl}/projects/${evidence.project_id}/documents/${evidence.document_id}`, { waitUntil: 'domcontentloaded' })
      await expect(approverPage.getByTestId('unresolved-comments-count')).toHaveText('1')
      await expect(approverPage.getByTestId('document-approve-action')).toBeDisabled()
      evidence.blocked_paths.push('unresolved_comment_blocks_approval')

      await reviewerPage.getByTestId(`resolve-comment-${comment.id}`).click()
      await pollFor<any>(
        'resolved review comment',
        async () => {
          const comments = await apiJson<any[]>(request, 'get', `/collaboration/documents/${evidence.document_id}/comments`, leadToken)
          return comments.find((item) => item.id === comment.id)
        },
        (item) => item.resolved === true,
      )
      await approverPage.reload({ waitUntil: 'domcontentloaded' })
      await expect(approverPage.getByTestId('document-approve-action')).toBeEnabled({ timeout: 30000 })
      await approverPage.getByTestId('document-approve-action').click()
      await expect(approverPage.getByTestId('document-publish-action')).toBeEnabled({ timeout: 30000 })
      await approverPage.getByTestId('document-publish-action').click()
      await pollFor<any>(
        'published document',
        () => apiJson<any>(request, 'get', `/documents/${evidence.document_id}`, leadToken),
        (document) => document.status === 'published' || (document.metadata_json || document.metadata || {}).status === 'published',
      )

      await page.goto(`${webUrl}/projects/${evidence.project_id}/acceptance`, { waitUntil: 'domcontentloaded' })
      await page.getByTestId('customer-portal-email').fill(customerEmail)
      await expect(page.getByTestId('customer-portal-package-blocker')).toBeVisible()
      await expect(page.getByTestId('create-customer-portal')).toBeDisabled()
      evidence.blocked_paths.push('package_not_ready_blocks_customer_portal')

      await page.goto(`${webUrl}/projects/${evidence.project_id}/documents`, { waitUntil: 'domcontentloaded' })
      await expect(page.getByTestId(`project-document-card-${evidence.document_id}`)).toBeVisible({ timeout: 30000 })
      await expect(page.getByTestId('create-project-package-action')).toBeEnabled({ timeout: 30000 })
      const exportStartedAt = Date.now()
      await page.getByTestId('create-project-package-action').click()
      const exportJob = await pollFor<any>(
        'completed project package export',
        async () => {
          const jobs = await apiJson<any[]>(request, 'get', '/exports', leadToken)
          return jobs
            .filter((job) => job.project_id === evidence.project_id && job.export_type === 'project_package')
            .find((job) => Date.parse(job.created_at || '') >= exportStartedAt - 5000 && job.status === 'completed' && job.artifacts?.length > 0)
        },
        (job) => Boolean(job.id && job.artifacts?.[0]?.id),
        120000,
        3000,
      )
      evidence.export_job_id = exportJob.id
      evidence.artifact_id = exportJob.artifacts[0].id

      await page.goto(`${webUrl}/projects/${evidence.project_id}/acceptance`, { waitUntil: 'domcontentloaded' })
      await page.getByTestId('acceptance-customer-name').fill('Synthetic Browser Customer')
      await page.getByTestId('acceptance-contact-name').fill('Browser Delivery Approver')
      await page.getByTestId('acceptance-contact-email').fill(customerEmail)
      await page.getByTestId('acceptance-decision').selectOption('pending')
      await page.getByTestId('add-acceptance-item').click()
      const acceptanceItems = page.getByTestId('acceptance-items')
      await acceptanceItems.locator('input').nth(0).fill('Commercial delivery artifact accepted')
      await acceptanceItems.locator('select').nth(0).selectOption('pending')
      await acceptanceItems.locator('input').nth(1).fill(`Synthetic evidence for ${marker}`)
      await page.getByTestId('save-acceptance').click()
      await page.getByTestId('customer-portal-email').fill(customerEmail)
      await expect(page.getByTestId('create-customer-portal')).toBeEnabled({ timeout: 30000 })
      await page.getByTestId('create-customer-portal').click()
      const portalUrl = await page.getByTestId('created-customer-portal-url').textContent({ timeout: 30000 })
      expect(portalUrl).toContain('/delivery-portal/')
      const portalLinks = await pollFor<any[]>(
        'customer portal link',
        () => apiJson<any[]>(request, 'get', `/projects/${evidence.project_id}/customer-portal-links`, leadToken),
        (items) => items.some((item) => item.customer_email === customerEmail),
      )
      evidence.portal_link_id = portalLinks.find((item) => item.customer_email === customerEmail).id

      await page.getByTestId('customer-portal-email').fill(revokedCustomerEmail)
      await page.getByTestId('create-customer-portal').click()
      await expect(page.getByTestId('created-customer-portal-url')).not.toHaveText(portalUrl!, { timeout: 30000 })
      const revokedPortalUrl = await page.getByTestId('created-customer-portal-url').textContent()
      const linksWithRevokedCandidate = await pollFor<any[]>(
        'revocable customer portal link',
        () => apiJson<any[]>(request, 'get', `/projects/${evidence.project_id}/customer-portal-links`, leadToken),
        (items) => items.some((item) => item.customer_email === revokedCustomerEmail),
      )
      const revokedLink = linksWithRevokedCandidate.find((item) => item.customer_email === revokedCustomerEmail)
      await expect(page.getByTestId(`revoke-customer-portal-${revokedLink.id}`)).toBeVisible({ timeout: 30000 })
      await page.getByTestId(`revoke-customer-portal-${revokedLink.id}`).click()

      revokedContext = await browser.newContext()
      const revokedPage = await revokedContext.newPage()
      await revokedPage.goto(revokedPortalUrl!, { waitUntil: 'domcontentloaded' })
      await expect(revokedPage.getByTestId('portal-unavailable')).toBeVisible({ timeout: 30000 })
      evidence.blocked_paths.push('revoked_customer_token_denied')

      customerContext = await browser.newContext({ acceptDownloads: true })
      const customerPage = await customerContext.newPage()
      await customerPage.goto(portalUrl!, { waitUntil: 'domcontentloaded' })
      expect(await customerPage.evaluate(() => window.localStorage.getItem('auth_token'))).toBeNull()
      await expect(customerPage.getByTestId('portal-artifacts')).toContainText(exportJob.artifacts[0].filename, { timeout: 30000 })
      const internalResponse = await customerContext.request.get(`${apiUrl}/projects`)
      expect([401, 403]).toContain(internalResponse.status())
      evidence.blocked_paths.push('customer_token_cannot_access_internal_api')

      const downloadPromise = customerPage.waitForEvent('download')
      await customerPage.getByTestId(`portal-download-artifact-${evidence.artifact_id}`).click()
      const download = await downloadPromise
      const downloadPath = await download.path()
      expect(downloadPath, 'customer browser download must produce a local artifact').toBeTruthy()
      const downloadedContent = await readFile(downloadPath!)
      expect(downloadedContent.toString('utf-8')).toContain(marker)
      const portalScreenshot = testInfo.outputPath('02-customer-portal.png')
      await customerPage.screenshot({ path: portalScreenshot, fullPage: true })
      evidence.screenshots.push(path.basename(portalScreenshot))

      await customerPage.getByTestId('portal-contact-name').fill('Browser Delivery Approver')
      await customerPage.getByTestId('portal-contact-email').fill(customerEmail)
      await customerPage.getByTestId('portal-decision').selectOption('accepted')
      await customerPage.getByTestId('portal-acceptance-criteria').locator('select').first().selectOption('accepted')
      await customerPage.getByTestId('submit-customer-acceptance').click()
      await expect(customerPage.getByTestId('acceptance-receipt')).toBeVisible({ timeout: 30000 })

      await page.goto(`${webUrl}/projects/${evidence.project_id}/acceptance`, { waitUntil: 'domcontentloaded' })
      await expect(page.getByTestId('close-formal-delivery')).toBeEnabled({ timeout: 30000 })
      await page.getByTestId('close-formal-delivery').click()
      const closedAcceptance = await pollFor<any>(
        'formal delivery closeout',
        () => apiJson<any>(request, 'get', `/projects/${evidence.project_id}/acceptance`, leadToken),
        (acceptance) => Boolean(acceptance.closed_at),
      )
      evidence.acceptance_evidence = `decision=${closedAcceptance.decision};closed=true`

      const auditResponse = await pollFor<any>(
        'sanitized closeout audit evidence',
        () => apiJson<any>(request, 'get', '/identity/audit-logs', adminToken, {
          params: { resource_id: evidence.project_id, limit: '100' },
        }),
        (response) => responseItems<any>(response).some((item) => item.action === 'project.acceptance.close'),
      )
      const closeoutAudit = responseItems<any>(auditResponse).find((item) => item.action === 'project.acceptance.close')
      evidence.audit_evidence_id = closeoutAudit.id

      adminContext = await browser.newContext()
      const adminPage = await adminContext.newPage()
      await loginThroughBrowser(adminPage, bootstrapEmail, bootstrapPassword)
      await adminPage.goto(`${webUrl}/audit`, { waitUntil: 'domcontentloaded' })
      await adminPage.getByTestId('audit-search').fill('project.acceptance.close')
      await expect(adminPage.getByTestId('audit-entry').filter({ hasText: 'project.acceptance.close' }).first()).toBeVisible({ timeout: 30000 })
      const auditScreenshot = testInfo.outputPath('03-sanitized-audit.png')
      await adminPage.screenshot({ path: auditScreenshot, fullPage: true })
      evidence.screenshots.push(path.basename(auditScreenshot))
    } finally {
      if (leadToken && evidence.project_id) {
        const archiveResponse = await request.post(`${apiUrl}/projects/${evidence.project_id}/archive`, {
          headers: { Authorization: `Bearer ${leadToken}` },
        }).catch(() => undefined)
        evidence.application_cleanup = archiveResponse?.ok() ? 'project_archived; disposable_staging_teardown_required' : 'archive_failed; disposable_staging_teardown_required'
      }
      await testInfo.attach('commercial-delivery-evidence.json', {
        body: Buffer.from(JSON.stringify(evidence, null, 2), 'utf-8'),
        contentType: 'application/json',
      })
      await Promise.all([
        closeContext(reviewerContext),
        closeContext(approverContext),
        closeContext(customerContext),
        closeContext(revokedContext),
        closeContext(adminContext),
      ])
      await rm(tempDir, { recursive: true, force: true }).catch(() => undefined)
    }
  })
})
