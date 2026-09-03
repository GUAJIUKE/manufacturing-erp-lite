#!/bin/bash
# Phase 11 Dashboard smoke: real uvicorn + dev DB（需先跑 seed_demo_data）。
# 覆盖：五角色 summary 数值与角色隔离、口径一致性（dashboard vs 列表页计数）、
# 趋势 7/30/90、PO 状态分布含 0、待办角色收敛、动态区、低库存排序。
set -u
cd "C:/Users/Administrator/Desktop/8.26/backend"
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8006 > /tmp/uvicorn_ph11.log 2>&1 &
UV=$!
sleep 5

J() { ./.venv/Scripts/python.exe -c "import sys,json;print(json.load(sys.stdin)$1)"; }
BASE=http://127.0.0.1:8006/api/v1
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

# ================= summary 数值与角色隔离 =================
S=$(curl -s $BASE/dashboard/summary -H "$H")
check "admin pending_pr=2" 2 "$(echo "$S" | J "['data']['pending_pr_count']")"
check "admin pending_purchase=2" 2 "$(echo "$S" | J "['data']['pending_purchase_count']")"
check "admin draft_po=1" 1 "$(echo "$S" | J "['data']['draft_po_count']")"
check "admin pending_po=1" 1 "$(echo "$S" | J "['data']['pending_po_count']")"
check "admin low_stock=2" 2 "$(echo "$S" | J "['data']['low_stock_count']")"
check "admin inventory_amount=1190.00" "1190.00" "$(echo "$S" | J "['data']['inventory_total_amount']")"

WS=$(curl -s $BASE/dashboard/summary -H "$WHH")
check "WAREHOUSE 无 pr:view -> pending_pr=0" 0 "$(echo "$WS" | J "['data']['pending_pr_count']")"
check "WAREHOUSE pending_po=1" 1 "$(echo "$WS" | J "['data']['pending_po_count']")"
check "WAREHOUSE draft_po=0（无 po:confirm）" 0 "$(echo "$WS" | J "['data']['draft_po_count']")"

ZS=$(curl -s $BASE/dashboard/summary -H "$ZH")
check "APPLICANT 只见自己 PENDING PR=1" 1 "$(echo "$ZS" | J "['data']['pending_pr_count']")"

# ================= 口径一致性：dashboard vs 列表页 =================
PRP=$(curl -s --get $BASE/purchase-requisitions -H "$H" --data-urlencode "status=PENDING")
check "pending_pr == PR列表(PENDING) total" "$(echo "$S" | J "['data']['pending_pr_count']")" "$(echo "$PRP" | J "['data']['total']")"
POD=$(curl -s --get $BASE/purchase-orders -H "$H" --data-urlencode "status=DRAFT")
check "draft_po == PO列表(DRAFT) total" "$(echo "$S" | J "['data']['draft_po_count']")" "$(echo "$POD" | J "['data']['total']")"
POR=$(curl -s --get $BASE/purchase-orders -H "$H" --data-urlencode "status=RECEIVED")
check "PO状态分布 RECEIVED==2 与列表一致" 2 "$(echo "$POR" | J "['data']['total']")"
LOW=$(curl -s --get $BASE/inventory/balances --data-urlencode "below_safety_stock=true" -H "$H")
check "low_stock == 库存页低库存筛选 total" "$(echo "$S" | J "['data']['low_stock_count']")" "$(echo "$LOW" | J "['data']['total']")"

# ================= 趋势 7/30/90 =================
for D in 7 30 90; do
  LEN=$(curl -s --get $BASE/dashboard/pr-trend -H "$H" --data-urlencode "days=$D" | ./.venv/Scripts/python.exe -c "import sys,json;print(len(json.load(sys.stdin)['data']))")
  check "pr-trend days=$D 返回 $D 个点" "$D" "$LEN"
done
TD=$(curl -s --get $BASE/dashboard/pr-trend -H "$H" --data-urlencode "days=30")
TODAY=$(./.venv/Scripts/python.exe -c "import datetime;print(datetime.date.today().isoformat())")
TC=$(echo "$TD" | ./.venv/Scripts/python.exe -c "import sys,json,datetime;d=json.load(sys.stdin)['data'];print(next((p['count'] for p in d if p['date']=='$TODAY'),'NA'))")
check "pr-trend 今日 count=7（PR7 取消不计）" 7 "$TC"
TA=$(echo "$TD" | ./.venv/Scripts/python.exe -c "import sys,json,datetime;d=json.load(sys.stdin)['data'];print(next((p['amount'] for p in d if p['date']=='$TODAY'),'NA'))")
check "pr-trend 今日 amount=1910.00" "1910.00" "$TA"

# ================= PO 状态分布（含 0） =================
DST=$(curl -s $BASE/dashboard/po-status-distribution -H "$H")
DLEN=$(echo "$DST" | ./.venv/Scripts/python.exe -c "import sys,json;print(len(json.load(sys.stdin)['data']))")
check "po-status 全 5 状态含 0" 5 "$DLEN"
CD=$(echo "$DST" | ./.venv/Scripts/python.exe -c "import sys,json;d=json.load(sys.stdin)['data'];print(dict((x['status'],x['count']) for x in d).get('DRAFT','NA'))")
check "po-status DRAFT=1" 1 "$CD"
CR=$(echo "$DST" | ./.venv/Scripts/python.exe -c "import sys,json;d=json.load(sys.stdin)['data'];print(dict((x['status'],x['count']) for x in d).get('RECEIVED','NA'))")
check "po-status RECEIVED=2" 2 "$CR"
CP=$(echo "$DST" | ./.venv/Scripts/python.exe -c "import sys,json;d=json.load(sys.stdin)['data'];print(dict((x['status'],x['count']) for x in d).get('PARTIALLY_RECEIVED','NA'))")
check "po-status PARTIALLY_RECEIVED=1" 1 "$CP"
CC=$(echo "$DST" | ./.venv/Scripts/python.exe -c "import sys,json;d=json.load(sys.stdin)['data'];print(dict((x['status'],x['count']) for x in d).get('CONFIRMED','NA'))")
check "po-status CONFIRMED=0（含 0 返回）" 0 "$CC"

# ================= 待办角色收敛 =================
TB=$(curl -s $BASE/dashboard/todos -H "$WH")
TBC=$(echo "$TB" | ./.venv/Scripts/python.exe -c "import sys,json;d=json.load(sys.stdin)['data'];print(dict((x['type'],x['count']) for x in d))")
check "BUYER todos PR_TO_PO=2" "2" "$(echo "$TB" | ./.venv/Scripts/python.exe -c "import sys,json;d=json.load(sys.stdin)['data'];print(dict((x['type'],x['count']) for x in d).get('PR_TO_PO','NA'))")"
check "BUYER todos PO_CONFIRM=1" "1" "$(echo "$TB" | ./.venv/Scripts/python.exe -c "import sys,json;d=json.load(sys.stdin)['data'];print(dict((x['type'],x['count']) for x in d).get('PO_CONFIRM','NA'))")"
check "BUYER todos PO_RECEIVE=1" "1" "$(echo "$TB" | ./.venv/Scripts/python.exe -c "import sys,json;d=json.load(sys.stdin)['data'];print(dict((x['type'],x['count']) for x in d).get('PO_RECEIVE','NA'))")"
TZA=$(curl -s $BASE/dashboard/todos -H "$ZH")
TZA_N=$(echo "$TZA" | ./.venv/Scripts/python.exe -c "import sys,json;print(len(json.load(sys.stdin)['data']))")
check "APPLICANT todos 为空（不可执行动作）" 0 "$TZA_N"
TZW=$(curl -s $BASE/dashboard/todos -H "$WHH")
TZW_R=$(echo "$TZW" | ./.venv/Scripts/python.exe -c "import sys,json;d=json.load(sys.stdin)['data'];print(dict((x['type'],x['count']) for x in d).get('PO_RECEIVE','NA'))")
check "WAREHOUSE todos PO_RECEIVE=1（唯一动作）" "1" "$TZW_R"

# ================= 动态区 =================
ACT=$(curl -s $BASE/dashboard/recent-activities -H "$H")
check "recent-activities 不含 LOGIN" 0 "$(echo "$ACT" | ./.venv/Scripts/python.exe -c "import sys,json;d=json.load(sys.stdin)['data'];print(sum(1 for x in d if x['action'] in ('LOGIN','LOGIN_FAILED')))")"
check "recent-activities 含单据号" 1 "$(echo "$ACT" | ./.venv/Scripts/python.exe -c "import sys,json;d=json.load(sys.stdin)['data'];print(1 if any(x.get('document_no') for x in d) else 0)")"
IACT=$(curl -s --get $BASE/dashboard/inventory-activities -H "$H" --data-urlencode "limit=6")
IALEN=$(echo "$IACT" | ./.venv/Scripts/python.exe -c "import sys,json;print(len(json.load(sys.stdin)['data']))")
check "inventory-activities=5 条（5 张入库单）" 5 "$IALEN"
check "inventory-activities 带符号（存在 +）" 1 "$(echo "$IACT" | ./.venv/Scripts/python.exe -c "import sys,json;d=json.load(sys.stdin)['data'];print(1 if any(float(x['quantity'])>0 for x in d) else 0)")"

# ================= 低库存 Top 排序 =================
LS=$(curl -s --get $BASE/dashboard/low-stock -H "$H" --data-urlencode "limit=5")
LSLEN=$(echo "$LS" | ./.venv/Scripts/python.exe -c "import sys,json;print(len(json.load(sys.stdin)['data']))")
check "low-stock list=2 行" 2 "$LSLEN"
SHORT1=$(echo "$LS" | J "['data'][0]['shortage_quantity']")
SHORT2=$(echo "$LS" | J "['data'][1]['shortage_quantity']")
OKORD=$([ "$(echo "$SHORT1 $SHORT2" | ./.venv/Scripts/python.exe -c "import sys;a,b=sys.stdin.read().split();print(1 if float(a)>=float(b) else 0)")" = "1" ] && echo 1 || echo 0)
check "low-stock 按缺口倒序" 1 "$OKORD"

echo "----------------------------------------"
echo "Phase 11 smoke: PASS=$PASS FAIL=$FAIL"
kill $UV 2>/dev/null
[ "$FAIL" -eq 0 ] && echo "SMOKE OK" || { echo "SMOKE FAILED"; exit 1; }
