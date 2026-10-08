import test from 'node:test'
import assert from 'node:assert/strict'
import {
  adoptText,
  buildGeneration,
  callsNoModel,
  giftCardBox,
  sellingProductZone,
  zoneOverlap,
  newDraft,
  placeText,
  pointText,
  presetBox,
  textSpec,
  widestPoint,
} from './generation.ts'
import { Submission } from './model.ts'

const ready = () => ({ ...newDraft(), product: 'product', gift: 'gift' })

test('V4: each entry sends only its own fields and defaults to one PNG image', () => {
  // ADR-20261008-G: the gift page never sends text, even if a draft still holds some.
  const gift = buildGeneration('GIFT', 'p', {
    ...ready(),
    title: '下单即送',
    points: '软勺',
  })
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

test('ADR-20260930-E: the gift can keep the product photo background', () => {
  const draft = ready()
  draft.backgroundMode = 'ORIGINAL'
  assert.deepEqual(buildGeneration('GIFT', 'p', draft).background, {
    mode: 'ORIGINAL',
  })
})

test('ADR-20260929-C: a chosen model travels with the task', () => {
  const draft = ready()
  draft.model = 'model-2'
  assert.equal(buildGeneration('SCENE', 'p', draft).model_id, 'model-2')
})

test('ADR-20261008-G: one selling image per point in one style, text verbatim', () => {
  const draft = ready()
  draft.title = ' 轻松喂养\n宝宝更舒适 '
  draft.points = ' 安全材质 \n\n防胀气设计'
  draft.styles = ['green']
  draft.model = 'model-2'
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
  assert.equal(selling.style, 'green')
  assert.equal('styles' in selling, false)
  assert.equal(selling.model_id, 'model-2')
  draft.title = '   '
  assert.equal('title' in textSpec(draft)!, false)
})

test('ADR-20261008-G: keep original sends no style and no model', () => {
  const draft = ready()
  draft.points = '安全材质\n易清洗\n防胀气'
  draft.model = 'model-2'
  draft.keepOriginal = true
  const selling = buildGeneration('SELLING_POINT', 'p', draft)
  assert.equal(selling.keep_original, true)
  assert.equal('style' in selling, false)
  assert.equal('model_id' in selling, false)
  assert.equal((selling.output as { count: number }).count, 3)
  draft.keepOriginal = false
  draft.styles = []
  assert.throws(() => buildGeneration('SELLING_POINT', 'p', draft), /风格/)
})

test('ADR-20261008-G: each image shows the shared title and its own point', () => {
  const draft = ready()
  draft.title = '宝宝奶瓶'
  draft.points = 'Safe\n防胀气设计\n易清洗'
  const text = textSpec(draft, 800)
  assert.deepEqual(pointText(text, 1)!.points, ['防胀气设计'])
  assert.equal(pointText(text, 1)!.title, '宝宝奶瓶')
  assert.deepEqual(pointText(text, 9)!.points, ['易清洗'])
  assert.equal(widestPoint(['Safe', '防胀气设计', '易清洗']), 1)
  assert.equal(pointText(null, 0), null)
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
  text.points = '卖点'
  text.textBox = { x: 0.8, y: 0, width: 0.5, height: 0.2 }
  assert.throws(() => buildGeneration('SELLING_POINT', 'p', text), /画布范围/)
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

test('ADR-20261008-H: gift card request, no model on the original background', () => {
  const draft = ready()
  draft.model = 'model-2'
  draft.giftCard = true
  draft.giftLabel = ' 硅胶洗头刷 '
  let gift = buildGeneration('GIFT', 'p', draft)
  assert.deepEqual(gift.gift_card, { size: 'M', label: '硅胶洗头刷' })
  assert.equal(gift.model_id, 'model-2')
  draft.backgroundMode = 'ORIGINAL'
  gift = buildGeneration('GIFT', 'p', draft)
  assert.equal('model_id' in gift, false)
  assert.equal(callsNoModel('GIFT', draft), true)
  draft.giftLabel = ''
  assert.deepEqual(buildGeneration('GIFT', 'p', draft).gift_card, { size: 'M' })
  draft.giftCard = false
  assert.equal('gift_card' in buildGeneration('GIFT', 'p', draft), false)
  assert.equal(callsNoModel('GIFT', draft), false)
})

test('ADR-20261008-H: the card geometry matches the Worker', () => {
  // Same numbers as image_service.giftcard.geometry for 800 x 800.
  assert.deepEqual(giftCardBox('M', true, 800, 800, 'BOTTOM_RIGHT'), {
    x: 544,
    y: 539,
    width: 224,
    height: 229,
    pad: 18,
    top: 27,
    imageHeight: 139,
    labelHeight: 45,
    badge: 22,
    corner: 27,
  })
  const left = giftCardBox('S', true, 800, 800, 'LEFT')
  assert.equal(left.x, 32)
  assert.equal(left.y, 310)
})

test('ADR-20261008-H: product position travels only with an AI style', () => {
  const draft = ready()
  draft.points = '安全材质'
  assert.equal(
    'product_position' in buildGeneration('SELLING_POINT', 'p', draft),
    false,
  )
  draft.productPosition = 'LEFT'
  assert.equal(
    buildGeneration('SELLING_POINT', 'p', draft).product_position,
    'LEFT',
  )
  draft.keepOriginal = true
  assert.equal(
    'product_position' in buildGeneration('SELLING_POINT', 'p', draft),
    false,
  )
  // Left text box over a left product: mostly covered.
  const zone = sellingProductZone('LEFT', 'left')
  assert.ok(zoneOverlap(zone, presetBox('SELLING_POINT', 'TL')) > 0.25)
  assert.equal(zoneOverlap(zone, presetBox('SELLING_POINT', 'TR')), 0)
})
