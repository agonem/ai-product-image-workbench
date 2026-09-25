package com.productimage.business.runtime;

import static org.junit.jupiter.api.Assertions.*;

import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import javax.imageio.ImageIO;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class LocalObjectStoreTest {
  @TempDir Path root;

  static byte[] png() throws Exception {
    var output = new ByteArrayOutputStream();
    ImageIO.write(new BufferedImage(2, 3, BufferedImage.TYPE_INT_RGB), "png", output);
    return output.toByteArray();
  }

  @Test
  void immutableContentAndMetadata() throws Exception {
    var store = new LocalObjectStore(root, 10000, 100);
    var info = store.put("outputs/a/0.png", png());
    assertEquals(2, info.width());
    assertEquals(3, info.height());
    assertEquals(info, store.put("outputs/a/0.png", png()));
    assertArrayEquals(png(), store.read("outputs/a/0.png"));
    var other = new ByteArrayOutputStream();
    ImageIO.write(new BufferedImage(3, 2, BufferedImage.TYPE_INT_RGB), "png", other);
    assertThrows(RuntimeException.class, () -> store.put("outputs/a/0.png", other.toByteArray()));
  }

  @Test
  void rejectsTraversalCorruptionAndBudgets() throws Exception {
    var store = new LocalObjectStore(root, 10000, 100);
    assertThrows(RuntimeException.class, () -> store.put("../escape.png", png()));
    assertThrows(RuntimeException.class, () -> store.put("bad.png", new byte[] {1, 2, 3}));
    assertThrows(
        RuntimeException.class, () -> new LocalObjectStore(root, 1, 100).put("big.png", png()));
    assertThrows(
        RuntimeException.class,
        () -> new LocalObjectStore(root, 10000, 1).put("pixels.png", png()));
    assertFalse(Files.exists(root.resolve("big.png")));
  }
}
