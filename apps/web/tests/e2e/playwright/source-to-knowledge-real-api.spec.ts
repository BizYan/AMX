import { expect, test } from '@playwright/test'
import { Buffer } from 'node:buffer'

const runRealSourceKnowledge = process.env.RUN_REAL_SOURCE_KNOWLEDGE_TEST === 'true'
const apiUrl = process.env.E2E_API_URL || 'http://localhost:18000/api/v1'
const testEmail = process.env.E2E_USER_EMAIL || ''
const testPassword = process.env.E2E_PASSWORD || ''

test.describe('Source to Knowledge real API path', () => {
  test.skip(
    !runRealSourceKnowledge,
    'Set RUN_REAL_SOURCE_KNOWLEDGE_TEST=true with E2E_API_URL, E2E_USER_EMAIL, and E2E_PASSWORD to run real source-to-knowledge evidence.'
  )

  test('uploads a real file, executes ingestion, searches marker, verifies provenance, and shows UI evidence', async ({ page, request }) => {
    expect(testEmail, 'E2E_USER_EMAIL is required for real source-to-knowledge evidence').toBeTruthy()
    expect(testPassword, 'E2E_PASSWORD is required for real source-to-knowledge evidence').toBeTruthy()

    const loginResponse = await request.post(`${apiUrl}/identity/auth/login`, {
      data: { email: testEmail, password: testPassword },
    })
    expect(loginResponse.ok(), `login failed with HTTP ${loginResponse.status()}`).toBeTruthy()
    const loginBody = await loginResponse.json()
    const token = loginBody.access_token
    expect(token, 'real login must return an access token').toBeTruthy()
    const headers = { Authorization: `Bearer ${token}` }

    const marker = `AMX-REAL-SOURCE-KNOWLEDGE-${Date.now()}`
    const projectResponse = await request.post(`${apiUrl}/projects`, {
      headers,
      data: {
        name: `Real Source Knowledge ${marker}`,
        slug: `real-source-knowledge-${Date.now()}`,
        description: 'Disposable source-to-knowledge evidence project.',
      },
    })
    expect(projectResponse.status()).toBe(201)
    const project = await projectResponse.json()
    const projectId = project.id

    let sourceFileId = ''
    try {
      const uploadResponse = await request.post(`${apiUrl}/projects/${projectId}/files`, {
        headers,
        multipart: {
          file: {
            name: 'real-source-to-knowledge.md',
            mimeType: 'text/markdown',
            buffer: Buffer.from(`# Real source evidence\n\n${marker} must be searchable and traceable.`),
          },
        },
      })
      expect(uploadResponse.status()).toBe(201)
      const sourceFile = await uploadResponse.json()
      sourceFileId = sourceFile.id
      expect(sourceFileId).toBeTruthy()

      const jobsResponse = await request.get(`${apiUrl}/projects/${projectId}/ingestion-jobs?source_file_id=${sourceFileId}`, { headers })
      expect(jobsResponse.ok()).toBeTruthy()
      const jobs = await jobsResponse.json()
      const job = jobs.items?.[0]
      expect(job?.id, 'upload must queue an ingestion job').toBeTruthy()

      const executeResponse = await request.post(`${apiUrl}/projects/${projectId}/ingestion-jobs/${job.id}/execute`, { headers })
      expect(executeResponse.ok()).toBeTruthy()
      const completed = await executeResponse.json()
      expect(completed.status).toBe('completed')

      const searchResponse = await request.get(`${apiUrl}/knowledge/search`, {
        headers,
        params: { q: marker, type: 'fulltext', project_id: projectId },
      })
      expect(searchResponse.ok()).toBeTruthy()
      const search = await searchResponse.json()
      const entry = search.results?.[0]?.entry
      expect(entry?.id, 'knowledge search must return the marker entry').toBeTruthy()
      expect(entry.source_file_id).toBe(sourceFileId)

      const provenanceResponse = await request.get(`${apiUrl}/knowledge/provenance/${entry.id}`, { headers })
      expect(provenanceResponse.ok()).toBeTruthy()
      const provenance = await provenanceResponse.json()
      expect(provenance.some((item: any) => item.raw_artifact_id === sourceFileId)).toBeTruthy()

      await page.goto('/')
      await page.evaluate((authToken) => localStorage.setItem('auth_token', authToken), token)
      await page.goto(`/projects/${projectId}/files`, { waitUntil: 'domcontentloaded' })
      await expect(page.getByText('real-source-to-knowledge.md')).toBeVisible()
      await expect(page.getByTestId(`source-knowledge-evidence-${sourceFileId}`)).toContainText('知识可检索')
    } finally {
      if (sourceFileId) {
        await request.delete(`${apiUrl}/projects/${projectId}/files/${sourceFileId}`, { headers }).catch(() => undefined)
      }
      if (projectId) {
        await request.post(`${apiUrl}/projects/${projectId}/archive`, { headers }).catch(() => undefined)
      }
    }
  })
})
