import test from 'node:test'
import assert from 'node:assert/strict'
import { ApiError, checkedTask, json, request } from './workbench.ts'

test('ACC-T06 A2/A4: API uses Java prefix, same-origin session cookie, no cache', async (t) => {
  t.mock.method(
    globalThis,
    'fetch',
    async (path: string, init: RequestInit) => {
      assert.equal(path, '/api/v4/generation-tasks')
      assert.equal(init.credentials, 'same-origin')
      assert.equal(init.cache, 'no-store')
      assert.equal(new Headers(init.headers).get('Authorization'), null)
      assert.equal(new Headers(init.headers).get('Idempotency-Key'), 'same-key')
      assert.deepEqual(JSON.parse(String(init.body)), { feature_type: 'SCENE' })
      return Response.json({ id: 'task' })
    },
  )
  assert.deepEqual(
    await request('/v4/generation-tasks', {
      ...json({ feature_type: 'SCENE' }),
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': 'same-key',
      },
    }),
    { id: 'task' },
  )
})

test('ACC-T06 A2/A5: failures preserve HTTP meaning without exposing raw server data', async (t) => {
  for (const status of [401, 404, 413, 415, 429, 500]) {
    const mock = t.mock.method(globalThis, 'fetch', async () =>
      Response.json({ message: 'private-secret', code: 'UNKNOWN' }, { status }),
    )
    await assert.rejects(
      request('/projects'),
      (error: unknown) =>
        error instanceof ApiError &&
        error.status === status &&
        !error.message.includes('private-secret'),
    )
    mock.mock.restore()
  }
})

test('ACC-T06 A4: network failure and invalid task response remain ambiguous', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => {
    throw new TypeError('network')
  })
  await assert.rejects(
    request('/tasks'),
    (error: unknown) => error instanceof ApiError && error.status === 0,
  )
  assert.throws(() => checkedTask({ id: 'bad' } as never), ApiError)
})
