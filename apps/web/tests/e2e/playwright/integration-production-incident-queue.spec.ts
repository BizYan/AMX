import { expect, test } from '@playwright/test'

import { setupApiMocks } from './fixtures/api-mocks'

test('operates the cross-channel integration incident queue', async ({ page }) => {
  await setupApiMocks(page)
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef'))
  await page.goto('/integrations', { waitUntil: 'domcontentloaded' })

  const queue = page.getByTestId('integration-incident-queue')
  await expect(queue).toContainText('Webhook 投递失败')
  await expect(queue).toContainText('Outbox 事件失败')
  await expect(queue).toContainText('严重阻塞')

  await page.getByTestId('retry-incident-webhook-delivery-failed-e2e').click()
  await expect(queue).not.toContainText('目标服务返回 HTTP 503')
  await expect(page.getByTestId('integration-action-result')).toContainText('失败任务已重试')
})
