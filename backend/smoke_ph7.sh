#!/bin/bash
# Phase 7 approval-workflow smoke: real uvicorn + dev DB business chain.
# Covers approve / reject / revise / resubmit / admin override / scoping /
# optimistic lock / material-disabled-after-submit.
set -u
cd "C:/Users/Administrator/Desktop/8.26/backend"
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8003 > /tmp/uvicorn_ph7.log 2>&1 &
UV=$!
sleep 5

J() { python -c "import sys,json;print(json.load(sys.stdin)$1)"; }
BASE=http://127.0.0.1:8003/api/v1
TOKEN=$(curl -s -X POST $BASE/auth/login -H "Content-Type: application/json" -d '{"username":"admin","password":"admin123"}' | J "['data']['access_token']")
ZTOKEN=$(curl -s -X POST $BASE/auth/login -H "Content-Type: application/json" -d '{"username":"zhangsan","password":"demo123"}' | J "['data']['access_token']")
LTOKEN=$(curl -s -X POST $BASE/auth/login -H "Content-Type: application/json" -d '{"username":"lisi","password":"demo123"}' | J "['data']['access_token']")
WTOKEN=$(curl -s -X POST $BASE/auth/login -H "Content-Type: application/json" -d '{"username":"wangwu","password":"demo123"}' | J "['data']['access_token']")
H="Authorization: Bearer $TOKEN"; ZH="Authorization: Bearer $ZTOKEN"
LH="Authorization: Bearer $LTOKEN"; WH="Authorization: Bearer $WTOKEN"
PASS=0; FAIL=0
check() { if [ "$2" = "$3" ]; then PASS=$((PASS+1)); echo "PASS  $1  ($3)";
else FAIL=$((FAIL+1)); echo "FAIL  $1  expected=$2 actual=$3"; fi; }

MID=$(curl -s -X POST $BASE/materials -H "$H" -H "Content-Type: application/json" -d '{"material_name":"冒烟电阻P7","unit":"pcs","category":"电子件"}' | J "['data']['id']")
check "material created" 1 "$([ -n "$MID" ] && [ "$MID" -gt 0 ] && echo 1 || echo 0)"

# --- approve happy path ---------------------------------------------------
PR=$(curl -s -X POST $BASE/purchase-requisitions -H "$ZH" -H "Content-Type: application/json" -d "{\"reason\":\"冒烟\",\"items\":[{\"material_id\":$MID,\"requested_quantity\":\"10\",\"estimated_unit_price\":\"12.3456\"}]}")
PID=$(echo "$PR" | J "['data']['id']"); PRNO=$(echo "$PR" | J "['data']['pr_no']")
SUB=$(curl -s -X POST $BASE/purchase-requisitions/$PID/submit -H "$ZH")
check "submit -> PENDING" "PENDING" "$(echo "$SUB" | J "['data']['status']")"
V2=$(echo "$SUB" | J "['data']['version']")
APP=$(curl -s -X POST $BASE/purchase-requisitions/$PID/approve -H "$LH" -H "Content-Type: application/json" -d "{\"version\":$V2,\"comment\":\"同意\"}")
check "approve -> APPROVED" "APPROVED" "$(echo "$APP" | J "['data']['status']")"
check "approve version+1" $((V2+1)) "$(echo "$APP" | J "['data']['version']")"
V3=$(echo "$APP" | J "['data']['version']")
R2=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/purchase-requisitions/$PID/approve -H "$LH" -H "Content-Type: application/json" -d "{\"version\":$V3}")
check "re-approve 409" 409 "$R2"
STALE=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/purchase-requisitions/$PID/approve -H "$LH" -H "Content-Type: application/json" -d "{\"version\":1}")
check "stale version approve 409" 409 "$STALE"

# --- 403 matrix on a fresh PENDING PR -------------------------------------
PR3=$(curl -s -X POST $BASE/purchase-requisitions -H "$ZH" -H "Content-Type: application/json" -d "{\"items\":[{\"material_id\":$MID,\"requested_quantity\":\"1\",\"estimated_unit_price\":\"1\"}]}")
PID3=$(echo "$PR3" | J "['data']['id']")
SUB3=$(curl -s -X POST $BASE/purchase-requisitions/$PID3/submit -H "$ZH")
V3B=$(echo "$SUB3" | J "['data']['version']")
F1=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/purchase-requisitions/$PID3/approve -H "$WH" -H "Content-Type: application/json" -d "{\"version\":$V3B}")
check "buyer approve 403 (no pr:approve)" 403 "$F1"
F2=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/purchase-requisitions/$PID3/approve -H "$ZH" -H "Content-Type: application/json" -d "{\"version\":$V3B}")
check "applicant approve 403 (no pr:approve)" 403 "$F2"

# --- reject + revise + resubmit -------------------------------------------
RJ=$(curl -s -X POST $BASE/purchase-requisitions/$PID3/reject -H "$LH" -H "Content-Type: application/json" -d "{\"version\":$V3B,\"comment\":\"价格需核实\"}")
check "reject -> REJECTED" "REJECTED" "$(echo "$RJ" | J "['data']['status']")"
VR=$(echo "$RJ" | J "['data']['version']")
BLANK=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/purchase-requisitions/$PID3/reject -H "$LH" -H "Content-Type: application/json" -d "{\"version\":$V3B,\"comment\":\"   \"}")
check "blank reject comment 422" 422 "$BLANK"
RV=$(curl -s -X POST $BASE/purchase-requisitions/$PID3/revise -H "$ZH" -H "Content-Type: application/json" -d "{\"version\":$VR}")
check "revise -> DRAFT" "DRAFT" "$(echo "$RV" | J "['data']['status']")"
check "revise clears submitted_at" "None" "$(echo "$RV" | J "['data']['submitted_at']")"
RS=$(curl -s -X POST $BASE/purchase-requisitions/$PID3/submit -H "$ZH")
check "resubmit -> PENDING" "PENDING" "$(echo "$RS" | J "['data']['status']")"
check "resubmit sets new submitted_at" 1 "$([ "$(echo "$RS" | J "['data']['submitted_at']")" != "None" ] && echo 1 || echo 0)"

# --- approval history (REJECT only: SUBMIT 只写 audit，不写 approval_record) ----
AH=$(curl -s $BASE/purchase-requisitions/$PID3/approvals -H "$ZH")
check "approval history has 1 record" 1 "$(echo "$AH" | python -c "import sys,json;print(len(json.load(sys.stdin)['data']))")"
check "history first action REJECT" "REJECT" "$(echo "$AH" | python -c "import sys,json;print(json.load(sys.stdin)['data'][0]['action'])")"

# --- list scoping: lisi sees own-dept PENDING (PID3 is now PENDING) ----------
PR3NO=$(echo "$PR3" | J "['data']['pr_no']")
LST=$(curl -s --get $BASE/purchase-requisitions --data-urlencode "status=PENDING" -H "$LH")
check "dept manager sees own-dept PENDING" 1 "$(echo "$LST" | python -c "import sys,json;print(1 if any(i['pr_no']=='$PR3NO' for i in json.load(sys.stdin)['data']['items']) else 0)")"
ADM=$(curl -s --get $BASE/purchase-requisitions --data-urlencode "status=PENDING" -H "$H")
check "admin sees PENDING list" 1 "$([ "$(echo "$ADM" | J "['data']['total']")" -ge 1 ] && echo 1 || echo 0)"

# --- material disabled AFTER submit -> approve blocked ---------------------
PR4=$(curl -s -X POST $BASE/purchase-requisitions -H "$ZH" -H "Content-Type: application/json" -d "{\"items\":[{\"material_id\":$MID,\"requested_quantity\":\"1\",\"estimated_unit_price\":\"1\"}]}")
PID4=$(echo "$PR4" | J "['data']['id']")
SUB4=$(curl -s -X POST $BASE/purchase-requisitions/$PID4/submit -H "$ZH")
V4=$(echo "$SUB4" | J "['data']['version']")
curl -s -X POST $BASE/materials/$MID/disable -H "$H" > /dev/null
BLK=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/purchase-requisitions/$PID4/approve -H "$LH" -H "Content-Type: application/json" -d "{\"version\":$V4}")
check "approve blocked when material disabled 409" 409 "$BLK"
RJ4=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/purchase-requisitions/$PID4/reject -H "$LH" -H "Content-Type: application/json" -d "{\"version\":$V4,\"comment\":\"物料停用驳回\"}")
check "reject still allowed 200" 200 "$RJ4"

# --- admin override (fresh material: MID was disabled above) --------------
MID2=$(curl -s -X POST $BASE/materials -H "$H" -H "Content-Type: application/json" -d '{"material_name":"冒烟电阻P7-2","unit":"pcs","category":"电子件"}' | J "['data']['id']")
PR5=$(curl -s -X POST $BASE/purchase-requisitions -H "$ZH" -H "Content-Type: application/json" -d "{\"items\":[{\"material_id\":$MID2,\"requested_quantity\":\"1\",\"estimated_unit_price\":\"1\"}]}")
PID5=$(echo "$PR5" | J "['data']['id']")
SUB5=$(curl -s -X POST $BASE/purchase-requisitions/$PID5/submit -H "$ZH")
V5=$(echo "$SUB5" | J "['data']['version']")
AO=$(curl -s -X POST $BASE/purchase-requisitions/$PID5/approve -H "$H" -H "Content-Type: application/json" -d "{\"version\":$V5}")
check "admin override approve 200" "APPROVED" "$(echo "$AO" | J "['data']['status']")"
AH5=$(curl -s $BASE/purchase-requisitions/$PID5/approvals -H "$H")
check "admin override flagged in history" "管理员越权审批" "$(echo "$AH5" | python -c "import sys,json;print(json.load(sys.stdin)['data'][0]['step_name'])")"

echo "----------------------------------------"
echo "Phase 7 smoke: PASS=$PASS FAIL=$FAIL"
kill $UV 2>/dev/null
[ "$FAIL" -eq 0 ] && echo "SMOKE OK" || { echo "SMOKE FAILED"; exit 1; }
