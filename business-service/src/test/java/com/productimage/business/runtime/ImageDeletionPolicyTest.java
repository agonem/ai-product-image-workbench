package com.productimage.business.runtime;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

class ImageDeletionPolicyTest {
  @Test
  void producerAndProductionAdministratorHaveSeparateDeletionAuthorization() {
    assertTrue(ImageDeletionPolicy.allows("alice", "alice", true, "USER"));
    assertTrue(ImageDeletionPolicy.allows("admin", "alice", true, "ADMIN"));
    assertFalse(ImageDeletionPolicy.allows("bob", "alice", true, "USER"));
    assertFalse(ImageDeletionPolicy.allows("admin", "alice", false, "ADMIN"));
    assertFalse(ImageDeletionPolicy.allows(null, "alice", true, "ADMIN"));
    assertFalse(ImageDeletionPolicy.allows("alice", "alice", true, "UNKNOWN"));
    assertFalse(ImageDeletionPolicy.allows("admin", null, true, "ADMIN"));
  }
}
