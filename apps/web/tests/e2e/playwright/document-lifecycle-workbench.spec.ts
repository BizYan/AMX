import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, Page, test } from '@playwright/test'
import { setupApiMocks } from './fixtures/api-mocks'
import * as MOCK from './fixtures/mock-data'

const repoRoot = join(__dirname, '..', '..', '..', '..', '..')

async function gotoAppPage(page: Page, path: string) {
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => {
    localStorage.setItem('auth_token', 'mock-jwt-token-1234567890abcdef')
  })
  await page.goto(path, { waitUntil: 'domcontentloaded' })
}

test.describe('P2 document lifecycle workbench', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page, {
      documents: MOCK.MOCK_DOCUMENTS.map((document) =>
        document.id === 'doc-e2e-001'
          ? {
              ...document,
              status: 'approved',
              metadata: { ...(document.metadata || {}), status: 'approved' },
              metadata_json: { ...(document.metadata_json || {}), status: 'approved' },
            }
          : document
      ),
    })
  })

  test('supports review gating, versions, baselines, snapshots, and comments', async ({ page }) => {
    await gotoAppPage(page, '/projects/project-e2e-001/documents/doc-e2e-001')

    await expect(page.getByTestId('document-lifecycle-heading')).toBeVisible({ timeout: 8000 })
    await expect(page.getByTestId('unresolved-comments-count')).toHaveText('1')
    await expect(page.getByTestId('document-publish-action')).toBeDisabled()

    await page.getByTestId('document-tab-comments').click()
    await page.getByTestId('resolve-comment-comment-e2e-001').click()
    await expect(page.getByTestId('unresolved-comments-count')).toHaveText('0')
    await expect(page.getByTestId('document-publish-action')).toBeEnabled()

    await page.getByTestId('document-tab-versions').click()
    await expect(page.getByTestId('version-item-version-e2e-001')).toContainText('Initial template import')
    await page.getByTestId('open-edit-document').click()
    await page.getByTestId('edit-document-summary').fill('Add review requirements')
    await page.getByTestId('edit-document-content').fill('# User Requirements\n\nUpdated review requirements.')
    await page.getByTestId('save-document-action').click()
    await expect(page.getByTestId('version-item-version-created')).toContainText('Add review requirements')

    await page.getByTestId('document-tab-baselines').click()
    await page.getByTestId('baseline-name-input').fill('Review approved baseline')
    await page.getByTestId('create-baseline-action').click()
    await expect(page.getByTestId('baseline-item-baseline-created')).toContainText('Review approved baseline')
    await page.getByTestId('rollback-baseline-baseline-e2e-001').click()
    await page.getByTestId('document-tab-content').click()
    await expect(page.getByTestId('document-content-preview')).toContainText('Baseline restored content')

    await page.getByTestId('document-tab-snapshots').click()
    await page.getByTestId('create-snapshot-action').click()
    await expect(page.getByTestId('snapshot-item-snapshot-created')).toContainText('人工快照')
    page.on('dialog', (dialog) => dialog.accept())
    await page.getByTestId('restore-snapshot-snapshot-e2e-001').click()
    await page.getByTestId('document-tab-content').click()
    await expect(page.getByTestId('document-content-preview')).toContainText('Snapshot restored content')
  })

  test('autosaves an unsaved editor draft and restores it with visible recovery status', async ({ page }) => {
    await gotoAppPage(page, '/projects/project-e2e-001/documents/doc-e2e-001')
    await page.clock.install()

    await page.getByTestId('open-edit-document').click()
    await page.getByLabel('标题').fill('自动保存恢复标题')
    await page.getByTestId('edit-document-content').fill('# User Requirements\n\nAutosaved recovery draft.')
    await page.clock.fastForward(5 * 60 * 1000)

    await expect(page.getByTestId('document-autosave-status')).toContainText('已自动保存')
    await page.getByRole('button', { name: '取消' }).click()
    await page.getByTestId('document-tab-snapshots').click()
    await expect(page.getByTestId('snapshot-item-snapshot-created')).toContainText('自动保存草稿')
    await expect(page.getByTestId('snapshot-item-snapshot-created')).toContainText('Autosaved recovery draft')

    page.on('dialog', (dialog) => dialog.accept())
    await page.getByTestId('restore-snapshot-snapshot-created').click()
    await page.getByTestId('document-tab-content').click()
    await expect(page.getByTestId('document-content-preview')).toContainText('Autosaved recovery draft')
  })

  test('keeps the editor open when autosave fails during close', async ({ page }) => {
    await page.route(/\/api\/v1\/collaboration\/documents\/[^/]+\/snapshots$/, async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Snapshot storage unavailable' }),
        })
        return
      }
      await route.fallback()
    })
    await gotoAppPage(page, '/projects/project-e2e-001/documents/doc-e2e-001')

    await page.getByTestId('open-edit-document').click()
    await page.getByTestId('edit-document-content').fill('# User Requirements\n\nDraft that must remain visible.')
    await page.getByRole('button', { name: '取消' }).click()

    await expect(page.getByTestId('document-autosave-status')).toContainText('自动保存失败')
    await expect(page.getByTestId('edit-document-content')).toHaveValue(/Draft that must remain visible/)
    await expect(page.getByRole('dialog')).toBeVisible()
  })

  test('supports anchored review comments, replies, locating, and unresolved filtering', async ({ page }) => {
    await gotoAppPage(page, '/projects/project-e2e-001/documents/doc-e2e-001')
    await page.getByTestId('document-tab-comments').click()

    await page.getByTestId('reply-comment-comment-e2e-001').click()
    await page.getByTestId('reply-input-comment-e2e-001').fill('已补充验收口径，请复核。')
    await page.getByTestId('submit-reply-comment-e2e-001').click()
    await expect(page.getByTestId('comment-reply-comment-reply-created')).toContainText('已补充验收口径')

    await page.getByTestId('comment-anchor-select').selectOption('# 用户需求规格说明书')
    await page.getByTestId('new-comment-input').fill('请确认本章节责任人。')
    await page.getByTestId('add-comment-action').click()
    await expect(page.getByTestId('comment-thread-comment-created')).toContainText('请确认本章节责任人')

    await page.getByTestId('locate-comment-comment-created').click()
    await expect(page.getByTestId('document-content-preview').locator('[data-comment-anchor="# 用户需求规格说明书"]')).toHaveClass(/border-indigo-500/)

    await page.getByTestId('document-tab-comments').click()
    await page.getByTestId('comment-status-filter').selectOption('resolved')
    await expect(page.getByText('当前筛选条件下暂无评论')).toBeVisible()
    await page.getByTestId('comment-status-filter').selectOption('unresolved')
    await expect(page.getByTestId('comment-thread-comment-e2e-001')).toBeVisible()
  })

  test('lists generation sessions and restores an active session', async ({ page }) => {
    await gotoAppPage(page, '/projects/project-e2e-001/documents/generate')

    await expect(page.getByTestId('generation-session-center')).toBeVisible({ timeout: 8000 })
    await expect(page.getByTestId('generation-session-center')).toContainText('WMS 升级 BRD 会话')
    await expect(page.getByTestId('generation-session-center')).toContainText('会员运营 PRD 会话')

    await page.getByTestId('restore-generation-session-gen-session-e2e-active').click()
    await expect(page.getByTestId('interactive-generation-session')).toContainText('WMS 升级 BRD 会话')
    await expect(page.getByTestId('interactive-generation-session')).toContainText('背景与目标')

    await page.getByTestId('open-generation-session-document-gen-session-e2e-finalized').click()
    await expect(page).toHaveURL(/\/projects\/project-e2e-001\/documents\/doc-e2e-001/)
  })

  test('restores a generation session from the sessionId query parameter', async ({ page }) => {
    await gotoAppPage(page, '/projects/project-e2e-001/documents/generate?sessionId=gen-session-e2e-active')

    await expect(page.getByTestId('interactive-generation-session')).toContainText('WMS 升级 BRD 会话', { timeout: 8000 })
    await expect(page.getByTestId('interactive-generation-session')).toContainText('背景与目标')
  })

  test('loads selected source file knowledge into editable generation context', async ({ page }) => {
    await gotoAppPage(page, '/projects/project-e2e-001/documents/generate?sourceFileId=file-e2e-ready')

    await expect(page.getByText('已从所选资料载入 1 条知识')).toBeVisible({ timeout: 8000 })
    await expect(page.getByLabel('需求与背景')).toContainText('以下内容来自已摄取的项目资料')
    await expect(page.getByLabel('需求与背景')).toContainText('仓储批次分配规则')
    await expect(page.getByLabel('需求与背景')).toContainText('仓储升级招标文件.pdf')
  })

  test('supports interactive BRD generation session before final document creation', async ({ page }) => {
    await gotoAppPage(page, '/projects/project-e2e-001/documents/generate')

    await page.getByRole('button', { name: /业务需求文档/ }).click()
    await page.getByLabel('需求与背景').fill('现有 WMS 波次分配依赖人工经验，错发率高，需要优化收货、上架、拣货、复核和发运。')
    await page.getByRole('button', { name: /开始交互式生成/ }).click()

    await expect(page.locator('body')).toContainText('交互式生成会话', { timeout: 8000 })
    await expect(page.locator('body')).toContainText('背景与目标', { timeout: 8000 })

    await page.getByPlaceholder(/补充本节业务事实/).fill('业务目标是降低错发率，并让仓管员、复核员和主管在同一流程中留痕。')
    await page.getByRole('button', { name: /写入本节/ }).click()
    await expect(page.locator('body')).toContainText('当前章节草稿', { timeout: 8000 })
    await expect(page.locator('body')).toContainText('降低错发率', { timeout: 8000 })

    await page.getByRole('button', { name: /确认本节/ }).click()
    await expect(page.locator('body')).toContainText('干系人与业务角色', { timeout: 8000 })

    await page.getByRole('button', { name: /生成交互式文档/ }).click()
    await expect(page.locator('body')).toContainText('文档生成成功', { timeout: 8000 })
  })

  test('does not create fallback documents when direct generation fails', async ({ page }) => {
    let documentCreateRequests = 0
    await page.route(/\/api\/v1\/documents(?:\?.*)?$/, async (route) => {
      if (route.request().method() === 'POST') {
        documentCreateRequests += 1
      }
      await route.fallback()
    })
    await page.route('**/api/v1/documents/generate', async (route) => {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'LLM provider unavailable' }),
      })
    })

    await gotoAppPage(page, '/projects/project-e2e-001/documents/generate?docType=brd')
    await page.getByLabel('需求与背景').fill('WMS 升级需要覆盖收货、上架、拣货、复核和发运，并给出验收标准。')
    await page.getByRole('button', { name: '直接生成文档' }).click()

    await expect(page.locator('body')).toContainText('生成文档失败', { timeout: 8000 })
    await expect(page.locator('body')).not.toContainText('文档已生成')
    expect(documentCreateRequests).toBe(0)
  })

  test('autosave status preserves backend snapshot timestamps', () => {
    const source = readFileSync(
      join(repoRoot, 'apps/web/src/app/(app)/projects/[projectId]/documents/[docId]/page.tsx'),
      'utf8'
    )

    expect(source).not.toContain('setLastAutoSavedAt(snapshot.createdAt || new Date().toISOString())')
    expect(source).toContain('setLastAutoSavedAt(snapshot.createdAt || null)')
    expect(source).toContain("'已自动保存 · 未提供时间'")
  })

  test('status history items use transition identity instead of list index', () => {
    const source = readFileSync(
      join(repoRoot, 'apps/web/src/app/(app)/projects/[projectId]/documents/[docId]/page.tsx'),
      'utf8'
    )

    expect(source).toContain('function statusTransitionKey')
    expect(source).toContain('item.transition_id')
    expect(source).toContain('data-testid={`status-history-item-${transitionKey}`}')
    expect(source).not.toContain('data-testid={`status-history-item-${index}`}')
    expect(source).not.toContain('key={`${item.changed_at}-${index}`}')
  })

  test('document content preview lines use stable keys', () => {
    const source = readFileSync(
      join(repoRoot, 'apps/web/src/app/(app)/projects/[projectId]/documents/[docId]/page.tsx'),
      'utf8'
    )

    expect(source).toContain('function getDocumentContentPreviewLines')
    expect(source).toContain('getDocumentContentPreviewLines(document.content).map(({ line, anchor, key })')
    expect(source).not.toContain('key={`${index}-${line}`}')
  })

  test('shows document generation command flow before starting a session', async ({ page }) => {
    await gotoAppPage(page, '/projects/project-e2e-001/documents/generate')

    await page.getByRole('button', { name: /业务需求文档/ }).click()
    await page.getByLabel('需求与背景').fill([
      'WMS 升级需要统一收货、上架、拣货、复核和发运流程。',
      '关键角色包括仓管员、复核员、主管和客户评审人。',
      '验收标准是错发率下降 30%，所有异常处理必须可追溯。',
    ].join('\n'))

    await expect(page.getByTestId('generation-command-flow')).toContainText('上下文准备度')
    await expect(page.getByTestId('generation-readiness-requirements')).toContainText('已覆盖')
    await expect(page.getByTestId('generation-readiness-stakeholders')).toContainText('已覆盖')
    await expect(page.getByTestId('generation-readiness-process')).toContainText('已覆盖')
    await expect(page.getByTestId('generation-readiness-acceptance')).toContainText('已覆盖')
    await expect(page.getByTestId('generation-template-plan')).toContainText('BRD 商业需求文档模板')
    await expect(page.getByTestId('generation-agent-skill-plan')).toContainText('需求澄清器')
    await expect(page.getByTestId('generation-section-roadmap')).toContainText('背景与目标')
    await expect(page.getByTestId('generation-section-roadmap')).toContainText('质量门禁')
  })
})
