import { expect, Page, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'

async function gotoAppPage(page: Page, path: string) {
  await page.goto(path, { waitUntil: 'domcontentloaded' })
}

test.describe('settings API Key production management', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
    await gotoAppPage(page, '/login')
    await page.evaluate(() => {
      localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
    })
  })

  test('uses backend-managed API Key copy, create flow, and revoke flow', async ({ page }) => {
    await gotoAppPage(page, '/settings')
    await page.getByRole('tab', { name: /API Key|密钥/ }).click()

    const panel = page.getByTestId('settings-api-key-panel')
    await expect(panel).toContainText('管理租户级服务端 API Key')
    await expect(panel).toContainText('后端生成、hash 存储并写入审计记录')
    await expect(panel).toContainText('GitNexus Provider 生产接入')
    await expect(panel.getByTestId('api-key-production-summary')).toContainText('启用密钥')
    await expect(panel.getByTestId('api-key-production-summary')).toContainText('高权限密钥')
    await expect(panel).not.toContainText('本地演示')
    await expect(panel).not.toContainText('不会写入仓库或后端')
    await expect(panel).not.toContainText('用于联调的临时 Key')

    await page.getByRole('button', { name: /生成 Key/ }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('租户级服务端密钥')
    await expect(dialog).toContainText('后端仅保存 hash、权限范围和审计记录')
    await dialog.getByLabel('名称').fill('自动化回归接入')

    const createRequestPromise = page.waitForRequest((request) =>
      request.method() === 'POST' && request.url().includes('/api/v1/identity/api-keys')
    )
    await dialog.getByRole('button', { name: /^生成$/ }).click()
    const createRequest = await createRequestPromise
    expect(createRequest.postDataJSON()).toMatchObject({
      name: '自动化回归接入',
      permissions: ['read'],
    })

    await expect(panel).toContainText('完整密钥只显示一次')
    await expect(panel).toContainText('amx_live_new_')
    await expect(panel).toContainText('自动化回归接入')

    const createdKeyRow = panel.getByTestId('api-key-row').filter({ hasText: '自动化回归接入' }).first()
    const revokeRequestPromise = page.waitForRequest((request) =>
      request.method() === 'DELETE' && request.url().includes('/api/v1/identity/api-keys/')
    )
    await createdKeyRow.getByRole('button', { name: /撤销/ }).click()
    const revokeRequest = await revokeRequestPromise
    expect(revokeRequest.url()).toContain('/api/v1/identity/api-keys/')
    await expect(createdKeyRow).toContainText('已撤销')
  })
})
