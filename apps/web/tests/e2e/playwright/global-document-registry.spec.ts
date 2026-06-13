import { expect, Page, test } from '@playwright/test'

import { setupApiMocks } from './fixtures/api-mocks'
import * as MOCK from './fixtures/mock-data'

const TEMPLATE_PLACEHOLDER_DOCUMENT = {
  id: 'doc-e2e-007',
  projectId: 'project-e2e-001',
  project_id: 'project-e2e-001',
  name: '客户验收确认书',
  title: '客户验收确认书',
  type: 'acceptance_report',
  doc_type: 'acceptance_report',
  status: 'approved',
  content: '# 客户验收确认书\n\n验收负责人：{{验收负责人}}\n客户名称：{{客户名称}}',
  metadata: {
    status: 'approved',
    generation_status: 'generated',
    unresolved_template_placeholders: ['验收负责人', '客户名称'],
    template_placeholder_evidence: {
      unresolved_placeholders: ['验收负责人', '客户名称'],
    },
  },
  metadata_json: {
    status: 'approved',
    generation_status: 'generated',
    unresolved_template_placeholders: ['验收负责人', '客户名称'],
    template_placeholder_evidence: {
      unresolved_placeholders: ['验收负责人', '客户名称'],
    },
  },
  version: 1,
  createdAt: '2026-05-21T09:18:00Z',
  created_at: '2026-05-21T09:18:00Z',
  updatedAt: '2026-05-21T09:18:00Z',
  updated_at: '2026-05-21T09:18:00Z',
}

async function prepareAuthenticatedPage(page: Page) {
  await setupApiMocks(page, { documents: [...MOCK.MOCK_DOCUMENTS, TEMPLATE_PLACEHOLDER_DOCUMENT] })
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => {
    localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
  })
}

test('document detail blocks publish and export while template variables are unresolved', async ({ page }) => {
  await prepareAuthenticatedPage(page)

  await page.goto('/projects/project-e2e-001/documents/doc-e2e-007', { waitUntil: 'domcontentloaded' })

  await expect(page.getByTestId('document-template-placeholder-panel')).toContainText('验收负责人')
  await expect(page.getByTestId('document-template-placeholder-panel')).toContainText('客户名称')
  await expect(page.getByTestId('document-template-placeholder-release-blocker')).toBeVisible()
  await expect(page.getByTestId('document-publish-action')).toBeDisabled()
  await expect(page.getByTestId('document-export-action')).toBeDisabled()
})

test('global document registry filters delivery risks and links back to project documents', async ({ page }) => {
  await prepareAuthenticatedPage(page)

  await page.goto('/documents', { waitUntil: 'domcontentloaded' })

  await expect(page.getByRole('heading', { name: '全局文档注册表' })).toBeVisible()
  await expect(page.getByText('交付风险摘要')).toBeVisible()
  await expect(page.getByText('类型分布')).toBeVisible()
  await expect(page.getByTestId('global-document-row')).toHaveCount(7)

  await page.getByTestId('global-document-risk-filter').selectOption('blocked')
  await expect(page.getByTestId('global-document-row')).toHaveCount(3)
  await expect(page.getByTestId('global-document-template-placeholders')).toContainText('验收负责人')
  await expect(page.getByTestId('global-document-template-placeholders')).toContainText('客户名称')
  await expect(page.locator('body')).toContainText('阻塞')

  await page.getByTestId('global-document-status-filter').selectOption('draft')
  await expect(page.getByTestId('global-document-row')).toHaveCount(1)
  await expect(page.locator('body')).toContainText('尚未完成评审闭环')

  await page.getByTestId('global-document-risk-filter').selectOption('all')
  await page.getByTestId('global-document-status-filter').selectOption('all')
  await page.getByTestId('global-document-type-filter').selectOption('prd')
  await expect(page.getByTestId('global-document-row')).toHaveCount(1)
  await expect(page.locator('body')).toContainText('产品需求文档')

  await page.getByTestId('global-document-type-filter').selectOption('all')
  await page.getByTestId('global-document-search').fill('占位')
  await expect(page.getByTestId('global-document-row')).toHaveCount(1)
  await expect(page.locator('body')).toContainText('占位内容')
  await expect(page.getByRole('link', { name: '查看' }).first()).toHaveAttribute(
    'href',
    /\/projects\/project-e2e-001\/documents\/doc-e2e-006$/
  )
})
