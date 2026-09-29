#!/usr/bin/env bash
# One-time preparation on the server: private secrets, internal TLS certificates, first admin.
# Usage: ./init.sh <server-ip> <admin-username>
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
PYTHON="${PYTHON:-python3}"
command -v openssl >/dev/null || { echo "openssl is required" >&2; exit 1; }
command -v "$PYTHON" >/dev/null || { echo "$PYTHON is required" >&2; exit 1; }

umask 077
mkdir -p secrets/bootstrap data/objects data/journal

random() { openssl rand -hex 32; }
printf '%s' "$(random)" > secrets/db_password
printf '%s' "$(random)" > secrets/worker_token
printf '%s' "$(random)" > secrets/keystore_password
# AES-256 key for stored provider API keys; losing it makes saved keys unreadable.
openssl rand -base64 32 | tr -d '\n' > secrets/provider_master_key

# Internal CA, limited by name constraints to this server's IP and the internal API name.
openssl req -x509 -new -newkey rsa:3072 -nodes -sha256 -days 3650 \
  -keyout secrets/ca.key -out secrets/ca.pem -subj "/CN=Product Image Workbench CA" \
  -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -addext "nameConstraints=critical,permitted;IP:${SERVER_IP}/255.255.255.255,permitted;DNS:business" \
  2>/dev/null

issue() { # name, subjectAltName, common name (no dots, so it is never read as a host name)
  openssl req -new -newkey rsa:2048 -nodes -keyout "secrets/$1.key" -out "secrets/$1.csr" \
    -subj "/CN=$3" 2>/dev/null
  printf '%s\n' "subjectAltName=$2" "basicConstraints=critical,CA:FALSE" \
    "keyUsage=critical,digitalSignature,keyEncipherment" "extendedKeyUsage=serverAuth" \
    > "secrets/$1.ext"
  openssl x509 -req -in "secrets/$1.csr" -CA secrets/ca.pem -CAkey secrets/ca.key \
    -CAcreateserial -days 825 -sha256 -extfile "secrets/$1.ext" -out "secrets/$1.crt" 2>/dev/null
  rm -f "secrets/$1.csr" "secrets/$1.ext"
}
issue web "IP:${SERVER_IP}" workbench-web
issue business "DNS:business" business
openssl pkcs12 -export -name business -inkey secrets/business.key -in secrets/business.crt \
  -out secrets/business.p12 -passout file:secrets/keystore_password
rm -f secrets/business.key secrets/business.crt
openssl verify -CAfile secrets/ca.pem -verify_ip "$SERVER_IP" secrets/web.crt >/dev/null

# First administrator: only a salted PBKDF2 verifier is stored, never the password.
echo "Choose the first administrator password (15-128 characters):"
if [ -t 0 ]; then
  "$PYTHON" ../scripts/prod_accounts.py --file secrets/bootstrap/admin.json --username "$ADMIN"
else
  "$PYTHON" ../scripts/prod_accounts.py --file secrets/bootstrap/admin.json --username "$ADMIN" \
    --password-stdin
fi

# Containers run as this user so they can read the secrets and write ./data.
cat > .env <<EOF
RUN_UID=$(id -u)
RUN_GID=$(id -g)
SERVER_IP=${SERVER_IP}
HTTPS_PORT=443
HTTP_PORT=80
OPENROUTER_PROXY_URL=
EOF
chmod 600 .env
# Public certificate for colleagues' computers (removes the browser warning once trusted).
umask 022
cp secrets/ca.pem workbench-ca.crt

echo
echo "Done. Next: docker compose up -d --build   then open https://${SERVER_IP}/"
echo "Keep ./secrets private and backed up; never commit or share it (except workbench-ca.crt)."
