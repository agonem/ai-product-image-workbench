package com.productimage.business.runtime;

import static org.junit.jupiter.api.Assertions.*;

import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.util.Arrays;
import javax.imageio.ImageIO;
import org.junit.jupiter.api.Test;

class UploadValidationTest {
  private byte[] image(String format) throws Exception {
    var out = new ByteArrayOutputStream();
    assertTrue(ImageIO.write(new BufferedImage(4, 3, BufferedImage.TYPE_INT_RGB), format, out));
    return out.toByteArray();
  }

  @Test
  void allowsActualPngAndJpegWithoutRewriting() throws Exception {
    for (String format : new String[] {"png", "jpeg"}) {
      byte[] bytes = image(format), original = bytes.clone();
      assertEquals(
          "image/" + format, UploadValidation.validate(bytes, "image/" + format, 10000, 100));
      assertArrayEquals(original, bytes);
    }
  }

  @Test
  void rejectsMismatchedTypesDamageAndResourceBudgets() throws Exception {
    byte[] png = image("png"), jpeg = image("jpeg");
    assertEquals(
        415,
        assertThrows(Problem.class, () -> UploadValidation.validate(png, "image/jpeg", 10000, 100))
            .status);
    assertEquals(
        413,
        assertThrows(Problem.class, () -> UploadValidation.validate(png, "image/png", 1, 100))
            .status);
    assertEquals(
        413,
        assertThrows(Problem.class, () -> UploadValidation.validate(png, "image/png", 10000, 1))
            .status);
    for (byte[] bytes :
        new byte[][] {
          new byte[] {1, 2, 3},
          Arrays.copyOf(png, png.length - 6),
          Arrays.copyOf(png, png.length + 1)
        }) {
      assertEquals(
          422,
          assertThrows(
                  Problem.class, () -> UploadValidation.validate(bytes, "image/png", 10000, 100))
              .status);
    }
    assertEquals(
        422,
        assertThrows(
                Problem.class,
                () ->
                    UploadValidation.validate(
                        Arrays.copyOf(jpeg, jpeg.length - 2), "image/jpeg", 10000, 100))
            .status);
    byte[] badCrc = png.clone();
    badCrc[29] ^= 1;
    assertEquals(
        422,
        assertThrows(
                Problem.class, () -> UploadValidation.validate(badCrc, "image/png", 10000, 100))
            .status);
  }

  @Test
  void rejectsUnreviewedMetadata() throws Exception {
    byte[] jpeg = image("jpeg");
    var out = new ByteArrayOutputStream();
    out.write(jpeg, 0, 2);
    out.write(new byte[] {(byte) 255, (byte) 225, 0, 8, 'E', 'x', 'i', 'f', 0, 0});
    out.write(jpeg, 2, jpeg.length - 2);
    assertEquals(
        422,
        assertThrows(
                Problem.class,
                () -> UploadValidation.validate(out.toByteArray(), "image/jpeg", 10000, 100))
            .status);
  }
}
