import { expect, test } from '@playwright/test'
import { join } from 'node:path'

const artifacts = process.env.T06_ARTIFACTS!

test('N0-B1: upload, generate a cutout candidate, review side by side and confirm', async ({
  page,
}) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/')
  await page.getByLabel('本地账号', { exact: true }).fill('alice')
  await page.getByLabel('密码', { exact: true }).fill(process.env.T06_PASSWORD!)
  await page.getByRole('button', { name: '登录生产账号' }).click()
  await expect(page.getByText('正在读取项目素材与任务…')).toHaveCount(0)

  await page
    .getByLabel('上传商品图')
    .setInputFiles(process.env.CORE_PRODUCT_FILE!)
  await expect(page.getByRole('status').first()).toContainText('原图已保存')
  const panel = page.getByRole('region', { name: '商品抠图确认' })
  const status = panel.getByTestId('cutout-status')
  await expect(status).toHaveText('未抠图：需生成抠图并由你确认后才能用于生成')
  await expect(page.locator('#submit-reason')).toContainText('商品抠图尚未确认')

  await panel.getByRole('button', { name: '生成抠图候选' }).click()
  await expect(status).toHaveText('抠图候选待你确认')
  const compare = panel.getByTestId('cutout-compare')
  await expect(compare.getByAltText('商品原图')).toBeVisible()
  await expect(compare.getByAltText('商品抠图蒙版')).toBeVisible()
  await expect(compare.getByAltText('商品透明预览')).toBeVisible()
  await panel.screenshot({ path: join(artifacts, 'cutout-review.png') })

  await panel.getByRole('button', { name: '确认边缘可用' }).click()
  await expect(status).toHaveText('已确认：生成时使用这份抠图')
  await expect(
    page
      .getByRole('combobox', { name: '商品原图', exact: true })
      .locator('option:checked'),
  ).toContainText('抠图已确认')
  await expect(page.locator('#submit-reason')).not.toContainText(
    '商品抠图尚未确认',
  )
  await page.screenshot({
    path: join(artifacts, 'cutout-confirmed-desktop.png'),
    fullPage: true,
  })

  await page.setViewportSize({ width: 390, height: 844 })
  await panel.getByRole('button', { name: '重新生成抠图候选' }).click()
  await expect(status).toHaveText('抠图候选待你确认')
  await expect(compare.getByAltText('商品透明预览')).toBeVisible()
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true)
  await panel.screenshot({ path: join(artifacts, 'cutout-review-mobile.png') })
  await panel.getByRole('button', { name: '不可用' }).click()
  await expect(status).toHaveText('最新候选已拒绝；生成仍使用此前已确认的抠图')
  expect(errors).toEqual([])
})
