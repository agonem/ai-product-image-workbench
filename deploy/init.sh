#!/usr/bin/env bash
# One-time preparation on the server: private secrets, internal TLS certificates, first admin.
# Usage: ./init.sh <server-ip> <admin-username>
# Other ports: HTTP_PORT=8080 HTTPS_PORT=8443 ./init.sh <server-ip> <admin-username>
# Nothing is overwritten; everything private goes to ./secrets (mode 0700, files 0600).
set -euo pipefail
# Git Bash on Windows would rewrite "/CN=..." subjects as paths; harmless elsewhere.
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")"

SERVER_IP="${1:-}"
ADMIN="${2:-}"
if ! [[ "$SERVER_IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || [ -z "$ADMIN" ]; then
  echo "Usage: ./init.sh <server-ip> <admin-username>   e.g. ./init.sh 192.168.1.20 admin" >&2
  exit 2
fi
if ! [[ "$ADMIN" =~ ^[a-z0-9][a-z0-9_-]{0,63}$ ]]; then
  echo "Admin username: lowercase letters, digits, '_' or '-', at most 64 characters." >&2
  exit 2
fi
if [ -e secrets ] || [ -e .env ]; then
  echo "secrets/ or .env already exists; refusing to overwrite an existing installation." >&2
  exit 1
fi
HTTP_PORT="${HTTP_PORT:-80}"
HTTPS_PORT="${HTTPS_PORT:-443}"
for port in "$HTTP_PORT" "$HTTPS_PORT"; do
  if ! [[ "$port" =~ ^[0-9]{1,5}$ ]] || [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
    echo "HTTP_PORT and HTTPS_PORT must be numbers between 1 and 65535." >&2
    exit 2
  fi
  if command -v ss >/dev/null && [ -n "$(ss -ltnH "( sport = :$port )")" ]; then
    echo "Port $port is already in use on this server. Choose another, for example:" >&2
    echo "  HTTP_PORT=8080 HTTPS_PORT=8443 ./init.sh $SERVER_IP $ADMIN" >&2
    exit 2
  fi
done
[ "$HTTP_PORT" != "$HTTPS_PORT" ] || { echo "HTTP_PORT and HTTPS_PORT must differ." >&2; exit 2; }
PYTHON="${PYTHON:-python3}"
command -v openssl >/dev/null || { echo "openssl is required" >&2; exit 1; }
command -v "$PYTHON" >/dev/null || { echo "$PYTHON is required" >&2; exit 1; }

# Everything is built in a staging directory and only moved into place when complete, so a
# failed run leaves nothing behind and can simply be repeated.
STAGE=secrets.partial
LOG="$STAGE/openssl.log"
rm -rf "$STAGE"
umask 077
mkdir -p "$STAGE/bootstrap"
finished=0
cleanup() {
  if [ "$finished" != 1 ]; then
    if [ -s "$LOG" ]; then
      echo "--- openssl output ---" >&2
      tail -n 20 "$LOG" >&2
    fi
    rm -rf "$STAGE"
    echo "init.sh failed; nothing was installed. Fix the problem above and run it again." >&2
  fi
}
trap cleanup EXIT
ssl() { openssl "$@" >>"$LOG" 2>&1; }

random() { openssl rand -hex 32; }
printf '%s' "$(random)" > "$STAGE/db_password"
printf '%s' "$(random)" > "$STAGE/worker_token"
printf '%s' "$(random)" > "$STAGE/keystore_password"
# AES-256 key for stored provider API keys; losing it makes saved keys unreadable.
openssl rand -base64 32 | tr -d '\n' > "$STAGE/provider_master_key"

# Certificates use only the configuration written here (never the system openssl.cnf or
# -addext), so OpenSSL 1.1.1 and 3.x produce the same, duplicate-free extensions.
# Internal CA, limited by name constraints to this server's IP and the internal API name.
cat > "$STAGE/ca.cnf" <<EOF
[req]
distinguished_name = dn
x509_extensions = ext
prompt = no
[dn]
CN = Product Image Workbench CA
[ext]
basicConstraints = critical,CA:TRUE,pathlen:0
keyUsage = critical,keyCertSign,cRLSign
subjectKeyIdentifier = hash
nameConstraints = critical,permitted;IP:${SERVER_IP}/255.255.255.255,permitted;DNS:business
EOF
ssl req -x509 -new -config "$STAGE/ca.cnf" -newkey rsa:3072 -nodes -sha256 -days 3650 \
  -keyout "$STAGE/ca.key" -out "$STAGE/ca.pem"

issue() { # name, subjectAltName, common name (no dots, so it is never read as a host name)
  cat > "$STAGE/$1.cnf" <<EOF
[req]
distinguished_name = dn
prompt = no
[dn]
CN = $3
[ext]
subjectAltName = $2
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = serverAuth
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always
EOF
  ssl req -new -config "$STAGE/$1.cnf" -newkey rsa:2048 -nodes \
    -keyout "$STAGE/$1.key" -out "$STAGE/$1.csr"
  ssl x509 -req -in "$STAGE/$1.csr" -CA "$STAGE/ca.pem" -CAkey "$STAGE/ca.key" \
    -CAcreateserial -days 825 -sha256 -extfile "$STAGE/$1.cnf" -extensions ext \
    -out "$STAGE/$1.crt"
  rm -f "$STAGE/$1.csr" "$STAGE/$1.cnf"
}
issue web "IP:${SERVER_IP}" workbench-web
issue business "DNS:business" business
ssl verify -CAfile "$STAGE/ca.pem" -verify_ip "$SERVER_IP" "$STAGE/web.crt"
ssl verify -CAfile "$STAGE/ca.pem" -verify_hostname business "$STAGE/business.crt"
# Explicit modern PKCS12 algorithms (OpenSSL 1.1.1 defaults to legacy RC2/3DES).
ssl pkcs12 -export -name business -inkey "$STAGE/business.key" -in "$STAGE/business.crt" \
  -keypbe AES-256-CBC -certpbe AES-256-CBC -macalg sha256 \
  -out "$STAGE/business.p12" -passout "file:$STAGE/keystore_password"
rm -f "$STAGE/business.key" "$STAGE/business.crt" "$STAGE/ca.cnf" "$LOG"

# First administrator: only a salted PBKDF2 verifier is stored, never the password.
echo "Choose the first administrator password (6-15 characters):"
if [ -t 0 ]; then
  "$PYTHON" ../scripts/prod_accounts.py --file "$STAGE/bootstrap/admin.json" --username "$ADMIN"
else
  "$PYTHON" ../scripts/prod_accounts.py --file "$STAGE/bootstrap/admin.json" \
    --username "$ADMIN" --password-stdin
fi

mv "$STAGE" secrets
mkdir -p data/objects data/journal
# Containers run as this user so they can read the secrets and write ./data.
cat > .env <<EOF
RUN_UID=$(id -u)
RUN_GID=$(id -g)
SERVER_IP=${SERVER_IP}
HTTPS_PORT=${HTTPS_PORT}
HTTP_PORT=${HTTP_PORT}
OPENROUTER_PROXY_URL=
EOF
chmod 600 .env
# Public certificate for colleagues' computers (removes the browser warning once trusted).
umask 022
cp secrets/ca.pem workbench-ca.crt
chmod 644 workbench-ca.crt
finished=1

echo
URL="https://${SERVER_IP}/"
[ "$HTTPS_PORT" = 443 ] || URL="https://${SERVER_IP}:${HTTPS_PORT}/"
echo "Done. Next: docker compose up -d --build   then open ${URL}"
echo "Keep ./secrets private and backed up; never commit or share it (except workbench-ca.crt)."
