import { expect, test, type Page, type Request } from '@playwright/test'
import { join } from 'node:path'

const artifacts = process.env.T06_ARTIFACTS!
const withText = !!process.env.CORE_FONT

async function login(page: Page, name = 'alice') {
  await page.goto('/')
  await page.getByLabel('本地账号', { exact: true }).fill(name)
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
async function submitAndTrack(page: Page, match = generationPost) {
  const sent = page.waitForRequest(match)
  const answered = page.waitForResponse(
    (r) => match(r.request()) && r.status() === 202,
  )
  const body = (await sent).postDataJSON()
  const task = await (await answered).json()
  return { body, id: task.id as string }
}
function done(page: Page, task: string) {
  return page
    .locator(`[data-task="${task}"]`)
    .filter({ hasText: '已完成 · 待人工审核' })
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
  for (const name of ['赠品+文字主图', '场景主图', '卖点主图'])
    await expect(
      page.getByRole('button', { name: `${name} 立即生成` }),
    ).toBeVisible()
  await expect(page.getByText('模拟模型验收模式')).toBeVisible()
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

test('V4-B2: scene - upload, preset, one image by default, compare, download', async ({
  page,
}) => {
  const errors = watchErrors(page)
  await login(page)
  await page.getByRole('button', { name: '场景主图 立即生成' }).click()
  await expect(page.getByRole('heading', { name: '场景主图' })).toBeVisible()
  await page
    .getByLabel('上传产品主图（白底图）')
    .setInputFiles(process.env.CORE_PRODUCT_FILE!)
  await expect(page.getByRole('status').first()).toContainText('商品原图已保存')
  await page.getByRole('button', { name: '木质桌面' }).click()
  const tracked = submitAndTrack(page)
  await page.getByRole('button', { name: /生成图片/ }).click()
  const { body, id } = await tracked
  expect(body.feature_type).toBe('SCENE')
  expect(body.scene_preset).toBe('wood_table')
  expect(body.output.count).toBe(1)
  expect(body).not.toHaveProperty('text')
  const card = done(page, id).first()
  await expect(card).toBeVisible({ timeout: 60000 })
  await expect(page.getByTestId('design-stage').locator('img')).toBeVisible()
  await card.getByRole('button', { name: '对照原图' }).click()
  const dialog = page.getByRole('dialog', { name: '原图对照' })
  await expect(dialog.getByAltText('商品原图')).toBeVisible()
  await expect(dialog.getByAltText('生成结果')).toBeVisible()
  await dialog.getByRole('button', { name: '关闭' }).click()
  const download = page.waitForEvent('download')
  await card.getByRole('button', { name: '下载' }).click()
  expect((await download).suggestedFilename()).toMatch(/^scene-.+\.png$/)
  await page.screenshot({
    path: join(artifacts, 'scene-desktop.png'),
    fullPage: true,
  })
  expect(errors).toEqual([])
})

test('V4-B3: gift with text, then a free text-only re-render', async ({
  page,
}) => {
  const errors = watchErrors(page)
  await login(page)
  await page.getByRole('link', { name: '赠品+文字主图' }).click()
  await page
    .getByLabel('上传赠品图片（独立图）')
    .setInputFiles(process.env.CORE_GIFT_FILE!)
  await expect(page.getByRole('status').first()).toContainText('赠品原图已保存')
  await page.getByRole('button', { name: '左下' }).click()
  await page.getByRole('button', { name: '背景颜色 #FFF6EC' }).click()
  if (withText) {
    await page
      .getByLabel('标题文字（可选，原文使用）')
      .fill('下单即送\n防撞护角')
    await page.getByLabel('营销标签（每行一条，可选）').fill('安全材质')
    const layer = page.getByTestId('text-layer')
    await expect(layer).toContainText('防撞护角')
    await layer.scrollIntoViewIfNeeded()
    const box = (await layer.boundingBox())!
    await page.mouse.move(box.x + 20, box.y + 20)
    await page.mouse.down()
    await page.mouse.move(box.x + 50, box.y + 40, { steps: 5 })
    await page.mouse.up()
  }
  const tracked = submitAndTrack(page)
  await page.getByRole('button', { name: /生成图片/ }).click()
  const { body, id } = await tracked
  expect(body.feature_type).toBe('GIFT')
  expect(body.gift_position).toBe('BOTTOM_LEFT')
  expect(body.background).toEqual({ mode: 'SOLID', color: '#FFF6EC' })
  expect(body.output.count).toBe(1)
  if (withText) {
    expect(body.text.title).toBe('下单即送\n防撞护角')
    expect(body.text.points).toEqual(['安全材质'])
    expect(body.text.box.x).toBeGreaterThan(0.05)
  }
  await expect(done(page, id)).toHaveCount(1, { timeout: 60000 })
  await page.screenshot({
    path: join(artifacts, 'gift-desktop.png'),
    fullPage: true,
  })
  if (withText) {
    // The model output stays; only the text is re-rendered and no model is called.
    await page.getByLabel('标题文字（可选，原文使用）').fill('新标题')
    const retyped = submitAndTrack(page, (r) =>
      r.url().endsWith(`/api/v4/generation-tasks/${id}/retypeset`),
    )
    await page
      .getByRole('button', { name: '应用文字修改（免费，不重新生成）' })
      .click()
    const retype = await retyped
    expect(retype.body.ordinal).toBe(0)
    expect(retype.body.text.title).toBe('新标题')
    await expect(done(page, retype.id)).toHaveCount(1, { timeout: 60000 })
    await page.screenshot({
      path: join(artifacts, 'gift-retypeset.png'),
      fullPage: true,
    })
  }
  await page.setViewportSize({ width: 390, height: 844 })
  await noHorizontalScroll(page)
  await page.screenshot({
    path: join(artifacts, 'gift-mobile.png'),
    fullPage: true,
  })
  expect(errors).toEqual([])
})

test('V4-B4: selling points - one image per chosen style, verbatim points', async ({
  page,
}) => {
  test.skip(!withText, 'needs a deployment font for text overlay')
  const errors = watchErrors(page)
  await login(page)
  await page.getByRole('link', { name: '卖点主图' }).click()
  await page.getByRole('button', { name: '自然绿' }).click()
  await expect(page.getByText('已选 2 种，将生成 2 张。')).toBeVisible()
  await page.getByLabel('标题文字（可选，原文使用）').fill('轻松喂养')
  await page
    .getByLabel('卖点（每行一条，原文使用）')
    .fill(' 安全材质 \n防胀气设计\n易清洗')
  const tracked = submitAndTrack(page)
  await page.getByRole('button', { name: /生成图片/ }).click()
  const { body, id } = await tracked
  expect(body.styles).toEqual(['warm', 'green'])
  expect(body.output.count).toBe(2)
  expect(body.text.points).toEqual([' 安全材质 ', '防胀气设计', '易清洗'])
  await expect(done(page, id)).toHaveCount(2, { timeout: 60000 })
  await page.screenshot({
    path: join(artifacts, 'selling-desktop.png'),
    fullPage: true,
  })
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
  await page.getByRole('button', { name: /生成图片/ }).click()
  const resend = page.getByRole('button', { name: '用原请求重发' })
  await expect(resend).toBeVisible()
  const again = page.waitForRequest(generationPost)
  await resend.click()
  const request = await again
  expect(request.headers()['idempotency-key']).toBe(firstKey)
  expect(request.postData()).toBe(firstBody)
  await expect(resend).toHaveCount(0)
})

test('V4-B6: history, works and admin-only settings', async ({
  page,
  browser,
}) => {
  await login(page)
  await page.getByRole('link', { name: '任务记录' }).click()
  await expect(page.locator('.history-item').first()).toBeVisible()
  await page.getByRole('link', { name: '我的作品' }).click()
  await expect(page.getByTestId('result-card').first()).toBeVisible()
  await page.getByRole('link', { name: '账号与安全' }).click()
  await expect(page.getByRole('button', { name: '本人改密' })).toBeVisible()
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
  await admin.getByRole('button', { name: '供应商配置' }).click()
  await expect(admin.getByTestId('provider-state')).toContainText('已启用')
  await expect(
    admin.getByTestId('provider-version-row').filter({ hasText: 'mock-model' }),
  ).toContainText('****')
  await expect(admin.getByText('付费')).toHaveCount(0)
  await admin.screenshot({
    path: join(artifacts, 'settings-admin.png'),
    fullPage: true,
  })
  await admin.close()
})
