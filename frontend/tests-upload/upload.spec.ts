import { expect, test, type Locator, type Page } from '@playwright/test'
import type { Asset, AssetKind } from '../src/workbench/model'

const png = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAB9klEQVR4nO3aT0iTcRwG8GfP3g6SZbfQxppu7d2cYhmBf4JgGoPKJNbBLgpCIXgXPChUt24dAjEIFPHiisAaoRhE1KFLl0oDPRixQErSckZsQ+SFEQ5qqPvzsD6nL+/7/b28D98fvLy8r+3j199QRogjxBHiCHGEOEIcIY4QR4gzsmm62D+EQnh67/Y/e0pjApae3hvIl7EHo1l2yk+AEEeII8QR4ghxhDhCHCGOEEeII8QR4ghxhDhCHFE6b2SZlhbev33zGkDs03KV8ziAhjPNM4+njh5zWA01Xn9j09mVL7FXz5+lkimS7ZfDK7HPmatO+OuQ/wBuX8DtCwAYuXPravd16+Dc9KN0bZmdftjZ1V1+uGJx/t3L2eiF8LXMVbu2pwBZ2tz4mUgktgdi+ssOlu/vxQ3kXkswNDU2Wu3x+upPOVw1xR4gmUxGxu9bdWswVOlw1jY0uk3/0sKHFzNP3Gag6VxbUQew2+1/7uzN+Mb31W/bMU6ervb6Jkbu7m8AIveikckf62sAfsXjhyqOKG2hSoezNRhqu3QlGpk0jAM22s53hIsxQN/AcLruH7y546zLY7o85t9Xle6TmBBHiCPEEeIIcYQ4QhwhjhBHiCPEEeKMXHy7zSdCnO3/X4sFRogjxBHiCHGEOEIcIY6FvoG92gJVgHeIFsmS3wAAAABJRU5ErkJggg==',
  'base64',
)
async function setup(page: Page) {
  const assets: Asset[] = (['PRODUCT', 'GIFT', 'REFERENCE'] as AssetKind[]).map(
    (kind, index) => ({
      id: `original-${index}`,
      project_id: 'project-ui',
      kind,
      width: 100 + index,
      height: 100 + index,
      review_status: 'PENDING',
    }),
  )
  const state = {
    assets,
    uploads: [] as string[],
    deletes: [] as string[],
    tasks: [] as Record<string, unknown>[],
    taskKeys: [] as string[],
    errors: [] as string[],
    failUpload: 0,
    taskStatus: 422,
    pageSize: 20,
    hold: null as Promise<void> | null,
  }
  page.on('pageerror', (error) => state.errors.push(error.message))
  page.on('console', (message) => {
    if (
      message.type() === 'error' &&
      !message.text().includes('Failed to load resource')
    )
      state.errors.push(message.text())
  })
  await page.route('**/api/**', async (route) => {
    const req = route.request(),
      url = new URL(req.url()),
      path = url.pathname
    if (!path.startsWith('/api/')) return route.fallback()
    const respond = (json: unknown, status = 200) =>
      route.fulfill({ json, status })
    if (req.method() === 'DELETE') state.deletes.push(path)
    if (path.endsWith('/local-auth/me'))
      return respond({
        id: 'user-ui',
        username: '上传交互测试',
        role: 'USER',
        mode: 'production-local',
        expires_at: new Date(Date.now() + 3600000).toISOString(),
      })
    if (path === '/api/v1/projects')
      return respond([{ id: 'project-ui', name: 'UI测试' }])
    if (path.endsWith('/workbench/options'))
      return respond({
        mode: 'production-local',
        generation_available: false,
        generation: {
          enabled: true,
          max_count: 4,
          max_side: 2048,
          max_pixels: 4194304,
          presets_version: 'ui',
          aspect_ratios: ['1:1'],
          formats: ['png'],
          scene_presets: [{ id: 'warm', name: '暖色房间' }],
          styles: [],
        },
        models: [
          {
            id: 'model-ui',
            name: '模拟模型',
            provider: 'openrouter',
            model: 'mock',
            default: true,
          },
        ],
      })
    if (path.endsWith('/assets') && req.method() === 'POST') {
      state.uploads.push(url.searchParams.get('kind')!)
      const ordinal = state.uploads.length
      if (state.hold) await state.hold
      if (state.failUpload === ordinal)
        return respond({ code: 'INVALID_ASSET' }, 422)
      expect(req.headers()['content-type']).toBe('image/png')
      expect(req.postDataBuffer()?.subarray(0, 8)).toEqual(png.subarray(0, 8))
      const asset: Asset = {
        id: `upload-${ordinal}`,
        project_id: 'project-ui',
        kind: url.searchParams.get('kind') as AssetKind,
        width: 64,
        height: 64,
        review_status: 'PENDING',
      }
      assets.unshift(asset)
      return respond(asset, 201)
    }
    if (path.endsWith('/assets')) {
      const offset = Number(url.searchParams.get('offset') ?? 0)
      return respond({
        items: assets.slice(offset, offset + state.pageSize),
        next_offset:
          offset + state.pageSize < assets.length
            ? offset + state.pageSize
            : null,
      })
    }
    if (path.endsWith('/tasks'))
      return respond({ items: [], next_offset: null })
    if (path.endsWith('/content'))
      return route.fulfill({ contentType: 'image/png', body: png })
    if (path.endsWith('/agents'))
      return respond({ items: [], text_model: false, admin: false })
    if (path.endsWith('/conversations'))
      return respond(
        req.method() === 'POST'
          ? { id: 'conversation-ui', title: 'UI测试' }
          : { items: [] },
      )
    if (path.endsWith('/canvas')) return respond({ version: 0, layout: null })
    if (path.endsWith('/generation-tasks')) {
      state.tasks.push(req.postDataJSON())
      state.taskKeys.push(req.headers()['idempotency-key']!)
      // Deliberate rejection: only inspect the outgoing request, never run a model.
      return respond({ code: 'MODEL_UNAVAILABLE' }, state.taskStatus)
    }
    state.errors.push(`Unexpected API: ${req.method()} ${path}`)
    return respond({ code: 'NOT_FOUND' }, 404)
  })
  return state
}

async function drop(page: Page, target: Locator, count = 1, invalid = false) {
  const transfer = await page.evaluateHandle(
    ({ count, invalid, bytes }) => {
      const data = new DataTransfer()
      for (let i = 0; i < count; i++)
        data.items.add(
          new File(
            [invalid ? 'not an image' : new Uint8Array(bytes)],
            `image-${i}.png`,
            { type: 'image/png' },
          ),
        )
      return data
    },
    { count, invalid, bytes: [...png] },
  )
  await target.dispatchEvent('dragenter', { dataTransfer: transfer })
  await target.dispatchEvent('dragover', { dataTransfer: transfer })
  await target.dispatchEvent('drop', { dataTransfer: transfer })
  await transfer.dispose()
}
const slot = (page: Page, label: string) =>
  page.getByRole('button', { name: new RegExp(`^${label}(（|$)`) })
async function pick(page: Page, label: string, size: number) {
  await slot(page, label).click()
  await page.getByRole('menuitem', { name: '从素材库选择' }).click()
  const picker = page.getByRole('dialog', { name: `选择${label}` })
  await expect(
    picker.getByRole('button', { name: '已上传的素材', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true')
  await expect(picker.getByRole('button', { name: /^选择/ })).toHaveCount(3)
  await picker
    .getByRole('button', { name: `选择${label} ${size}×${size}`, exact: true })
    .click()
}

test('AC-1/2: unified originals, cross-role selection and clear without deleting', async ({
  page,
}, info) => {
  const state = await setup(page)
  await page.goto('/#/assets')
  await expect(page).toHaveTitle(/工作台/)
  const kinds = page.getByRole('group', { name: '素材类型' })
  await expect(kinds.getByRole('button')).toHaveText(['已上传的素材', '作品图'])
  await expect(page.getByTestId('asset-card')).toHaveCount(3)
  await page.getByRole('link', { name: '赠品主图', exact: true }).click()
  await pick(page, '商品图', 102) // Historical REFERENCE fills product.
  await pick(page, '赠品图', 100) // Historical PRODUCT fills gift.
  await page.getByRole('button', { name: '清除商品图', exact: true }).click()
  await expect(slot(page, '商品图')).toHaveAttribute('aria-label', '商品图')
  await expect(slot(page, '赠品图')).toHaveAttribute('aria-label', /已选择/)
  await expect(page.getByRole('menu')).toHaveCount(0)
  await pick(page, '商品图', 102)
  await page.getByRole('button', { name: '清除赠品图', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(slot(page, '赠品图')).toHaveAttribute('aria-label', '赠品图')
  expect(state.assets).toHaveLength(3)
  expect(state.deletes).toEqual([])
  expect(state.tasks).toEqual([])
  expect(state.errors).toEqual([])
  await page.screenshot({ path: info.outputPath('gift-clear-desktop.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await page
    .getByRole('button', { name: '清除商品图' })
    .scrollIntoViewIfNeeded()
  await expect(page.getByRole('button', { name: '清除商品图' })).toBeVisible()
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true)
  await page.screenshot({ path: info.outputPath('gift-clear-mobile.png') })
  await page.getByRole('button', { name: '清除商品图' }).click()
  await expect(slot(page, '商品图')).toHaveAttribute('aria-label', '商品图')
})

test('AC-3: slot drop, single-file limit, busy guard and failures preserve selection', async ({
  page,
}) => {
  const state = await setup(page)
  await page.goto('/#/create/gift')
  await expect(slot(page, '商品图')).toBeVisible()
  await drop(page, slot(page, '商品图'))
  await expect(page.getByRole('button', { name: '清除商品图' })).toBeVisible()
  await drop(page, slot(page, '赠品图'))
  await expect(page.getByRole('button', { name: '清除赠品图' })).toBeVisible()
  expect(state.uploads).toEqual(['PRODUCT', 'GIFT'])
  await drop(page, slot(page, '商品图'), 2)
  await expect(page.getByRole('alert')).toContainText('一次只能上传一张')
  expect(state.uploads).toHaveLength(2)
  await drop(page, slot(page, '商品图'), 1, true)
  await expect(page.getByRole('alert')).toContainText('无法读取')
  expect(state.uploads).toHaveLength(2)
  state.failUpload = 3
  let release!: () => void
  state.hold = new Promise<void>((resolve) => {
    release = resolve
  })
  await drop(page, slot(page, '商品图'))
  await expect.poll(() => state.uploads.length).toBe(3)
  await expect(page.getByRole('button', { name: '清除商品图' })).toBeDisabled()
  await drop(page, slot(page, '商品图'))
  expect(state.uploads).toHaveLength(3)
  release()
  await expect(page.getByRole('alert')).toContainText('图片内容或尺寸')
  await expect(slot(page, '商品图')).toHaveAttribute('aria-label', /已选择/)
  await slot(page, '商品图').click()
  await page.getByRole('menuitem', { name: '从素材库选择' }).click()
  await expect(
    page
      .getByRole('dialog')
      .getByRole('button', { name: '选择商品图 64×64' })
      .filter({ has: page.locator('img') })
      .last(),
  ).toHaveAttribute('aria-pressed', 'true')
  expect(state.tasks).toEqual([])
  expect(state.errors).toEqual([])
})

test('AC-4/5/6: composer drop fills empty slots once, keeps names and request order', async ({
  page,
}, info) => {
  const state = await setup(page)
  await page.goto('/#/chat')
  await page
    .getByLabel('描述', { exact: true })
    .fill('把商品图放进参考图1的场景，参考图2仅作配色参考')
  let release!: () => void
  state.hold = new Promise<void>((resolve) => {
    release = resolve
  })
  await drop(page, page.getByLabel('描述', { exact: true }), 3)
  await expect.poll(() => state.uploads.length).toBe(1)
  await expect(page.getByTestId('chat-send')).toBeDisabled()
  release()
  state.hold = null
  await expect(page.getByRole('button', { name: '清除参考图2' })).toBeVisible()
  expect(state.uploads).toEqual(['PRODUCT', 'REFERENCE', 'REFERENCE'])
  await expect(page.getByTestId('image-names')).toContainText(
    '“商品图”、“参考图1”、“参考图2”',
  )
  await drop(page, page.getByLabel('描述', { exact: true }))
  await expect(page.getByRole('alert')).toContainText('空位')
  expect(state.uploads).toHaveLength(3)
  // Dropping on a nested slot replaces that slot exactly once, not the whole composer.
  await drop(page, slot(page, '参考图1'))
  await expect.poll(() => state.uploads.length).toBe(4)
  await expect(slot(page, '参考图1')).toBeEnabled()
  expect(state.tasks).toEqual([])
  await page.getByTestId('chat-send').click()
  await expect.poll(() => state.tasks.length).toBe(1)
  expect(state.tasks[0]).toMatchObject({
    product_asset_id: 'upload-1',
    reference_asset_ids: ['upload-4', 'upload-3'],
  })
  await expect(page.getByRole('alert')).toContainText('所选模型已停用')
  await page.getByRole('button', { name: '清除参考图1' }).click()
  await expect(page.getByRole('button', { name: '清除参考图2' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '清除参考图1' })).toBeVisible()
  await page.screenshot({ path: info.outputPath('chat-drop-desktop.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByLabel('描述', { exact: true }).scrollIntoViewIfNeeded()
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true)
  await page.screenshot({ path: info.outputPath('chat-drop-mobile.png') })
  await page.getByRole('button', { name: '清除商品图' }).click()
  await expect(page.getByTestId('chat-send')).toBeDisabled()
  expect(state.errors).toEqual([])
})

test('AC-4: a failed upload stops the queue and retains earlier successful files', async ({
  page,
}) => {
  const state = await setup(page)
  state.failUpload = 2
  await page.goto('/#/chat')
  await expect(page.getByLabel('描述', { exact: true })).toBeVisible()
  await drop(page, page.getByLabel('描述', { exact: true }), 3)
  await expect(page.getByRole('alert')).toContainText('图片内容或尺寸')
  expect(state.uploads).toHaveLength(2)
  await expect(page.getByRole('button', { name: '清除商品图' })).toBeVisible()
  await expect(page.getByRole('button', { name: '清除参考图1' })).toHaveCount(0)
  expect(state.tasks).toEqual([])
  expect(state.errors).toEqual([])
})

test('AC-2: unified pagination and the file chooser retain uploaded originals', async ({
  page,
}, info) => {
  const state = await setup(page)
  state.pageSize = 2
  await page.goto('/#/assets')
  await expect(page.getByTestId('asset-card')).toHaveCount(2)
  await page.getByRole('button', { name: '加载更多素材' }).click()
  await expect(page.getByTestId('asset-card')).toHaveCount(3)
  await page
    .getByLabel('上传素材', { exact: true })
    .setInputFiles({ name: 'photo.jpg', mimeType: 'image/jpeg', buffer: png })
  await expect(page.getByTestId('asset-card')).toHaveCount(4)
  expect(state.uploads).toEqual(['PRODUCT'])
  await expect(page.locator('.toasts')).toContainText('原图已保存')
  await page.getByRole('button', { name: '作品图', exact: true }).click()
  await expect(page.getByRole('link', { name: '打开我的作品' })).toBeVisible()
  await page.getByRole('button', { name: '已上传的素材', exact: true }).click()
  await expect(page.getByTestId('asset-card')).toHaveCount(4)
  await page.screenshot({ path: info.outputPath('materials-desktop.png') })
  expect(state.errors).toEqual([])
})

test('AC-4/5: excess batch is rejected before upload; uncertain submission is locked and resent unchanged', async ({
  page,
}) => {
  const state = await setup(page)
  await page.goto('/#/chat')
  await expect(slot(page, '商品图')).toBeVisible()
  await drop(page, page.getByLabel('描述', { exact: true }), 4)
  await expect(page.getByRole('alert')).toContainText('3 个图片空位')
  expect(state.uploads).toEqual([])
  await drop(page, slot(page, '商品图'))
  await expect(page.getByRole('button', { name: '清除商品图' })).toBeVisible()
  await page.getByLabel('描述', { exact: true }).fill('放在木桌上')
  state.taskStatus = 503
  await page.getByTestId('chat-send').click()
  await expect(page.getByTestId('chat-send')).toHaveText('重发')
  await expect(page.getByRole('button', { name: '清除商品图' })).toBeDisabled()
  await drop(page, page.getByLabel('描述', { exact: true }))
  expect(state.uploads).toHaveLength(1)
  await page.getByTestId('chat-send').click()
  await expect.poll(() => state.tasks.length).toBe(2)
  expect(state.tasks[1]).toEqual(state.tasks[0])
  expect(state.taskKeys[1]).toBe(state.taskKeys[0])
  expect(state.errors).toEqual([])
})

test('AC-3: changing entry during upload cannot select the file in another entry', async ({
  page,
}) => {
  const state = await setup(page)
  let release!: () => void
  state.hold = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.goto('/#/create/gift')
  await expect(slot(page, '商品图')).toBeVisible()
  await drop(page, slot(page, '商品图'))
  await expect.poll(() => state.uploads.length).toBe(1)
  await page.getByRole('link', { name: '场景主图', exact: true }).click()
  release()
  await expect(slot(page, '商品图')).toBeEnabled()
  await expect(slot(page, '商品图')).toHaveAttribute('aria-label', '商品图')
  await expect(page.getByRole('button', { name: '清除商品图' })).toHaveCount(0)
  expect(state.assets).toHaveLength(4)
  expect(state.errors).toEqual([])
})
