// Uploads (ADR-20260930-D): PNG and JPEG files are sent unchanged; any other image the
// browser can open (WebP, GIF, BMP, AVIF, ICO...) is stored as a lossless PNG of its pixels.
// The type always comes from the file content, never from its name or the operating system.
export type ImageType = 'image/png' | 'image/jpeg'

export const UNREADABLE =
  '无法读取这张图片。HEIC、TIFF 等格式浏览器打不开，请先另存为 JPG 或 PNG 再上传。'

export function sniff(head: Uint8Array): ImageType | null {
  const png = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]
  if (png.every((value, index) => head[index] === value)) return 'image/png'
  if (head[0] === 0xff && head[1] === 0xd8 && head[2] === 0xff)
    return 'image/jpeg'
  return null
}

export async function prepareUpload(
  file: Blob,
): Promise<{ body: Blob; type: ImageType; converted: boolean }> {
  const type = sniff(new Uint8Array(await file.slice(0, 8).arrayBuffer()))
  if (type) return { body: file, type, converted: false }
  let bitmap: ImageBitmap
  try {
    bitmap = await createImageBitmap(file)
  } catch {
    throw new Error(UNREADABLE)
  }
  try {
    const canvas = document.createElement('canvas')
    canvas.width = bitmap.width
    canvas.height = bitmap.height
    canvas.getContext('2d')!.drawImage(bitmap, 0, 0)
    const body = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, 'image/png'),
    )
    if (!body) throw new Error(UNREADABLE)
    return { body, type: 'image/png', converted: true }
  } finally {
    bitmap.close()
  }
}
