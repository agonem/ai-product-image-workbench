import { test, expect, type Page } from '@playwright/test'
import { createHash } from 'node:crypto'
import { existsSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const password = process.env.T06_PASSWORD!
// New passwords are limited to 6-15 characters.
const changed = password.slice(0, 10) + '-c2'
async function login(page: Page, username: string, secret = password) {
  // Each login starts from an empty cookie jar, like a fresh browser.
  await page.context().clearCookies()
  await page.goto('/')
  await page.getByLabel('本地账号', { exact: true }).fill(username)
  await page.getByLabel('密码', { exact: true }).fill(secret)
  const response = page.waitForResponse((r) =>
    r.url().endsWith('/api/v1/local-auth/login'),
  )
  await page.getByRole('button', { name: '登录生产账号', exact: true }).click()
  return (await (await response).json()).access_token as string
}

async function settings(page: Page) {
  await page.getByRole('link', { name: '账号与安全', exact: true }).click()
  await expect(
    page.getByRole('button', { name: '本人改密', exact: true }),
  ).toBeVisible()
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

async function synchronize(phase: 'expire' | 'seed', payload: object) {
  const directory = process.env.T06_SYNC_DIR!
  const temporary = join(directory, `${phase}.request.tmp`)
  writeFileSync(temporary, JSON.stringify(payload), { flag: 'wx' })
  renameSync(temporary, join(directory, `${phase}.request.json`))
  const done = join(directory, `${phase}.done.json`)
  await expect.poll(() => existsSync(done), { timeout: 20000 }).toBe(true)
  return JSON.parse(readFileSync(done, 'utf8'))
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
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible()
  for (const name of ['赠品+文字主图', '场景主图', '卖点主图'])
    await expect(
      page.getByRole('button', { name: `${name} 立即生成` }),
    ).toBeVisible()
  expect(
    await page.evaluate(() => localStorage.length + sessionStorage.length),
  ).toBe(0)
  await settings(page)
  await expect(
    page.getByRole('button', { name: '账号管理', exact: true }),
  ).toHaveCount(0)
  await expect(page.getByTestId('provider-state')).toHaveCount(0)
  await page.getByRole('button', { name: '本人改密', exact: true }).click()
  await page.getByLabel('当前密码', { exact: true }).fill(password)
  await page.getByLabel('新密码', { exact: true }).fill(changed)
  await page.getByRole('button', { name: '保存新密码' }).click()
  await expect(
    page.getByRole('heading', { name: '生产账号登录' }),
  ).toBeVisible()
  await expect(
    second.getByRole('heading', { name: '生产账号登录' }),
  ).toBeVisible({ timeout: 15000 })
  expect(await apiStatus(page, original, '/local-auth/me')).toBe(401)
  expect(await apiStatus(second, secondToken, '/local-auth/me')).toBe(401)
  await login(page, 'alice', changed)
  const resetToken = await login(second, 'alice', changed)

  const admin = await browser.newPage()
  const adminToken = await login(admin, 'admin')
  for (const path of [
    `/projects/${process.env.T06_PROJECT}/assets`,
    `/projects/${process.env.T06_PROJECT}/tasks`,
    `/assets/${process.env.T06_ASSET}/content`,
  ])
    expect(await apiStatus(admin, adminToken, path)).toBe(404)
  await settings(admin)
  await admin.getByRole('button', { name: '账号管理', exact: true }).click()
  await expect(
    admin.getByRole('heading', { name: '账号管理', exact: true }),
  ).toBeVisible()
  const alice = admin.getByTestId('account-row').filter({ hasText: 'alice' })
  await alice.getByRole('button', { name: '重置密码' }).click()
  await admin.getByLabel('重置后的密码').fill(password)
  await admin.getByRole('button', { name: '确认重置' }).click()
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

  const expiryToken = await login(page, 'alice')
  expect(await apiStatus(page, expiryToken, '/local-auth/me')).toBe(200)
  expect(await apiStatus(admin, adminToken, '/local-auth/me')).toBe(200)
  const hashes = [expiryToken, adminToken].map((token) =>
    createHash('sha256').update(token).digest('hex'),
  )
  expect(await synchronize('expire', { hashes })).toEqual({
    verified_hashes: hashes,
    expired_count: 2,
  })
  expect(await apiStatus(page, expiryToken, '/local-auth/me')).toBe(401)
  expect(await apiStatus(admin, adminToken, '/local-auth/me')).toBe(401)
  await expect(page.getByRole('heading', { name: '生产账号登录' })).toBeVisible(
    { timeout: 15000 },
  )
  await expect(
    admin.getByRole('heading', { name: '生产账号登录' }),
  ).toBeVisible({ timeout: 15000 })
  await login(page, 'alice')
  await page.getByRole('button', { name: '退出登录' }).click()
  await expect(
    page.getByRole('heading', { name: '生产账号登录' }),
  ).toBeVisible()
  await login(admin, 'admin')
  await settings(admin)
  await admin.getByRole('button', { name: '账号管理', exact: true }).click()
  await admin.screenshot({
    path: `${process.env.T06_ARTIFACTS}/accounts.png`,
    fullPage: true,
  })
  // Synthetic identities in the disposable schema exercise the second account page.
  expect(await synchronize('seed', {})).toEqual({ account_count: 104 })
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
  // Within its lifetime the session survives a reload; after sign-out it does not.
  await login(admin, 'admin')
  await admin.reload()
  await expect(admin.getByRole('button', { name: '退出登录' })).toBeVisible()
  await admin.getByRole('button', { name: '退出登录' }).click()
  await admin.reload()
  await expect(
    admin.getByRole('heading', { name: '生产账号登录' }),
  ).toBeVisible()
  await admin.close()
})
