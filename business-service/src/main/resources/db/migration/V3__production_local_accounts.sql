-- T04-PROD / PRD-G08. No production identity or credential is seeded by migration.
CREATE TABLE local_credentials (
    user_id opaque_id PRIMARY KEY REFERENCES users(id),
    username text NOT NULL UNIQUE CHECK (username ~ '^[a-z0-9][a-z0-9_-]{0,63}$'),
    salt text NOT NULL CHECK (salt ~ '^[0-9a-f]{32}$'),
    password_hash sha256_hash NOT NULL,
    role text NOT NULL CHECK (role IN ('ADMIN', 'USER'))
);
CREATE TABLE local_sessions (
    token_hash sha256_hash PRIMARY KEY,
    user_id opaque_id NOT NULL REFERENCES local_credentials(user_id),
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX local_sessions_user_idx ON local_sessions(user_id);
CREATE INDEX local_sessions_expiry_idx ON local_sessions(expires_at);
CREATE TABLE local_auth_throttle (
    id integer PRIMARY KEY CHECK (id = 1),
    window_started timestamptz NOT NULL,
    attempts integer NOT NULL CHECK (attempts > 0)
);
