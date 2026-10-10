// The conversation canvas layout (ADR-20261010-V, W): where each finished picture (or a failed
// message's card) sits, the copies and what was taken off the canvas, plus the user's own text
// boxes, library pictures and boards. Saved per conversation through PUT
// /conversations/{id}/canvas; these functions only compute the next layout.
import {
  bounds,
  fitSide,
  overlaps,
  stackRows,
  type Placed,
  type Rect,
  type Size,
} from './canvas.ts'

export type TextSpec = {
  content: string
  size: number
  color: string
  align: 'left' | 'center' | 'right'
}
/** A board: the exported picture's size in pixels and its background colour. */
export type FrameSpec = { width: number; height: number; background: string }
export type Placement = {
  id: string
  artifact_id?: string
  task_id?: string
  asset_id?: string
  text?: TextSpec
  frame?: FrameSpec
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
/** Where a message's pictures go instead of a new row (an export: next to its board). */
export type Anchors = Map<string, { x: number; y: number }>

export const PICTURE_SIDE = 360
export const CARD_SIDE = 240
export const BOARD_SIDE = 600
export const GAP = 20
export const ROW_GAP = 56
export const CAPTION = 28
export const COPY_SHIFT = 24
export const MIN_SIDE = 24

export const EMPTY: Layout = { items: [], removed: [] }
/** The user's own things (text, library pictures, boards) rather than conversation results. */
export const isOwn = (item: Placement) => !item.artifact_id && !item.task_id
export const refOf = (item: Placement) => item.artifact_id ?? item.task_id
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

/** A row of pictures from a given corner. */
function inRow(origin: { x: number; y: number }, sizes: Size[]): Rect[] {
  let left = origin.x
  return sizes.map((size) => {
    const rect = { x: left, y: origin.y, ...size }
    left += size.width + GAP
    return rect
  })
}

/**
 * Adds what is not on the canvas yet (and was not taken off): new results go in rows below
 * everything, one row per message; a failed message that was retried hands its card's place
 * to its pictures, an export goes to its anchor (next to its board). Results that no longer
 * exist are dropped; the user's own things always stay.
 */
export function complete(
  layout: Layout,
  pieces: Piece[],
  anchors: Anchors = new Map(),
): { layout: Layout; changed: boolean; added: boolean } {
  const known = new Set(pieces.map((piece) => piece.ref))
  const items = layout.items.filter(
    (item) => isOwn(item) || known.has(refOf(item)!),
  )
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
    const origin = card ?? anchors.get(taskId)
    if (origin)
      inRow(
        origin,
        group.map((piece) => piece.size),
      ).forEach((rect, i) => added.push(placement(group[i]!, rect)))
    else
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

/** Placeholders for messages still generating: below everything, or at their card or anchor. */
export function pendingCells(
  layout: Layout,
  pending: Pending[],
  // The saved layout: a failed message being retried left its card there.
  earlier: Layout = layout,
  anchors: Anchors = new Map(),
): Placed[] {
  const cells: Placed[] = []
  const rows: { key: string; items: { key: string; size: Size }[] }[] = []
  for (const task of pending) {
    const keys = Array.from(
      { length: task.count },
      (_, i) => `p:${task.taskId}:${i}`,
    )
    const origin =
      earlier.items.find((item) => item.task_id === task.taskId) ??
      anchors.get(task.taskId)
    if (origin)
      inRow(
        origin,
        keys.map(() => task.size),
      ).forEach((rect, i) => cells.push({ key: keys[i]!, rect }))
    else
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

export function resizeItem(
  layout: Layout,
  id: string,
  width: number,
  height: number,
): Layout {
  return {
    items: layout.items.map((item) =>
      item.id === id
        ? {
            ...item,
            width: Math.max(MIN_SIDE, width),
            height: Math.max(MIN_SIDE, height),
          }
        : item,
    ),
    removed: layout.removed,
  }
}

/** Edits a text box or a board (merging the given fields). */
export function updateItem(
  layout: Layout,
  id: string,
  change: (item: Placement) => Placement,
): Layout {
  return {
    items: layout.items.map((item) => (item.id === id ? change(item) : item)),
    removed: layout.removed,
  }
}

/** Brings the items to the front (drawn last) or sends them to the back, keeping their order. */
export function reorder(
  layout: Layout,
  ids: string[],
  where: 'front' | 'back',
): Layout {
  const chosen = new Set(ids)
  const picked = layout.items.filter((item) => chosen.has(item.id))
  const rest = layout.items.filter((item) => !chosen.has(item.id))
  return {
    items: where === 'front' ? [...rest, ...picked] : [...picked, ...rest],
    removed: layout.removed,
  }
}

/**
 * Takes items off the canvas. A result with no copy left stays off until put back; the user's
 * own things are simply deleted.
 */
export function removeItems(layout: Layout, ids: string[]): Layout {
  const gone = new Set(ids)
  const items = layout.items.filter((item) => !gone.has(item.id))
  const still = new Set(items.map(refOf))
  const removed = [...layout.removed]
  for (const item of layout.items) {
    const ref = refOf(item)
    if (gone.has(item.id) && ref && !still.has(ref) && !removed.includes(ref))
      removed.push(ref)
  }
  return { items, removed }
}

/** A copy of each item but message cards, shifted down and to the right. */
export function duplicate(
  layout: Layout,
  ids: string[],
  newId: () => string,
): { layout: Layout; ids: string[] } {
  const wanted = new Set(ids)
  const copies = layout.items
    .filter((item) => wanted.has(item.id) && !item.task_id)
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

/**
 * One row per message in order, each picture followed by its copies; removed stay removed. The
 * user's own things keep their places and the rows start to their right.
 */
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
  const own = layout.items.filter(isOwn)
  const area = bounds(own.map(rectOf))
  const left = area ? area.x + area.width + 120 : 0
  const top = area ? area.y : 0
  const arranged = new Map(
    stackRows(rows, left, top, GAP, ROW_GAP, CAPTION).map((cell) => [
      cell.key,
      cell.rect,
    ]),
  )
  return {
    items: layout.items
      .filter((item) => isOwn(item) || arranged.has(item.id))
      .map((item) =>
        arranged.has(item.id)
          ? { ...byId.get(item.id)!, ...arranged.get(item.id)! }
          : item,
      ),
    removed: layout.removed,
  }
}

/** Puts everything taken off back, in rows below. */
export const restoreRemoved = (layout: Layout, pieces: Piece[]) =>
  complete({ items: layout.items, removed: [] }, pieces).layout

/** Size of a piece on the canvas: pictures by their own proportions, cards a little smaller. */
export const pieceSize = (size: Size, card = false) =>
  fitSide(size, card ? CARD_SIDE : PICTURE_SIDE)

const gcd = (a: number, b: number): number => (b ? gcd(b, a % b) : a)
/** "4:3" for 1200 × 900. */
export const ratioOf = (width: number, height: number) => {
  const d = gcd(width, height)
  return `${width / d}:${height / d}`
}

export type ExportLayer =
  | {
      artifact_id?: string
      asset_id?: string
      x: number
      y: number
      width: number
      height: number
    }
  | {
      text: string
      color: string
      size: number
      align: TextSpec['align']
      x: number
      y: number
      width: number
      height: number
    }
const share = (value: number) => Math.round(value * 10000) / 10000

/**
 * The layers of a board's export (ADR-20261010-W), bottom first: every picture, library picture
 * and text box touching the board, as shares of the board; text sizes as shares of its width.
 * Message cards and other boards are left out.
 */
export function exportLayers(
  layout: Layout,
  frameId: string,
): { key: string; layer: ExportLayer }[] {
  const board = layout.items.find((item) => item.id === frameId && item.frame)
  if (!board) return []
  const area = rectOf(board)
  const layers: { key: string; layer: ExportLayer }[] = []
  for (const item of layout.items) {
    if (item.frame || item.task_id || !overlaps(area, rectOf(item))) continue
    const place = {
      x: share((item.x - board.x) / board.width),
      y: share((item.y - board.y) / board.height),
      width: share(item.width / board.width),
      height: share(item.height / board.height),
    }
    // Beyond what the export accepts (far bigger than the board): left out.
    if (
      Math.abs(place.x) > 4 ||
      Math.abs(place.y) > 4 ||
      place.width > 8 ||
      place.height > 8 ||
      place.width <= 0 ||
      place.height <= 0
    )
      continue
    if (item.text)
      layers.push({
        key: item.id,
        layer: {
          text: item.text.content,
          color: item.text.color,
          size: Math.min(
            0.5,
            Math.max(0.004, share(item.text.size / board.width)),
          ),
          align: item.text.align,
          ...place,
        },
      })
    else if (item.artifact_id)
      layers.push({
        key: item.id,
        layer: { artifact_id: item.artifact_id, ...place },
      })
    else if (item.asset_id)
      layers.push({
        key: item.id,
        layer: { asset_id: item.asset_id, ...place },
      })
  }
  return layers
}
