#!/bin/bash
# Phase 8 purchase-order smoke: real uvicorn + dev DB business chain.
# Covers PR->PO conversion (§9.2), split/merge source mapping, PR->CONVERTED,
# over-conversion 4009, confirm (Q9 unit_price>0), cancel + rollback (R14),
# Q2 (APPROVED PR cancel with active PO), RBAC 403s, list visibility.
set -u
cd "C:/Users/Administrator/Desktop/8.26/backend"
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8004 > /tmp/uvicorn_ph8.log 2>&1 &
UV=$!
sleep 5

J() { python -c "import sys,json;print(json.load(sys.stdin)$1)"; }
BASE=http://127.0.0.1:8004/api/v1
TOKEN=$(curl -s -X POST $BASE/auth/login -H "Content-Type: application/json" -d '{"username":"admin","password":"admin123"}' | J "['data']['access_token']")
ZTOKEN=$(curl -s -X POST $BASE/auth/login -H "Content-Type: application/json" -d '{"username":"zhangsan","password":"demo123"}' | J "['data']['access_token']")
LTOKEN=$(curl -s -X POST $BASE/auth/login -H "Content-Type: application/json" -d '{"username":"lisi","password":"demo123"}' | J "['data']['access_token']")
WTOKEN=$(curl -s -X POST $BASE/auth/login -H "Content-Type: application/json" -d '{"username":"wangwu","password":"demo123"}' | J "['data']['access_token']")
WHT=$(curl -s -X POST $BASE/auth/login -H "Content-Type: application/json" -d '{"username":"zhaoliu","password":"demo123"}' | J "['data']['access_token']")
H="Authorization: Bearer $TOKEN"; ZH="Authorization: Bearer $ZTOKEN"
LH="Authorization: Bearer $LTOKEN"; WH="Authorization: Bearer $WTOKEN"; WHH="Authorization: Bearer $WHT"
PASS=0; FAIL=0
check() { if [ "$2" = "$3" ]; then PASS=$((PASS+1)); echo "PASS  $1  ($3)";
else FAIL=$((FAIL+1)); echo "FAIL  $1  expected=$2 actual=$3"; fi; }

MID=$(curl -s -X POST $BASE/materials -H "$H" -H "Content-Type: application/json" -d '{"material_name":"冒烟物料P8","unit":"pcs","category":"电子件"}' | J "['data']['id']")
SUP=$(curl -s -X POST $BASE/suppliers -H "$H" -H "Content-Type: application/json" -d '{"supplier_name":"冒烟供应商P8"}' | J "['data']['id']")
check "material+supplier created" 1 "$([ -n "$MID" ] && [ -n "$SUP" ] && echo 1 || echo 0)"

# --- PR -> APPROVED ---------------------------------------------------------
PR=$(curl -s -X POST $BASE/purchase-requisitions -H "$ZH" -H "Content-Type: application/json" -d "{\"reason\":\"P8冒烟\",\"items\":[{\"material_id\":$MID,\"requested_quantity\":\"10\",\"estimated_unit_price\":\"12.3456\"}]}")
PID=$(echo "$PR" | J "['data']['id']"); PRITEM=$(echo "$PR" | J "['data']['items'][0]['id']")
SUB=$(curl -s -X POST $BASE/purchase-requisitions/$PID/submit -H "$ZH")
V2=$(echo "$SUB" | J "['data']['version']")
APP=$(curl -s -X POST $BASE/purchase-requisitions/$PID/approve -H "$LH" -H "Content-Type: application/json" -d "{\"version\":$V2}")
check "PR approved" "APPROVED" "$(echo "$APP" | J "['data']['status']")"

# --- convert to PO (full 10) -> DRAFT + PR CONVERTED -------------------------
PO=$(curl -s -X POST $BASE/purchase-orders -H "$WH" -H "Content-Type: application/json" -d "{\"supplier_id\":$SUP,\"items\":[{\"material_id\":$MID,\"ordered_quantity\":\"10\",\"unit_price\":\"12.3456\",\"sources\":[{\"pr_item_id\":$PRITEM,\"quantity\":\"10\"}]}]}")
POID=$(echo "$PO" | J "['data']['id']"); PONO=$(echo "$PO" | J "['data']['po_no']")
check "PO created DRAFT" "DRAFT" "$(echo "$PO" | J "['data']['status']")"
check "PO amount 123.46" "123.46" "$(echo "$PO" | J "['data']['total_amount']")"
check "PO number format" 1 "$(echo "$PONO" | grep -cE '^PO-[0-9]{8}-[0-9]{4}$')"
check "PR fully converted -> CONVERTED" "CONVERTED" "$(curl -s $BASE/purchase-requisitions/$PID -H "$ZH" | J "['data']['status']")"
check "source pr_no mapped" "$(echo "$PR" | J "['data']['pr_no']")" "$(echo "$PO" | J "['data']['items'][0]['sources'][0]['pr_no']")"

# --- over-conversion blocked (PR partial: 10, convert 7 first) ----------------
PR2=$(curl -s -X POST $BASE/purchase-requisitions -H "$ZH" -H "Content-Type: application/json" -d "{\"items\":[{\"material_id\":$MID,\"requested_quantity\":\"10\",\"estimated_unit_price\":\"1\"}]}")
PID2=$(echo "$PR2" | J "['data']['id']"); PRITEM2=$(echo "$PR2" | J "['data']['items'][0]['id']")
SUB2=$(curl -s -X POST $BASE/purchase-requisitions/$PID2/submit -H "$ZH")
V22=$(echo "$SUB2" | J "['data']['version']")
curl -s -X POST $BASE/purchase-requisitions/$PID2/approve -H "$LH" -H "Content-Type: application/json" -d "{\"version\":$V22}" > /dev/null
# 先转 7(PR 保持 APPROVED),再试图转 5(剩余 3)-> 4009
curl -s -X POST $BASE/purchase-orders -H "$WH" -H "Content-Type: application/json" -d "{\"supplier_id\":$SUP,\"items\":[{\"material_id\":$MID,\"ordered_quantity\":\"7\",\"unit_price\":\"1\",\"sources\":[{\"pr_item_id\":$PRITEM2,\"quantity\":\"7\"}]}]}" > /dev/null
OVR=$(curl -s -X POST $BASE/purchase-orders -H "$WH" -H "Content-Type: application/json" -d "{\"supplier_id\":$SUP,\"items\":[{\"material_id\":$MID,\"ordered_quantity\":\"5\",\"unit_price\":\"1\",\"sources\":[{\"pr_item_id\":$PRITEM2,\"quantity\":\"5\"}]}]}")
check "over-convert 4009" 4009 "$(echo "$OVR" | J "['code']")"

# --- non-APPROVED PR -> 4002 -------------------------------------------------
PR3=$(curl -s -X POST $BASE/purchase-requisitions -H "$ZH" -H "Content-Type: application/json" -d "{\"items\":[{\"material_id\":$MID,\"requested_quantity\":\"1\",\"estimated_unit_price\":\"1\"}]}")
PID3=$(echo "$PR3" | J "['data']['id']"); PRITEM3=$(echo "$PR3" | J "['data']['items'][0]['id']")
NA=$(curl -s -X POST $BASE/purchase-orders -H "$WH" -H "Content-Type: application/json" -d "{\"supplier_id\":$SUP,\"items\":[{\"material_id\":$MID,\"ordered_quantity\":\"1\",\"unit_price\":\"1\",\"sources\":[{\"pr_item_id\":$PRITEM3,\"quantity\":\"1\"}]}]}")
check "DRAFT PR convert 4002" 4002 "$(echo "$NA" | J "['code']")"

# --- confirm: zero-price blocked, then success -------------------------------
# Review fix：无来源手工采购未实现，zero-price PO 也须挂 APPROVED PR 来源（sum == ordered）
PRZ=$(curl -s -X POST $BASE/purchase-requisitions -H "$ZH" -H "Content-Type: application/json" -d "{\"items\":[{\"material_id\":$MID,\"requested_quantity\":\"1\",\"estimated_unit_price\":\"1\"}]}")
PIDZ=$(echo "$PRZ" | J "['data']['id']"); PRITEMZ=$(echo "$PRZ" | J "['data']['items'][0]['id']")
SUBZ=$(curl -s -X POST $BASE/purchase-requisitions/$PIDZ/submit -H "$ZH")
VZ=$(echo "$SUBZ" | J "['data']['version']")
curl -s -X POST $BASE/purchase-requisitions/$PIDZ/approve -H "$LH" -H "Content-Type: application/json" -d "{\"version\":$VZ}" > /dev/null
POZ=$(curl -s -X POST $BASE/purchase-orders -H "$WH" -H "Content-Type: application/json" -d "{\"supplier_id\":$SUP,\"items\":[{\"material_id\":$MID,\"ordered_quantity\":\"1\",\"unit_price\":\"0\",\"sources\":[{\"pr_item_id\":$PRITEMZ,\"quantity\":\"1\"}]}]}")
POZID=$(echo "$POZ" | J "['data']['id']"); POZV=$(echo "$POZ" | J "['data']['version']")
ZP=$(curl -s -X POST $BASE/purchase-orders/$POZID/confirm -H "$WH" -H "Content-Type: application/json" -d "{\"version\":$POZV}")
check "confirm zero price 5007" 5007 "$(echo "$ZP" | J "['code']")"
CF=$(curl -s -X POST $BASE/purchase-orders/$POID/confirm -H "$WH" -H "Content-Type: application/json" -d "{\"version\":1}")
check "confirm -> CONFIRMED" "CONFIRMED" "$(echo "$CF" | J "['data']['status']")"
check "confirm version+1" 2 "$(echo "$CF" | J "['data']['version']")"
VC=$(echo "$CF" | J "['data']['version']")
RC=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/purchase-orders/$POID/confirm -H "$WH" -H "Content-Type: application/json" -d "{\"version\":$VC}")
check "re-confirm 409" 409 "$RC"
STALE=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/purchase-orders/$POID/confirm -H "$WH" -H "Content-Type: application/json" -d "{\"version\":1}")
check "stale version confirm 409" 409 "$STALE"

# --- cancel: rollback converted_quantity + PR back to APPROVED ----------------
CL=$(curl -s -X POST $BASE/purchase-orders/$POID/cancel -H "$WH" -H "Content-Type: application/json" -d "{\"version\":$VC,\"reason\":\"计划调整\"}")
check "cancel -> CANCELLED" "CANCELLED" "$(echo "$CL" | J "['data']['status']")"
check "PR rolled back APPROVED" "APPROVED" "$(curl -s $BASE/purchase-requisitions/$PID -H "$ZH" | J "['data']['status']")"
check "converted_quantity rolled back" "0.0000" "$(curl -s $BASE/purchase-requisitions/$PID -H "$ZH" | J "['data']['items'][0]['converted_quantity']")"
VCL=$(echo "$CL" | J "['data']['version']")
RC2=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/purchase-orders/$POID/cancel -H "$WH" -H "Content-Type: application/json" -d "{\"version\":$VCL}")
check "re-cancel 409" 409 "$RC2"

# --- Q2: APPROVED PR with active PO cannot be cancelled ------------------------
PR4=$(curl -s -X POST $BASE/purchase-requisitions -H "$ZH" -H "Content-Type: application/json" -d "{\"items\":[{\"material_id\":$MID,\"requested_quantity\":\"8\",\"estimated_unit_price\":\"1\"}]}")
PID4=$(echo "$PR4" | J "['data']['id']"); PRITEM4=$(echo "$PR4" | J "['data']['items'][0]['id']")
SUB4=$(curl -s -X POST $BASE/purchase-requisitions/$PID4/submit -H "$ZH")
V42=$(echo "$SUB4" | J "['data']['version']")
curl -s -X POST $BASE/purchase-requisitions/$PID4/approve -H "$LH" -H "Content-Type: application/json" -d "{\"version\":$V42}" > /dev/null
curl -s -X POST $BASE/purchase-orders -H "$WH" -H "Content-Type: application/json" -d "{\"supplier_id\":$SUP,\"items\":[{\"material_id\":$MID,\"ordered_quantity\":\"5\",\"unit_price\":\"1\",\"sources\":[{\"pr_item_id\":$PRITEM4,\"quantity\":\"5\"}]}]}" > /dev/null
QC=$(curl -s -X POST $BASE/purchase-requisitions/$PID4/cancel -H "$ZH")
check "PR cancel with active PO 4008" 4008 "$(echo "$QC" | J "['code']")"

# --- RBAC 403s ---------------------------------------------------------------
F1=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/purchase-orders -H "$ZH" -H "Content-Type: application/json" -d "{\"supplier_id\":$SUP,\"items\":[{\"material_id\":$MID,\"ordered_quantity\":\"1\",\"unit_price\":\"1\"}]}")
check "applicant create PO 403" 403 "$F1"
F2=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/purchase-orders/$POZID/confirm -H "$WHH" -H "Content-Type: application/json" -d "{\"version\":$POZV}")
check "warehouse confirm 403" 403 "$F2"

# --- list visibility: applicant sees own-chain PO; warehouse sees all ----------
LST=$(curl -s --get $BASE/purchase-orders -H "$ZH")
check "applicant sees own-chain PO" 1 "$(echo "$LST" | python -c "import sys,json;print(1 if any(i['po_no']=='$PONO' for i in json.load(sys.stdin)['data']['items']) else 0)")"
LST2=$(curl -s --get $BASE/purchase-orders -H "$WHH")
check "warehouse sees full list" 1 "$([ "$(echo "$LST2" | J "['data']['total']")" -ge 1 ] && echo 1 || echo 0)"

echo "----------------------------------------"
echo "Phase 8 smoke: PASS=$PASS FAIL=$FAIL"
kill $UV 2>/dev/null
[ "$FAIL" -eq 0 ] && echo "SMOKE OK" || { echo "SMOKE FAILED"; exit 1; }
