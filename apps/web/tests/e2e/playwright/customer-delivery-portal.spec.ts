import { expect, test } from '@playwright/test'

test('customer reviews delivery evidence and submits acceptance', async ({ page }) => {
  let submitted = false
  await page.route(/\/api\/v1\/projects\/customer-portal\/portal-token\/acceptance$/, async (route) => {
    const payload = route.request().postDataJSON()
    submitted = true
    await route.fulfill({
      json: {
        project_name: '客户门户交付项目',
        customer_name: '示例客户',
        package_ready: true,
        decision: payload.decision,
        accepted_at: new Date().toISOString(),
        submitted_at: new Date().toISOString(),
        criteria: payload.items,
        artifacts: [
          {
            id: 'artifact-001',
            filename: 'customer-delivery.zip',
            content_type: 'application/zip',
            file_size: 2048,
            file_hash: 'delivery-hash',
            created_at: new Date().toISOString(),
          },
        ],
        receipt: {
          id: 'receipt-001',
          contact_name: payload.contact_name,
          contact_email: payload.contact_email,
          decision: payload.decision,
          submitted_at: new Date().toISOString(),
          item_count: payload.items.length,
          accepted_item_count: payload.items.filter((item: { status: string }) => item.status === 'accepted').length,
        },
        follow_ups: [
          {
            key: 'scope',
            title: '客户验收整改：范围已经交付',
            status: 'done',
            priority: 'high',
            updated_at: new Date().toISOString(),
          },
        ],
        gate: { status: 'passed', label: '可正式关闭', blockers: [], warnings: [] },
      },
    })
  })
  await page.route(/\/api\/v1\/projects\/customer-portal\/portal-token$/, async (route) => {
    await route.fulfill({
      json: {
        project_name: '客户门户交付项目',
        customer_name: '示例客户',
        package_ready: true,
        decision: submitted ? 'accepted' : 'pending',
        submitted_at: submitted ? new Date().toISOString() : null,
        criteria: [
          { key: 'scope', title: '范围已经交付', status: 'pending', evidence: '交付评审纪要' },
        ],
        artifacts: [
          {
            id: 'artifact-001',
            filename: 'customer-delivery.zip',
            content_type: 'application/zip',
            file_size: 2048,
            file_hash: 'delivery-hash',
            created_at: new Date().toISOString(),
          },
        ],
        receipt: submitted ? {
          id: 'receipt-001',
          contact_name: '客户签署人',
          contact_email: 'sponsor@example.com',
          decision: 'accepted',
          submitted_at: new Date().toISOString(),
          item_count: 1,
          accepted_item_count: 1,
        } : null,
        follow_ups: submitted ? [
          {
            key: 'scope',
            title: '客户验收整改：范围已经交付',
            status: 'done',
            priority: 'high',
            updated_at: new Date().toISOString(),
          },
        ] : [],
        gate: { status: 'blocked', label: '等待客户验收', blockers: ['等待客户结论'], warnings: [] },
      },
    })
  })

  await page.goto('/delivery-portal/portal-token', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '客户门户交付项目' })).toBeVisible()
  await expect(page.getByText('范围已经交付')).toBeVisible()
  await expect(page.getByTestId('portal-artifacts')).toContainText('customer-delivery.zip')
  await page.getByTestId('portal-contact-name').fill('客户签署人')
  await page.getByTestId('portal-contact-email').fill('sponsor@example.com')
  await page.getByTestId('portal-decision').selectOption('accepted')
  await page.getByTestId('submit-customer-acceptance').click()

  await expect(page.getByText(/已于 .* 提交/)).toBeVisible()
  await expect(page.getByTestId('acceptance-receipt')).toContainText('receipt-001')
  await expect(page.getByTestId('portal-follow-ups')).toContainText('已整改')
})
