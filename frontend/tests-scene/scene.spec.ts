import { test, expect } from '@playwright/test'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

test('browser submits three scenes through authenticated Java and previews results', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/')
  await page.getByLabel('本地账号', { exact: true }).fill('alice')
  await page.getByLabel('密码', { exact: true }).fill(process.env.T06_PASSWORD!)
  await page.getByRole('button', { name: '登录生产账号', exact: true }).click()
  await expect(page.getByRole('button', { name: '退出本地账号' })).toBeVisible()
  await page.getByRole('button', { name: '场景图', exact: false }).click()
  await page
    .getByLabel('场景描述', { exact: true })
    .fill(
      'A quiet nursery with a pale oak tabletop, soft warm neutral wall, empty spacious stage, photographed at a slight downward angle. No people or objects.',
    )
  await expect(page.getByLabel('生成数量')).toHaveValue('3')
  const placement = page.getByTestId('subject-placement')
  await expect(placement).toBeVisible()
  await page.getByText('位置与尺寸参数', { exact: true }).click()
  const xField = page.getByLabel('横向位置', { exact: true })
  const oldX = Number(await xField.inputValue())
  const box = (await placement.boundingBox())!
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width / 2 + 15, box.y + box.height / 2)
  await page.mouse.up()
  await expect
    .poll(async () => Number(await xField.inputValue()))
    .toBeGreaterThan(oldX)
  await page.getByLabel('等比例缩放', { exact: true }).fill('0.6')
  await expect(page.getByLabel('宽度', { exact: true })).toHaveValue('0.6')
  await xField.fill('0.2')
  await expect(placement).toHaveCSS('left', /.+px/)
  await page.screenshot({
    path: join(process.env.T06_ARTIFACTS!, 'scene-editor.png'),
    fullPage: true,
  })
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true)
  const submission = page.waitForResponse(
    (r) =>
      r.url().endsWith('/api/v3/scene-tasks') &&
      r.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '生成场景图', exact: true }).click()
  const response = await submission
  expect(response.status()).toBe(202)
  const task = await response.json()
  writeFileSync(
    join(process.env.T09_SYNC_DIR!, 'submitted.json'),
    JSON.stringify({ task_id: task.id }),
  )
  await expect(page.locator('.task-status')).toHaveAttribute(
    'data-status',
    'SUCCEEDED',
    { timeout: 600000 },
  )
  const mock = process.env.T09_MODE === 'mock'
  await expect(page.locator('.task-status')).toHaveText(
    mock ? '模拟链路完成 · 非真实生成' : '场景合成完成 · 待人工审核',
  )
  if (mock)
    await expect(
      page.getByText('模拟供应商验收模式 · 非真实生成', { exact: true }),
    ).toBeVisible()
  await expect(
    page.getByRole('button', { name: '查看场景图', exact: true }),
  ).toHaveCount(3)
  await page
    .getByRole('button', { name: '查看场景图', exact: true })
    .first()
    .click()
  const image = page.getByRole('img', {
    name: mock ? '模拟供应商合成 · 非真实生成' : '真实背景合成 · 待人工审核',
  })
  await expect(image).toBeVisible()
  expect(
    await image.evaluate((element: HTMLImageElement) => element.naturalWidth),
  ).toBeGreaterThan(0)
  const download = page.waitForEvent('download')
  await page
    .getByRole('button', { name: '下载场景图', exact: true })
    .first()
    .click()
  expect((await download).suggestedFilename()).toMatch(
    /^scene-pending-.+\.(png|jpeg)$/,
  )
  await page.screenshot({
    path: join(process.env.T06_ARTIFACTS!, 'scene-page.png'),
    fullPage: true,
  })
  await page.getByRole('button', { name: '关闭放大预览', exact: true }).click()
  await page.screenshot({
    path: join(process.env.T06_ARTIFACTS!, 'scene-layout.png'),
    fullPage: true,
  })
  if (mock) {
    const failureFile = join(process.env.T09_SYNC_DIR!, 'failed.json')
    await expect
      .poll(() => existsSync(failureFile), { timeout: 60000 })
      .toBe(true)
    const failure = JSON.parse(readFileSync(failureFile, 'utf8'))
    await page.getByRole('button', { name: '刷新历史', exact: true }).click()
    await page
      .locator('.history-item')
      .filter({ hasText: failure.task_id })
      .click()
    await expect(page.locator('.task-status')).toHaveAttribute(
      'data-status',
      'FAILED',
    )
    await expect(page.locator('.task-panel .artifact')).toHaveCount(0)
    await expect(page.locator('.preview-panel img')).toHaveCount(0)
    await expect(
      page.getByText('PROVIDER_UNAVAILABLE', { exact: false }),
    ).toBeVisible()
    writeFileSync(join(process.env.T09_SYNC_DIR!, 'failure-viewed.json'), '{}')
  }
})
