import { expect, Page, test } from '@playwright/test'

import { setupApiMocks } from './fixtures/api-mocks'

async function prepareAuthenticatedPage(page: Page) {
  await setupApiMocks(page)
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef'))
}

test('project owner creates, renews, and revokes invitations', async ({ page }) => {
  await prepareAuthenticatedPage(page)
  await page.goto('/projects/project-e2e-001/members', { waitUntil: 'domcontentloaded' })

  await expect(page.getByText('consultant@example.com')).toBeVisible()
  await expect(page.getByText('待接受')).toBeVisible()

  await page.getByLabel('邮箱').fill('new-consultant@example.com')
  await page.getByRole('button', { name: '创建邀请' }).click()
  await expect(page.getByText('已为 new-consultant@example.com 创建邀请')).toBeVisible()
  await expect(page.getByText(/邀请链接：/)).toContainText('/invitations/mock-invite-token-998877')

  await page.getByRole('button', { name: '续期' }).click()
  await expect(page.getByText(/mock-renewed-invite-token/)).toBeVisible()
  await page.getByRole('button', { name: '撤销' }).click()
  await expect(page.getByText('已撤销')).toBeVisible()
})

test('signed-in invitee accepts invitation and enters project', async ({ page }) => {
  await prepareAuthenticatedPage(page)
  await page.route(/\/api\/v1\/projects\/invitations\/[^/]+\/accept$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        project_id: 'project-e2e-001',
        project_name: 'WMS 智能升级项目',
        user_id: 'user-e2e-001',
        status: 'accepted',
      }),
    })
  })

  await page.goto('/invitations/mock-invite-token-998877', { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: '接受并加入项目' }).click()
  await expect(page.getByText('邀请已接受')).toBeVisible()
  await expect(page.getByRole('button', { name: '进入项目' })).toBeVisible()
})
