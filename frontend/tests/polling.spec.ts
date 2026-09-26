import { test, expect } from '@playwright/test'

test('ACC-T06 A2/A5: explicit UI fault injection checks RUNNING, polling recovery and expiry', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByLabel('本地账号').fill('alice')
  await page.getByLabel('密码', { exact: true }).fill(process.env.T06_PASSWORD!)
  await page.getByLabel('密码', { exact: true }).press('Enter')
  await expect(page.locator('.task-panel dd').first()).toBeVisible()
  const id = await page.locator('.task-panel dd').first().innerText()
  const url = `**/api/v1/tasks/${id}`
  let calls = 0
  // Only this isolated test changes a GET response to exercise short-lived UI states.
  // It does not write a successful task or change any persisted server state.
  await page.route(url, async (route) => {
    calls++
    if (calls === 1) {
      const response = await route.fetch()
      const task = await response.json()
      await route.fulfill({
        response,
        json: { ...task, status: 'RUNNING', artifacts: [], error: null },
      })
    } else if (calls === 2) await route.abort('failed')
    else await route.continue()
  })
  await page.getByRole('button', { name: '刷新状态', exact: true }).click()
  await expect(page.locator('.task-status')).toHaveText('执行中')
  await expect(page.getByRole('alert')).toContainText('连接中断或超时', {
    timeout: 10000,
  })
  await expect.poll(() => calls, { timeout: 10000 }).toBeGreaterThanOrEqual(3)
  await expect(page.locator('.task-status')).not.toHaveText('执行中')
  await page.unroute(url)
  await page.getByLabel('新项目名称').fill('private unsaved project')
  await page.route(
    url,
    (route) =>
      route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: '{"code":"UNAUTHORIZED"}',
      }),
    { times: 1 },
  )
  await page.getByRole('button', { name: '刷新状态', exact: true }).click()
  await expect(page.getByRole('button', { name: '登录开发环境' })).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('会话已过期')
  await expect(page.locator('.history-item')).toHaveCount(0)
  await page.getByLabel('密码', { exact: true }).fill(process.env.T06_PASSWORD!)
  await page.getByLabel('密码', { exact: true }).press('Enter')
  await expect(page.getByLabel('新项目名称')).toHaveValue('')
})
