#!/bin/bash
# Phase 5 master-data smoke test: start uvicorn, run full chain, report.
set -u
cd "C:/Users/Administrator/Desktop/8.26/backend"
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001 > /tmp/uvicorn_ph5c.log 2>&1 &
UV=$!
sleep 5

J() { python -c "import sys,json;print(json.load(sys.stdin)$1)"; }
BASE=http://127.0.0.1:8001/api/v1
TOKEN=$(curl -s -X POST $BASE/auth/login -H "Content-Type: application/json" -d '{"username":"admin","password":"admin123"}' | J "['data']['access_token']")
H="Authorization: Bearer $TOKEN"
PASS=0; FAIL=0
check() { # name expected actual
  if [ "$2" = "$3" ]; then PASS=$((PASS+1)); echo "PASS  $1  ($3)";
  else FAIL=$((FAIL+1)); echo "FAIL  $1  expected=$2 actual=$3"; fi
}

# --- materials ---
MID=$(curl -s -X POST $BASE/materials -H "$H" -H "Content-Type: application/json" -d '{"material_name":"冒烟电阻","unit":"pcs","category":"电子件"}' | J "['data']['id']")
CODE_BEFORE=$(curl -s $BASE/materials/$MID -H "$H" | J "['data']['material_code']")
CODE=$(curl -s -X POST $BASE/materials -H "$H" -H "Content-Type: application/json" -d '{"material_name":"冒烟电容","unit":"pcs","category":"电子件"}' | J "['data']['material_code']")
check "material auto code MAT-xxxxxx" 1 "$(echo "$CODE" | grep -cE '^MAT-[0-9]{6}$')"
UPD=$(curl -s -X PUT $BASE/materials/$MID -H "$H" -H "Content-Type: application/json" -d '{"material_name":"冒烟电阻改","material_code":"MAT-000000"}' | J "['data']['material_code']")
check "update keeps material_code (extra field ignored)" "$CODE_BEFORE" "$UPD"
FOUND=$(curl -s --get "$BASE/materials" --data-urlencode "name=冒烟电" -H "$H" | J "['data']['total']")
check "material name fuzzy filter total>=2" 1 "$([ "$FOUND" -ge 2 ] && echo 1 || echo 0)"

# --- suppliers ---
SCODE=$(curl -s -X POST $BASE/suppliers -H "$H" -H "Content-Type: application/json" -d '{"supplier_name":"冒烟供应商"}' | J "['data']['supplier_code']")
check "supplier auto code SUP-xxxxxx" 1 "$(echo "$SCODE" | grep -cE '^SUP-[0-9]{6}$')"
SID=$(curl -s -X POST $BASE/suppliers -H "$H" -H "Content-Type: application/json" -d '{"supplier_name":"冒烟供应商2"}' | J "['data']['id']")
SDIS=$(curl -s -X POST $BASE/suppliers/$SID/disable -H "$H" | J "['data']['status']")
check "supplier disable" "DISABLED" "$SDIS"

# --- warehouses (stock guard) ---
WID=$(curl -s -X POST $BASE/warehouses -H "$H" -H "Content-Type: application/json" -d '{"warehouse_name":"冒烟仓"}' | J "['data']['id']")
WCODE=$(curl -s -X POST $BASE/warehouses -H "$H" -H "Content-Type: application/json" -d '{"warehouse_name":"冒烟仓2"}' | J "['data']['warehouse_code']")
check "warehouse auto code WH-xxxxxx" 1 "$(echo "$WCODE" | grep -cE '^WH-[0-9]{6}$')"
"E:/dev/mysql8/mysql-8.0.39-winx64/bin/mysql.exe" -uroot -perp_lite_dev erp_lite -e "INSERT INTO inventory_balances (warehouse_id, material_id, quantity) VALUES ($WID, $MID, 5);" 2>/dev/null
WBAD=$(curl -s -X POST $BASE/warehouses/$WID/disable -H "$H" | J "['code']")
check "disable warehouse with stock -> 3010" "3010" "$WBAD"
"E:/dev/mysql8/mysql-8.0.39-winx64/bin/mysql.exe" -uroot -perp_lite_dev erp_lite -e "DELETE FROM inventory_balances WHERE warehouse_id=$WID;" 2>/dev/null
WOK=$(curl -s -X POST $BASE/warehouses/$WID/disable -H "$H" | J "['data']['status']")
check "disable warehouse after clear" "DISABLED" "$WOK"

# --- inventory policies (material MID still ACTIVE here) ---
POL_W=$(curl -s -X POST $BASE/warehouses -H "$H" -H "Content-Type: application/json" -d '{"warehouse_name":"策略仓"}' | J "['data']['id']")
PDIS=$(curl -s -X POST $BASE/inventory-policies -H "$H" -H "Content-Type: application/json" -d "{\"warehouse_id\":$WID,\"material_id\":$MID,\"safety_stock\":10}" | J "['code']")
check "policy on disabled warehouse -> 3009" "3009" "$PDIS"
POK=$(curl -s -X POST $BASE/inventory-policies -H "$H" -H "Content-Type: application/json" -d "{\"warehouse_id\":$POL_W,\"material_id\":$MID,\"safety_stock\":10,\"reorder_point\":20,\"max_stock\":100}" | J "['data']['safety_stock']")
check "policy create safety_stock" "10" "$POK"
PDUP=$(curl -s -X POST $BASE/inventory-policies -H "$H" -H "Content-Type: application/json" -d "{\"warehouse_id\":$POL_W,\"material_id\":$MID,\"safety_stock\":1}" | J "['code']")
check "duplicate pair -> 3011" "3011" "$PDUP"
PNEG=$(curl -s -X POST $BASE/inventory-policies -H "$H" -H "Content-Type: application/json" -d "{\"warehouse_id\":$POL_W,\"material_id\":$MID,\"safety_stock\":-5}" | J "['code']")
check "negative safety -> 422" "1001" "$PNEG"
PPM=$(curl -s -X POST $BASE/inventory-policies -H "$H" -H "Content-Type: application/json" -d "{\"warehouse_id\":$POL_W,\"material_id\":$MID,\"safety_stock\":50,\"reorder_point\":10}" | J "['code']")
check "safety>reorder -> 422" "1001" "$PPM"
# material disable/enable + disabled-material policy guard
DIS=$(curl -s -X POST $BASE/materials/$MID/disable -H "$H" | J "['data']['status']")
check "material disable" "DISABLED" "$DIS"
EN=$(curl -s -X POST $BASE/materials/$MID/enable -H "$H" | J "['data']['status']")
check "material enable" "ACTIVE" "$EN"
MID2=$(curl -s -X POST $BASE/materials -H "$H" -H "Content-Type: application/json" -d '{"material_name":"停用拦截物料","unit":"pcs"}' | J "['data']['id']")
curl -s -X POST $BASE/materials/$MID2/disable -H "$H" > /dev/null
PDM=$(curl -s -X POST $BASE/inventory-policies -H "$H" -H "Content-Type: application/json" -d "{\"warehouse_id\":$POL_W,\"material_id\":$MID2,\"safety_stock\":1}" | J "['code']")
check "policy on disabled material -> 3009" "3009" "$PDM"

# --- RBAC 403 ---
T2=$(curl -s -X POST $BASE/auth/login -H "Content-Type: application/json" -d '{"username":"zhangsan","password":"demo123"}' | J "['data']['access_token']")
FBD=$(curl -s -X POST $BASE/materials -H "Authorization: Bearer $T2" -H "Content-Type: application/json" -d '{"material_name":"越权","unit":"pcs"}' | J "['code']")
check "applicant create material -> 2005" "2005" "$FBD"
FBP=$(curl -s "$BASE/inventory-policies" -H "Authorization: Bearer $T2" | J "['code']")
check "applicant view policies -> 2005" "2005" "$FBP"

echo ""
echo "===== SMOKE RESULT: $PASS passed, $FAIL failed ====="
kill $UV 2>/dev/null
exit $FAIL
