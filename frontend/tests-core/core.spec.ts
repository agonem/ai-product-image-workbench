import { expect, test, type Page, type Request } from '@playwright/test'
import { join } from 'node:path'

const artifacts = process.env.T06_ARTIFACTS!
const withText = !!process.env.CORE_FONT

async function login(page: Page, name = 'alice') {
  await page.goto('/')
  await page.getByLabel('账号', { exact: true }).fill(name)
  await page.getByLabel('密码', { exact: true }).fill(process.env.T06_PASSWORD!)
  await page.getByRole('button', { name: '登录生产账号' }).click()
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible()
  await expect(page.getByText('正在读取素材与任务…')).toHaveCount(0)
}
function generationPost(request: Request) {
  return (
    request.method() === 'POST' &&
    request.url().endsWith('/api/v4/generation-tasks')
  )
}
async function noHorizontalScroll(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true)
}
/** Click generate and return the new task id plus the request body that was sent. */
async function submitAndTrack(
  page: Page,
  click: () => Promise<void>,
  match = generationPost,
) {
  const sent = page.waitForRequest(match)
  const answered = page.waitForResponse(
    (r) => match(r.request()) && r.status() === 202,
  )
  await click()
  const body = (await sent).postDataJSON()
  const task = await (await answered).json()
  return { body, id: task.id as string }
}
const toast = (page: Page) => page.locator('.toasts [role="status"]')
const alert = (page: Page) => page.locator('.toasts [role="alert"]')
function done(page: Page, task: string) {
  return page.locator(
    `[data-testid="result-card"][data-task="${task}"][data-status="SUCCEEDED"]`,
  )
}
/** Open a collapsed parameter group (its header also shows the current summary). */
async function section(page: Page, title: string) {
  const head = page
    .locator('button.acc-head')
    .filter({ hasText: new RegExp(`^${title}`) })
  if ((await head.getAttribute('aria-expanded')) !== 'true') await head.click()
}
/** Answer the in-page confirmation dialog with its action button. */
async function confirm(page: Page, title: string | RegExp) {
  const dialog = page.getByRole('dialog', { name: title })
  await dialog.getByTestId('confirm-action').click()
  await expect(dialog).toHaveCount(0)
}
function watchErrors(page: Page) {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  return errors
}

test('V4-B1: home shows three independent entries and navigation', async ({
  page,
}) => {
  const errors = watchErrors(page)
  await login(page)
  await expect(
    page.getByRole('heading', { name: '选择功能开始生成' }),
  ).toBeVisible()
  for (const name of ['赠品主图', '场景主图', '卖点主图'])
    await expect(
      page.getByRole('button', { name: `${name} 立即生成` }),
    ).toBeVisible()
  await expect(page.getByText('模拟模型验收模式')).toBeVisible()
  // Removed on request: review reminders and the session clock are not shown in the chrome.
  await expect(page.getByText('待人工审核')).toHaveCount(0)
  await expect(page.getByText('有效至')).toHaveCount(0)
  expect(
    await page.evaluate(() => localStorage.length + sessionStorage.length),
  ).toBe(0)
  // The session is an HttpOnly cookie: scripts cannot read it, and a reload keeps it.
  expect(await page.evaluate(() => document.cookie)).toBe('')
  const cookie = (await page.context().cookies()).find(
    (c) => c.name === 'wb_session',
  )!
  expect(cookie.httpOnly && cookie.sameSite === 'Strict').toBe(true)
  await page.reload()
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible()
  await expect(page.getByText('alice', { exact: true })).toBeVisible()
  await page.screenshot({ path: join(artifacts, 'home-desktop.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await noHorizontalScroll(page)
  await page.screenshot({
    path: join(artifacts, 'home-mobile.png'),
    fullPage: true,
  })
  expect(errors).toEqual([])
})

test('V4-B2: scene - upload, preset, model and size, compare, download', async ({
  page,
}) => {
  const errors = watchErrors(page)
  await login(page)
  await page.getByRole('button', { name: '场景主图 立即生成' }).click()
  // Before generating the canvas shows the composition guide only.
  await expect(page.getByTestId('design-stage')).toContainText('商品')
  await page.screenshot({ path: join(artifacts, 'scene-empty.png') })
  await page
    .getByLabel('上传商品图')
    .setInputFiles(process.env.CORE_PRODUCT_FILE!)
  await expect(toast(page)).toContainText('商品原图已保存')
  await expect(
    page.getByRole('button', { name: /^商品图（已选择/ }).locator('img'),
  ).toBeVisible()
  await page.getByRole('button', { name: '木质桌面' }).click()
  await section(page, '输出设置')
  // The admin's default model is preselected; only its name and provider are shown.
  await expect(
    page.getByRole('button', { name: /^模型：模拟主力/ }),
  ).toContainText('OpenRouter')
  await page.getByRole('button', { name: /^尺寸：/ }).click()
  await page.getByRole('option', { name: /750 × 1000/ }).click()
  await expect(page.getByRole('button', { name: /^输出设置/ })).toContainText(
    '模拟主力 · 750 × 1000 · 1 张',
  )
  const { body, id } = await submitAndTrack(page, () =>
    page.getByTestId('generate').click(),
  )
  expect(body.feature_type).toBe('SCENE')
  expect(body.scene_preset).toBe('wood_table')
  expect(body.output).toEqual({
    aspect_ratio: '3:4',
    width: 750,
    height: 1000,
    format: 'png',
    count: 1,
  })
  expect(typeof body.model_id).toBe('string')
  expect(body).not.toHaveProperty('text')
  expect(body).not.toHaveProperty('style_prompt')
  const tile = done(page, id).first()
  await expect(tile).toBeVisible({ timeout: 60000 })
  const stage = page.getByTestId('design-stage')
  await expect(stage.locator('img.base')).toBeVisible()
  await tile.hover()
  await tile.getByRole('button', { name: '对照原图' }).click()
  await expect(
    page.getByTestId('compare-original').getByAltText('商品原图'),
  ).toBeVisible()
  await page.screenshot({ path: join(artifacts, 'scene-compare.png') })
  await tile.hover()
  const download = page.waitForEvent('download')
  await tile.getByRole('button', { name: '下载' }).click()
  expect((await download).suggestedFilename()).toMatch(/^scene-.+\.png$/)
  expect(errors).toEqual([])
})

test('V4-B3: gift - position and background only, no text', async ({
  page,
}) => {
  const errors = watchErrors(page)
  await login(page)
  await page.getByRole('link', { name: '赠品主图' }).click()
  // The product comes from the library picker, the gift from a new upload.
  await page.getByRole('button', { name: /^商品图/ }).click()
  await page.getByRole('menuitem', { name: '从素材库选择' }).click()
  const picker = page.getByRole('dialog', { name: '选择商品图' })
  await picker
    .getByRole('button', { name: /^选择商品图/ })
    .first()
    .click()
  await expect(picker).toHaveCount(0)
  await page.getByLabel('上传赠品图').setInputFiles(process.env.CORE_GIFT_FILE!)
  await expect(toast(page)).toContainText('赠品原图已保存')
  await section(page, '赠品位置')
  await page.getByRole('button', { name: '左下' }).click()
  await section(page, '背景')
  await page.getByRole('button', { name: '背景 奶油' }).click()
  // No text settings and no text box on the gift page (ADR-20261008-G).
  await expect(
    page.locator('button.acc-head').filter({ hasText: /文字/ }),
  ).toHaveCount(0)
  await expect(page.getByTestId('text-layer')).toHaveCount(0)
  await page.screenshot({ path: join(artifacts, 'gift-plan.png') })
  const { body, id } = await submitAndTrack(page, () =>
    page.getByTestId('generate').click(),
  )
  expect(body.feature_type).toBe('GIFT')
  expect(body.gift_position).toBe('BOTTOM_LEFT')
  expect(body.background).toEqual({ mode: 'SOLID', color: '#FFF6EC' })
  expect(body.output.count).toBe(1)
  expect(body.text).toBeUndefined()
  await expect(done(page, id)).toHaveCount(1, { timeout: 60000 })
  await expect(page.getByRole('button', { name: '应用文字修改' })).toHaveCount(
    0,
  )
  await page.screenshot({ path: join(artifacts, 'gift-result.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await noHorizontalScroll(page)
  await page.screenshot({
    path: join(artifacts, 'gift-mobile.png'),
    fullPage: true,
  })
  expect(errors).toEqual([])
})

test('V4-B4: selling points - one image per point in one style, verbatim text', async ({
  page,
}) => {
  test.skip(!withText, 'needs a deployment font for text overlay')
  const errors = watchErrors(page)
  await login(page)
  await page.getByRole('link', { name: '卖点主图' }).click()
  await page.getByLabel('标题').fill('宝宝奶瓶')
  await page.getByLabel('卖点（每行一条').fill(' 安全材质 \n防胀气设计\n易清洗')
  await section(page, '风格')
  await page.getByRole('button', { name: '自然绿' }).click()
  await expect(page.getByRole('button', { name: '暖木奶油' })).toHaveAttribute(
    'aria-pressed',
    'false',
  )
  await expect(page.getByTestId('generate')).toHaveText('生成 3 张')
  // The plan preview shows the title and the point needing the most room (spaces count).
  const layer = page.getByTestId('text-layer')
  await expect(layer).toContainText('安全材质')
  await expect(layer).not.toContainText('易清洗')
  await expect(layer).not.toContainText('防胀气设计')
  const { body, id } = await submitAndTrack(page, () =>
    page.getByTestId('generate').click(),
  )
  expect(body.style).toBe('green')
  expect(body.styles).toBeUndefined()
  expect(body.output.count).toBe(3)
  expect(body.text.title).toBe('宝宝奶瓶')
  expect(body.text.points).toEqual([' 安全材质 ', '防胀气设计', '易清洗'])
  // No colour choice for a style: the title takes the style's colour.
  expect(body.text.color).toBe('#2F5D3A')
  await expect(done(page, id)).toHaveCount(3, { timeout: 60000 })
  // Each result previews its own point for further text edits.
  await page.getByRole('button', { name: '查看结果 3' }).first().click()
  await expect(layer).toContainText('易清洗')
  await expect(layer).not.toContainText('防胀气设计')
  await page.screenshot({ path: join(artifacts, 'selling-desktop.png') })
  expect(errors).toEqual([])
})

test('V4-B5: a lost response is resent with the same key and body', async ({
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
      await route.fetch() // Java commits the task, but the response is lost.
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
})

test('V4-B8: a new result finishes on screen while another result is being viewed', async ({
  page,
}) => {
  await login(page)
  await page.getByRole('link', { name: '场景主图' }).click()
  const tiles = page.getByTestId('result-card')
  await expect(tiles.first()).toBeVisible()
  const older = new Set(
    await tiles.evaluateAll((items) =>
      items.map((item) => item.getAttribute('data-task')!),
    ),
  )
  // Hold the new task at QUEUED in every response until the user has moved to another result.
  let hold = true
  await page.route('**/api/v4/generation-tasks/*', async (route) => {
    const id = new URL(route.request().url()).pathname.split('/').pop()!
    if (route.request().method() !== 'GET' || !hold || older.has(id))
      return route.continue()
    const response = await route.fetch()
    const detail = await response.json()
    await route.fulfill({
      response,
      json: { ...detail, status: 'QUEUED', artifacts: [], bases: [] },
    })
  })
  await page.route('**/api/v1/projects/*/tasks*', async (route) => {
    if (!hold) return route.continue()
    const response = await route.fetch()
    const listing = await response.json()
    for (const item of listing.items)
      if (!older.has(item.task.id))
        item.task = { ...item.task, status: 'QUEUED', artifacts: [] }
    await route.fulfill({ response, json: listing })
  })
  const { id } = await submitAndTrack(page, () =>
    page.getByTestId('generate').click(),
  )
  const fresh = page.locator(`[data-testid="result-card"][data-task="${id}"]`)
  await expect(fresh).toHaveAttribute('data-status', 'QUEUED')
  await expect(page.getByTestId('design-stage')).toContainText('正在生成')
  await tiles
    .and(page.locator(`[data-status="SUCCEEDED"]`))
    .first()
    .getByRole('button', { name: /^查看结果/ })
    .click()
  hold = false
  // No manual refresh: the background check picks up the finished task.
  await expect(done(page, id)).toHaveCount(1, { timeout: 20000 })
})

test('V4-B9: text that cannot fit its box is flagged before generating', async ({
  page,
}) => {
  await login(page)
  await page.getByRole('link', { name: '卖点主图' }).click()
  await section(page, '卖点文字')
  await page.getByLabel('卖点（每行一条').fill('安全材质')
  await page.getByLabel('标题').fill('测'.repeat(60))
  await expect(page.getByTestId('text-overflow')).toBeVisible()
  await expect(page.getByTestId('text-layer')).toHaveAttribute(
    'data-overflow',
    'true',
  )
  await page.screenshot({ path: join(artifacts, 'selling-overflow.png') })
  await page.getByLabel('标题').fill('下单即送')
  await expect(page.getByTestId('text-overflow')).toHaveCount(0)
  await expect(page.getByTestId('text-layer')).toHaveAttribute(
    'data-overflow',
    'false',
  )
})

test('V4-B6: history, works, account page and the admin model settings', async ({
  page,
  browser,
}) => {
  await login(page)
  await page.getByRole('link', { name: '任务记录' }).click()
  await expect(page.locator('.history-item').first()).toBeVisible()
  await page.screenshot({ path: join(artifacts, 'tasks-desktop.png') })
  await page.getByRole('link', { name: '我的作品' }).click()
  await expect(page.getByTestId('result-card').first()).toBeVisible()
  await page.screenshot({ path: join(artifacts, 'works-desktop.png') })
  await page.getByRole('link', { name: '我的账号' }).click()
  await expect(page.getByRole('heading', { name: '修改密码' })).toBeVisible()
  // Admin tools are a separate sidebar group that operators never see.
  await expect(page.getByRole('link', { name: '账号管理' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: '模型配置' })).toHaveCount(0)
  // Sign-out is an icon at the bottom of the sidebar; the next visit needs a login.
  await page.getByRole('button', { name: '退出登录' }).click()
  await expect(
    page.getByRole('heading', { name: '生产账号登录' }),
  ).toBeVisible()
  await page.reload()
  await expect(
    page.getByRole('heading', { name: '生产账号登录' }),
  ).toBeVisible()

  const admin = await browser.newPage()
  await login(admin, 'admin')
  await admin.getByRole('link', { name: '模型配置' }).click()
  const rows = admin.getByTestId('model-row')
  const main = rows.filter({ hasText: '模拟主力' })
  await expect(main).toContainText('默认')
  await expect(main).toContainText('****')
  await expect(admin.getByText('付费')).toHaveCount(0)
  // Official interfaces plus third-party endpoints in either format (ADR-20260930-E).
  await admin.getByRole('button', { name: '添加模型' }).click()
  let dialog = admin.getByRole('dialog', { name: '添加模型' })
  await expect(dialog.getByLabel('接口类型').locator('option')).toHaveText([
    'OpenRouter',
    'OpenAI 官方',
    'Gemini 官方',
    'OpenAI 格式（第三方）',
    'Gemini 格式（第三方）',
  ])
  await dialog.getByLabel('显示名称').fill('Gemini 备用')
  await dialog.getByLabel('接口类型').selectOption('gemini')
  await dialog.getByLabel('模型标识').fill('gemini-2.5-flash-image')
  await dialog.getByLabel('API Key').fill('mock-gemini-key')
  await dialog.getByLabel('通过网络代理访问').check()
  await dialog.getByRole('button', { name: '保存模型' }).click()
  await expect(dialog).toHaveCount(0)
  const added = rows.filter({ hasText: 'Gemini 备用' })
  await expect(added).toContainText('Gemini 官方')
  await expect(
    added.getByRole('switch', { name: 'Gemini 备用 走代理' }),
  ).toHaveAttribute('aria-checked', 'true')
  // The default model cannot be switched off.
  await main.getByRole('switch', { name: '模拟主力 启用' }).click()
  await expect(admin.locator('.banner[role="alert"]')).toContainText(
    '默认模型不能停用',
  )
  await added.getByRole('button', { name: '设为默认' }).click()
  await expect(added).toContainText('默认')
  await main.getByRole('button', { name: '设为默认' }).click()
  await expect(main).toContainText('默认')
  // Third-party endpoint: plain http only to intranet addresses, with a warning.
  await admin.getByRole('button', { name: '添加模型' }).click()
  dialog = admin.getByRole('dialog', { name: '添加模型' })
  await dialog.getByLabel('显示名称').fill('中转备用')
  await dialog.getByLabel('接口类型').selectOption('openai-compatible')
  await dialog.getByLabel('接口地址').fill('http://8.8.8.8/v1')
  await expect(dialog.getByRole('note')).toContainText('明文传输')
  await dialog.getByLabel('模型标识').fill('gpt-image-2')
  await dialog.getByLabel('API Key').fill('mock-relay-key')
  await dialog.getByRole('button', { name: '保存模型' }).click()
  await expect(dialog.getByRole('alert')).toContainText('只允许内网 IP')
  await dialog.getByLabel('接口地址').fill('http://10.0.0.5:3000/v1')
  await dialog.getByLabel('API Key').fill('mock-relay-key')
  await dialog.getByRole('button', { name: '保存模型' }).click()
  await expect(dialog).toHaveCount(0)
  await expect(rows.filter({ hasText: '中转备用' })).toContainText(
    'http://10.0.0.5:3000/v1',
  )
  await admin.screenshot({
    path: join(artifacts, 'models-admin.png'),
    fullPage: true,
  })
  // Proxy (its own tab): no paths; credentials are masked once saved.
  await admin.getByRole('button', { name: '网络代理' }).click()
  await admin
    .getByLabel('代理地址')
    .fill('http://user:secret@proxy.internal:3128/x')
  await admin.getByRole('button', { name: '保存代理' }).click()
  await expect(admin.locator('.banner[role="alert"]')).toBeVisible()
  await admin
    .getByLabel('代理地址')
    .fill('http://user:secret@proxy.internal:3128')
  await admin.getByRole('button', { name: '保存代理' }).click()
  await expect(admin.getByTestId('proxy-state')).toHaveText('已设置')
  await expect(admin.getByText('http://****@proxy.internal:3128')).toBeVisible()
  await expect(admin.getByText('secret')).toHaveCount(0)
  await admin.getByRole('button', { name: '清除代理' }).click()
  await confirm(admin, '清除代理')
  await expect(admin.getByTestId('proxy-state')).toHaveText('未设置')
  // Operators pick any enabled model on the create pages.
  await admin.getByRole('link', { name: '场景主图' }).click()
  await section(admin, '输出设置')
  await admin.getByRole('button', { name: /^模型：/ }).click()
  await expect(
    admin.getByRole('option', { name: /Gemini 备用.*Gemini 官方/ }),
  ).toBeVisible()
  await admin.keyboard.press('Escape')
  // Account management has its own page; an admin can delete others, never themself.
  await admin.getByRole('link', { name: '账号管理' }).click()
  const accountRows = admin.getByTestId('account-row')
  await expect(accountRows).not.toHaveCount(0)
  await expect(
    accountRows
      .filter({ hasText: '当前登录' })
      .getByRole('button', { name: '删除' }),
  ).toHaveCount(0)
  await admin.getByRole('button', { name: '新建账号' }).click()
  const create = admin.getByRole('dialog', { name: '新建账号' })
  await create.getByLabel('新账号名称').fill('temp-ui')
  await create.getByLabel('初始密码').fill(process.env.T06_PASSWORD!)
  await create.getByRole('button', { name: '创建账号' }).click()
  const temp = accountRows.filter({ hasText: 'temp-ui' })
  await expect(temp).toBeVisible()
  await admin.screenshot({
    path: join(artifacts, 'accounts-admin.png'),
    fullPage: true,
  })
  await temp.getByRole('button', { name: '删除' }).click()
  await confirm(admin, '删除账号 temp-ui')
  await expect(temp).toHaveCount(0)
  await expect(admin.locator('.banner[role="status"]')).toContainText('已删除')
  await admin.close()
})

test('V4-B7: owners delete an original and a result; history keeps a placeholder', async ({
  page,
}) => {
  await login(page)
  // Every confirmation is an in-page dialog; a native browser box would fail this test.
  page.on('dialog', (dialog) => {
    throw new Error(`unexpected native dialog: ${dialog.message()}`)
  })
  await page.getByRole('link', { name: '素材管理' }).click()
  const assets = page.getByTestId('asset-card')
  await expect(assets.first()).toBeVisible()
  const before = await assets.count()
  await assets.first().hover()
  await assets
    .first()
    .getByRole('button', { name: /^删除素材/ })
    .click()
  await confirm(page, '删除原图')
  await expect(toast(page)).toContainText('原图已删除')
  await expect(assets).toHaveCount(before - 1)
  await page.screenshot({ path: join(artifacts, 'assets-desktop.png') })

  // Results made from a deleted original stay, and the comparison says so.
  await page.getByRole('link', { name: '我的作品' }).click()
  await page.getByRole('button', { name: '场景主图' }).click()
  const cards = page.getByTestId('result-card')
  await cards.first().hover()
  await cards.first().getByRole('button', { name: '对照原图' }).click()
  const dialog = page.getByRole('dialog', { name: '原图对照' })
  await expect(dialog).toContainText('原图已删除')
  await dialog.getByRole('button', { name: '关闭' }).click()

  const results = await cards.count()
  await cards.first().hover()
  await cards.first().getByRole('button', { name: '删除' }).click()
  // Cancelling keeps the result.
  await page
    .getByRole('dialog', { name: '删除生成结果' })
    .getByRole('button', { name: '取消' })
    .click()
  await expect(cards).toHaveCount(results)
  await cards.first().hover()
  await cards.first().getByRole('button', { name: '删除' }).click()
  await confirm(page, '删除生成结果')
  await expect(toast(page)).toContainText('生成结果已删除')
  await expect(cards).toHaveCount(results - 1)
  expect(await alert(page).count()).toBe(0)
})

test('V4-B10: an image the browser can open is accepted whatever its name or format', async ({
  page,
}) => {
  await login(page)
  await page.getByRole('link', { name: '素材管理' }).click()
  const cards = page.getByTestId('asset-card')
  await expect(cards.first()).toBeVisible()
  const before = await cards.count()
  // WebP content under a ".jpg" name: stored as a PNG copy of its pixels.
  await page.getByLabel('上传商品图').setInputFiles(process.env.CORE_WEBP_FILE!)
  await expect(toast(page)).toContainText('已转为 PNG 保存')
  await expect(cards).toHaveCount(before + 1)
  await expect(cards.first().locator('img')).toBeVisible()
})

test('V4-B11: a finished work becomes the product image; the gift keeps the original background', async ({
  page,
}) => {
  await login(page)
  await page.getByRole('link', { name: '赠品主图' }).click()
  await page.getByRole('button', { name: /^商品图/ }).click()
  await page.getByRole('menuitem', { name: '从素材库选择' }).click()
  const picker = page.getByRole('dialog', { name: '选择商品图' })
  await picker.getByRole('button', { name: '我的作品' }).click()
  await picker
    .getByRole('button', { name: /^使用作品/ })
    .first()
    .click()
  await expect(picker).toHaveCount(0)
  await expect(toast(page)).toContainText('已把作品复制为商品图')
  await section(page, '背景')
  await page.getByRole('button', { name: '保持原图' }).click()
  await expect(page.getByRole('button', { name: /^背景/ })).toContainText(
    '保持原图背景',
  )
  const { body, id } = await submitAndTrack(page, () =>
    page.getByTestId('generate').click(),
  )
  expect(body.background).toEqual({ mode: 'ORIGINAL' })
  await expect(done(page, id)).toHaveCount(1, { timeout: 60000 })
  // The copy shows in the library, marked as coming from a work.
  await page.getByRole('link', { name: '素材管理' }).click()
  await expect(
    page.getByTestId('asset-card').filter({ hasText: '来自作品' }).first(),
  ).toBeVisible()
})

test('V4-B12: images open full-screen with zoom and previous/next', async ({
  page,
}) => {
  await login(page)
  await page.getByRole('link', { name: '我的作品' }).click()
  const cards = page.getByTestId('result-card')
  await expect(cards.nth(1)).toBeVisible()
  await cards.first().locator('figure').click()
  const viewer = page.getByRole('dialog', { name: '图片查看' })
  await expect(viewer.locator('img')).toBeVisible()
  await expect(viewer).toContainText('1 /')
  await viewer.getByRole('button', { name: '放大' }).click()
  await expect(viewer.getByRole('button', { name: '适应窗口' })).toHaveText(
    '125%',
  )
  await page.keyboard.press('ArrowRight')
  await expect(viewer).toContainText('2 /')
  await expect(viewer.getByRole('button', { name: '适应窗口' })).toHaveText(
    '100%',
  )
  await page.screenshot({ path: join(artifacts, 'viewer.png') })
  await page.keyboard.press('Escape')
  await expect(viewer).toHaveCount(0)
})

test('V4-B13: admins edit scene presets; saving publishes and a rollback restores', async ({
  page,
}) => {
  await login(page, 'admin')
  await page.getByRole('link', { name: '模板管理' }).click()
  const scenes = page.getByTestId('preset-scene')
  await expect(scenes.first()).toBeVisible()
  const before = await scenes.count()
  await page.getByRole('button', { name: '添加场景' }).click()
  await expect(scenes).toHaveCount(before + 1)
  await page.getByLabel(`场景名称 ${before + 1}`).fill('露台花园')
  await page
    .getByLabel(`场景描述 ${before + 1}`)
    .fill('a sunny balcony garden with potted plants')
  await page.getByLabel('修改说明').fill('新增露台花园')
  await page.getByRole('button', { name: '保存并发布' }).click()
  await expect(page.locator('.banner[role="status"]')).toContainText(
    '已发布版本',
  )
  await page.screenshot({
    path: join(artifacts, 'presets-admin.png'),
    fullPage: true,
  })
  // The new scene is offered on the scene page right away.
  await page.getByRole('link', { name: '场景主图' }).click()
  await section(page, '场景')
  await expect(page.getByRole('button', { name: '露台花园' })).toBeVisible()
  await page.getByRole('link', { name: '模板管理' }).click()
  await page.getByRole('button', { name: '版本记录' }).click()
  await expect(page.getByTestId('preset-version').first()).toContainText(
    '新增露台花园',
  )
  await page.getByRole('button', { name: '恢复内置默认' }).click()
  await confirm(page, '恢复内置默认')
  await expect(page.locator('.banner[role="status"]')).toContainText(
    '已发布版本',
  )
  await page.getByRole('link', { name: '场景主图' }).click()
  await section(page, '场景')
  await expect(page.getByRole('button', { name: '露台花园' })).toHaveCount(0)
})

test('V4-B14: personal templates and undo/redo (gift), layers (selling)', async ({
  page,
}) => {
  await login(page)
  await page.getByRole('link', { name: '赠品主图' }).click()
  // The accordion header; the colour swatches are also named "背景 …".
  const background = page
    .locator('button.acc-head')
    .filter({ hasText: /^背景/ })
  await section(page, '背景')
  await page.getByRole('button', { name: '保持原图' }).click()
  // Save the settings as a personal template.
  await page.getByRole('button', { name: '我的模板' }).click()
  await page.getByRole('button', { name: '保存当前参数为模板' }).click()
  const dialog = page.getByRole('dialog', { name: '保存为模板' })
  await dialog.getByLabel('模板名称').fill('原图背景')
  await dialog.getByRole('button', { name: '保存模板' }).click()
  await expect(toast(page)).toContainText('已保存模板')
  // Change the settings, then apply the template again.
  await section(page, '背景')
  await page.getByRole('button', { name: '纯色' }).click()
  await expect(background).toContainText('纯白')
  await page.waitForTimeout(600) // let the edit settle into its own undo step
  await page.getByRole('button', { name: '我的模板' }).click()
  await page
    .getByTestId('template-row')
    .filter({ hasText: '原图背景' })
    .getByRole('button', { name: '原图背景', exact: true })
    .click()
  await expect(toast(page)).toContainText('已套用模板')
  await expect(background).toContainText('保持原图背景')
  await page.waitForTimeout(600)
  // Undo returns to the solid background, redo applies the template again.
  await page.getByRole('button', { name: '撤销' }).click()
  await expect(background).toContainText('纯白')
  await page.getByRole('button', { name: '重做' }).click()
  await expect(background).toContainText('保持原图背景')
  // Templates are personal and can be deleted.
  await page.getByRole('button', { name: '我的模板' }).click()
  await page.getByRole('button', { name: '删除模板 原图背景' }).click()
  await confirm(page, '删除模板“原图背景”')
  await expect(page.getByTestId('template-row')).toHaveCount(0)
  // Layers: guides on, text locked (dragging no longer moves it).
  await page.getByRole('link', { name: '卖点主图' }).click()
  await page.getByRole('button', { name: '图层' }).click()
  await page.getByLabel('显示参考线').check()
  await page.getByLabel('锁定文字位置').check()
  await expect(page.locator('.guides')).toBeVisible()
  const layer = page.getByTestId('text-layer')
  const box = (await layer.boundingBox())!
  await page.mouse.move(box.x + 20, box.y + 20)
  await page.mouse.down()
  await page.mouse.move(box.x - 60, box.y + 60, { steps: 5 })
  await page.mouse.up()
  expect((await layer.boundingBox())!.x).toBeCloseTo(box.x, 0)
  await page.screenshot({ path: join(artifacts, 'selling-tools.png') })
})

test('V4-B16: selling text on a finished work with "keep original" (no model)', async ({
  page,
}) => {
  test.skip(!withText, 'needs a deployment font for text overlay')
  const errors = watchErrors(page)
  await login(page)
  await page.getByRole('link', { name: '卖点主图' }).click()
  // A finished gift image becomes the product image.
  await page.getByRole('button', { name: /^商品图/ }).click()
  await page.getByRole('menuitem', { name: '从素材库选择' }).click()
  const picker = page.getByRole('dialog', { name: '选择商品图' })
  await picker.getByRole('button', { name: '我的作品' }).click()
  await picker
    .getByRole('button', { name: /^使用作品/ })
    .first()
    .click()
  await expect(picker).toHaveCount(0)
  await page.getByLabel('标题').fill('下单即送')
  await page.getByLabel('卖点（每行一条').fill('防撞护角\n安全材质')
  await section(page, '风格')
  await page.getByRole('button', { name: '保持原图' }).click()
  await expect(
    page.locator('button.acc-head').filter({ hasText: /^输出设置/ }),
  ).toContainText('不调用模型')
  await section(page, '卖点文字')
  await page.getByRole('button', { name: '文字 深蓝' }).click()
  // The plan shows the image itself under the text box.
  await expect(page.locator('.artboard img.base')).toBeVisible()
  await expect(page.getByTestId('generate')).toHaveText('生成 2 张')
  await page.screenshot({ path: join(artifacts, 'selling-original-plan.png') })
  const { body, id } = await submitAndTrack(page, () =>
    page.getByTestId('generate').click(),
  )
  expect(body.keep_original).toBe(true)
  expect(body.style).toBeUndefined()
  expect(body.model_id).toBeUndefined()
  expect(body.output.count).toBe(2)
  expect(body.text.color).toBe('#1E3A5F')
  await expect(done(page, id)).toHaveCount(2, { timeout: 60000 })
  await page.screenshot({ path: join(artifacts, 'selling-original.png') })
  // A text-only edit of one image, again without the model.
  await section(page, '卖点文字')
  await page.getByLabel('标题').fill('新标题')
  const retype = await submitAndTrack(
    page,
    () => page.getByRole('button', { name: '应用文字修改' }).click(),
    (r) => r.url().endsWith(`/api/v4/generation-tasks/${id}/retypeset`),
  )
  expect(retype.body.ordinal).toBe(0)
  expect(retype.body.text.title).toBe('新标题')
  expect(retype.body.text.points).toEqual(['防撞护角'])
  await expect(done(page, retype.id)).toHaveCount(1, { timeout: 60000 })
  expect(errors).toEqual([])
})

test('V4-B15: image management, dashboard and operation log for admins', async ({
  page,
}) => {
  await login(page, 'admin')
  await page.getByRole('link', { name: '图片管理' }).click()
  const images = page.getByTestId('admin-image')
  await expect(images.first()).toBeVisible()
  await page.getByRole('button', { name: '作品', exact: true }).click()
  await page
    .getByLabel('账号', { exact: true })
    .selectOption({ label: 'alice' })
  await expect(images.first()).toContainText('alice')
  const count = await images.count()
  await images.first().hover()
  await images.first().getByRole('button', { name: '删除' }).click()
  await confirm(page, /^删除 alice 的/)
  await expect(page.locator('.banner[role="status"]')).toContainText(
    '图片已删除',
  )
  await expect(images).toHaveCount(count - 1)
  await page.screenshot({ path: join(artifacts, 'images-admin.png') })
  await page.getByRole('link', { name: '数据看板' }).click()
  await expect(page.getByTestId('stat-tasks')).not.toContainText(
    /生成任务\s*0\b/,
  )
  await expect(page.locator('.daily-chart')).toBeVisible()
  await expect(
    page.getByRole('table').filter({ hasText: 'alice' }),
  ).toBeVisible()
  await page.screenshot({
    path: join(artifacts, 'dashboard-admin.png'),
    fullPage: true,
  })
  await page.getByRole('link', { name: '操作日志' }).click()
  const rows = page.getByTestId('audit-row')
  await expect(rows.first()).toBeVisible()
  await page.getByLabel('动作').selectOption({ label: '删除作品' })
  await expect(rows.first()).toContainText('删除作品')
  await expect(rows.first()).toContainText('admin')
  await page.screenshot({
    path: join(artifacts, 'audit-admin.png'),
    fullPage: true,
  })
})
