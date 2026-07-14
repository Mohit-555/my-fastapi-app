#!/usr/bin/env bash
# generate-test-certs.sh
#
# Generates a throwaway CA + one server certificate + one client (gateway)
# certificate, for TESTING the mTLS setup in nginx-mtls.conf.example against
# a local/staging RDPMS instance.
#
# THIS IS NOT PRODUCTION-GRADE PKI. For production, your Vendor CA should be
# run properly (offline root, intermediate signing CA, real revocation via
# CRL/OCSP, HSM-backed keys if your org requires it) — this script is only
# meant to let you flip REQUIRE_MTLS=true and see the whole flow work
# end-to-end before your real CA process is in place.
#
# Usage:
#   chmod +x generate-test-certs.sh
#   ./generate-test-certs.sh <gateway-cn>
#   e.g. ./generate-test-certs.sh GW-LJN-01
#
# Produces (in ./certs/):
#   vendor-ca.crt / vendor-ca.key   — the test CA (goes on the nginx server)
#   rdpms-server.crt / .key         — RDPMS's own server cert (goes on nginx server)
#   <gateway-cn>.crt / .key / .p12  — the gateway's client cert (goes on the gateway device)
#
# After running:
#   1. Copy vendor-ca.crt + rdpms-server.crt/.key to the nginx server per
#      nginx-mtls.conf.example.
#   2. Give the gateway team <gateway-cn>.p12 (password: "changeit" below —
#      change it) to load into their device's TLS client config.
#   3. In RDPMS, set that gateway's mtls_cn column (in the `gateways` table)
#      to exactly <gateway-cn>, so _check_gateway_cert_binding() in
#      app/routers/webhook.py enforces that THIS gateway can only present
#      THIS certificate.

set -euo pipefail

GATEWAY_CN="${1:?Usage: ./generate-test-certs.sh <gateway-cn>, e.g. GW-LJN-01}"
OUT_DIR="./certs"
DAYS_CA=3650
DAYS_CERT=825   # keep well under typical 398-day browser/TLS max lifetime guidance; adjust per your policy
P12_PASSWORD="changeit"   # CHANGE THIS before using outside a quick local test

mkdir -p "$OUT_DIR"
cd "$OUT_DIR"

echo "== 1. Generating test Vendor CA =="
openssl genrsa -out vendor-ca.key 4096
openssl req -x509 -new -nodes -key vendor-ca.key -sha256 -days "$DAYS_CA" \
    -subj "/C=IN/O=Softflew Technology (TEST CA)/CN=RDPMS Test Vendor CA" \
    -out vendor-ca.crt

echo "== 2. Generating RDPMS server certificate (signed by test CA) =="
openssl genrsa -out rdpms-server.key 2048
openssl req -new -key rdpms-server.key \
    -subj "/C=IN/O=Softflew Technology/CN=rdpms.yourdomain.example" \
    -out rdpms-server.csr
openssl x509 -req -in rdpms-server.csr -CA vendor-ca.crt -CAkey vendor-ca.key \
    -CAcreateserial -out rdpms-server.crt -days "$DAYS_CERT" -sha256
rm rdpms-server.csr

echo "== 3. Generating gateway client certificate for CN=$GATEWAY_CN =="
openssl genrsa -out "${GATEWAY_CN}.key" 2048
openssl req -new -key "${GATEWAY_CN}.key" \
    -subj "/C=IN/O=Softflew Technology/CN=${GATEWAY_CN}" \
    -out "${GATEWAY_CN}.csr"
openssl x509 -req -in "${GATEWAY_CN}.csr" -CA vendor-ca.crt -CAkey vendor-ca.key \
    -CAcreateserial -out "${GATEWAY_CN}.crt" -days "$DAYS_CERT" -sha256
rm "${GATEWAY_CN}.csr"

# Bundle into a .p12 for easy loading onto embedded/gateway hardware.
openssl pkcs12 -export \
    -inkey "${GATEWAY_CN}.key" -in "${GATEWAY_CN}.crt" -certfile vendor-ca.crt \
    -out "${GATEWAY_CN}.p12" -passout pass:"$P12_PASSWORD"

echo
echo "Done. Files written to $OUT_DIR/:"
ls -la
echo
echo "Next steps:"
echo "  - nginx server needs: vendor-ca.crt, rdpms-server.crt, rdpms-server.key"
echo "  - Gateway '$GATEWAY_CN' needs: ${GATEWAY_CN}.p12 (password: $P12_PASSWORD — change this)"
echo "  - In RDPMS DB: UPDATE gateways SET mtls_cn = '${GATEWAY_CN}' WHERE stngw_id = '<its stngw_id>';"
