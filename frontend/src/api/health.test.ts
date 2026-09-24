import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { after, before, test } from 'node:test'
import { fetchBusinessHealth } from './health.ts'

let origin: string
const expected = {
  status: 'UP',
  service: 'business-service',
  api_version: 'v1',
}
const server = createServer((request, response) => {
  response.setHeader('Content-Type', 'application/json')
  if (request.url === '/unavailable') {
    response.writeHead(503).end(JSON.stringify({ message: 'unavailable' }))
  } else if (request.url === '/wrong-service') {
    response.end(JSON.stringify({ ...expected, service: 'image-service' }))
  } else if (request.url === '/invalid-json') {
    response.end('not json')
  } else {
    response.end(JSON.stringify(expected))
  }
})

before(async () => {
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const address = server.address()
  assert.ok(address && typeof address !== 'string')
  origin = `http://127.0.0.1:${address.port}`
})

after(async () => {
  server.closeAllConnections()
  await new Promise<void>((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()))
  })
})

test('accepts the Java v1 health contract over HTTP', async () => {
  assert.deepEqual(await fetchBusinessHealth(`${origin}/health`), expected)
})

test('rejects non-success HTTP status', async () => {
  await assert.rejects(fetchBusinessHealth(`${origin}/unavailable`), /HTTP 503/)
})

test('rejects a response from a different service', async () => {
  await assert.rejects(
    fetchBusinessHealth(`${origin}/wrong-service`),
    /响应格式/,
  )
})

test('rejects invalid JSON', async () => {
  await assert.rejects(
    fetchBusinessHealth(`${origin}/invalid-json`),
    SyntaxError,
  )
})
