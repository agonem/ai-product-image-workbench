package com.productimage.business.runtime;

import java.nio.ByteBuffer;

/**
 * Original uploads (ADR-20260930-D). The file content decides the type - PNG or JPEG; the
 * browser-declared Content-Type is ignored, because it depends on the operator's computer and file
 * name. Metadata (EXIF, colour profiles, text) is kept byte for byte and never re-encoded.
 * Dimensions come from the file header, so very large images need no decoding here; other formats
 * are converted to PNG by the page before upload, and the Worker decodes the image when it is used.
 */
final class UploadValidation {
  /** Upper bound of a JPEG side; PNG shares it so every stored original has sane geometry. */
  static final int MAX_SIDE = 65535;

  record Result(String mime, int width, int height) {}

  private UploadValidation() {}

  static Result validate(byte[] data, int maximum, long pixels) {
    if (data.length > maximum) throw new Problem(413, "UPLOAD_BUDGET_EXCEEDED");
    if (data.length == 0) throw rejected();
    int[] size;
    String mime;
    if (data.length >= 8 && ByteBuffer.wrap(data).getLong() == 0x89504e470d0a1a0aL) {
      mime = "image/png";
      size = png(data);
    } else if (data.length >= 3
        && unsigned(data[0]) == 255
        && unsigned(data[1]) == 216
        && unsigned(data[2]) == 255) {
      mime = "image/jpeg";
      size = jpeg(data);
    } else throw new Problem(415, "UPLOAD_TYPE_UNSUPPORTED");
    int width = size[0], height = size[1];
    if (width < 1 || height < 1) throw rejected();
    if (width > MAX_SIDE || height > MAX_SIDE || (long) width * height > pixels)
      throw new Problem(413, "UPLOAD_BUDGET_EXCEEDED");
    return new Result(mime, width, height);
  }

  private static Problem rejected() {
    return new Problem(422, "UPLOAD_CONTENT_REJECTED");
  }

  private static int unsigned(byte value) {
    return value & 255;
  }

  private static int u16(byte[] data, int offset) {
    return (unsigned(data[offset]) << 8) | unsigned(data[offset + 1]);
  }

  /** Walks the chunk list: IHDR first, sizes in range, image data present, ends with IEND. */
  private static int[] png(byte[] data) {
    if (data.length < 33
        || !"IHDR".equals(type(data, 12))
        || ByteBuffer.wrap(data, 8, 4).getInt() != 13) throw rejected();
    int width = ByteBuffer.wrap(data, 16, 4).getInt(),
        height = ByteBuffer.wrap(data, 20, 4).getInt();
    boolean image = false;
    int offset = 8;
    while (offset + 12 <= data.length) {
      int size = ByteBuffer.wrap(data, offset, 4).getInt();
      if (size < 0 || (long) offset + size + 12 > data.length) throw rejected();
      String type = type(data, offset + 4);
      offset += size + 12;
      if (type.equals("IDAT")) image = true;
      if (type.equals("IEND")) {
        // A truncated file never reaches IEND; nothing may follow it.
        if (!image || offset != data.length) throw rejected();
        return new int[] {width, height};
      }
    }
    throw rejected();
  }

  private static String type(byte[] data, int offset) {
    return new String(data, offset, 4, java.nio.charset.StandardCharsets.US_ASCII);
  }

  /**
   * Reads the frame header (SOF) for the size and requires scan data followed by an end marker. Any
   * metadata segment is allowed; bytes after the end marker (e.g. phone "motion photos") are kept.
   */
  private static int[] jpeg(byte[] data) {
    int offset = 2;
    int[] size = null;
    while (offset + 4 <= data.length) {
      if (unsigned(data[offset]) != 255) throw rejected();
      int marker = unsigned(data[offset + 1]);
      if (marker == 255) {
        offset++; // fill byte
        continue;
      }
      if (marker == 1 || (marker >= 208 && marker <= 215)) {
        offset += 2;
        continue;
      }
      int length = u16(data, offset + 2);
      if (length < 2 || (long) offset + 2 + length > data.length) throw rejected();
      boolean frame =
          marker >= 192 && marker <= 207 && marker != 196 && marker != 200 && marker != 204;
      if (frame) {
        if (length < 8) throw rejected();
        size = new int[] {u16(data, offset + 7), u16(data, offset + 5)};
      }
      if (marker == 218) {
        // Scan data follows; a complete file has an end-of-image marker after it.
        if (size == null) throw rejected();
        for (int i = data.length - 2; i >= offset + 2 + length; i--)
          if (unsigned(data[i]) == 255 && unsigned(data[i + 1]) == 217) return size;
        throw rejected();
      }
      offset += 2 + length;
    }
    throw rejected();
  }
}
