package com.productimage.business.runtime;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.SecureRandom;
import java.util.Base64;
import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;

/** AES-256-GCM at rest; the master key stays outside the database, logs, and responses. */
final class ProviderCrypto {
  private ProviderCrypto() {}

  static byte[] masterKey(String key, String keyFile) {
    try {
      if (key.isBlank() == keyFile.isBlank()) throw new IllegalArgumentException();
      byte[] bytes;
      if (keyFile.isBlank()) {
        bytes = Base64.getDecoder().decode(key.strip());
      } else {
        var path = Path.of(keyFile.strip());
        if (!path.isAbsolute()) throw new IllegalArgumentException();
        bytes = Base64.getDecoder().decode(Files.readString(path).strip());
      }
      if (bytes.length != 32) throw new IllegalArgumentException();
      return bytes;
    } catch (Exception ex) {
      throw new IllegalStateException("Invalid or missing provider master key configuration");
    }
  }

  static String encrypt(byte[] master, String plaintext) {
    try {
      byte[] nonce = new byte[12];
      new SecureRandom().nextBytes(nonce);
      var cipher = Cipher.getInstance("AES/GCM/NoPadding");
      cipher.init(
          Cipher.ENCRYPT_MODE, new SecretKeySpec(master, "AES"), new GCMParameterSpec(128, nonce));
      var sealed = cipher.doFinal(plaintext.getBytes(StandardCharsets.UTF_8));
      var combined = new byte[nonce.length + sealed.length];
      System.arraycopy(nonce, 0, combined, 0, nonce.length);
      System.arraycopy(sealed, 0, combined, nonce.length, sealed.length);
      return Base64.getEncoder().encodeToString(combined);
    } catch (Exception ex) {
      throw new IllegalStateException("Provider secret encryption failed");
    }
  }

  static String decrypt(byte[] master, String sealed) {
    try {
      var combined = Base64.getDecoder().decode(sealed);
      if (combined.length <= 12) throw new IllegalArgumentException();
      var cipher = Cipher.getInstance("AES/GCM/NoPadding");
      cipher.init(
          Cipher.DECRYPT_MODE,
          new SecretKeySpec(master, "AES"),
          new GCMParameterSpec(128, combined, 0, 12));
      return new String(cipher.doFinal(combined, 12, combined.length - 12), StandardCharsets.UTF_8);
    } catch (Exception ex) {
      throw new IllegalStateException("Provider secret decryption failed");
    }
  }

  static String mask(String secret) {
    return secret.length() >= 12 ? "****" + secret.substring(secret.length() - 4) : "****";
  }
}
