import { expect, Page, test } from '@playwright/test'
import { projectMembersApi, templatesApi } from '../../../src/lib/api-client'
import { setupApiMocks } from './fixtures/api-mocks'

async function prepareAuthenticatedPage(page: Page) {
  await setupApiMocks(page)
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => {
    localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
  })
}

function reviewDocumentPayload(status = 'review') {
  return {
    id: 'doc-review-001',
    projectId: 'project-e2e-001',
    project_id: 'project-e2e-001',
    name: 'Review status regression',
    title: 'Review status regression',
    type: 'urs',
    doc_type: 'urs',
    status,
    content: '# Review status regression\n\nStable content for core workflow tests.',
    metadata: { status },
    metadata_json: { status },
    createdAt: '2026-05-25T00:00:00Z',
    created_at: '2026-05-25T00:00:00Z',
    updatedAt: '2026-05-25T00:00:00Z',
    updated_at: '2026-05-25T00:00:00Z',
  }
}

test('document list uses the backend review status value', async ({ page }) => {
  await prepareAuthenticatedPage(page)

  await page.route(/\/api\/v1\/documents(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [reviewDocumentPayload()],
        total: 1,
        page: 1,
        page_size: 10,
        has_more: false,
      }),
    })
  })

  await page.goto('/projects/project-e2e-001/documents', { waitUntil: 'domcontentloaded' })

  const statusFilter = page.getByTestId('document-status-filter')
  await expect(statusFilter).toBeVisible()
  await expect(statusFilter.locator('option[value="review"]')).toHaveCount(1)
  await expect(statusFilter.locator('option[value="under_review"]')).toHaveCount(0)

  await statusFilter.selectOption('review')
  await expect(page.getByRole('link', { name: 'Review status regression' })).toBeVisible()
})

test('document detail supports archive and delete actions', async ({ page }) => {
  await prepareAuthenticatedPage(page)

  const statusPayloads: Array<Record<string, unknown>> = []
  let deletedDocument = false

  await page.route(/\/api\/v1\/documents\/doc-review-001\/status$/, async (route) => {
    const payload = JSON.parse(route.request().postData() || '{}')
    statusPayloads.push(payload)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(reviewDocumentPayload(String(payload.status || 'review'))),
    })
  })

  await page.route(/\/api\/v1\/documents\/doc-review-001(?:\?.*)?$/, async (route) => {
    const method = route.request().method()

    if (method === 'DELETE') {
      deletedDocument = true
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      })
      return
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(reviewDocumentPayload()),
    })
  })

  page.on('dialog', (dialog) => dialog.accept())

  await page.goto('/projects/project-e2e-001/documents/doc-review-001', { waitUntil: 'domcontentloaded' })

  await page.getByTestId('document-archive-action').click()
  await expect.poll(() => statusPayloads.some((payload) => payload.status === 'archived')).toBe(true)

  await page.getByTestId('document-delete-action').click()
  await expect.poll(() => deletedDocument).toBe(true)
  await expect(page).toHaveURL(/\/projects\/project-e2e-001\/documents$/)
})

test('typed API helpers use backend routes for template uploads and member removal', async () => {
  const requests: Array<{ method?: string; url: string }> = []
  const originalFetch = globalThis.fetch
  const originalLocalStorage = (globalThis as typeof globalThis & { localStorage?: Storage }).localStorage

  try {
    ;(globalThis as typeof globalThis & { localStorage: Pick<Storage, 'getItem'> }).localStorage = {
      getItem: () => 'mock-jwt-token-1234567890abcdef',
    }
    globalThis.fetch = async (input, init) => {
      requests.push({ method: init?.method, url: String(input) })
      return new Response(JSON.stringify({ id: 'ok' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }

    const formData = new FormData()
    formData.append('file', new Blob(['template']), 'template.docx')
    formData.append('description', 'Next version')

    await templatesApi.uploadVersion('template-123', formData)
    await (
      projectMembersApi as typeof projectMembersApi & {
        remove: (projectId: string, userId: string) => Promise<unknown>
      }
    ).remove('project-123', 'user-456')
  } finally {
    globalThis.fetch = originalFetch
    if (originalLocalStorage) {
      ;(globalThis as typeof globalThis & { localStorage: Storage }).localStorage = originalLocalStorage
    } else {
      delete (globalThis as typeof globalThis & { localStorage?: Storage }).localStorage
    }
  }

  expect(requests).toHaveLength(2)

  const templateUploadUrl = new URL(requests[0].url)
  expect(requests[0].method).toBe('POST')
  expect(templateUploadUrl.pathname).toBe('/api/v1/templates/upload')
  expect(templateUploadUrl.searchParams.get('template_id')).toBe('template-123')
  expect(templateUploadUrl.searchParams.get('description')).toBe('Next version')

  const memberRemoveUrl = new URL(requests[1].url)
  expect(requests[1].method).toBe('DELETE')
  expect(memberRemoveUrl.pathname).toBe('/api/v1/projects/project-123/members/user-456')
})

test('project members and project list expose explicit removal controls', async ({ page }) => {
  await prepareAuthenticatedPage(page)

  let members = [
    {
      user_id: 'user-admin-001',
      role_id: 'admin',
      project_id: 'project-e2e-001',
      created_at: '2026-05-21T09:00:00Z',
      updated_at: '2026-05-21T09:00:00Z',
    },
    {
      user_id: 'user-member-001',
      role_id: 'member',
      project_id: 'project-e2e-001',
      created_at: '2026-05-25T00:00:00Z',
      updated_at: '2026-05-25T00:00:00Z',
    },
  ]
  let projects = [
    {
      id: 'project-e2e-001',
      name: 'Core workflow project',
      description: 'Project removal regression',
      slug: 'project-e2e-001',
      documentCount: 2,
      document_count: 2,
      createdAt: '2026-05-21T09:00:00Z',
      created_at: '2026-05-21T09:00:00Z',
      updatedAt: '2026-05-21T09:00:00Z',
      updated_at: '2026-05-21T09:00:00Z',
    },
  ]
  let removedMember = false
  let deletedProject = false

  await page.route(/\/api\/v1\/identity\/users(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [
          { id: 'user-admin-001', email: 'admin@example.com', full_name: 'Admin User' },
          { id: 'user-member-001', email: 'member@example.com', full_name: 'Member User' },
        ],
        total: 2,
      }),
    })
  })

  await page.route(/\/api\/v1\/projects\/project-e2e-001\/members(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: members,
        total: members.length,
        page: 1,
        page_size: 10,
        has_more: false,
      }),
    })
  })

  await page.route(/\/api\/v1\/projects\/project-e2e-001\/members\/user-member-001$/, async (route) => {
    removedMember = true
    members = members.filter((member) => member.user_id !== 'user-member-001')
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true }),
    })
  })

  await page.route(/\/api\/v1\/projects(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: projects,
        total: projects.length,
        page: 1,
        page_size: 10,
        has_more: false,
      }),
    })
  })

  await page.route(/\/api\/v1\/projects\/project-e2e-001(?:\?.*)?$/, async (route) => {
    if (route.request().method() === 'DELETE') {
      deletedProject = true
      projects = []
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      })
      return
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(projects[0]),
    })
  })

  page.on('dialog', (dialog) => dialog.accept())

  await page.goto('/projects/project-e2e-001/members', { waitUntil: 'domcontentloaded' })
  await page.getByTestId('project-member-remove-user-member-001').click()
  await expect.poll(() => removedMember).toBe(true)
  await expect(page.getByTestId('project-member-remove-user-member-001')).not.toBeVisible()

  await page.goto('/projects', { waitUntil: 'domcontentloaded' })
  await page.getByTestId('project-actions-project-e2e-001').click()
  await page.getByTestId('project-delete-project-e2e-001').click()
  await expect.poll(() => deletedProject).toBe(true)
  await expect(page.getByTestId('project-card-project-e2e-001')).not.toBeVisible()
})
