import test from 'node:test'
import assert from 'node:assert/strict'
import {
  MAX_SCALE,
  MIN_SCALE,
  between,
  bounds,
  columnsFor,
  fitSide,
  fitView,
  grid,
  nearScreen,
  onScreen,
  overlaps,
  stackRows,
  toWorld,
  turns,
  zoomAt,
} from './canvas.ts'

test('"show all" centres everything and never enlarges past 100%', () => {
  const rects = [
    { x: 0, y: 0, width: 400, height: 400 },
    { x: 464, y: 0, width: 200, height: 300 },
  ]
  assert.deepEqual(bounds(rects), { x: 0, y: 0, width: 664, height: 400 })
  // Plenty of room: 100%, centred.
  const roomy = fitView(rects, { width: 1000, height: 600 }, 32)
  assert.equal(roomy.scale, 1)
  assert.equal(roomy.x, 500 - 332)
  assert.equal(roomy.y, 300 - 200)
  // A narrow viewport shrinks to the width that is left after the padding.
  const narrow = fitView(rects, { width: 396, height: 600 }, 32)
  assert.equal(narrow.scale, 332 / 664)
  const box = onScreen(bounds(rects)!, narrow)
  assert.equal(box.x, 32)
  assert.equal(box.x + box.width, 396 - 32)
  // Nothing to show: the plain view.
  assert.deepEqual(fitView([], { width: 400, height: 400 }), {
    x: 0,
    y: 0,
    scale: 1,
  })
})

test('zooming keeps the point under the pointer in place, within the limits', () => {
  const view = { x: 40, y: -20, scale: 0.5 }
  const point = { x: 300, y: 200 }
  const world = {
    x: (point.x - view.x) / view.scale,
    y: (point.y - view.y) / view.scale,
  }
  const zoomed = zoomAt(view, 2, point)
  assert.equal(zoomed.scale, 1)
  assert.equal(world.x * zoomed.scale + zoomed.x, point.x)
  assert.equal(world.y * zoomed.scale + zoomed.y, point.y)
  assert.equal(zoomAt(view, 1000, point).scale, MAX_SCALE)
  assert.equal(zoomAt(view, 0.0001, point).scale, MIN_SCALE)
})

test('only pictures near the screen are loaded', () => {
  const view = { x: 0, y: 0, scale: 1 }
  const viewport = { width: 800, height: 600 }
  const near = { x: 900, y: 0, width: 100, height: 100 }
  const far = { x: 1300, y: 0, width: 100, height: 100 }
  assert.equal(nearScreen(near, view, viewport), true)
  assert.equal(nearScreen(far, view, viewport), false)
  // Zoomed out, the far one comes into range.
  assert.equal(nearScreen(far, { x: 0, y: 0, scale: 0.5 }, viewport), true)
})

test('results keep their proportions and form a compact grid', () => {
  assert.deepEqual(fitSide({ width: 750, height: 1000 }, 360), {
    width: 270,
    height: 360,
  })
  assert.deepEqual(fitSide({ width: 2048, height: 1152 }, 360), {
    width: 360,
    height: 203,
  })
  assert.deepEqual([1, 2, 3, 4, 5, 6].map(columnsFor), [1, 2, 2, 2, 3, 3])
  const placed = grid(
    [
      { key: 'a', size: { width: 100, height: 100 } },
      { key: 'b', size: { width: 100, height: 140 } },
      { key: 'c', size: { width: 100, height: 100 } },
    ],
    2,
    500,
    40,
    20,
  )
  assert.deepEqual(
    placed.map((item) => [item.key, item.rect.x, item.rect.y]),
    [
      ['a', 500, 40],
      ['b', 620, 40],
      ['c', 500, 200], // below the taller picture of the first row
    ],
  )
})

test('conversation rows go top to bottom, pictures side by side', () => {
  const placed = turns(
    [
      {
        key: 't1',
        label: { key: 'l1', height: 30 },
        items: [
          { key: 'a', size: { width: 200, height: 200 } },
          { key: 'b', size: { width: 200, height: 100 } },
        ],
      },
      { key: 't2', label: { key: 'l2', height: 30 }, items: [] },
      {
        key: 't3',
        label: { key: 'l3', height: 30 },
        items: [{ key: 'c', size: { width: 150, height: 200 } }],
      },
    ],
    300,
    16,
    40,
  )
  const at = Object.fromEntries(placed.map((item) => [item.key, item.rect]))
  // The label line is as wide as its pictures (at least the minimum).
  assert.deepEqual(at.l1, { x: 0, y: 0, width: 416, height: 30 })
  assert.equal(at.l2!.width, 300)
  assert.deepEqual([at.a!.x, at.a!.y, at.b!.x, at.b!.y], [0, 38, 216, 38])
  // A row without pictures (failed or waiting) only takes its label line.
  assert.equal(at.l2!.y, 38 + 200 + 40)
  assert.equal(at.l3!.y, at.l2!.y + 30 + 40)
  assert.equal(at.c!.y, at.l3!.y + 38)
})

test('a box drawn either way selects what it touches, in world units', () => {
  const box = between({ x: 300, y: 200 }, { x: 100, y: 50 })
  assert.deepEqual(box, { x: 100, y: 50, width: 200, height: 150 })
  // Zoomed to 50% and panned: the same screen box covers twice the world.
  const world = toWorld(box, { x: 20, y: -10, scale: 0.5 })
  assert.deepEqual(world, { x: 160, y: 120, width: 400, height: 300 })
  assert.equal(
    overlaps(world, { x: 550, y: 400, width: 100, height: 100 }),
    true,
  )
  assert.equal(
    overlaps(world, { x: 560, y: 120, width: 100, height: 100 }),
    false,
  )
  // Touching edges do not count.
  assert.equal(overlaps(world, { x: 0, y: 0, width: 160, height: 120 }), false)
})

test('new rows stack below, each with room for its captions', () => {
  const placed = stackRows(
    [
      {
        key: 't1',
        items: [
          { key: 'a', size: { width: 200, height: 200 } },
          { key: 'b', size: { width: 100, height: 300 } },
        ],
      },
      { key: 't2', items: [] },
      { key: 't3', items: [{ key: 'c', size: { width: 120, height: 120 } }] },
    ],
    -40,
    500,
    20,
    48,
    28,
  )
  const at = Object.fromEntries(placed.map((item) => [item.key, item.rect]))
  assert.deepEqual(Object.keys(at), ['a', 'b', 'c'])
  assert.deepEqual([at.a!.x, at.a!.y, at.b!.x], [-40, 528, 180])
  assert.equal(at.c!.y, 528 + 300 + 48 + 28)
})
