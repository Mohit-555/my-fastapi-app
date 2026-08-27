#!/usr/bin/env bash
# Send synthetic fixed-parameter telemetry to the RDPMS webhook.
#
# Usage:
#   ./send_test_telemetry.sh [BASE_URL] [STNGW_ID] [ASSET_TYPE_HEX] [ASSET_NUM_HEX]
# Defaults: http://localhost:8000  07011200(CNB)  20(DC Track Circuit)  0C(TC-12)
#
# API key is read from .env (API_KEY=...) or overridden via env var.

BASE_URL="${1:-http://localhost:8000}"
STNGW_ID="${2:-07011200}"
TYPE_HEX="${3:-20}"
NUM_HEX="${4:-0C}"

API_KEY="${API_KEY:-$(grep -E '^API_KEY=' "$(dirname "$0")/../.env" | cut -d= -f2)}"
TS=$(date -u +"%d-%m-%Y %H:%M:%S.000")
RQI="RQI-TEST-$(date +%s)"

# Slightly randomized values so charts visibly move between runs
I_AVG=$(awk -v s=$RANDOM 'BEGIN{printf "%.2f", 3.8+rand()*1.2}')
I_PEAK=$(awk -v s=$RANDOM 'BEGIN{printf "%.2f", 6.2+rand()*1.5}')
V_BATT=$(awk -v s=$RANDOM 'BEGIN{printf "%.2f", 12.1+rand()*0.5}')
STROKE=$(awk -v s=$RANDOM 'BEGIN{printf "%d", 1950+rand()*120}')
TEMP=$(awk -v s=$RANDOM 'BEGIN{printf "%.1f", 36+rand()*6}')

curl -s -X POST "${BASE_URL}/webhook/parameters/fixed" \
  -H "X-API-Key: ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{
    \"rqi\": \"${RQI}\",
    \"stngw_id\": \"${STNGW_ID}\",
    \"parameters\": [
      {\"para_id\": \"${TYPE_HEX}${NUM_HEX}0101\", \"prv\": [${I_AVG}],   \"prt\": [\"${TS}\"]},
      {\"para_id\": \"${TYPE_HEX}${NUM_HEX}0201\", \"prv\": [${I_PEAK}],  \"prt\": [\"${TS}\"]},
      {\"para_id\": \"${TYPE_HEX}${NUM_HEX}0301\", \"prv\": [${STROKE}],  \"prt\": [\"${TS}\"]},
      {\"para_id\": \"${TYPE_HEX}${NUM_HEX}0401\", \"prv\": [${V_BATT}],  \"prt\": [\"${TS}\"]},
      {\"para_id\": \"${TYPE_HEX}${NUM_HEX}0501\", \"prv\": [${TEMP}],    \"prt\":[\"${TS}\"]}
    ]
  }"
echo
echo "Sent: stngw=${STNGW_ID} asset_prefix=${TYPE_HEX}${NUM_HEX} @ ${TS}"
