package com.productimage.business.runtime;

public final class Problem extends RuntimeException {
  private static final long serialVersionUID = 1L;
  public final int status;
  public final String code;

  public Problem(int status, String code) {
    super(code);
    this.status = status;
    this.code = code;
  }
}
