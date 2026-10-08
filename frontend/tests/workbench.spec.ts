import { test, expect } from '@playwright/test'
import type { Page, Request } from '@playwright/test'
import { readFileSync } from 'node:fs'

// dev-local has no provider configuration and the Worker gets no credentials, so every
// generation here fails visibly; no model is ever called by these page tests.
async function login(page: Page, name = 'alice') {
  await page.goto('/')
  await page.getByLabel('账号', { exact: true }).fill(name)
  await page.getByLabel('密码', { exact: true }).fill(process.env.T06_PASSWORD!)
  await page.getByRole('button', { name: '登录开发环境' }).click()
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible()
  await expect(page.getByText('正在读取素材与任务…')).toHaveCount(0)
}
function generationPost(request: Request) {
  return (
    request.method() === 'POST' &&
    request.url().endsWith('/api/v4/generation-tasks')
  )
}
function card(page: Page, task: string) {
  return page.locator(`[data-testid="result-card"][data-task="${task}"]`)
}
const toast = (page: Page) => page.locator('.toasts [role="status"]')

test('ACC-T06 A1/A3/A6–A8: dev-local entries, history, uploads, visible failure and responsive pages', async ({
  page,
}, info) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await login(page)
  await expect(
    page.getByRole('heading', { name: '选择功能开始生成' }),
  ).toBeVisible()
  for (const name of ['赠品主图', '场景主图', '卖点主图'])
    await expect(
      page.getByRole('button', { name: `${name} 立即生成` }),
    ).toBeVisible()
  await expect(page.getByText('模拟模型验收模式')).toHaveCount(0)
  await page.reload()
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible()

  // Old fixture tasks stay labelled as test data and cannot be opened as results.
  await page.getByRole('link', { name: '任务记录' }).click()
  const rows = page.locator('.history-item')
  await expect(rows).toHaveCount(20)
  await expect(rows.filter({ hasText: '开发/测试任务' })).toHaveCount(20)
  await expect(rows.filter({ hasText: '（旧版任务）' })).toHaveCount(20)
  await expect(page.getByRole('button', { name: '查看' })).toHaveCount(0)
  await page.getByRole('button', { name: '加载更早任务' }).click()
  await expect(rows).toHaveCount(22)

  await page.getByRole('link', { name: '素材管理' }).click()
  await page.getByLabel('上传商品图').setInputFiles({
    name: 'invalid.png',
    mimeType: 'image/png',
    buffer: Buffer.from('not an image'),
  })
  await expect(page.getByRole('alert')).toContainText('无法读取这张图片')
  await page.getByLabel('上传商品图').setInputFiles({
    name: 'synthetic.jpg',
    mimeType: 'image/jpeg',
    buffer: Buffer.from(
      readFileSync('../contracts/fixtures/t04-synthetic-jpeg.base64', 'utf8'),
      'base64',
    ),
  })
  await expect(toast(page)).toContainText('原图已保存')
  await expect(page.getByTestId('asset-card')).not.toHaveCount(0)

  // Without a configured provider the task fails with a diagnosable code, never silently.
  await page.getByRole('link', { name: '场景主图' }).click()
  await page.getByLabel('补充描述（可选）').fill('仅用于页面测试的场景描述')
  const sent = page.waitForRequest(generationPost)
  const answered = page.waitForResponse(
    (r) => generationPost(r.request()) && r.status() === 202,
  )
  await page.getByTestId('generate').click()
  const body = (await sent).postDataJSON()
  const task = (await (await answered).json()).id as string
  expect(body.feature_type).toBe('SCENE')
  expect(body.output.count).toBe(1)
  expect(body.scene_prompt).toBe('仅用于页面测试的场景描述')
  expect(body).not.toHaveProperty('text')
  await expect(card(page, task)).toContainText('生成失败', { timeout: 30000 })
  await expect(card(page, task)).toContainText('PROVIDER_UNAVAILABLE')
  await card(page, task).getByRole('button', { name: '重试' }).click()
  await expect(page.getByRole('alert')).toContainText('不可重试')
  await page.screenshot({
    path: info.outputPath('desktop-scene.png'),
    fullPage: true,
  })

  await page.setViewportSize({ width: 390, height: 844 })
  for (const link of ['首页', '赠品主图', '卖点主图', '任务记录']) {
    await page.getByRole('link', { name: link }).click()
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true)
  }
  await page.screenshot({
    path: info.outputPath('mobile-tasks.png'),
    fullPage: true,
  })
  await page.setViewportSize({ width: 1440, height: 1000 })

  await page.getByRole('button', { name: '退出登录' }).click()
  await expect(page.getByRole('button', { name: '登录开发环境' })).toBeVisible()
  await login(page)
  await page.getByRole('link', { name: '任务记录' }).click()
  await expect(rows).toHaveCount(20)
  await page.getByRole('button', { name: '退出登录' }).click()
  // Bob has no project yet: one is created implicitly and starts empty.
  await login(page, 'bob')
  await page.getByRole('link', { name: '任务记录' }).click()
  await expect(rows).toHaveCount(0)
  expect(errors).toEqual([])
})

test('ACC-T06 A2/A4: lost response reuses the key; network error and expired session are visible', async ({
  page,
}) => {
  await login(page)
  await page.getByRole('link', { name: '场景主图' }).click()
  let firstKey = '',
    firstBody = ''
  await page.route(
    '**/api/v4/generation-tasks',
    async (route) => {
      firstKey = route.request().headers()['idempotency-key']!
      firstBody = route.request().postData()!
      await route.fetch() // Java commits the task, but its response is deliberately lost.
      await route.abort('failed')
    },
    { times: 1 },
  )
  await page.getByTestId('generate').click()
  const resend = page.getByRole('button', { name: '用原请求重发' })
  await expect(resend).toBeVisible()
  const again = page.waitForRequest(generationPost)
  await resend.click()
  const request = await again
  expect(request.headers()['idempotency-key']).toBe(firstKey)
  expect(request.postData()).toBe(firstBody)
  await expect(resend).toHaveCount(0)

  await page.getByRole('link', { name: '任务记录' }).click()
  await page.route(
    '**/api/v1/projects/p/tasks?offset=0',
    (route) => route.abort('failed'),
    { times: 1 },
  )
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('连接中断或超时')
  await page.route(
    '**/api/v1/projects/p/tasks?offset=0',
    (route) =>
      route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: '{"code":"UNAUTHORIZED"}',
      }),
    { times: 1 },
  )
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await expect(page.getByRole('button', { name: '登录开发环境' })).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('会话已过期')
  expect(
    await page.evaluate(() => [localStorage.length, sessionStorage.length]),
  ).toEqual([0, 0])
})

test('ACC-T06 A2/A5: task polling shows RUNNING, survives a network error and recovers', async ({
  page,
}) => {
  await login(page)
  await page.getByRole('link', { name: '任务记录' }).click()
  // Only this test rewrites GET responses to reach short-lived UI states;
  // it never writes a successful task or changes persisted server state.
  let calls = 0
  await page.route('**/api/v4/generation-tasks/*', async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    calls++
    if (calls === 1) {
      const response = await route.fetch()
      const detail = await response.json()
      await route.fulfill({
        response,
        json: {
          ...detail,
          status: 'RUNNING',
          artifacts: [],
          bases: [],
          error: null,
        },
      })
    } else if (calls === 2) await route.abort('failed')
    else await route.continue()
  })
  await page
    .locator('.history-item')
    .filter({ hasText: '场景主图' })
    .filter({ hasNotText: '旧版任务' })
    .first()
    .getByRole('button', { name: '查看' })
    .click()
  const current = page.getByTestId('result-card').first()
  await expect(current).toContainText('生成中')
  await expect(page.getByRole('alert')).toContainText('连接中断或超时', {
    timeout: 10000,
  })
  await expect.poll(() => calls, { timeout: 15000 }).toBeGreaterThanOrEqual(3)
  await expect(current).toContainText('生成失败', { timeout: 10000 })
  await page.unroute('**/api/v4/generation-tasks/*')

  await page.getByLabel('补充描述（可选）').fill('private unsaved draft')
  await page.route(
    '**/api/v1/projects/p/tasks?offset=0',
    (route) =>
      route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: '{"code":"UNAUTHORIZED"}',
      }),
    { times: 1 },
  )
  await page.getByRole('button', { name: '刷新结果' }).click()
  await expect(page.getByRole('button', { name: '登录开发环境' })).toBeVisible()
  await page.getByLabel('账号', { exact: true }).fill('alice')
  await page.getByLabel('密码', { exact: true }).fill(process.env.T06_PASSWORD!)
  await page.getByLabel('密码', { exact: true }).press('Enter')
  await expect(page.getByLabel('补充描述（可选）')).toHaveValue('')
})
