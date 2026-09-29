/**
 * Browser-only review preview: original RGB with the candidate alpha applied. Display only —
 * generation reads the stored original and the confirmed alpha on the server side.
 */
export async function maskedPreview(
  original: Blob,
  alpha: Blob,
): Promise<string> {
  const [image, mask] = await Promise.all([
    createImageBitmap(original),
    createImageBitmap(alpha),
  ])
  try {
    if (image.width !== mask.width || image.height !== mask.height)
      throw new Error('抠图尺寸与原图不一致。')
    const canvas = document.createElement('canvas')
    canvas.width = image.width
    canvas.height = image.height
    const context = canvas.getContext('2d')!
    context.drawImage(mask, 0, 0)
    const weights = context.getImageData(0, 0, canvas.width, canvas.height)
    context.clearRect(0, 0, canvas.width, canvas.height)
    context.drawImage(image, 0, 0)
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height)
    for (let i = 0; i < pixels.data.length; i += 4)
      pixels.data[i + 3] = Math.round(
        (pixels.data[i + 3]! * weights.data[i]!) / 255,
      )
    context.putImageData(pixels, 0, 0)
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, 'image/png'),
    )
    if (!blob) throw new Error('预览生成失败。')
    return URL.createObjectURL(blob)
  } finally {
    image.close()
    mask.close()
  }
}
