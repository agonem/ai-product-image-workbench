import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { validateContract } from './validate.ts'

const cases = JSON.parse(
  readFileSync(
    new URL('../../../contracts/fixtures/cases.json', import.meta.url),
    'utf8',
  ),
) as { name: string; contract: string; valid: boolean; payload: unknown }[]
for (const fixture of cases) {
  test(fixture.name, () => {
    assert.equal(
      validateContract(fixture.contract, fixture.payload).length === 0,
      fixture.valid,
    )
  })
}

test('unknown contracts fail closed and errors omit input values', () => {
  assert.throws(
    () => validateContract('https://example.invalid/unregistered', {}),
    /Unknown contract/,
  )
  const errors = validateContract('task-create', {
    api_key: 'dummy-sensitive-value',
  })
  assert.ok(errors.length > 0)
  assert.ok(!JSON.stringify(errors).includes('dummy-sensitive-value'))
})
