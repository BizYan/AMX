import { expect, Page, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'
import * as MOCK from './fixtures/mock-data'

async function gotoAppPage(page: Page, path: string) {
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => {
    localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
  })
  await page.goto(path, { waitUntil: 'domcontentloaded' })
}

test.describe('P2 document review and release flow', () => {
  test.beforeEach(async ({ page }) => {
    const documents = MOCK.MOCK_DOCUMENTS.map((document) =>
      document.id === 'doc-e2e-001'
        ? {
            ...document,
            status: 'approved',
            metadata: { ...(document.metadata || {}), status: 'approved' },
            metadata_json: { ...(document.metadata_json || {}), status: 'approved' },
          }
        : document
    )

    await setupApiMocks(page, {
      documents,
      statusHistory: [
        {
          from_status: 'review',
          to_status: 'approved',
          reason: 'QA accepted review findings',
          changed_by: 'user-admin-001',
          changed_at: '2026-05-21T09:04:00Z',
          unresolved_comment_count: 0,
        },
      ],
    })
  })

  test('shows review history and only publishes an approved document after comments are resolved', async ({ page }) => {
    await gotoAppPage(page, '/projects/project-e2e-001/documents/doc-e2e-001')

    await expect(page.getByTestId('document-review-flow-heading')).toBeVisible({ timeout: 8000 })
    await expect(page.getByTestId('document-status-governance')).toBeVisible()
    await expect(page.getByTestId('document-status-capability-published')).toContainText('受限')
    await expect(page.getByTestId('document-status-capability-message-published')).toContainText('评论未解决')
    await expect(page.getByTestId('document-status-current')).toContainText('approved')
    await expect(page.getByTestId('status-history-list')).toContainText('QA accepted review findings')
    await expect(page.getByTestId('document-publish-action')).toBeDisabled()

    await page.getByTestId('document-tab-comments').click()
    await page.getByTestId('resolve-comment-comment-e2e-001').click()
    await expect(page.getByTestId('unresolved-comments-count')).toHaveText('0')
    await expect(page.getByTestId('document-status-capability-published')).toContainText('可执行')

    await page.getByTestId('document-publish-action').click()
    await expect(page.getByTestId('document-status-current')).toContainText('published')
    await expect(page.getByTestId('status-history-list')).toContainText('Release after comment resolution')
  })

  test('explains missing publish permission and keeps the action disabled', async ({ page }) => {
    await setupApiMocks(page, {
      documents: MOCK.MOCK_DOCUMENTS.map((document) =>
        document.id === 'doc-e2e-001'
          ? { ...document, status: 'approved' }
          : document
      ),
      statusCapabilities: [
        {
          status: 'published',
          permission_action: 'documents.publish',
          allowed: false,
          authorization_reason: 'no_grant',
          blockers: [],
        },
      ],
    })

    await gotoAppPage(page, '/projects/project-e2e-001/documents/doc-e2e-001')

    await expect(page.getByTestId('document-status-capability-published')).toContainText('受限')
    await expect(page.getByTestId('document-status-capability-message-published')).toContainText('缺少“发布文档”权限')
    await expect(page.getByTestId('document-publish-action')).toBeDisabled()
  })

  test('explains delivery readiness blockers from status capabilities', async ({ page }) => {
    await setupApiMocks(page, {
      documents: MOCK.MOCK_DOCUMENTS.map((document) =>
        document.id === 'doc-e2e-001'
          ? { ...document, status: 'approved' }
          : document
      ),
      statusCapabilities: [
        {
          status: 'published',
          permission_action: 'documents.publish',
          allowed: false,
          authorization_reason: 'rbac',
          blockers: [
            'Document delivery readiness blocks publish: low quality sections: brd.requirement_modules',
          ],
        },
      ],
    })

    await gotoAppPage(page, '/projects/project-e2e-001/documents/doc-e2e-001')

    await expect(page.getByTestId('document-status-capability-published')).toContainText('受限')
    await expect(page.getByTestId('document-status-capability-message-published')).toContainText('交付准备度未达标')
    await expect(page.getByTestId('document-publish-action')).toBeDisabled()
  })
})
