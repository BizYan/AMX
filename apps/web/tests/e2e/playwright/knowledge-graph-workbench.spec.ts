import { expect, Page, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'

async function gotoAppPage(page: Page, path: string) {
  try {
    await page.goto(path, { waitUntil: 'domcontentloaded' })
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    if (!message.includes('net::ERR_ABORTED')) throw error
    await page.goto(path, { waitUntil: 'domcontentloaded' })
  }
}

test.describe('knowledge graph workbench', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page)
    await gotoAppPage(page, '/login')
    await page.evaluate(() => {
      localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
    })
  })

  test('connects project knowledge, graph canvas, gaps, search, context and writeback actions', async ({ page }) => {
    await gotoAppPage(page, '/projects/project-e2e-001/knowledge')

    await expect(page.getByRole('heading', { name: '项目知识工作台' })).toBeVisible()
    await expect(page.getByText('仓储批次分配规则')).toBeVisible()
    await expect(page.getByText('来源：仓储升级招标文件.pdf')).toBeVisible()
    await expect(page.getByText('缺少验收签收日期，需要补充客户确认材料。').first()).toBeVisible()

    await page.getByPlaceholder('搜索知识、来源、证据或结论').fill('签收')
    await expect(page.getByRole('heading', { name: '验收证据缺口' })).toBeVisible()
    await expect(page.getByText('仓储批次分配规则')).not.toBeVisible()

    await page.getByRole('button', { name: '选择' }).first().click()
    await page.getByRole('button', { name: '加入生成上下文' }).click()
    await expect(page.getByText('已加入生成上下文')).toBeVisible()

    await page.getByRole('link', { name: '打开图谱' }).click()
    await expect(page).toHaveURL(/\/knowledge\/graph\?projectId=project-e2e-001/)
    await expect(page.getByRole('heading', { name: '知识图谱', exact: true })).toBeVisible()
    await expect(page.getByText('图谱画布')).toBeVisible()
    await expect(page.getByTestId('knowledge-production-loop')).toBeVisible()
    await expect(page.getByTestId('knowledge-production-evidence-source_file_count')).toContainText('3')
    await expect(page.getByTestId('knowledge-production-evidence-knowledge_entry_count')).toContainText('18')
    await expect(page.getByTestId('knowledge-production-evidence-knowledge_link_count')).toContainText('2')
    await expect(page.getByTestId('knowledge-production-source-link')).toHaveAttribute('href', '/projects/project-e2e-001/files')
    await expect(page.getByTestId('knowledge-activation-action-seed_core_project_knowledge_evidence')).toBeEnabled()
    await page.getByTestId('knowledge-activation-action-seed_core_project_knowledge_evidence').click()
    await expect(page.getByText('知识图谱证据已初始化')).toBeVisible()
    await expect(page.getByTestId('knowledge-production-commissioning-run')).toBeEnabled()
    await page.getByTestId('knowledge-production-commissioning-run').click()
    await expect(page.getByText('知识图谱校准已完成')).toBeVisible()
    await expect(page.getByText('节点详情')).toBeVisible()
    await expect(page.getByText('来源证据')).toBeVisible()
    await expect(page.getByText('source_file_ingest')).toBeVisible()
    await expect(page.getByText('血缘记录')).toBeVisible()
    await expect(page.getByText('derived_from')).toBeVisible()
    await expect(page.getByRole('button', { name: /删除关系/ }).first()).toBeVisible()

    await page.getByPlaceholder('搜索知识、来源、证据或结论').fill('上线')
    await page.getByRole('button', { name: '全文检索' }).click()
    await expect(page.getByText('检索完成')).toBeVisible()

    await page.getByRole('button', { name: /删除关系/ }).first().click()
    await expect(page.getByText('关系已删除')).toBeVisible()
    await expect(page.getByRole('button', { name: '导出图谱' })).toBeEnabled()

    await page.getByPlaceholder('条目标题').fill('客户补充验收负责人')
    await page.getByPlaceholder('输入已确认的知识、证据、约束或待补充说明').fill('客户确认验收负责人为项目群 PMO，签收日期待最终排期确认。')
    await page.getByRole('button', { name: '保存到图谱' }).click()
    await expect(page.getByText('知识条目已创建')).toBeVisible()
  })

  test('shows explicit fulltext search failure without presenting it as local fallback', async ({ page }) => {
    await page.route('**/api/v1/knowledge/search*', async (route) => {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Knowledge fulltext index unavailable' }),
      })
    })

    await gotoAppPage(page, '/knowledge/graph?projectId=project-e2e-001')
    await page.getByPlaceholder('搜索知识、来源、证据或结论').fill('上线')
    await page.getByRole('button', { name: '全文检索' }).click()

    await expect(page.getByTestId('knowledge-search-error')).toContainText('全文检索不可用')
    await expect(page.locator('body')).not.toContainText('检索完成')
    await expect(page.locator('body')).not.toContainText('已保留本地筛选')
  })
})
