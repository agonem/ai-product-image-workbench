import test from 'node:test'
import assert from 'node:assert/strict'
import { buildGeneration, newDraft, textSpec } from './generation.ts'
import { Submission } from './model.ts'

const ready = () => ({ ...newDraft(), product: 'product', gift: 'gift' })

test('V4: each entry sends only its own fields and defaults to one image', () => {
  const gift = buildGeneration('GIFT', 'p', ready())
  const scene = buildGeneration('SCENE', 'p', ready())
  assert.equal(gift.gift_asset_id, 'gift')
  assert.equal(gift.gift_position, 'BOTTOM_RIGHT')
  assert.deepEqual(gift.background, { mode: 'SOLID', color: '#FFFFFF' })
  assert.equal('text' in gift, false)
  assert.equal('gift_asset_id' in scene, false)
  assert.equal(scene.scene_preset, 'nursery')
  assert.deepEqual(scene.output, {
    aspect_ratio: '1:1',
    width: 800,
    height: 800,
    format: 'png',
    count: 1,
  })
  assert.equal('styles' in scene, false)
})

test('V4: manual text is verbatim and selling points map one image per style', () => {
  const draft = ready()
  draft.title = ' 轻松喂养\n宝宝更舒适 '
  draft.points = ' 安全材质 \n\n防胀气设计'
  draft.styles = ['warm', 'green']
  const selling = buildGeneration('SELLING_POINT', 'p', draft)
  assert.deepEqual((selling.text as { points: string[] }).points, [
    ' 安全材质 ',
    '防胀气设计',
  ])
  assert.equal(
    (selling.text as { title: string }).title,
    ' 轻松喂养\n宝宝更舒适 ',
  )
  assert.equal((selling.output as { count: number }).count, 2)
  assert.deepEqual(selling.styles, ['warm', 'green'])
  draft.title = '   '
  assert.equal('title' in textSpec(draft)!, false)
})

test('V4: missing inputs and out-of-canvas text are explained before sending', () => {
  assert.throws(() => buildGeneration('SCENE', 'p', newDraft()), /商品白底图/)
  assert.throws(
    () => buildGeneration('GIFT', 'p', { ...ready(), gift: '' }),
    /赠品图/,
  )
  assert.throws(() => buildGeneration('SELLING_POINT', 'p', ready()), /卖点/)
  const custom = ready()
  custom.scenePreset = ''
  assert.throws(() => buildGeneration('SCENE', 'p', custom), /场景/)
  custom.scenePrompt = '浅色木桌'
  assert.equal(buildGeneration('SCENE', 'p', custom).scene_prompt, '浅色木桌')
  const text = ready()
  text.title = '标题'
  text.textBox = { x: 0.8, y: 0, width: 0.5, height: 0.2 }
  assert.throws(() => buildGeneration('GIFT', 'p', text), /画布范围/)
  const long = ready()
  long.points = '超'.repeat(21)
  assert.throws(() => buildGeneration('SELLING_POINT', 'p', long), /20 字/)
})

test('uncertain submission freezes payload, path and key until resolved', () => {
  const submission = new Submission()
  const first = submission.prepare('/v4/generation-tasks', { value: 'first' })
  assert.deepEqual(submission.prepare('/other', { value: 'changed' }), first)
  submission.resolve()
  assert.notEqual(
    submission.prepare('/v4/generation-tasks', { value: 'changed' }).key,
    first.key,
  )
})
