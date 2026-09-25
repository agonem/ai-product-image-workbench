package com.productimage.business.runtime;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.Set;
import java.util.zip.CRC32;
import javax.imageio.ImageIO;
import javax.imageio.stream.MemoryCacheImageInputStream;

/** A deliberately narrow original-upload format boundary; never re-encodes source pixels. */
final class UploadValidation {
  private UploadValidation() {}

  static String validate(byte[] data, String mime, int maximum, long pixels) {
    if (data.length > maximum) throw new Problem(413, "UPLOAD_BUDGET_EXCEEDED");
    if (!"image/png".equalsIgnoreCase(mime) && !"image/jpeg".equalsIgnoreCase(mime))
      throw new Problem(415, "UPLOAD_TYPE_UNSUPPORTED");
    String actual;
    if (data.length >= 8 && ByteBuffer.wrap(data).getLong() == 0x89504e470d0a1a0aL)
      actual = "image/png";
    else if (data.length >= 2 && unsigned(data[0]) == 255 && unsigned(data[1]) == 216)
      actual = "image/jpeg";
    else throw rejected();
    if (!actual.equalsIgnoreCase(mime)) throw new Problem(415, "UPLOAD_TYPE_UNSUPPORTED");
    if (actual.equals("image/png")) png(data);
    else jpeg(data);
    try (var input = new MemoryCacheImageInputStream(new ByteArrayInputStream(data))) {
      var readers = ImageIO.getImageReaders(input);
      if (!readers.hasNext()) throw rejected();
      var reader = readers.next();
      try {
        reader.setInput(input, true, true);
        int width = reader.getWidth(0), height = reader.getHeight(0);
        if (width < 1
            || height < 1
            || width > 16384
            || height > 16384
            || (long) width * height > pixels) throw new Problem(413, "UPLOAD_BUDGET_EXCEEDED");
        boolean[] warning = {false};
        reader.addIIOReadWarningListener((source, message) -> warning[0] = true);
        if (reader.read(0) == null || warning[0]) throw rejected();
      } finally {
        reader.dispose();
      }
    } catch (IOException | IllegalArgumentException ex) {
      throw rejected();
    }
    return actual;
  }

  private static Problem rejected() {
    return new Problem(422, "UPLOAD_CONTENT_REJECTED");
  }

  private static int unsigned(byte value) {
    return value & 255;
  }

  private static void png(byte[] data) {
    Set<String> allowed =
        Set.of("IHDR", "PLTE", "IDAT", "IEND", "tRNS", "sRGB", "gAMA", "cHRM", "pHYs");
    var seen = new HashSet<String>();
    boolean image = false;
    int offset = 8;
    while (offset + 12 <= data.length) {
      int size = ByteBuffer.wrap(data, offset, 4).getInt();
      if (size < 0 || (long) offset + size + 12 > data.length) throw rejected();
      String type = new String(data, offset + 4, 4, StandardCharsets.US_ASCII);
      if (!allowed.contains(type) || (offset == 8 && !type.equals("IHDR"))) throw rejected();
      if (!type.equals("IDAT") && !seen.add(type)) throw rejected();
      if (image && !type.equals("IDAT") && !type.equals("IEND")) throw rejected();
      boolean sizeValid =
          switch (type) {
            case "IHDR" -> size == 13;
            case "IEND" -> size == 0;
            case "sRGB" -> size == 1;
            case "gAMA" -> size == 4;
            case "cHRM" -> size == 32;
            case "pHYs" -> size == 9;
            case "PLTE" -> size > 0 && size <= 768 && size % 3 == 0;
            case "tRNS" -> size > 0 && size <= 256;
            default -> true;
          };
      if (!sizeValid) throw rejected();
      CRC32 crc = new CRC32();
      crc.update(data, offset + 4, size + 4);
      if ((int) crc.getValue() != ByteBuffer.wrap(data, offset + 8 + size, 4).getInt())
        throw rejected();
      offset += size + 12;
      if (type.equals("IDAT")) image = true;
      if (type.equals("IEND")) {
        if (!image || offset != data.length) throw rejected();
        return;
      }
    }
    throw rejected();
  }

  private static void jpeg(byte[] data) {
    int offset = 2;
    boolean scan = false, image = false;
    while (offset < data.length) {
      if (scan && unsigned(data[offset]) != 255) {
        offset++;
        continue;
      }
      if (unsigned(data[offset++]) != 255) throw rejected();
      while (offset < data.length && unsigned(data[offset]) == 255) offset++;
      if (offset == data.length) throw rejected();
      int marker = unsigned(data[offset++]);
      if (scan && (marker == 0 || (marker >= 208 && marker <= 215))) continue;
      scan = false;
      if (marker == 217) {
        if (!image || offset != data.length) throw rejected();
        return;
      }
      if (!Set.of(192, 194, 196, 219, 221, 218, 224).contains(marker) || offset + 2 > data.length)
        throw rejected();
      int size = (unsigned(data[offset]) << 8) | unsigned(data[offset + 1]);
      if (size < 2 || (long) offset + size > data.length) throw rejected();
      if (marker == 224) {
        if (size < 16
            || !new String(data, offset + 2, 5, StandardCharsets.US_ASCII).equals("JFIF\0"))
          throw rejected();
        if (size != 16 + 3 * unsigned(data[offset + 14]) * unsigned(data[offset + 15]))
          throw rejected();
      }
      offset += size;
      if (marker == 218) {
        scan = true;
        image = true;
      }
    }
    throw rejected();
  }
}
