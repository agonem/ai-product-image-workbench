package com.productimage.business.runtime;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.FileAlreadyExistsException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import javax.imageio.ImageIO;
import javax.imageio.stream.MemoryCacheImageInputStream;

/** Private local storage adapter. No image transformation is performed here. */
public final class LocalObjectStore {
  public record Info(String objectKey, String sha256, int width, int height) {}

  private final Path root;
  private final int maxBytes;
  private final long maxPixels;

  public LocalObjectStore(Path root, int maxBytes, long maxPixels) {
    this.maxBytes = maxBytes;
    this.maxPixels = maxPixels;
    try {
      Files.createDirectories(root);
      this.root = root.toRealPath();
    } catch (IOException ex) {
      throw new IllegalStateException("Cannot initialize private object store");
    }
  }

  private Path path(String key, boolean createParents) throws IOException {
    if (!key.matches("[A-Za-z0-9][A-Za-z0-9/_.-]*")
        || key.matches(".*(^|/)\\.{1,2}(/|$).*")
        || key.endsWith("/")) {
      throw new Problem(400, "INVALID_ASSET");
    }
    Path target = root.resolve(key).normalize();
    if (!target.startsWith(root) || target.equals(root)) throw new Problem(400, "INVALID_ASSET");
    Path current = root;
    for (Path part : root.relativize(target)) {
      current = current.resolve(part);
      if (Files.isSymbolicLink(current)
          || (Files.exists(current, LinkOption.NOFOLLOW_LINKS)
              && !current.toRealPath().equals(current))) {
        throw new Problem(400, "INVALID_ASSET");
      }
      if (!current.equals(target) && createParents) {
        try {
          Files.createDirectory(current);
        } catch (FileAlreadyExistsException ex) {
          if (!Files.isDirectory(current, LinkOption.NOFOLLOW_LINKS)) {
            throw new Problem(400, "INVALID_ASSET");
          }
        }
      }
    }
    return target;
  }

  public byte[] read(String key) {
    try {
      Path target = path(key, false);
      try (var input = Files.newInputStream(target, LinkOption.NOFOLLOW_LINKS)) {
        byte[] bytes = input.readNBytes(maxBytes + 1);
        if (bytes.length > maxBytes) throw new Problem(413, "INVALID_ASSET");
        return bytes;
      }
    } catch (IOException ex) {
      throw new Problem(422, "OUTPUT_VALIDATION_FAILED");
    }
  }

  public Info inspect(String key, byte[] data) {
    if (data.length == 0 || data.length > maxBytes) throw new Problem(413, "INVALID_ASSET");
    try (var input = new MemoryCacheImageInputStream(new ByteArrayInputStream(data))) {
      var readers = ImageIO.getImageReaders(input);
      if (!readers.hasNext()) throw new Problem(422, "OUTPUT_VALIDATION_FAILED");
      var reader = readers.next();
      try {
        reader.setInput(input, true, true);
        String format = reader.getFormatName();
        if (!format.equalsIgnoreCase("png") && !format.equalsIgnoreCase("jpeg")) {
          throw new Problem(422, "OUTPUT_VALIDATION_FAILED");
        }
        int width = reader.getWidth(0);
        int height = reader.getHeight(0);
        if (width < 1 || height < 1 || (long) width * height > maxPixels) {
          throw new Problem(413, "OUTPUT_VALIDATION_FAILED");
        }
        reader.read(0); // Decode only to reject damaged content, never transform/re-encode.
        return new Info(key, Json.hash(data), width, height);
      } finally {
        reader.dispose();
      }
    } catch (IOException | IllegalArgumentException ex) {
      throw new Problem(422, "OUTPUT_VALIDATION_FAILED");
    }
  }

  public Info put(String key, byte[] data) {
    Info info = inspect(key, data);
    Path temporary = null;
    try {
      Path target = path(key, true);
      temporary = Files.createTempFile(root, ".pending-", ".bin");
      try (var channel = FileChannel.open(temporary, StandardOpenOption.WRITE)) {
        ByteBuffer buffer = ByteBuffer.wrap(data);
        while (buffer.hasRemaining()) channel.write(buffer);
        channel.force(true);
      }
      try {
        Files.createLink(target, temporary);
      } catch (FileAlreadyExistsException ex) {
        if (!Json.hash(read(key)).equals(info.sha256())) throw new Problem(409, "TASK_CONFLICT");
      }
      return info;
    } catch (IOException | UnsupportedOperationException ex) {
      throw new Problem(503, "STORAGE_UNAVAILABLE");
    } finally {
      if (temporary != null) {
        try {
          Files.deleteIfExists(temporary);
        } catch (IOException ex) {
          /* Orphan staging file is not a published object. */
        }
      }
    }
  }
}
