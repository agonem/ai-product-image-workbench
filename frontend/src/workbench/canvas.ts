// Geometry of the result canvas (ADR-20261010-S): world rectangles, the view that maps them onto
// the screen (screen = world × scale + offset), fitting, zooming and the automatic layouts.

export type Rect = { x: number; y: number; width: number; height: number }
export type View = { x: number; y: number; scale: number }
export type Size = { width: number; height: number }
/** A thing on the canvas; `movable` ones can be selected and dragged (ADR-20261010-V). */
export type Placed = {
  key: string
  rect: Rect
  movable?: boolean
  /** A single selected item gets a corner handle: keeping its proportions or freely. */
  resize?: 'ratio' | 'free'
}

export const MIN_SCALE = 0.05
export const MAX_SCALE = 4

const clampScale = (scale: number) =>
  Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale))

/** The smallest rectangle around all the given ones (null when there are none). */
export function bounds(rects: Rect[]): Rect | null {
  if (!rects.length) return null
  const left = Math.min(...rects.map((r) => r.x))
  const top = Math.min(...rects.map((r) => r.y))
  const right = Math.max(...rects.map((r) => r.x + r.width))
  const bottom = Math.max(...rects.map((r) => r.y + r.height))
  return { x: left, y: top, width: right - left, height: bottom - top }
}

/** The view that shows the rectangles whole and centred, never enlarged beyond `maxScale`. */
export function fitView(
  rects: Rect[],
  viewport: Size,
  padding = 32,
  maxScale = 1,
): View {
  const box = bounds(rects)
  if (!box || viewport.width <= 0 || viewport.height <= 0)
    return { x: 0, y: 0, scale: 1 }
  const roomWidth = Math.max(1, viewport.width - 2 * padding)
  const roomHeight = Math.max(1, viewport.height - 2 * padding)
  const scale = clampScale(
    Math.min(
      maxScale,
      roomWidth / Math.max(1, box.width),
      roomHeight / Math.max(1, box.height),
    ),
  )
  return {
    x: viewport.width / 2 - (box.x + box.width / 2) * scale,
    y: viewport.height / 2 - (box.y + box.height / 2) * scale,
    scale,
  }
}

/** Zooms by `factor` keeping the world point under `point` (screen pixels) in place. */
export function zoomAt(
  view: View,
  factor: number,
  point: { x: number; y: number },
): View {
  const scale = clampScale(view.scale * factor)
  const ratio = scale / view.scale
  return {
    x: point.x - (point.x - view.x) * ratio,
    y: point.y - (point.y - view.y) * ratio,
    scale,
  }
}

/** Where a world rectangle appears on screen. */
export function onScreen(rect: Rect, view: View): Rect {
  return {
    x: rect.x * view.scale + view.x,
    y: rect.y * view.scale + view.y,
    width: rect.width * view.scale,
    height: rect.height * view.scale,
  }
}

/** Whether a world rectangle is on screen or within `margin` (share of the viewport) of it. */
export function nearScreen(
  rect: Rect,
  view: View,
  viewport: Size,
  margin = 0.5,
): boolean {
  const r = onScreen(rect, view)
  const dx = viewport.width * margin,
    dy = viewport.height * margin
  return (
    r.x < viewport.width + dx &&
    r.x + r.width > -dx &&
    r.y < viewport.height + dy &&
    r.y + r.height > -dy
  )
}

/** The size of a picture with the given proportions whose longer side is `side`. */
export function fitSide(size: Size, side: number): Size {
  const width = Math.max(1, size.width),
    height = Math.max(1, size.height)
  const scale = side / Math.max(width, height)
  return {
    width: Math.round(width * scale),
    height: Math.round(height * scale),
  }
}

/** Columns for a group of results: 1–2 side by side, 3–4 in two columns, more in three. */
export const columnsFor = (count: number) =>
  count <= 2 ? Math.max(1, count) : count <= 4 ? 2 : 3

/**
 * Lays pictures out in rows of `columns`, left to right then top to bottom, starting at
 * (`x`, `y`). Each row is as tall as its tallest picture.
 */
export function grid(
  items: { key: string; size: Size }[],
  columns: number,
  x: number,
  y: number,
  gap: number,
): Placed[] {
  const placed: Placed[] = []
  let top = y
  for (let start = 0; start < items.length; start += columns) {
    const row = items.slice(start, start + columns)
    let left = x
    for (const item of row) {
      placed.push({ key: item.key, rect: { x: left, y: top, ...item.size } })
      left += item.size.width + gap
    }
    top += Math.max(...row.map((item) => item.size.height)) + gap
  }
  return placed
}

export type Turn = {
  key: string
  label: { key: string; height: number }
  items: { key: string; size: Size }[]
}

/**
 * The conversation canvas: one row per message, oldest at the top, each row a label line (at
 * least `labelWidth` wide, as wide as its pictures) and then its pictures side by side.
 */
export function turns(
  rows: Turn[],
  labelWidth: number,
  gap: number,
  rowGap: number,
): Placed[] {
  const placed: Placed[] = []
  let top = 0
  for (const row of rows) {
    const pictures = row.items.length
      ? grid(row.items, row.items.length, 0, top + row.label.height + 8, gap)
      : []
    const box = bounds(pictures.map((item) => item.rect))
    placed.push({
      key: row.label.key,
      rect: {
        x: 0,
        y: top,
        width: Math.max(labelWidth, box?.width ?? 0),
        height: row.label.height,
      },
    })
    placed.push(...pictures)
    top = (box ? box.y + box.height : top + row.label.height) + rowGap
  }
  return placed
}

/** The rectangle between two corners, whichever way it was drawn. */
export function between(
  a: { x: number; y: number },
  b: { x: number; y: number },
): Rect {
  return {
    x: Math.min(a.x, b.x),
    y: Math.min(a.y, b.y),
    width: Math.abs(a.x - b.x),
    height: Math.abs(a.y - b.y),
  }
}

/** Whether two rectangles share any area (a box selection touching a picture selects it). */
export function overlaps(a: Rect, b: Rect): boolean {
  return (
    a.x < b.x + b.width &&
    b.x < a.x + a.width &&
    a.y < b.y + b.height &&
    b.y < a.y + a.height
  )
}

/** A screen rectangle (relative to the canvas) in world units. */
export function toWorld(rect: Rect, view: View): Rect {
  return {
    x: (rect.x - view.x) / view.scale,
    y: (rect.y - view.y) / view.scale,
    width: rect.width / view.scale,
    height: rect.height / view.scale,
  }
}

export type Row = { key: string; items: { key: string; size: Size }[] }

/**
 * Rows of pictures from (`x`, `y`) downwards, oldest first: each row keeps `caption` pixels
 * above its pictures for their captions, then the pictures side by side. Empty rows take no room.
 */
export function stackRows(
  rows: Row[],
  x: number,
  y: number,
  gap: number,
  rowGap: number,
  caption: number,
): Placed[] {
  const placed: Placed[] = []
  let top = y
  for (const row of rows) {
    if (!row.items.length) continue
    const pictures = grid(row.items, row.items.length, x, top + caption, gap)
    placed.push(...pictures)
    const box = bounds(pictures.map((item) => item.rect))!
    top = box.y + box.height + rowGap
  }
  return placed
}
