// The conversation canvas layout (ADR-20261010-V): where each finished picture (or a failed
// message's card) sits, the copies and what was taken off the canvas. Saved per conversation
// through PUT /conversations/{id}/canvas; these functions only compute the next layout.
import {
  bounds,
  fitSide,
  stackRows,
  type Placed,
  type Rect,
  type Size,
} from './canvas.ts'

export type Placement = {
  id: string
  artifact_id?: string
  task_id?: string
  x: number
  y: number
  width: number
  height: number
}
export type Layout = { items: Placement[]; removed: string[] }
/** Something that can sit on the canvas: a finished picture or a failed message's card. */
export type Piece = {
  ref: string
  kind: 'artifact' | 'task'
  taskId: string
  index: number
  size: Size
}
/** A message still generating: placeholders, never saved. */
export type Pending = { taskId: string; count: number; size: Size }

export const PICTURE_SIDE = 360
export const CARD_SIDE = 240
export const GAP = 20
export const ROW_GAP = 56
export const CAPTION = 28
export const COPY_SHIFT = 24

export const EMPTY: Layout = { items: [], removed: [] }
export const refOf = (item: Placement) => (item.artifact_id ?? item.task_id)!
export const rectOf = (item: Placement): Rect => ({
  x: item.x,
  y: item.y,
  width: item.width,
  height: item.height,
})
/** Originals keep a fixed id (a: picture, t: failed message); copies get their own. */
export const idOf = (piece: Piece) =>
  `${piece.kind === 'artifact' ? 'a' : 't'}:${piece.ref}`

function placement(piece: Piece, rect: Rect): Placement {
  return {
    id: idOf(piece),
    ...(piece.kind === 'artifact'
      ? { artifact_id: piece.ref }
      : { task_id: piece.ref }),
    x: rect.x,
    y: rect.y,
    width: rect.width,
    height: rect.height,
  }
}

/** Below everything on the canvas, at its left edge (the top-left corner when empty). */
function below(items: Placement[]) {
  const box = bounds(items.map(rectOf))
  return box ? { x: box.x, y: box.y + box.height + ROW_GAP } : { x: 0, y: 0 }
}

/**
 * Adds what is not on the canvas yet (and was not taken off): new results go in rows below
 * everything, one row per message; a failed message that was retried hands its card's place
 * to its pictures. Things that no longer exist are dropped.
 */
export function complete(
  layout: Layout,
  pieces: Piece[],
): { layout: Layout; changed: boolean; added: boolean } {
  const known = new Set(pieces.map((piece) => piece.ref))
  const items = layout.items.filter((item) => known.has(refOf(item)))
  const placed = new Set(items.map(refOf))
  const removed = new Set(layout.removed)
  const missing = pieces.filter(
    (piece) => !placed.has(piece.ref) && !removed.has(piece.ref),
  )
  const changed = items.length !== layout.items.length
  if (!missing.length)
    return { layout: { items, removed: layout.removed }, changed, added: false }
  const order = [...new Set(missing.map((piece) => piece.taskId))]
  const rows: { key: string; items: { key: string; size: Size }[] }[] = []
  const added: Placement[] = []
  for (const taskId of order) {
    const group = missing
      .filter((piece) => piece.taskId === taskId)
      .sort((a, b) => a.index - b.index)
    const card = layout.items.find(
      (item) => item.task_id === taskId && !known.has(taskId),
    )
    if (card) {
      let left = card.x
      for (const piece of group) {
        added.push(placement(piece, { x: left, y: card.y, ...piece.size }))
        left += piece.size.width + GAP
      }
    } else
      rows.push({
        key: taskId,
        items: group.map((piece) => ({ key: piece.ref, size: piece.size })),
      })
  }
  const byRef = new Map(missing.map((piece) => [piece.ref, piece]))
  const start = below([...items, ...added])
  for (const cell of stackRows(rows, start.x, start.y, GAP, ROW_GAP, CAPTION))
    added.push(placement(byRef.get(cell.key)!, cell.rect))
  return {
    layout: { items: [...items, ...added], removed: layout.removed },
    changed: true,
    added: true,
  }
}

/** Placeholders for messages still generating, below everything (or where their card was). */
export function pendingCells(
  layout: Layout,
  pending: Pending[],
  // The saved layout: a failed message being retried left its card there.
  earlier: Layout = layout,
): Placed[] {
  const cells: Placed[] = []
  const rows: { key: string; items: { key: string; size: Size }[] }[] = []
  for (const task of pending) {
    const keys = Array.from(
      { length: task.count },
      (_, i) => `p:${task.taskId}:${i}`,
    )
    const card = earlier.items.find((item) => item.task_id === task.taskId)
    if (card) {
      let left = card.x
      for (const key of keys) {
        cells.push({ key, rect: { x: left, y: card.y, ...task.size } })
        left += task.size.width + GAP
      }
    } else
      rows.push({
        key: task.taskId,
        items: keys.map((key) => ({ key, size: task.size })),
      })
  }
  const start = below(layout.items)
  cells.push(...stackRows(rows, start.x, start.y, GAP, ROW_GAP, CAPTION))
  return cells
}

export function moveItems(
  layout: Layout,
  ids: string[],
  dx: number,
  dy: number,
): Layout {
  const moving = new Set(ids)
  return {
    items: layout.items.map((item) =>
      moving.has(item.id) ? { ...item, x: item.x + dx, y: item.y + dy } : item,
    ),
    removed: layout.removed,
  }
}

/** Takes items off the canvas; a picture with no copy left stays off until put back. */
export function removeItems(layout: Layout, ids: string[]): Layout {
  const gone = new Set(ids)
  const items = layout.items.filter((item) => !gone.has(item.id))
  const still = new Set(items.map(refOf))
  const removed = [...layout.removed]
  for (const item of layout.items)
    if (
      gone.has(item.id) &&
      !still.has(refOf(item)) &&
      !removed.includes(refOf(item))
    )
      removed.push(refOf(item))
  return { items, removed }
}

/** A copy of each picture (not of message cards), shifted down and to the right. */
export function duplicate(
  layout: Layout,
  ids: string[],
  newId: () => string,
): { layout: Layout; ids: string[] } {
  const wanted = new Set(ids)
  const copies = layout.items
    .filter((item) => wanted.has(item.id) && item.artifact_id)
    .map((item) => ({
      ...item,
      id: newId(),
      x: item.x + COPY_SHIFT,
      y: item.y + COPY_SHIFT,
    }))
  return {
    layout: { items: [...layout.items, ...copies], removed: layout.removed },
    ids: copies.map((item) => item.id),
  }
}

/** One row per message in order, each picture followed by its copies; removed stay removed. */
export function tidy(layout: Layout, pieces: Piece[]): Layout {
  const rows: { key: string; items: { key: string; size: Size }[] }[] = []
  const byId = new Map(layout.items.map((item) => [item.id, item]))
  for (const taskId of [...new Set(pieces.map((piece) => piece.taskId))]) {
    const items = pieces
      .filter((piece) => piece.taskId === taskId)
      .sort((a, b) => a.index - b.index)
      .flatMap((piece) =>
        layout.items
          .filter((item) => refOf(item) === piece.ref)
          // The original first, then its copies in the order they were made.
          .sort(
            (a, b) =>
              Number(b.id === idOf(piece)) - Number(a.id === idOf(piece)),
          )
          .map((item) => ({
            key: item.id,
            size: { width: item.width, height: item.height },
          })),
      )
    rows.push({ key: taskId, items })
  }
  return {
    items: stackRows(rows, 0, 0, GAP, ROW_GAP, CAPTION).map((cell) => ({
      ...byId.get(cell.key)!,
      ...cell.rect,
    })),
    removed: layout.removed,
  }
}

/** Puts everything taken off back, in rows below. */
export const restoreRemoved = (layout: Layout, pieces: Piece[]) =>
  complete({ items: layout.items, removed: [] }, pieces).layout

/** Size of a piece on the canvas: pictures by their own proportions, cards a little smaller. */
export const pieceSize = (size: Size, card = false) =>
  fitSide(size, card ? CARD_SIDE : PICTURE_SIDE)
