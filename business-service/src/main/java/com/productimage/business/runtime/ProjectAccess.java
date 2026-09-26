package com.productimage.business.runtime;

import org.springframework.jdbc.core.JdbcTemplate;

/** Owner-only project access; account administrators receive no implicit cross-project access. */
public final class ProjectAccess {
  private final JdbcTemplate jdbc;

  ProjectAccess(JdbcTemplate jdbc) {
    this.jdbc = jdbc;
  }

  void active(String actor) {
    if (jdbc.queryForObject(
            "SELECT count(*) FROM users WHERE id=? AND status='ACTIVE'", Long.class, actor)
        != 1) {
      throw new Problem(401, "UNAUTHORIZED");
    }
  }

  void require(String actor, String project) {
    if (jdbc.queryForObject(
            "SELECT count(*) FROM projects p JOIN users u ON u.id=p.owner_id WHERE p.id=? AND u.id=? AND u.status='ACTIVE'",
            Long.class,
            project,
            actor)
        != 1) {
      throw new Problem(404, "NOT_FOUND");
    }
  }
}
