package com.productimage.business.runtime;

/** Replace this adapter when D-05 is decided; callers never select their own actor ID. */
@FunctionalInterface
public interface UserAuthenticator {
  String authenticate(String authorization);
}
