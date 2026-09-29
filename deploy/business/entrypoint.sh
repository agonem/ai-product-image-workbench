#!/bin/sh
# Secrets arrive as files (compose secrets) and are exported only inside this process.
set -eu
DB_PASSWORD="$(cat /run/secrets/db_password)"
RUNTIME_WORKER_TOKEN="$(cat /run/secrets/worker_token)"
SERVER_SSL_KEY_STORE_PASSWORD="$(cat /run/secrets/keystore_password)"
export DB_PASSWORD RUNTIME_WORKER_TOKEN SERVER_SSL_KEY_STORE_PASSWORD
exec java -Djava.io.tmpdir=/tmp -jar /app/business-service.jar
