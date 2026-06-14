import { expect, test } from '@playwright/test'

import { setupApiMocks } from './fixtures/api-mocks'

test('external invitee previews invitation and activates an account', async ({ page }) => {
  await setupApiMocks(page)
  await page.route(/\/api\/v1\/projects\/invitations\/[^/]+\/preview$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'active',
        project_name: '供应链升级项目',
        masked_email: 'n************t@example.com',
        expires_at: new Date(Date.now() + 86400000).toISOString(),
      }),
    })
  })
  await page.route(/\/api\/v1\/projects\/invitations\/[^/]+\/activate$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        project_id: 'project-e2e-001',
        project_name: '供应链升级项目',
        user_id: 'new-user-e2e-001',
        status: 'accepted',
        access_token: 'activated-jwt-token',
        token_type: 'bearer',
      }),
    })
  })

  await page.goto('/invitations/external-invite-token', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '供应链升级项目' })).toBeVisible()
  await expect(page.getByText('n************t@example.com')).toBeVisible()
  await page.getByLabel('姓名').fill('新顾问')
  await page.getByLabel('设置密码').fill('SecurePass123!')
  await page.getByRole('button', { name: '激活账号并加入项目' }).click()

  await expect(page.getByRole('heading', { name: '已加入项目' })).toBeVisible()
  await expect(page.getByRole('button', { name: '进入项目' })).toBeVisible()
  await expect.poll(() => page.evaluate(() => localStorage.getItem('auth_token'))).toBe('activated-jwt-token')
})

test('invalid invitation does not disclose project or email', async ({ page }) => {
  await setupApiMocks(page)
  await page.route(/\/api\/v1\/projects\/invitations\/[^/]+\/preview$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'invalid' }),
    })
  })

  await page.goto('/invitations/invalid-token', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '邀请链接无效' })).toBeVisible()
  await expect(page.getByText('请联系项目负责人重新发送邀请。')).toBeVisible()
  await expect(page.getByLabel('姓名')).toHaveCount(0)
})

test('existing account is sent to login with the invitation return path', async ({ page }) => {
  await setupApiMocks(page)
  await page.route(/\/api\/v1\/projects\/invitations\/[^/]+\/preview$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'active',
        project_name: '供应链升级项目',
        masked_email: 'm*****r@example.com',
        expires_at: new Date(Date.now() + 86400000).toISOString(),
      }),
    })
  })

  await page.goto('/invitations/existing-user-token', { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: '已有账号，前往登录' }).click()
  await expect(page).toHaveURL(/\/login\?next=\/invitations\/existing-user-token$/)
})
