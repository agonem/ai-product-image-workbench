package com.productimage.business.runtime;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.nio.charset.StandardCharsets;
import java.util.Base64;
import org.junit.jupiter.api.Test;

public class ProviderCryptoTest {
  private static byte[] master(String value) {
    return value.getBytes(StandardCharsets.US_ASCII);
  }

  @Test
  void encryptsAndDecryptsWithAuthenticatedCipher() {
    byte[] master = master("12345678901234567890123456789012");
    String sealed = ProviderCrypto.encrypt(master, "sk-secret-credential");
    assertTrue(ProviderCrypto.decrypt(master, sealed).equals("sk-secret-credential"));
    assertNotEquals("sk-secret-credential", sealed);
    byte[] other = master("22345678901234567890123456789012");
    assertThrows(IllegalStateException.class, () -> ProviderCrypto.decrypt(other, sealed));
  }

  @Test
  void masterKeyRequiresExactlyOneThirtyTwoByteSource() {
    assertThrows(IllegalStateException.class, () -> ProviderCrypto.masterKey("", "relative/path"));
    assertThrows(IllegalStateException.class, () -> ProviderCrypto.masterKey("abc", "def"));
    assertThrows(IllegalStateException.class, () -> ProviderCrypto.masterKey("short", ""));
    assertEquals(
        "12345678901234567890123456789012",
        new String(
            ProviderCrypto.masterKey(
                Base64.getEncoder()
                    .encodeToString(
                        "12345678901234567890123456789012".getBytes(StandardCharsets.US_ASCII)),
                ""),
            StandardCharsets.US_ASCII));
  }

  @Test
  void masksNeverRevealLongSecrets() {
    assertEquals("****last", ProviderCrypto.mask("something-whose-last"));
    assertEquals("****", ProviderCrypto.mask("short"));
  }
}
