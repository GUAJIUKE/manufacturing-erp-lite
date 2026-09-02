#!/bin/bash
# Phase 9 purchase-receipt + inventory smoke: real uvicorn + dev DB.
# Full chain PR->Approval->PO->Receipt->Inventory and the reverse path:
# partial receipt (PARTIALLY_RECEIVED), full receipt (RECEIVED), over-receipt
# 409/6002, moving-average balance, append-only ledger, whole-receipt reversal
# (REVERSED, PURCHASE_IN_REVERSAL -qty, PO status re-derived, balance 0/0/0),
# double-reversal 409/6005, 405 on PUT/DELETE, RBAC 403s, inactive material /
# warehouse linkage (3009/3010) and inactive-material reversal still allowed.
set -u
cd "C:/Users/Administrator/Desktop/8.26/backend"
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8005 > /tmp/uvicorn_ph9.log 2>&1 &
UV=$!
sleep 5

J() { python -c "import sys,json;print(json.load(sys.stdin)$1)"; }
BASE=http://127.0.0.1:8005/api/v1
TOKEN=$(curl -s -X POST $BASE/auth/login -H "Content-Type: application/json" -d '{"username":"admin","password":"admin123"}' | J "['data']['access_token']")
ZTOKEN=$(curl -s -X POST $BASE/auth/login -H "Content-Type: application/json" -d '{"username":"zhangsan","password":"demo123"}' | J "['data']['access_token']")
LTOKEN=$(curl -s -X POST $BASE/auth/login -H "Content-Type: application/json" -d '{"username":"lisi","password":"demo123"}' | J "['data']['access_token']")
WTOKEN=$(curl -s -X POST $BASE/auth/login -H "Content-Type: application/json" -d '{"username":"wangwu","password":"demo123"}' | J "['data']['access_token']")
ZLT=$(curl -s -X POST $BASE/auth/login -H "Content-Type: application/json" -d '{"username":"zhaoliu","password":"demo123"}' | J "['data']['access_token']")
H="Authorization: Bearer $TOKEN"; ZH="Authorization: Bearer $ZTOKEN"
LH="Authorization: Bearer $LTOKEN"; WH="Authorization: Bearer $WTOKEN"; WHH="Authorization: Bearer $ZLT"
PASS=0; FAIL=0
check() { if [ "$2" = "$3" ]; then PASS=$((PASS+1)); echo "PASS  $1  ($3)";
else FAIL=$((FAIL+1)); echo "FAIL  $1  expected=$2 actual=$3"; fi; }

TS=$(date +%s)
MID=$(curl -s -X POST $BASE/materials -H "$H" -H "Content-Type: application/json" -d "{\"material_name\":\"冒烟物料P9-$TS\",\"unit\":\"pcs\",\"category\":\"电子件\"}" | J "['data']['id']")
SUP=$(curl -s -X POST $BASE/suppliers -H "$H" -H "Content-Type: application/json" -d "{\"supplier_name\":\"冒烟供应商P9-$TS\"}" | J "['data']['id']")
WHID=$(curl -s -X POST $BASE/warehouses -H "$H" -H "Content-Type: application/json" -d "{\"warehouse_name\":\"冒烟仓库P9-$TS\"}" | J "['data']['id']")
check "material/supplier/warehouse created" 1 "$([ -n "$MID" ] && [ "$MID" -gt 0 ] && [ "$SUP" -gt 0 ] && [ "$WHID" -gt 0 ] && echo 1 || echo 0)"

# --- PR -> APPROVED -> PO CONFIRMED (100 @ 10.0000) --------------------------
PR=$(curl -s -X POST $BASE/purchase-requisitions -H "$ZH" -H "Content-Type: application/json" -d "{\"reason\":\"P9冒烟\",\"items\":[{\"material_id\":$MID,\"requested_quantity\":\"100\",\"estimated_unit_price\":\"10\"}]}")
PID=$(echo "$PR" | J "['data']['id']"); PRITEM=$(echo "$PR" | J "['data']['items'][0]['id']")
SUB=$(curl -s -X POST $BASE/purchase-requisitions/$PID/submit -H "$ZH")
V2=$(echo "$SUB" | J "['data']['version']")
APP=$(curl -s -X POST $BASE/purchase-requisitions/$PID/approve -H "$LH" -H "Content-Type: application/json" -d "{\"version\":$V2}")
check "PR approved" "APPROVED" "$(echo "$APP" | J "['data']['status']")"
PO=$(curl -s -X POST $BASE/purchase-orders -H "$WH" -H "Content-Type: application/json" -d "{\"supplier_id\":$SUP,\"items\":[{\"material_id\":$MID,\"ordered_quantity\":\"100\",\"unit_price\":\"10\",\"sources\":[{\"pr_item_id\":$PRITEM,\"quantity\":\"100\"}]}]}")
POID=$(echo "$PO" | J "['data']['id']"); POITEM=$(echo "$PO" | J "['data']['items'][0]['id']")
CF=$(curl -s -X POST $BASE/purchase-orders/$POID/confirm -H "$WH" -H "Content-Type: application/json" -d "{\"version\":1}")
check "PO confirmed" "CONFIRMED" "$(echo "$CF" | J "['data']['status']")"

# --- Receipt 40: POSTED + RCV number + received_by server-side -----------------
R1=$(curl -s -X POST $BASE/purchase-receipts -H "$WHH" -H "Content-Type: application/json" -d "{\"po_id\":$POID,\"warehouse_id\":$WHID,\"items\":[{\"po_item_id\":$POITEM,\"received_quantity\":\"40\"}]}")
R1ID=$(echo "$R1" | J "['data']['id']"); R1NO=$(echo "$R1" | J "['data']['receipt_no']")
check "receipt POSTED" "POSTED" "$(echo "$R1" | J "['data']['status']")"
check "RCV number format" 1 "$(echo "$R1NO" | grep -cE '^RCV-[0-9]{8}-[0-9]{4}$')"
check "received_by is server-side (zhaoliu)" "赵敏" "$(echo "$R1" | J "['data']['received_by_name']")"
check "unit_price from PO" "10.0000" "$(echo "$R1" | J "['data']['items'][0]['unit_price']")"
check "amount server-computed 400.00" "400.00" "$(echo "$R1" | J "['data']['items'][0]['amount']")"
PO1=$(curl -s $BASE/purchase-orders/$POID -H "$WH")
check "PO -> PARTIALLY_RECEIVED" "PARTIALLY_RECEIVED" "$(echo "$PO1" | J "['data']['status']")"
check "PO item received 40" "40.0000" "$(echo "$PO1" | J "['data']['items'][0]['received_quantity']")"

# --- balance after 40 ----------------------------------------------------------
B1=$(curl -s --get $BASE/inventory/balances -H "$WHH" --data-urlencode "warehouse_id=$WHID" --data-urlencode "material_id=$MID")
check "balance qty 40" "40.0000" "$(echo "$B1" | J "['data']['items'][0]['quantity']")"
check "balance total 400.00" "400.00" "$(echo "$B1" | J "['data']['items'][0]['total_amount']")"
check "balance avg 10.0000" "10.0000" "$(echo "$B1" | J "['data']['items'][0]['average_unit_cost']")"

# --- Receipt 60 -> RECEIVED, balance 100 ---------------------------------------
R2=$(curl -s -X POST $BASE/purchase-receipts -H "$WHH" -H "Content-Type: application/json" -d "{\"po_id\":$POID,\"warehouse_id\":$WHID,\"items\":[{\"po_item_id\":$POITEM,\"received_quantity\":\"60\"}]}")
R2ID=$(echo "$R2" | J "['data']['id']"); R2NO=$(echo "$R2" | J "['data']['receipt_no']")
PO2=$(curl -s $BASE/purchase-orders/$POID -H "$WH")
check "PO -> RECEIVED" "RECEIVED" "$(echo "$PO2" | J "['data']['status']")"
B2=$(curl -s --get $BASE/inventory/balances -H "$WHH" --data-urlencode "warehouse_id=$WHID" --data-urlencode "material_id=$MID")
check "balance qty 100" "100.0000" "$(echo "$B2" | J "['data']['items'][0]['quantity']")"
check "balance total 1000.00" "1000.00" "$(echo "$B2" | J "['data']['items'][0]['total_amount']")"

# --- over-receipt on RECEIVED PO -> 409/5009 (already fully received) -----------
OVR=$(curl -s -X POST $BASE/purchase-receipts -H "$WHH" -H "Content-Type: application/json" -d "{\"po_id\":$POID,\"warehouse_id\":$WHID,\"items\":[{\"po_item_id\":$POITEM,\"received_quantity\":\"1\"}]}")
check "receipt on RECEIVED PO 5009" 5009 "$(echo "$OVR" | J "['code']")"
check "over-receipt HTTP 409" 409 "$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/purchase-receipts -H "$WHH" -H "Content-Type: application/json" -d "{\"po_id\":$POID,\"warehouse_id\":$WHID,\"items\":[{\"po_item_id\":$POITEM,\"received_quantity\":\"1\"}]}")"

# --- ledger: 2 PURCHASE_IN rows referencing the receipts ------------------------
TX=$(curl -s --get $BASE/inventory/transactions -H "$WHH" --data-urlencode "material_id=$MID" --data-urlencode "warehouse_id=$WHID")
check "ledger 2 rows" 2 "$(echo "$TX" | J "['data']['total']")"
check "txn +40" "40.0000" "$(echo "$TX" | J "['data']['items'][1]['quantity']")"
check "txn +60 first row" "60.0000" "$(echo "$TX" | J "['data']['items'][0]['quantity']")"
check "txn reference_no R1" "$R1NO" "$(echo "$TX" | J "['data']['items'][1]['reference_no']")"
check "txn type PURCHASE_IN" "PURCHASE_IN" "$(echo "$TX" | J "['data']['items'][0]['transaction_type']")"
check "txn operator zhaoliu" "赵敏" "$(echo "$TX" | J "['data']['items'][0]['operator_name']")"

# --- warehouse with stock cannot be disabled (3010) ----------------------------
DIS=$(curl -s -X POST $BASE/warehouses/$WHID/disable -H "$H")
check "disable stocked warehouse 3010" 3010 "$(echo "$DIS" | J "['code']")"

# --- reverse R2 (60) -> REVERSED, balance 40, PO PARTIALLY_RECEIVED -------------
RV=$(curl -s -X POST $BASE/purchase-receipts/$R2ID/reverse -H "$WHH" -H "Content-Type: application/json" -d '{"reason":"到货数量录错"}')
check "reverse -> REVERSED" "REVERSED" "$(echo "$RV" | J "['data']['status']")"
check "reverse_reason recorded" "到货数量录错" "$(echo "$RV" | J "['data']['reverse_reason']")"
PO3=$(curl -s $BASE/purchase-orders/$POID -H "$WH")
check "PO back to PARTIALLY_RECEIVED" "PARTIALLY_RECEIVED" "$(echo "$PO3" | J "['data']['status']")"
check "PO item received 40" "40.0000" "$(echo "$PO3" | J "['data']['items'][0]['received_quantity']")"
B3=$(curl -s --get $BASE/inventory/balances -H "$WHH" --data-urlencode "warehouse_id=$WHID" --data-urlencode "material_id=$MID")
check "balance qty 40 after reversal" "40.0000" "$(echo "$B3" | J "['data']['items'][0]['quantity']")"
# PO back to PARTIALLY_RECEIVED (40/100): try over-receipt 61 (> remaining 60) -> 6002
OVR2=$(curl -s -X POST $BASE/purchase-receipts -H "$WHH" -H "Content-Type: application/json" -d "{\"po_id\":$POID,\"warehouse_id\":$WHID,\"items\":[{\"po_item_id\":$POITEM,\"received_quantity\":\"61\"}]}")
check "over-receipt on partial PO 6002" 6002 "$(echo "$OVR2" | J "['code']")"
TX2=$(curl -s --get $BASE/inventory/transactions -H "$WHH" --data-urlencode "material_id=$MID" --data-urlencode "warehouse_id=$WHID")
check "ledger now 3 rows" 3 "$(echo "$TX2" | J "['data']['total']")"
check "reversal txn -60" "-60.0000" "$(echo "$TX2" | J "['data']['items'][0]['quantity']")"
check "reversal type PURCHASE_IN_REVERSAL" "PURCHASE_IN_REVERSAL" "$(echo "$TX2" | J "['data']['items'][0]['transaction_type']")"
check "reversal source is R2" "$R2NO" "$(echo "$TX2" | J "['data']['items'][0]['reference_no']")"
RV2=$(curl -s -X POST $BASE/purchase-receipts/$R2ID/reverse -H "$WHH" -H "Content-Type: application/json" -d '{"reason":"重复冲销"}')
check "double reversal 6005" 6005 "$(echo "$RV2" | J "['code']")"

# --- reverse R1 (40) -> PO CONFIRMED, balance 0/0/0 ------------------------------
RV1=$(curl -s -X POST $BASE/purchase-receipts/$R1ID/reverse -H "$WHH" -H "Content-Type: application/json" -d '{"reason":"全部退回"}')
PO4=$(curl -s $BASE/purchase-orders/$POID -H "$WH")
check "PO -> CONFIRMED after full reversal" "CONFIRMED" "$(echo "$PO4" | J "['data']['status']")"
B4=$(curl -s --get $BASE/inventory/balances -H "$WHH" --data-urlencode "warehouse_id=$WHID" --data-urlencode "material_id=$MID")
check "balance qty 0" "0.0000" "$(echo "$B4" | J "['data']['items'][0]['quantity']")"
check "balance total 0" "0.00" "$(echo "$B4" | J "['data']['items'][0]['total_amount']")"
check "balance avg 0" "0.0000" "$(echo "$B4" | J "['data']['items'][0]['average_unit_cost']")"

# --- inactive material: new receipt blocked (3009), reversal still allowed ------
MDIS=$(curl -s -X POST $BASE/materials/$MID/disable -H "$H")
check "material disabled" "DISABLED" "$(echo "$MDIS" | J "['data']['status']")"
RM=$(curl -s -X POST $BASE/purchase-receipts -H "$WHH" -H "Content-Type: application/json" -d "{\"po_id\":$POID,\"warehouse_id\":$WHID,\"items\":[{\"po_item_id\":$POITEM,\"received_quantity\":\"1\"}]}")
check "receipt on inactive material 3009" 3009 "$(echo "$RM" | J "['code']")"

# --- RBAC 403 matrix on receipt create ------------------------------------------
A1=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/purchase-receipts -H "$WH" -H "Content-Type: application/json" -d "{\"po_id\":$POID,\"warehouse_id\":$WHID,\"items\":[{\"po_item_id\":$POITEM,\"received_quantity\":\"1\"}]}")
check "buyer create receipt 403" 403 "$A1"
A2=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/purchase-receipts -H "$ZH" -H "Content-Type: application/json" -d "{\"po_id\":$POID,\"warehouse_id\":$WHID,\"items\":[{\"po_item_id\":$POITEM,\"received_quantity\":\"1\"}]}")
check "applicant create receipt 403" 403 "$A2"
A3=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/purchase-receipts -H "$LH" -H "Content-Type: application/json" -d "{\"po_id\":$POID,\"warehouse_id\":$WHID,\"items\":[{\"po_item_id\":$POITEM,\"received_quantity\":\"1\"}]}")
check "dept_manager create receipt 403" 403 "$A3"
RA=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/purchase-receipts/$R1ID/reverse -H "$WH" -H "Content-Type: application/json" -d '{"reason":"buyer 无权限"}')
check "buyer reverse receipt 403" 403 "$RA"

# --- no PUT/PATCH/DELETE on posted receipt (405) ---------------------------------
P1=$(curl -s -o /dev/null -w "%{http_code}" -X PUT $BASE/purchase-receipts/$R1ID -H "$WHH" -H "Content-Type: application/json" -d '{"remark":"x"}')
check "PUT receipt 405" 405 "$P1"
D1=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE $BASE/purchase-receipts/$R1ID -H "$WHH")
check "DELETE receipt 405" 405 "$D1"
D2=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE $BASE/inventory/transactions/1 -H "$H")
check "DELETE transaction rejected (404/405)" 1 "$([ "$D2" = "404" ] || [ "$D2" = "405" ] && echo 1 || echo 0)"

# --- receipt list filter by po_no / detail ----------------------------------------
LST=$(curl -s --get $BASE/purchase-receipts -H "$WHH" --data-urlencode "po_no=$(echo "$PO" | J "['data']['po_no']")")
check "list by po_no total 2" 2 "$(echo "$LST" | J "['data']['total']")"
check "list contains R1+R2 reversed" 2 "$([ "$(echo "$LST" | J "['data']['items'][0]['status']")" = "REVERSED" ] && [ "$(echo "$LST" | J "['data']['items'][1]['status']")" = "REVERSED" ] && echo 2 || echo 0)"

echo "----------------------------------------"
echo "Phase 9 smoke: PASS=$PASS FAIL=$FAIL"
kill $UV 2>/dev/null
[ "$FAIL" -eq 0 ] && echo "SMOKE OK" || { echo "SMOKE FAILED"; exit 1; }
