import test from 'node:test'
import assert from 'node:assert/strict'
import { buildRequest, newDraft } from './model.ts'

test('real scene is versioned, defaults to three, and rejects fractional count', () => {
  const draft = newDraft()
  Object.assign(draft, {
    product: 'product',
    scene: 'empty table',
    preset: 'old',
  })
  const request = buildRequest('SCENE', 'project', draft, true)
  assert.equal(request.output_preset_id, undefined)
  assert.deepEqual(request.output, {
    aspect_ratio: '1:1',
    width: 1024,
    height: 1024,
    format: 'png',
    count: 3,
  })
  assert.equal(buildRequest('SCENE', 'project', draft).output_preset_id, 'old')
  draft.sceneOutput.count = 1.5
  assert.throws(() => buildRequest('SCENE', 'project', draft, true))
})
