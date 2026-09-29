package com.productimage.business.runtime;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import javax.imageio.ImageIO;
import org.junit.jupiter.api.Test;

class CutoutServiceTest {
  private static final String TOKEN = "t".repeat(40);

  @Test
  void imageServiceUrlKeepsTlsOrLoopback() {
    assertDoesNotThrow(() -> CutoutService.validate("https://images.internal:8443", TOKEN));
    assertDoesNotThrow(() -> CutoutService.validate("http://127.0.0.1:8001", TOKEN));
    assertDoesNotThrow(() -> CutoutService.validate("http://localhost:8001", TOKEN));
    assertDoesNotThrow(() -> CutoutService.validate("http://[::1]:8001", TOKEN));
    for (String url :
        new String[] {
          "http://10.0.0.5:8001",
          "http://images.internal",
          "https://user@images.internal",
          "https://images.internal/path",
          "https://images.internal?x=1",
          "ftp://127.0.0.1"
        }) {
      assertThrows(IllegalStateException.class, () -> CutoutService.validate(url, TOKEN), url);
    }
    assertThrows(
        IllegalStateException.class, () -> CutoutService.validate("https://images", "short"));
  }

  private static byte[] png(int type, int width, int height) throws Exception {
    var out = new ByteArrayOutputStream();
    ImageIO.write(new BufferedImage(width, height, type), "png", out);
    return out.toByteArray();
  }

  @Test
  void onlyGrayscalePngWithSourceDimensionsIsAccepted() throws Exception {
    assertTrue(CutoutService.grayscalePng(png(BufferedImage.TYPE_BYTE_GRAY, 12, 7), 12, 7));
    assertFalse(CutoutService.grayscalePng(png(BufferedImage.TYPE_BYTE_GRAY, 12, 7), 7, 12));
    assertFalse(CutoutService.grayscalePng(png(BufferedImage.TYPE_INT_RGB, 12, 7), 12, 7));
    var jpeg = new ByteArrayOutputStream();
    ImageIO.write(new BufferedImage(12, 7, BufferedImage.TYPE_INT_RGB), "jpeg", jpeg);
    assertFalse(CutoutService.grayscalePng(jpeg.toByteArray(), 12, 7));
    assertFalse(CutoutService.grayscalePng(new byte[10], 12, 7));
  }
}
