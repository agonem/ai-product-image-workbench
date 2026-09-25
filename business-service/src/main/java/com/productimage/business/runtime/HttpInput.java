package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.http.HttpServletRequest;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.StandardCharsets;

final class HttpInput {
  private HttpInput() {}

  static byte[] bytes(HttpServletRequest request, int maximum) {
    if (request.getContentLengthLong() > maximum) throw new Problem(413, "INVALID_ASSET");
    try {
      byte[] bytes = request.getInputStream().readNBytes(maximum + 1);
      if (bytes.length > maximum) throw new Problem(413, "INVALID_ASSET");
      if (request.getContentLengthLong() >= 0 && request.getContentLengthLong() != bytes.length)
        throw new Problem(400, "INVALID_CONTRACT");
      return bytes;
    } catch (IOException ex) {
      throw new Problem(400, "INVALID_CONTRACT");
    }
  }

  static JsonNode json(HttpServletRequest request, int maximum) {
    if (request.getContentType() == null
        || !request.getContentType().split(";", 2)[0].equalsIgnoreCase("application/json"))
      throw new Problem(415, "INVALID_CONTRACT");
    try {
      return Json.parse(
          StandardCharsets.UTF_8
              .newDecoder()
              .decode(ByteBuffer.wrap(bytes(request, maximum)))
              .toString());
    } catch (CharacterCodingException ex) {
      throw new Problem(400, "INVALID_CONTRACT");
    }
  }
}
