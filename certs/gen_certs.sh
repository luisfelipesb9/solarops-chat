#!/usr/bin/env bash
# Generates the SolarOps CA and the server certificate (CN=localhost, SAN localhost/127.0.0.1).
# Usage: certs/gen_certs.sh [--force] [outdir]   (default outdir: the folder of this script)
# Idempotent: an existing CA is reused unless --force is given.
set -euo pipefail

FORCE=0
OUT=""
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    -h|--help) echo "uso: $0 [--force] [diretorio_saida]"; exit 0 ;;
    *) OUT="$arg" ;;
  esac
done
OUT="${OUT:-$(cd "$(dirname "$0")" && pwd)}"
mkdir -p "$OUT"
cd "$OUT"
umask 077

command -v openssl >/dev/null || { echo "openssl não encontrado" >&2; exit 1; }

# 1) Certificate authority (CA) of the plant
if [[ -f ca.key && -f ca.crt && $FORCE -eq 0 ]]; then
  echo "CA existente reutilizada em $OUT (use --force para recriar)"
else
  openssl genrsa -out ca.key 2048 2>/dev/null
  openssl req -x509 -new -key ca.key -sha256 -days 365 \
    -subj "/O=SolarOps/CN=SolarOps CA" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "subjectKeyIdentifier=hash" \
    -out ca.crt
  rm -f server.crt   # a new CA invalidates the old server certificate
  echo "CA criada: $OUT/ca.crt"
fi

# 2) Server certificate, signed by the CA (skipped if still valid for this CA)
if [[ -f server.key && -f server.crt ]] && openssl verify -CAfile ca.crt server.crt >/dev/null 2>&1; then
  echo "Certificado do servidor válido reutilizado: $OUT/server.crt"
else
  cat > server.ext <<'EOF'
basicConstraints=CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:localhost,IP:127.0.0.1
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
EOF
  openssl genrsa -out server.key 2048 2>/dev/null
  openssl req -new -key server.key -subj "/O=SolarOps/CN=localhost" -out server.csr
  openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
    -days 365 -sha256 -extfile server.ext -out server.crt 2>/dev/null
  rm -f server.csr server.ext
  echo "Certificado do servidor criado: $OUT/server.crt"
fi

chmod 600 ca.key server.key
chmod 644 ca.crt server.crt
openssl verify -CAfile ca.crt server.crt
