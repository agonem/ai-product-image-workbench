import test from 'node:test'
import assert from 'node:assert/strict'
import {
  CAPTION,
  COPY_SHIFT,
  EMPTY,
  GAP,
  ROW_GAP,
  complete,
  duplicate,
  moveItems,
  exportLayers,
  pendingCells,
  ratioOf,
  removeItems,
  reorder,
  resizeItem,
  restoreRemoved,
  tidy,
  updateItem,
  type Piece,
} from './chatCanvas.ts'

const square = { width: 360, height: 360 }
const picture = (ref: string, taskId: string, index = 0): Piece => ({
  ref,
  kind: 'artifact',
  taskId,
  index,
  size: square,
})
const card = (taskId: string): Piece => ({
  ref: taskId,
  kind: 'task',
  taskId,
  index: 0,
  size: { width: 240, height: 240 },
})

test('a canvas never arranged shows one row per message, oldest on top', () => {
  const pieces = [picture('a1', 't1'), picture('a2', 't1', 1), card('t2')]
  const { layout, changed } = complete(EMPTY, pieces)
  assert.equal(changed, true)
  const at = Object.fromEntries(layout.items.map((item) => [item.id, item]))
  assert.deepEqual(
    [at['a:a1']!.x, at['a:a1']!.y, at['a:a2']!.x],
    [0, CAPTION, 360 + GAP],
  )
  assert.equal(at['t:t2']!.task_id, 't2')
  assert.equal(at['t:t2']!.y, CAPTION + 360 + ROW_GAP + CAPTION)
  // Nothing new: unchanged.
  assert.equal(complete(layout, pieces).changed, false)
})

test('new results go below what the user arranged; a retried card hands over its place', () => {
  const arranged = {
    items: [
      {
        id: 'a:a1',
        artifact_id: 'a1',
        x: 500,
        y: -200,
        width: 360,
        height: 360,
      },
      { id: 't:t2', task_id: 't2', x: 40, y: 900, width: 240, height: 240 },
    ],
    removed: [],
  }
  // t2 was retried and finished; t3 is a new message.
  const pieces = [
    picture('a1', 't1'),
    picture('b1', 't2'),
    picture('b2', 't2', 1),
    picture('c1', 't3'),
  ]
  const { layout } = complete(arranged, pieces)
  const at = Object.fromEntries(layout.items.map((item) => [item.id, item]))
  assert.equal(at['t:t2'], undefined)
  assert.deepEqual([at['a:b1']!.x, at['a:b1']!.y], [40, 900])
  assert.deepEqual([at['a:b2']!.x, at['a:b2']!.y], [40 + 360 + GAP, 900])
  // Below everything (the lowest is b1/b2 ending at 1260), at the left edge (40).
  assert.deepEqual(
    [at['a:c1']!.x, at['a:c1']!.y],
    [40, 1260 + ROW_GAP + CAPTION],
  )
  // A deleted result just disappears.
  assert.equal(
    complete(layout, pieces.slice(1)).layout.items.some(
      (item) => item.id === 'a:a1',
    ),
    false,
  )
})

test('remove, put back, copy and move', () => {
  const pieces = [picture('a1', 't1'), picture('a2', 't1', 1)]
  const base = complete(EMPTY, pieces).layout
  // A copy, shifted; removing the original keeps the picture on the canvas through the copy.
  const copied = duplicate(base, ['a:a1', 't:none'], () => 'c:1')
  assert.deepEqual(copied.ids, ['c:1'])
  const copy = copied.layout.items.find((item) => item.id === 'c:1')!
  assert.deepEqual(
    [copy.x, copy.y, copy.artifact_id],
    [COPY_SHIFT, CAPTION + COPY_SHIFT, 'a1'],
  )
  let layout = removeItems(copied.layout, ['a:a1'])
  assert.deepEqual(layout.removed, [])
  layout = removeItems(layout, ['c:1', 'a:a2'])
  assert.deepEqual([...layout.removed].sort(), ['a1', 'a2'])
  assert.equal(layout.items.length, 0)
  // Removed pictures are not brought back by new results...
  assert.equal(complete(layout, pieces).layout.items.length, 0)
  // ...only by "put back".
  const back = restoreRemoved(layout, pieces)
  assert.deepEqual(
    back.items.map((item) => item.id),
    ['a:a1', 'a:a2'],
  )
  assert.deepEqual(back.removed, [])
  const moved = moveItems(back, ['a:a2'], 15, -5)
  assert.deepEqual(
    moved.items.map((item) => [item.x, item.y]),
    [
      [0, CAPTION],
      [360 + GAP + 15, CAPTION - 5],
    ],
  )
})

test('tidy puts every message back in its row, copies after their picture', () => {
  const pieces = [picture('a1', 't1'), card('t2'), picture('c1', 't3')]
  let layout = complete(EMPTY, pieces).layout
  layout = duplicate(layout, ['a:a1'], () => 'c:x').layout
  layout = moveItems(layout, ['a:a1', 't:t2', 'a:c1'], 777, 333)
  layout = removeItems(layout, ['a:c1'])
  const tidied = tidy(layout, pieces)
  const at = Object.fromEntries(tidied.items.map((item) => [item.id, item]))
  assert.deepEqual([at['a:a1']!.x, at['a:a1']!.y], [0, CAPTION])
  assert.deepEqual([at['c:x']!.x, at['c:x']!.y], [360 + GAP, CAPTION])
  assert.equal(at['t:t2']!.y, CAPTION + 360 + ROW_GAP + CAPTION)
  assert.equal(at['a:c1'], undefined)
  assert.deepEqual(tidied.removed, ['c1'])
})

test('placeholders sit below everything, or where the failed card was', () => {
  const layout = complete(EMPTY, [picture('a1', 't1'), card('t2')]).layout
  const cells = pendingCells(layout, [
    { taskId: 't2', count: 1, size: square },
    { taskId: 't3', count: 2, size: square },
  ])
  const at = Object.fromEntries(cells.map((cell) => [cell.key, cell.rect]))
  const failed = layout.items.find((item) => item.id === 't:t2')!
  assert.deepEqual([at['p:t2:0']!.x, at['p:t2:0']!.y], [failed.x, failed.y])
  assert.equal(at['p:t3:1']!.x, 360 + GAP)
  assert.equal(at['p:t3:0']!.y, failed.y + 240 + ROW_GAP + CAPTION)
})

test('the user own text, pictures and boards always stay; exports land beside their board', () => {
  const board = {
    id: 'f:1',
    frame: { width: 800, height: 800, background: '#FFFFFF' },
    x: 0,
    y: 0,
    width: 600,
    height: 600,
  }
  const words = {
    id: 'x:1',
    text: {
      content: '下单即送',
      size: 48,
      color: '#1D2129',
      align: 'left' as const,
    },
    x: 40,
    y: 40,
    width: 360,
    height: 120,
  }
  const library = {
    id: 's:1',
    asset_id: 'g1',
    x: 300,
    y: 300,
    width: 200,
    height: 200,
  }
  const layout = { items: [board, words, library], removed: [] }
  const anchors = new Map([['e1', { x: 648, y: 0 }]])
  const { layout: next } = complete(layout, [picture('out', 'e1')], anchors)
  assert.deepEqual(
    next.items.map((item) => item.id),
    ['f:1', 'x:1', 's:1', 'a:out'],
  )
  const out = next.items.at(-1)!
  assert.deepEqual([out.x, out.y], [648, 0])
  // Removing them deletes them (they are not results); nothing is remembered as removed.
  const removed = removeItems(next, ['x:1', 's:1'])
  assert.deepEqual(removed.removed, [])
  assert.deepEqual(
    removed.items.map((item) => item.id),
    ['f:1', 'a:out'],
  )
  // Tidy leaves them where they are and puts the results to their right.
  const tidied = tidy(next, [picture('out', 'e1')])
  assert.deepEqual(
    tidied.items.find((item) => item.id === 'x:1'),
    words,
  )
  assert.equal(tidied.items.find((item) => item.id === 'a:out')!.x, 600 + 120)
  // Placeholders of an export wait beside its board too.
  const waiting = pendingCells(
    layout,
    [{ taskId: 'e2', count: 1, size: square }],
    layout,
    new Map([['e2', { x: 648, y: 0 }]]),
  )
  assert.deepEqual([waiting[0]!.rect.x, waiting[0]!.rect.y], [648, 0])
})

test('order, size and edits', () => {
  const items = ['a', 'b', 'c'].map((id, i) => ({
    id,
    asset_id: id,
    x: i * 10,
    y: 0,
    width: 100,
    height: 100,
  }))
  const layout = { items, removed: [] }
  assert.deepEqual(
    reorder(layout, ['a'], 'front').items.map((item) => item.id),
    ['b', 'c', 'a'],
  )
  assert.deepEqual(
    reorder(layout, ['c', 'b'], 'back').items.map((item) => item.id),
    ['b', 'c', 'a'],
  )
  const bigger = resizeItem(layout, 'b', 250, 3)
  assert.deepEqual(
    [bigger.items[1]!.width, bigger.items[1]!.height],
    [250, 24], // never smaller than 24
  )
  const edited = updateItem(layout, 'c', (item) => ({ ...item, x: 99 }))
  assert.equal(edited.items[2]!.x, 99)
  assert.equal(ratioOf(1200, 900), '4:3')
  assert.equal(ratioOf(1152, 2048), '9:16')
})

test('a board exports what touches it, bottom first, as shares of the board', () => {
  const layout = {
    items: [
      { id: 'a:r1', artifact_id: 'r1', x: -100, y: 0, width: 300, height: 300 },
      {
        id: 'f:1',
        frame: { width: 800, height: 800, background: '#FFF6EC' },
        x: 0,
        y: 0,
        width: 600,
        height: 600,
      },
      { id: 's:1', asset_id: 'g1', x: 330, y: 330, width: 240, height: 240 },
      { id: 't:bad', task_id: 'bad', x: 10, y: 10, width: 100, height: 100 },
      {
        id: 'x:1',
        text: {
          content: '送',
          size: 48,
          color: '#1E3A5F',
          align: 'center' as const,
        },
        x: 0,
        y: 492,
        width: 600,
        height: 96,
      },
      { id: 's:far', asset_id: 'g2', x: 2000, y: 0, width: 100, height: 100 },
    ],
    removed: [],
  }
  const layers = exportLayers(layout, 'f:1')
  assert.deepEqual(
    layers.map((entry) => entry.key),
    ['a:r1', 's:1', 'x:1'],
  )
  assert.deepEqual(layers[0]!.layer, {
    artifact_id: 'r1',
    x: -0.1667,
    y: 0,
    width: 0.5,
    height: 0.5,
  })
  assert.deepEqual(layers[1]!.layer, {
    asset_id: 'g1',
    x: 0.55,
    y: 0.55,
    width: 0.4,
    height: 0.4,
  })
  assert.deepEqual(layers[2]!.layer, {
    text: '送',
    color: '#1E3A5F',
    size: 0.08,
    align: 'center',
    x: 0,
    y: 0.82,
    width: 1,
    height: 0.16,
  })
  assert.deepEqual(exportLayers(layout, 's:1'), [])
})
