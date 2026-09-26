package com.productimage.business.runtime;

/** D08 authorization only. T10 must resolve trusted producer/role and delete transactionally. */
public final class ImageDeletionPolicy {
  private ImageDeletionPolicy() {}

  public static boolean allows(
      String actor, String producer, boolean active, String productionRole) {
    return active
        && actor != null
        && !actor.isBlank()
        && producer != null
        && !producer.isBlank()
        && ("USER".equals(productionRole) || "ADMIN".equals(productionRole))
        && (actor.equals(producer) || "ADMIN".equals(productionRole));
  }
}
