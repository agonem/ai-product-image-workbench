package com.productimage.business.runtime;

import static org.junit.jupiter.api.Assertions.*;

import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.zip.CRC32;
import javax.imageio.ImageIO;
import org.junit.jupiter.api.Test;

class UploadValidationTest {
  private static final int BYTES = 1 << 20;
  private static final long PIXELS = 100;

  private byte[] image(String format) throws Exception {
    var out = new ByteArrayOutputStream();
    assertTrue(ImageIO.write(new BufferedImage(4, 3, BufferedImage.TYPE_INT_RGB), format, out));
    return out.toByteArray();
  }

  private static byte[] chunk(String type, byte[] body) {
    var buffer = ByteBuffer.allocate(body.length + 12);
    byte[] name = type.getBytes(StandardCharsets.US_ASCII);
    var crc = new CRC32();
    crc.update(name);
    crc.update(body);
    return buffer.putInt(body.length).put(name).put(body).putInt((int) crc.getValue()).array();
  }

  private static byte[] join(byte[]... parts) throws Exception {
    var out = new ByteArrayOutputStream();
    for (byte[] part : parts) out.write(part);
    return out.toByteArray();
  }

  private static int status(byte[] data, int bytes, long pixels) {
    return assertThrows(Problem.class, () -> UploadValidation.validate(data, bytes, pixels)).status;
  }

  @Test
  void theContentDecidesTheTypeAndTheBytesAreNotTouched() throws Exception {
    for (String format : new String[] {"png", "jpeg"}) {
      byte[] bytes = image(format), original = bytes.clone();
      var result = UploadValidation.validate(bytes, BYTES, PIXELS);
      assertEquals("image/" + format, result.mime());
      assertEquals(4, result.width());
      assertEquals(3, result.height());
      assertArrayEquals(original, bytes);
    }
  }

  @Test
  void commonMetadataIsAccepted() throws Exception {
    byte[] png = image("png"), jpeg = image("jpeg");
    // PNG text, colour profile and EXIF chunks before the image data.
    byte[] withText =
        join(
            Arrays.copyOf(png, 33),
            chunk("tEXt", "Software\0Photoshop".getBytes(StandardCharsets.ISO_8859_1)),
            chunk("iCCP", "icc\0\0compressed".getBytes(StandardCharsets.ISO_8859_1)),
            chunk("eXIf", new byte[] {'M', 'M', 0, 42}),
            Arrays.copyOfRange(png, 33, png.length));
    assertEquals("image/png", UploadValidation.validate(withText, BYTES, PIXELS).mime());
    // JPEG with EXIF (APP1), ICC (APP2), Adobe (APP14) segments and data after the end marker.
    byte[] withExif =
        join(
            Arrays.copyOf(jpeg, 2),
            new byte[] {(byte) 255, (byte) 225, 0, 8, 'E', 'x', 'i', 'f', 0, 0},
            new byte[] {(byte) 255, (byte) 226, 0, 6, 'I', 'C', 'C', 0},
            new byte[] {(byte) 255, (byte) 238, 0, 4, 'A', 'd'},
            Arrays.copyOfRange(jpeg, 2, jpeg.length),
            "motion-photo-trailer".getBytes(StandardCharsets.US_ASCII));
    var result = UploadValidation.validate(withExif, BYTES, PIXELS);
    assertEquals("image/jpeg", result.mime());
    assertEquals(4, result.width());
  }

  @Test
  void unknownDamagedAndOversizedInputsAreRefused() throws Exception {
    byte[] png = image("png"), jpeg = image("jpeg");
    assertEquals(415, status(new byte[] {1, 2, 3}, BYTES, PIXELS));
    assertEquals(422, status(new byte[0], BYTES, PIXELS));
    assertEquals(415, status("GIF89a....".getBytes(StandardCharsets.US_ASCII), BYTES, PIXELS));
    assertEquals(413, status(png, 10, PIXELS));
    assertEquals(413, status(png, BYTES, 11));
    assertEquals(422, status(Arrays.copyOf(png, png.length - 6), BYTES, PIXELS));
    assertEquals(422, status(Arrays.copyOf(png, png.length + 1), BYTES, PIXELS));
    assertEquals(422, status(Arrays.copyOf(jpeg, jpeg.length - 2), BYTES, PIXELS));
    assertEquals(422, status(Arrays.copyOf(jpeg, 20), BYTES, PIXELS));
    // A header claiming a huge image is refused without decoding anything.
    byte[] huge = png.clone();
    ByteBuffer.wrap(huge, 16, 8).putInt(70000).putInt(3);
    assertEquals(413, status(huge, BYTES, Long.MAX_VALUE));
  }
}
