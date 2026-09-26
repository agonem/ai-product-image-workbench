import { test, expect, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'

const password = process.env.T06_PASSWORD!
async function login(page: Page, username: string, secret = password) {
  await page.goto('/')
  await page.getByLabel('本地账号', { exact: true }).fill(username)
  await page.getByLabel('密码', { exact: true }).fill(secret)
  const response = page.waitForResponse((r) =>
    r.url().endsWith('/api/v1/local-auth/login'),
  )
  await page.getByRole('button', { name: '登录生产账号', exact: true }).click()
  return (await (await response).json()).access_token as string
}

async function apiStatus(page: Page, token: string, path: string) {
  return page.evaluate(
    async ({ token, path }) =>
      (
        await fetch('/api/v1' + path, {
          headers: { Authorization: 'Bearer ' + token },
        })
      ).status,
    { token, path },
  )
}

function sql(statement: string) {
  const command = JSON.parse(process.env.T06_PSQL!) as string[]
  execFileSync(
    command[0]!,
    [
      ...command.slice(1),
      '-c',
      `SET search_path TO ${process.env.T06_SCHEMA}; ${statement}`,
    ],
    {
      env: { ...process.env, PGPASSWORD: process.env.DB_TEST_PASSWORD },
      stdio: 'pipe',
    },
  )
}

test('B1–B5 production authentication, revocation and permission boundaries', async ({
  page,
  browser,
}) => {
  await login(page, 'alice', 'incorrect-password')
  await expect(page.getByRole('alert')).toContainText('密码')
  const original = await login(page, 'alice')
  expect(await apiStatus(page, original, '/admin/accounts')).toBe(403)
  const second = await browser.newPage()
  const secondToken = await login(second, 'alice')
  await expect(page.getByRole('button', { name: '退出本地账号' })).toBeVisible()
  await expect(
    page.getByRole('button', { name: '账号管理', exact: true }),
  ).toHaveCount(0)
  for (const name of ['赠品图', '场景图', '卖点图'])
    await expect(
      page.getByRole('button', { name: new RegExp(name) }).first(),
    ).toBeVisible()
  await expect(page.getByLabel('能力边界')).toContainText(
    '真实图片生成尚未开放',
  )
  expect(
    await page.evaluate(() => localStorage.length + sessionStorage.length),
  ).toBe(0)
  await page.getByRole('button', { name: '本人改密', exact: true }).click()
  await page.getByLabel('当前密码', { exact: true }).fill(password)
  await page.getByLabel('新密码', { exact: true }).fill(password + '-changed')
  await page.getByRole('button', { name: '保存新密码' }).click()
  await expect(
    page.getByRole('heading', { name: '生产账号登录' }),
  ).toBeVisible()
  await expect(
    second.getByRole('heading', { name: '生产账号登录' }),
  ).toBeVisible({ timeout: 15000 })
  expect(await apiStatus(page, original, '/local-auth/me')).toBe(401)
  expect(await apiStatus(second, secondToken, '/local-auth/me')).toBe(401)
  await login(page, 'alice', password + '-changed')
  const resetToken = await login(second, 'alice', password + '-changed')

  const admin = await browser.newPage()
  const adminToken = await login(admin, 'admin')
  for (const path of [
    `/projects/${process.env.T06_PROJECT}/assets`,
    `/projects/${process.env.T06_PROJECT}/tasks`,
    `/assets/${process.env.T06_ASSET}/content`,
  ])
    expect(await apiStatus(admin, adminToken, path)).toBe(404)
  await expect(
    admin.getByRole('option', { name: 'Alice private', exact: true }),
  ).toHaveCount(0)
  await admin.getByRole('button', { name: '账号管理', exact: true }).click()
  await expect(
    admin.getByRole('heading', { name: '账号管理', exact: true }),
  ).toBeVisible()
  const alice = admin.getByTestId('account-row').filter({ hasText: 'alice' })
  await alice.getByRole('button', { name: '重置密码' }).click()
  await admin.getByLabel('重置后的密码').fill(password)
  await admin.getByRole('button', { name: '确认重置' }).click()
  await page.getByRole('button', { name: '本人改密', exact: true }).click()
  await expect(page.getByRole('heading', { name: '生产账号登录' })).toBeVisible(
    { timeout: 15000 },
  )
  await expect(
    second.getByRole('heading', { name: '生产账号登录' }),
  ).toBeVisible({ timeout: 15000 })
  expect(await apiStatus(second, resetToken, '/local-auth/me')).toBe(401)
  await second.close()

  await admin.getByLabel('新账号名称').fill('created')
  await admin.getByLabel('初始密码').fill(password)
  await admin.getByRole('button', { name: '创建账号', exact: true }).click()
  const created = admin
    .getByTestId('account-row')
    .filter({ hasText: 'created' })
  await expect(created).toBeVisible()
  await created.getByRole('button', { name: '停用', exact: true }).click()
  await expect(created).toContainText('DISABLED')
  await login(page, 'created')
  await expect(page.getByRole('alert')).toBeVisible()
  await created.getByRole('button', { name: '启用', exact: true }).click()
  await expect(created).toContainText('ACTIVE')
  await admin
    .getByTestId('account-row')
    .filter({ hasText: 'admin' })
    .getByRole('button', { name: '停用', exact: true })
    .click()
  await expect(admin.getByRole('alert')).toContainText('管理员')

  await login(page, 'alice')
  sql("UPDATE local_sessions SET expires_at=now()-interval '1 second'")
  await expect(page.getByRole('heading', { name: '生产账号登录' })).toBeVisible(
    { timeout: 15000 },
  )
  await expect(
    admin.getByRole('heading', { name: '生产账号登录' }),
  ).toBeVisible({ timeout: 15000 })
  await login(page, 'alice')
  await page.getByRole('button', { name: '退出本地账号' }).click()
  await expect(
    page.getByRole('heading', { name: '生产账号登录' }),
  ).toBeVisible()
  await login(admin, 'admin')
  await admin.getByRole('button', { name: '账号管理', exact: true }).click()
  await admin.screenshot({
    path: `${process.env.T06_ARTIFACTS}/accounts.png`,
    fullPage: true,
  })
  // Synthetic identities in the disposable schema exercise the second account page.
  sql(
    "INSERT INTO users(id,status) SELECT 'zz_page_'||n,'ACTIVE' FROM generate_series(1,101) n; INSERT INTO local_credentials(user_id,username,salt,password_hash,role) SELECT 'zz_page_'||n,'page_'||n,c.salt,c.password_hash,'USER' FROM generate_series(1,101) n CROSS JOIN local_credentials c WHERE c.username='alice'",
  )
  await admin.getByRole('button', { name: '账号管理', exact: true }).click()
  await expect(admin.getByTestId('account-row')).toHaveCount(100)
  await admin.getByRole('button', { name: '加载更多账号' }).click()
  await expect(admin.getByTestId('account-row')).toHaveCount(104)
  await expect(admin.getByRole('button', { name: '加载更多账号' })).toHaveCount(
    0,
  )
  await admin
    .getByTestId('account-row')
    .filter({ hasText: 'admin' })
    .getByRole('button', { name: '重置密码' })
    .click()
  await admin.getByLabel('重置后的密码').fill(password)
  await admin.getByRole('button', { name: '确认重置' }).click()
  await expect(
    admin.getByRole('heading', { name: '生产账号登录' }),
  ).toBeVisible()
  await login(admin, 'admin')
  await admin.reload()
  await expect(
    admin.getByRole('heading', { name: '生产账号登录' }),
  ).toBeVisible()
  await admin.close()
})
