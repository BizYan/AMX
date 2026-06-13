import { expect, Page, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'

async function gotoAppPage(page: Page, path: string) {
  await page.goto(path, { waitUntil: 'domcontentloaded' })
}

const binding = {
  id: 'binding-e2e-001',
  tenant_id: 'tenant-e2e-001',
  integration_provider_id: 'integration-e2e-001',
  project_id: 'project-e2e-001',
  name: 'Jira 需求池',
  scope_json: { item_path: 'issues', cursor_param: 'updated_after' },
  field_mapping_json: { external_id: 'key', title: 'fields.summary', content: 'fields.description' },
  cursor_json: { updated_after: '2026-06-10T10:00:00Z' },
  is_enabled: true,
  last_sync_status: 'completed',
  last_synced_at: '2026-06-10T10:00:00Z',
  last_error: null,
  created_by: 'user-e2e-001',
  created_at: '2026-06-10T09:00:00Z',
  updated_at: '2026-06-10T10:00:00Z',
}

test.describe('integration project knowledge sync', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
    await page.route(/\/api\/v1\/integrations(?:\?.*)?$/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [{
            id: binding.integration_provider_id,
            tenant_id: binding.tenant_id,
            provider_type: 'jira',
            name: 'Delivery Jira',
            config_json: { base_url: 'https://jira.example.com', api_key: 'masked' },
            is_enabled: true,
            last_sync_at: binding.last_synced_at,
            created_at: binding.created_at,
            updated_at: binding.updated_at,
          }],
          total: 1,
          page: 1,
          page_size: 100,
          has_more: false,
        }),
      })
    })
    await page.route('**/api/v1/integrations/*/project-bindings', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([binding]) })
    })
    await page.route('**/api/v1/integrations/project-bindings/*/runs*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([{
          id: 'sync-run-e2e-001',
          tenant_id: binding.tenant_id,
          binding_id: binding.id,
          status: 'completed',
          mode: 'sync',
          cursor_before_json: {},
          cursor_after_json: binding.cursor_json,
          total_count: 3,
          created_count: 2,
          updated_count: 1,
          unchanged_count: 0,
          failed_count: 0,
          error_message: null,
          details_json: {},
          requested_by: binding.created_by,
          started_at: binding.last_synced_at,
          completed_at: binding.last_synced_at,
          created_at: binding.last_synced_at,
        }]),
      })
    })
    await page.route('**/api/v1/integrations/project-bindings/*/preview*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          binding_id: binding.id,
          total: 1,
          cursor: { updated_after: '2026-06-11T08:00:00Z' },
          items: [{
            external_id: 'AMX-101',
            title: '导入外部需求',
            content: '将 Jira 需求写入项目知识并保留来源追溯。',
            external_url: 'https://jira.example.com/browse/AMX-101',
            external_updated_at: '2026-06-11T08:00:00Z',
            metadata: {},
          }],
        }),
      })
    })
    await page.route('**/api/v1/integrations/project-bindings/*/sync', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'sync-run-e2e-002',
          tenant_id: binding.tenant_id,
          binding_id: binding.id,
          status: 'completed',
          mode: 'sync',
          cursor_before_json: binding.cursor_json,
          cursor_after_json: { updated_after: '2026-06-11T08:00:00Z' },
          total_count: 1,
          created_count: 1,
          updated_count: 0,
          unchanged_count: 0,
          failed_count: 0,
          error_message: null,
          details_json: {},
          requested_by: binding.created_by,
          started_at: '2026-06-11T08:00:00Z',
          completed_at: '2026-06-11T08:00:01Z',
          created_at: '2026-06-11T08:00:00Z',
        }),
      })
    })
    await gotoAppPage(page, '/login')
    await page.evaluate(() => localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef'))
  })

  test('previews and synchronizes external content into project knowledge', async ({ page }) => {
    await gotoAppPage(page, '/settings')
    await page.getByRole('tab', { name: '外部集成' }).click()
    await page.getByRole('tab', { name: '项目同步' }).click()

    const panel = page.getByTestId('integration-project-sync')
    await expect(panel).toContainText('Jira 需求池')
    await expect(panel).toContainText('同步运行历史')
    await panel.getByRole('button', { name: '预览' }).click()
    await expect(page.getByTestId('integration-sync-preview')).toContainText('导入外部需求')
    await panel.getByRole('button', { name: '同步', exact: true }).click()
    await expect(page.getByText('项目知识同步完成')).toBeVisible()
  })
})
