import { expect, Page, test } from '@playwright/test'

import { setupApiMocks } from './fixtures/api-mocks'

async function gotoAppPage(page: Page, path: string) {
  await setupApiMocks(page)
  await page.addInitScript(() => {
    Date.now = () => 1712345678901
  })
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => {
    localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
  })
  await page.goto(path, { waitUntil: 'domcontentloaded' })
}

test('workflow editor persists UUID node IDs instead of timestamp IDs', async ({ page }) => {
  const createdVersions: any[] = []
  page.on('request', (request) => {
    if (request.method() !== 'POST' || !/\/api\/v1\/agent\/workflows\/[^/]+\/versions/.test(request.url())) return
    createdVersions.push(JSON.parse(request.postData() || '{}'))
  })

  await gotoAppPage(page, '/workflows/new/editor')

  await page.locator('main button').nth(6).click()
  await page.locator('main button').nth(4).click()

  await expect.poll(() => createdVersions.length).toBeGreaterThan(0)
  const nodeId = createdVersions[0]?.dag_json?.nodes?.[0]?.id
  expect(nodeId).toBeTruthy()
  expect(nodeId).not.toContain('1712345678901')
  expect(nodeId).toMatch(/^requirement_clarifier-[0-9a-f-]{36}$/)
})
