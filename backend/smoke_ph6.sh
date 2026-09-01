#!/bin/bash
# Phase 6 purchase-requisition smoke: start uvicorn, run the business chain
# against the real HTTP server (dev DB), report PASS/FAIL per step.
set -u
cd "C:/Users/Administrator/Desktop/8.26/backend"
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002 > /tmp/uvicorn_ph6.log 2>&1 &
UV=$!
sleep 5

J() { python -c "import sys,json;print(json.load(sys.stdin)$1)"; }
BASE=http://127.0.0.1:8002/api/v1
TOKEN=$(curl -s -X POST $BASE/auth/login -H "Content-Type: application/json" -d '{"username":"admin","password":"admin123"}' | J "['data']['access_token']")
ZTOKEN=$(curl -s -X POST $BASE/auth/login -H "Content-Type: application/json" -d '{"username":"zhangsan","password":"demo123"}' | J "['data']['access_token']")
WTOKEN=$(curl -s -X POST $BASE/auth/login -H "Content-Type: application/json" -d '{"username":"zhaoliu","password":"demo123"}' | J "['data']['access_token']")
H="Authorization: Bearer $TOKEN"; ZH="Authorization: Bearer $ZTOKEN"; WH="Authorization: Bearer $WTOKEN"
PASS=0; FAIL=0
check() { if [ "$2" = "$3" ]; then PASS=$((PASS+1)); echo "PASS  $1  ($3)";
else FAIL=$((FAIL+1)); echo "FAIL  $1  expected=$2 actual=$3"; fi; }

# material
MID=$(curl -s -X POST $BASE/materials -H "$H" -H "Content-Type: application/json" -d '{"material_name":"冒烟电阻P6","unit":"pcs","category":"电子件"}' | J "['data']['id']")
check "material created" 1 "$([ -n "$MID" ] && [ "$MID" -gt 0 ] && echo 1 || echo 0)"

# create PR -> PR-YYYYMMDD-0001, amount 10*12.3456=123.46
PR=$(curl -s -X POST $BASE/purchase-requisitions -H "$ZH" -H "Content-Type: application/json" -d "{\"reason\":\"冒烟\",\"items\":[{\"material_id\":$MID,\"requested_quantity\":\"10\",\"estimated_unit_price\":\"12.3456\"}]}")
PID=$(echo "$PR" | J "['data']['id']")
PRNO=$(echo "$PR" | J "['data']['pr_no']")
check "PR code format PR-YYYYMMDD-0001" 1 "$(echo "$PRNO" | grep -cE '^PR-[0-9]{8}-[0-9]{4}$')"
check "PR amount server-computed 123.46" "123.46" "$(echo "$PR" | J "['data']['total_estimated_amount']")"
check "PR status DRAFT" "DRAFT" "$(echo "$PR" | J "['data']['status']")"
check "PR applicant is zhangsan(2)" 2 "$(echo "$PR" | J "['data']['applicant_id']")"
check "PR department snapshot present" 1 "$([ -n "$(echo "$PR" | J "['data']['department_name']")" ] && echo 1 || echo 0)"

# detail
DET=$(curl -s $BASE/purchase-requisitions/$PID -H "$ZH")
check "detail pr_no matches" "$PRNO" "$(echo "$DET" | J "['data']['pr_no']")"

# list filter by pr_no (applicant sees own)
LS=$(curl -s --get $BASE/purchase-requisitions --data-urlencode "pr_no=$PRNO" -H "$ZH" | J "['data']['total']")
check "list pr_no filter total=1" 1 "$LS"

# edit: 5*2 + 3*1.5 = 14.50, version 1->2
ITEM1=$(echo "$PR" | J "['data']['items'][0]['id']")
UPD=$(curl -s -X PUT $BASE/purchase-requisitions/$PID -H "$ZH" -H "Content-Type: application/json" -d "{\"version\":1,\"reason\":\"改\",\"items\":[{\"id\":$ITEM1,\"material_id\":$MID,\"requested_quantity\":\"5\",\"estimated_unit_price\":\"2\"},{\"material_id\":$MID,\"requested_quantity\":\"3\",\"estimated_unit_price\":\"1.5\"}]}")
check "edit total 14.50" "14.50" "$(echo "$UPD" | J "['data']['total_estimated_amount']")"
check "edit version=2" 2 "$(echo "$UPD" | J "['data']['version']")"
check "edit items=2" 2 "$(echo "$UPD" | python -c "import sys,json;print(len(json.load(sys.stdin)['data']['items']))")"

# stale version -> 409
STALE=$(curl -s -o /dev/null -w "%{http_code}" -X PUT $BASE/purchase-requisitions/$PID -H "$ZH" -H "Content-Type: application/json" -d "{\"version\":1,\"items\":[{\"material_id\":$MID,\"requested_quantity\":\"1\",\"estimated_unit_price\":\"1\"}]}")
check "stale version 409" 409 "$STALE"

# submit -> PENDING + submitted_at + version=3
SUB=$(curl -s -X POST $BASE/purchase-requisitions/$PID/submit -H "$ZH")
check "submit status PENDING" "PENDING" "$(echo "$SUB" | J "['data']['status']")"
check "submit submitted_at set" 1 "$([ "$(echo "$SUB" | J "['data']['submitted_at']")" != "null" ] && echo 1 || echo 0)"
check "submit version=3" 3 "$(echo "$SUB" | J "['data']['version']")"

# resubmit 409
RS=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/purchase-requisitions/$PID/submit -H "$ZH")
check "resubmit 409" 409 "$RS"

# edit PENDING 409
EP=$(curl -s -o /dev/null -w "%{http_code}" -X PUT $BASE/purchase-requisitions/$PID -H "$ZH" -H "Content-Type: application/json" -d "{\"version\":3,\"items\":[{\"material_id\":$MID,\"requested_quantity\":\"1\",\"estimated_unit_price\":\"1\"}]}")
check "edit pending 409" 409 "$EP"

# cancel a fresh DRAFT -> CANCELLED
PR2=$(curl -s -X POST $BASE/purchase-requisitions -H "$ZH" -H "Content-Type: application/json" -d "{\"items\":[{\"material_id\":$MID,\"requested_quantity\":\"1\",\"estimated_unit_price\":\"1\"}]}")
PID2=$(echo "$PR2" | J "['data']['id']")
CC=$(curl -s -X POST $BASE/purchase-requisitions/$PID2/cancel -H "$ZH")
check "cancel -> CANCELLED" "CANCELLED" "$(echo "$CC" | J "['data']['status']")"
CS=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/purchase-requisitions/$PID2/submit -H "$ZH")
check "cancelled cannot submit 409" 409 "$CS"

# rbac: warehouse cannot create PR
RB=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/purchase-requisitions -H "$WH" -H "Content-Type: application/json" -d "{\"items\":[{\"material_id\":$MID,\"requested_quantity\":\"1\",\"estimated_unit_price\":\"1\"}]}")
check "warehouse create PR 403" 403 "$RB"

# audit rows exist for the PR
AUD=$(curl -s --get $BASE/purchase-requisitions -H "$H" --data-urlencode "pr_no=$PRNO" | J "['data']['total']")
check "admin sees PR in list" 1 "$([ "$AUD" -ge 1 ] && echo 1 || echo 0)"

echo "----------------------------------------"
echo "Phase 6 smoke: PASS=$PASS FAIL=$FAIL"
kill $UV 2>/dev/null
[ "$FAIL" -eq 0 ] && echo "SMOKE OK" || { echo "SMOKE FAILED"; exit 1; }
