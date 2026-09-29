import { test, expect } from '@playwright/test'
import type { Page } from '@playwright/test'
import { readFileSync } from 'node:fs'

async function login(page: Page, name = 'alice') {
  await page.goto('/')
  await page.getByLabel('本地账号').fill(name)
  await page.getByLabel('密码', { exact: true }).fill(process.env.T06_PASSWORD!)
  await page.getByRole('button', { name: '登录开发环境' }).click()
  await expect(page.getByRole('button', { name: '退出本地账号' })).toBeVisible()
  await expect(page.getByText('正在读取项目素材与任务…')).toHaveCount(0)
}
async function scene(page: Page) {
  await page
    .getByRole('button', { name: '场景图 选择场景预设或描述你的场景' })
    .click()
  await page
    .getByRole('combobox', { name: '商品原图', exact: true })
    .selectOption('product')
  await page
    .getByRole('combobox', { name: '输出预设', exact: true })
    .selectOption('t05_transport_fixture')
  await page
    .getByLabel('场景描述', { exact: true })
    .fill('仅用于页面测试的合成场景描述')
}

test('ACC-T06 A1–A3/A5–A8: dev-local workflows, history, errors and responsive pages', async ({
  page,
}, info) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await login(page)
  await expect(
    page.getByText('真实图片生成尚未开放', { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole('button', { name: '赠品图 独立赠品素材，手动调整位置' }),
  ).toBeVisible()
  // Current fixture success is explicitly presented as transport testing, never a product result.
  await page
    .locator('.history-item')
    .filter({ hasText: '开发/测试任务完成' })
    .first()
    .click()
  await page.getByRole('button', { name: '查看测试产物' }).click()
  await expect(
    page.getByAltText('开发/测试产物 · 非真实商品成品'),
  ).toBeVisible()
  const downloaded = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载测试产物' }).click()
  expect((await downloaded).suggestedFilename()).toMatch(/^development-test-/)
  await page.getByRole('button', { name: '加载更早任务' }).click()
  await expect(page.locator('.history-item')).toHaveCount(22)

  await page.getByLabel('上传商品图').setInputFiles({
    name: 'invalid.png',
    mimeType: 'image/png',
    buffer: Buffer.from('not an image'),
  })
  await expect(page.getByRole('alert')).toContainText('图片内容或尺寸')
  await page.getByLabel('上传商品图').setInputFiles({
    name: 'synthetic.jpg',
    mimeType: 'image/jpeg',
    buffer: Buffer.from(
      readFileSync('../contracts/fixtures/t04-synthetic-jpeg.base64', 'utf8'),
      'base64',
    ),
  })
  await expect(page.getByRole('status')).toContainText('原图已保存')
  await expect(
    page.getByRole('button', { name: '提交开发任务' }),
  ).toBeDisabled()
  await expect(
    page.getByText('商品抠图尚未确认：请在商品下方生成抠图候选并确认边缘。'),
  ).toBeVisible()
  await page.getByRole('button', { name: '查看商品原图' }).click()
  await expect(page.getByAltText('上传原图 · 非生成预览')).toBeVisible()

  await scene(page)
  await page.getByLabel('自定义风格（可选）').fill('保留我的风格文字')
  await page.getByRole('button', { name: /卖点图 人工输入卖点/ }).click()
  await expect(page.getByLabel('场景描述', { exact: true })).toHaveCount(0)
  await page
    .getByLabel('人工卖点（每行一条，原文提交）')
    .fill(' 人工第一条 \n第二条')
  await page
    .getByRole('button', { name: '场景图 选择场景预设或描述你的场景' })
    .click()
  await expect(page.getByLabel('自定义风格（可选）')).toHaveValue(
    '保留我的风格文字',
  )
  const sent = page.waitForRequest(
    (r) => r.method() === 'POST' && r.url().endsWith('/api/v1/tasks'),
  )
  await page.getByRole('button', { name: '提交开发任务' }).click()
  const sceneBody = (await sent).postDataJSON()
  expect(sceneBody.feature_type).toBe('SCENE')
  expect(sceneBody).not.toHaveProperty('gift_asset_id')
  expect(sceneBody).not.toHaveProperty('selling_points')
  await expect(page.locator('.task-status')).toHaveText('执行失败', {
    timeout: 20000,
  })
  await expect(page.locator('.task-panel')).toContainText(
    'PROVIDER_UNAVAILABLE',
  )
  await page.getByRole('button', { name: '重试任务', exact: true }).click()
  await expect(page.locator('.task-panel')).toContainText('第 2 次')
  await expect(page.locator('.task-status')).toHaveText('执行失败', {
    timeout: 20000,
  })

  for (const feature of ['GIFT', 'SELLING_POINT']) {
    await page
      .getByRole('button', {
        name:
          feature === 'GIFT'
            ? '赠品图 独立赠品素材，手动调整位置'
            : /卖点图 人工输入卖点/,
      })
      .click()
    await page
      .getByRole('combobox', { name: '商品原图', exact: true })
      .selectOption('product')
    await page
      .getByRole('combobox', { name: '排版模板版本', exact: true })
      .selectOption('layout_v1')
    await page
      .getByRole('combobox', { name: '输出预设', exact: true })
      .selectOption('t05_transport_fixture')
    const submitted = page.waitForRequest(
      (r) => r.method() === 'POST' && r.url().endsWith('/api/v1/tasks'),
    )
    await page.getByRole('button', { name: '提交开发任务' }).click()
    const body = (await submitted).postDataJSON()
    expect(body.feature_type).toBe(feature)
    expect(body).not.toHaveProperty('scene_custom_prompt')
    if (feature === 'SELLING_POINT')
      expect(body.selling_points).toEqual([' 人工第一条 ', '第二条'])
    await expect(page.locator('.task-status')).toHaveText('执行失败', {
      timeout: 20000,
    })
  }
  await page.screenshot({
    path: info.outputPath('desktop.png'),
    fullPage: true,
  })
  await page
    .locator('.workspace')
    .screenshot({ path: info.outputPath('desktop-workspace.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: info.outputPath('mobile.png'), fullPage: true })
  await page
    .locator('.inputs')
    .screenshot({ path: info.outputPath('mobile-inputs.png') })
  await page
    .locator('.task-panel')
    .screenshot({ path: info.outputPath('mobile-task.png') })
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true)
  await page.getByRole('button', { name: '退出本地账号' }).click()
  await expect(page.locator('.history-item')).toHaveCount(0)
  await login(page)
  await expect(page.locator('.history-item')).toHaveCount(20)
  await page.getByRole('button', { name: '退出本地账号' }).click()
  await login(page, 'bob')
  await expect(
    page.getByText('还没有项目。创建项目后上传素材，开始验证工作流程。'),
  ).toBeVisible()
  await expect(page.locator('.history-item')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('ACC-T06 A2/A4/A5: lost response reuses key; network and expired session are visible', async ({
  page,
}) => {
  await login(page)
  await scene(page)
  let firstKey = '',
    firstBody = ''
  await page.route(
    '**/api/v1/tasks',
    async (route) => {
      firstKey = route.request().headers()['idempotency-key']!
      firstBody = route.request().postData()!
      await route.fetch() // Java commits the task, but its response is deliberately lost.
      await route.abort('failed')
    },
    { times: 1 },
  )
  await page.getByRole('button', { name: '提交开发任务' }).click()
  await expect(page.getByRole('button', { name: '用原请求重发' })).toBeVisible()
  const resent = page.waitForRequest(
    (r) => r.method() === 'POST' && r.url().endsWith('/api/v1/tasks'),
  )
  await page.getByRole('button', { name: '用原请求重发' }).click()
  const request = await resent
  expect(request.headers()['idempotency-key']).toBe(firstKey)
  expect(request.postData()).toBe(firstBody)
  await expect(page.getByRole('button', { name: '用原请求重发' })).toHaveCount(
    0,
  )
  await page.route(
    '**/api/v1/projects/p/tasks?offset=0',
    (route) => route.abort('failed'),
    { times: 1 },
  )
  await page.getByRole('button', { name: '刷新历史', exact: true }).click()
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
  await page.getByRole('button', { name: '刷新历史', exact: true }).click()
  await expect(page.getByRole('button', { name: '登录开发环境' })).toBeVisible()
  await expect(page.locator('.history-item')).toHaveCount(0)
  expect(
    await page.evaluate(() => [localStorage.length, sessionStorage.length]),
  ).toEqual([0, 0])
})
