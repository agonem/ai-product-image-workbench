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
  pendingCells,
  removeItems,
  restoreRemoved,
  tidy,
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
