import test from 'node:test'
import assert from 'node:assert/strict'
import { buildRequest, newDraft, Submission } from './model.ts'

test('ACC-T06 A1: independent entries never leak other feature fields', () => {
  const draft = newDraft()
  Object.assign(draft, {
    product: 'product',
    gift: 'gift',
    preset: 'preset',
    template: 'layout_v1',
    scene: '明亮房间',
    selling: '人工卖点\n第二条',
  })
  const gift = buildRequest('GIFT', 'p', draft)
  const scene = buildRequest('SCENE', 'p', draft)
  const selling = buildRequest('SELLING_POINT', 'p', draft)
  assert.equal(gift.gift_asset_id, 'gift')
  assert.equal('selling_points' in gift, false)
  assert.equal('gift_asset_id' in scene, false)
  assert.equal('template_version_id' in scene, false)
  assert.deepEqual(selling.selling_points, ['人工卖点', '第二条'])
  assert.equal('scene_custom_prompt' in selling, false)
})

test('ACC-T06 A1/A3: required fields and boxes are checked', () => {
  assert.throws(() => buildRequest('GIFT', 'p', newDraft()))
  const draft = {
    ...newDraft(),
    product: 'product',
    preset: 'preset',
    scene: '房间',
  }
  draft.productBox.x = 0.9
  assert.throws(() => buildRequest('SCENE', 'p', draft))
})

test('ACC-T06 A4: uncertain submission freezes payload and key until resolved', () => {
  const submission = new Submission()
  const first = submission.prepare({ value: 'first' })
  assert.deepEqual(submission.prepare({ value: 'changed' }), first)
  submission.resolve()
  assert.notEqual(submission.prepare({ value: 'changed' }).key, first.key)
})
