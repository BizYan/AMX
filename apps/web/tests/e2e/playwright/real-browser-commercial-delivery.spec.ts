import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'

const runRealBrowserDelivery = process.env.RUN_REAL_BROWSER_DELIVERY_TEST === 'true'
const webUrl = normalizeBaseUrl(process.env.E2E_WEB_URL || '')
const apiUrl = normalizeApiUrl(process.env.E2E_API_URL || '')
const userEmail = process.env.E2E_USER_EMAIL || ''
const password = process.env.E2E_PASSWORD || ''

type ApiOptions = {
  data?: unknown
  headers?: Record<string, string>
  multipart?: Record<string, unknown>
  params?: Record<string, string>
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
  expect(webUrl, 'E2E_WEB_URL is required when RUN_REAL_BROWSER_DELIVERY_TEST=true').toBeTruthy()
  expect(apiUrl, 'E2E_API_URL is required when RUN_REAL_BROWSER_DELIVERY_TEST=true').toBeTruthy()
  expect(userEmail, 'E2E_USER_EMAIL is required when RUN_REAL_BROWSER_DELIVERY_TEST=true').toBeTruthy()
  expect(password, 'E2E_PASSWORD is required when RUN_REAL_BROWSER_DELIVERY_TEST=true').toBeTruthy()
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
  expect(response.ok(), `${method.toUpperCase()} ${endpoint} failed with HTTP ${response.status()}: ${body.slice(0, 600)}`).toBeTruthy()
  return body ? JSON.parse(body) as T : undefined as T
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

async function loginThroughBrowser(page: Page) {
  await page.goto(`${webUrl}/login`, { waitUntil: 'domcontentloaded' })
  await page.locator('#email').fill(userEmail)
  await page.locator('#password').fill(password)
  await page.locator('button[type="submit"]').click()
  await page.waitForFunction(() => Boolean(window.localStorage.getItem('auth_token')), null, { timeout: 30000 })
  const token = await page.evaluate(() => window.localStorage.getItem('auth_token') || '')
  expect(token, 'browser login must store a real auth token').toBeTruthy()
  expect(token).not.toContain('mock-jwt')
  return token
}

test.describe('Real browser commercial delivery validation', () => {
  test.skip(
    !runRealBrowserDelivery,
    'Set RUN_REAL_BROWSER_DELIVERY_TEST=true plus E2E_WEB_URL, E2E_API_URL, E2E_USER_EMAIL, and E2E_PASSWORD to run real browser delivery validation.',
  )

  test('runs the real browser delivery journey without API mocks or fake JWTs', async ({ page, request }) => {
    test.setTimeout(420000)
    requireRealBrowserDeliveryEnv()

    const marker = `AMX-REAL-BROWSER-DELIVERY-${Date.now()}`
    const customerEmail = `browser-delivery-${Date.now()}@example.test`
    const tempDir = await mkdtemp(path.join(os.tmpdir(), 'amx-real-browser-delivery-'))
    const sourcePath = path.join(tempDir, 'real-browser-delivery-source.md')
    let projectId = ''
    let sourceFileId = ''

    const token = await loginThroughBrowser(page)

    try {
      const project = await apiJson<any>(request, 'post', '/projects', token, {
        data: {
          name: `Real Browser Delivery ${marker}`,
          slug: `real-browser-delivery-${Date.now()}`,
          description: 'Synthetic real-browser commercial delivery validation project.',
        },
      })
      projectId = project.id
      expect(projectId, 'project must be created in the real backend').toBeTruthy()

      await page.goto(`${webUrl}/projects`, { waitUntil: 'domcontentloaded' })
      await expect(page.getByTestId(`project-card-${projectId}`)).toContainText(marker)
      await page.getByTestId(`project-card-${projectId}`).getByRole('link').first().click()
      await expect(page).toHaveURL(new RegExp(`/projects/${projectId}`))

      await writeFile(
        sourcePath,
        `# Real browser delivery source\n\nThe exact marker ${marker} must flow through ingestion, knowledge, generation, export, portal acceptance, and closeout evidence.\n`,
        'utf-8',
      )

      await page.goto(`${webUrl}/projects/${projectId}/files`, { waitUntil: 'domcontentloaded' })
      await page.getByTestId('source-file-input').setInputFiles(sourcePath)

      const sourceFile = await pollFor<any>(
        'uploaded source file',
        async () => {
          const files = await apiJson<any>(request, 'get', `/projects/${projectId}/files`, token, {
            params: { page_size: '100' },
          })
          return (files.items || []).find((item: any) => item.name === 'real-browser-delivery-source.md')
        },
        (item) => Boolean(item.id),
      )
      sourceFileId = sourceFile.id

      const queuedJob = await pollFor<any>(
        'queued source ingestion job',
        async () => {
          const jobs = await apiJson<any>(request, 'get', `/projects/${projectId}/ingestion-jobs`, token, {
            params: { source_file_id: sourceFileId },
          })
          return jobs.items?.[0]
        },
        (job) => Boolean(job.id && ['pending', 'running', 'completed'].includes(job.status)),
      )

      await page.goto(`${webUrl}/projects/${projectId}/files`, { waitUntil: 'domcontentloaded' })
      if (queuedJob.status === 'pending') {
        await page.getByTestId(`execute-ingestion-${sourceFileId}`).click()
      }

      const completedJob = await pollFor<any>(
        'completed ingestion job',
        async () => {
          const jobs = await apiJson<any>(request, 'get', `/projects/${projectId}/ingestion-jobs`, token, {
            params: { source_file_id: sourceFileId },
          })
          return jobs.items?.[0]
        },
        (job) => job.status === 'completed' && job.stage === 'knowledge_ready',
      )

      await page.goto(`${webUrl}/projects/${projectId}/files`, { waitUntil: 'domcontentloaded' })
      await expect(page.getByTestId(`source-knowledge-evidence-${sourceFileId}`)).toBeVisible({ timeout: 30000 })

      const search = await apiJson<any>(request, 'get', '/knowledge/search', token, {
        params: { q: marker, type: 'fulltext', project_id: projectId },
      })
      const knowledgeEntry = search.results?.[0]?.entry
      expect(knowledgeEntry?.id, 'knowledge search must return the uploaded marker').toBeTruthy()
      expect(knowledgeEntry.source_file_id).toBe(sourceFileId)

      const provenance = await apiJson<any[]>(request, 'get', `/knowledge/provenance/${knowledgeEntry.id}`, token)
      expect(provenance.some((item) => item.raw_artifact_id === sourceFileId), 'provenance must link knowledge to the source file').toBeTruthy()

      const generationContext = [
        `Use the exact source-backed marker phrase ${marker}.`,
        'Generate a commercial-delivery PRD section with source grounding, acceptance criteria, and export-ready language.',
        `Source file id: ${sourceFileId}. Knowledge entry id: ${knowledgeEntry.id}.`,
      ].join('\n')

      await page.goto(`${webUrl}/projects/${projectId}/documents/generate?sourceFileId=${sourceFileId}&docType=prd`, {
        waitUntil: 'domcontentloaded',
      })
      await page.locator('#context').fill(generationContext)
      await expect(page.getByTestId('direct-generate-document-action')).toBeEnabled({ timeout: 30000 })
      await page.getByTestId('direct-generate-document-action').click()

      const generatedDocument = await pollFor<any>(
        'provider-generated document',
        async () => {
          const documents = await apiJson<any>(request, 'get', '/documents', token, {
            params: { project_id: projectId, include_placeholders: 'true', page_size: '100' },
          })
          return (documents.items || []).find((item: any) => String(item.content || '').includes(marker))
        },
        (document) => {
          const metadata = document.metadata_json || document.metadata || {}
          return metadata.generation_status === 'generated'
        },
        120000,
        3000,
      )
      const documentId = generatedDocument.id
      const generationEvidence = (generatedDocument.metadata_json || generatedDocument.metadata || {}).generation_evidence || {}
      expect(generationEvidence.provider || generationEvidence.provider_run_id, 'generation must record provider identity or provider run evidence').toBeTruthy()
      expect(generationEvidence.usage || generationEvidence.model || generationEvidence.provider_run_id, 'generation must record model, usage, or run evidence').toBeTruthy()

      await page.goto(`${webUrl}/projects/${projectId}/documents/${documentId}`, { waitUntil: 'domcontentloaded' })
      await expect(page.getByTestId('document-content-preview')).toContainText(marker, { timeout: 30000 })
      await page.getByTestId('document-tab-comments').click()
      await page.getByTestId('new-comment-input').fill(`Review evidence for ${marker}`)
      await page.getByTestId('add-comment-action').click()

      const comment = await pollFor<any>(
        'created review comment',
        async () => {
          const comments = await apiJson<any[]>(request, 'get', `/collaboration/documents/${documentId}/comments`, token)
          return comments.find((item) => item.content === `Review evidence for ${marker}`)
        },
        (item) => Boolean(item.id && !item.resolved),
      )
      await page.getByTestId(`resolve-comment-${comment.id}`).click()
      await pollFor<any>(
        'resolved review comment',
        async () => {
          const comments = await apiJson<any[]>(request, 'get', `/collaboration/documents/${documentId}/comments`, token)
          return comments.find((item) => item.id === comment.id)
        },
        (item) => item.resolved === true,
      )

      await expect(page.getByTestId('document-approve-action')).toBeEnabled({ timeout: 30000 })
      await page.getByTestId('document-approve-action').click()
      await expect(page.getByTestId('document-publish-action')).toBeEnabled({ timeout: 30000 })
      await page.getByTestId('document-publish-action').click()

      await pollFor<any>(
        'published document',
        () => apiJson<any>(request, 'get', `/documents/${documentId}`, token),
        (document) => ['published', 'approved'].includes(document.status) || ['published', 'approved'].includes((document.metadata_json || document.metadata || {}).status),
      )

      await page.goto(`${webUrl}/projects/${projectId}/documents`, { waitUntil: 'domcontentloaded' })
      await expect(page.getByTestId(`project-document-card-${documentId}`)).toBeVisible({ timeout: 30000 })
      await expect(page.getByTestId('create-project-package-action')).toBeEnabled({ timeout: 30000 })
      const exportStartedAt = Date.now()
      await page.getByTestId('create-project-package-action').click()

      const exportJob = await pollFor<any>(
        'completed project package export',
        async () => {
          const jobs = await apiJson<any[]>(request, 'get', '/exports', token)
          return jobs
            .filter((job) => job.project_id === projectId && job.export_type === 'project_package')
            .find((job) => Date.parse(job.created_at || '') >= exportStartedAt - 5000 && job.status === 'completed' && (job.artifacts || []).length > 0)
        },
        (job) => Boolean(job.id && job.artifacts?.[0]?.id),
        120000,
        3000,
      )
      const artifact = exportJob.artifacts[0]

      await page.goto(`${webUrl}/projects/${projectId}/acceptance`, { waitUntil: 'domcontentloaded' })
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
      await page.getByTestId('create-customer-portal').click()
      const portalUrl = await page.getByTestId('created-customer-portal-url').textContent({ timeout: 30000 })
      expect(portalUrl, 'customer portal URL must be revealed exactly once after creation').toContain('/delivery-portal/')

      await page.goto(portalUrl!, { waitUntil: 'domcontentloaded' })
      await expect(page.getByTestId('portal-artifacts')).toContainText(artifact.filename, { timeout: 30000 })
      const downloadLink = page.getByTestId(`portal-download-artifact-${artifact.id}`)
      await expect(downloadLink).toBeVisible()
      const href = await downloadLink.getAttribute('href')
      expect(href, 'customer portal artifact download href must exist').toBeTruthy()
      const artifactResponse = await request.get(new URL(href!, webUrl).toString())
      expect(artifactResponse.ok(), `customer artifact download failed with HTTP ${artifactResponse.status()}`).toBeTruthy()
      expect((await artifactResponse.text()).includes(marker), 'downloaded package must contain the generated marker').toBeTruthy()

      await page.getByTestId('portal-contact-name').fill('Browser Delivery Approver')
      await page.getByTestId('portal-contact-email').fill(customerEmail)
      await page.getByTestId('portal-decision').selectOption('accepted')
      await page.getByTestId('portal-acceptance-criteria').locator('select').first().selectOption('accepted')
      await page.getByTestId('submit-customer-acceptance').click()
      await expect(page.getByTestId('acceptance-receipt')).toBeVisible({ timeout: 30000 })

      await page.goto(`${webUrl}/projects/${projectId}/acceptance`, { waitUntil: 'domcontentloaded' })
      await expect(page.getByTestId('close-formal-delivery')).toBeEnabled({ timeout: 30000 })
      await page.getByTestId('close-formal-delivery').click()

      const closedAcceptance = await pollFor<any>(
        'formal delivery closeout',
        () => apiJson<any>(request, 'get', `/projects/${projectId}/acceptance`, token),
        (acceptance) => Boolean(acceptance.closed_at),
      )

      expect(completedJob.id, 'evidence includes ingestion job id').toBeTruthy()
      expect(knowledgeEntry.id, 'evidence includes knowledge entry id').toBeTruthy()
      expect(exportJob.id, 'evidence includes export job id').toBeTruthy()
      expect(closedAcceptance.closed_at, 'delivery closeout must be recorded').toBeTruthy()
    } finally {
      if (sourceFileId && projectId) {
        await request.delete(`${apiUrl}/projects/${projectId}/files/${sourceFileId}`, {
          headers: { Authorization: `Bearer ${token}` },
        }).catch(() => undefined)
      }
      if (projectId) {
        await request.post(`${apiUrl}/projects/${projectId}/archive`, {
          headers: { Authorization: `Bearer ${token}` },
        }).catch(() => undefined)
      }
      await rm(tempDir, { recursive: true, force: true }).catch(() => undefined)
    }
  })
})
