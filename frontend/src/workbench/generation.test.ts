import test from 'node:test'
import assert from 'node:assert/strict'
import {
  adoptText,
  buildGeneration,
  newDraft,
  placeText,
  presetBox,
  textSpec,
} from './generation.ts'
import { Submission } from './model.ts'

const ready = () => ({ ...newDraft(), product: 'product', gift: 'gift' })

test('V4: each entry sends only its own fields and defaults to one PNG image', () => {
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
  // No model chosen: the admin's default applies on the server.
  assert.equal('model_id' in scene, false)
  assert.equal('style_prompt' in scene, false)
})

test('ADR-20260929-C: a chosen model travels with the task', () => {
  const draft = ready()
  draft.model = 'model-2'
  assert.equal(buildGeneration('SCENE', 'p', draft).model_id, 'model-2')
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

test('text presets set box and alignment; size levels scale with the width', () => {
  const draft = ready()
  draft.title = '标题'
  placeText('GIFT', draft, 'TR')
  let text = textSpec(draft, 800)!
  assert.equal(text.align, 'right')
  assert.ok(Math.abs(text.box.x + text.box.width - 0.95) < 1e-9)
  assert.equal(text.size, 56)
  assert.equal(textSpec(draft, 1280)!.size, 90)
  draft.textLevel = 2
  assert.equal(textSpec(draft, 800)!.size, 72)
  placeText('SELLING_POINT', draft, 'TC')
  text = textSpec(draft, 800)!
  assert.equal(text.align, 'center')
  assert.deepEqual(text.box, presetBox('SELLING_POINT', 'TC'))
})

test('editing a result starts from what was rendered', () => {
  const draft = ready()
  adoptText(
    'GIFT',
    draft,
    {
      title: '旧标题',
      points: ['一', '二'],
      color: '#1E3A5F',
      size: 72,
      align: 'right',
      box: presetBox('GIFT', 'TR'),
    },
    800,
  )
  assert.equal(draft.points, '一\n二')
  assert.equal(draft.textLevel, 2)
  assert.equal(draft.textPosition, 'TR')
  adoptText(
    'GIFT',
    draft,
    {
      title: '拖过',
      color: '#1E3A5F',
      size: 44,
      align: 'left',
      box: { x: 0.2, y: 0.3, width: 0.4, height: 0.3 },
    },
    800,
  )
  assert.equal(draft.textPosition, '')
  assert.equal(draft.textLevel, 0)
  assert.equal(textSpec(draft, 800)!.box.x, 0.2)
})

test('V4: missing inputs and out-of-canvas text are explained before sending', () => {
  assert.throws(() => buildGeneration('SCENE', 'p', newDraft()), /商品图/)
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
