import test from 'node:test'
import assert from 'node:assert/strict'
import { prepareUpload, sniff } from './upload.ts'

const PNG = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]

test('the file content decides the type, not its name or declared type', async () => {
  assert.equal(sniff(new Uint8Array(PNG)), 'image/png')
  assert.equal(sniff(new Uint8Array([0xff, 0xd8, 0xff, 0xe1])), 'image/jpeg')
  assert.equal(sniff(new Uint8Array([0x52, 0x49, 0x46, 0x46])), null) // WebP (RIFF)
  // A PNG saved as "photo.jpg" by another program is still sent as PNG, unchanged.
  const file = new Blob([new Uint8Array([...PNG, 1, 2, 3])], {
    type: 'image/jpeg',
  })
  const prepared = await prepareUpload(file)
  assert.equal(prepared.type, 'image/png')
  assert.equal(prepared.converted, false)
  assert.equal(prepared.body, file)
})
