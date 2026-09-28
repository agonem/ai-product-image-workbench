import { expect, test } from '@playwright/test'
import { join } from 'node:path'

test('admin manages provider configuration from the page', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/')
  await page.getByLabel('本地账号', { exact: true }).fill('admin')
  await page.getByLabel('密码', { exact: true }).fill(process.env.T06_PASSWORD!)
  await page.getByRole('button', { name: '登录生产账号' }).click()
  await expect(
    page.getByRole('heading', { name: '选择功能开始生成' }),
  ).toBeVisible()

  await page.getByRole('button', { name: '供应商配置' }).click()
  const state = page.getByTestId('provider-state')
  await expect(state).toContainText('已启用')
  const row = page
    .getByTestId('provider-version-row')
    .filter({ hasText: 'test/mock-model-b' })
    .first()
  await expect(row).toContainText('****')
  await expect(row).toContainText('当前版本')

  // The capability-check relay and the paid test generation were withdrawn from the page.
  await expect(page.getByTestId('provider-check')).toHaveCount(0)
  await expect(page.getByTestId('paid-dialog')).toHaveCount(0)
  await expect(page.getByText('付费', { exact: false })).toHaveCount(0)

  await page.getByRole('button', { name: '禁用当前版本' }).click()
  await expect(state).toContainText('已禁用')
  await page.getByRole('button', { name: '启用当前版本' }).click()
  await expect(state).toContainText('已启用')

  await page.screenshot({
    path: join(process.env.T06_ARTIFACTS!, 'admin-provider.png'),
    fullPage: true,
  })
})
