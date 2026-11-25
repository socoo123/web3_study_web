#!/usr/bin/env bash
# M04 owns the node in terminal A. This launcher owns only its three foreground-lifetime services.
set -euo pipefail
umask 077
fail() { printf '%s\n' "$*" >&2; exit 1; }
usage='用法：bash labs/m10/desk/run.sh init WORK ORDER EXPECTED_WEI MIN_DEPTH | resume WORK'
mode=${1:-}; [[ $mode == init && $# == 5 || $mode == resume && $# == 2 ]] || fail "$usage"
here=$(cd "$(dirname "$0")" && pwd); labs=$(cd "$here/../.." && pwd)
work=$(cd "$2" && pwd); m05="$labs/m05"
export M05_MANIFEST="$work/release/manifest.json"
[[ -f $M05_MANIFEST ]] || fail '请先在 A 启动不预付的 M04 部署，并传入该次 WORK。'
for port in 18020 18038 18039; do
    if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null; then fail "端口 $port 已有服务，不接管、不终止。"; fi
done
# Validate the real receipt, deployment input and live code before creating a database or opening the payer UI.
reading=$(python3 "$labs/m04/handoff.py" "$M05_MANIFEST")
if [[ ! -s $m05/target/classpath.txt || ! -f $m05/target/classes/course/m05/OrderApp.class ]]; then
    bash "$m05/build.sh"
fi
if [[ $mode == init ]]; then
    [[ ! -e $work/desk-db && ! -e $work/desk-order ]] || fail '此 WORK 已开单。重启请用 resume；新订单另起部署和目录。'
    order=$3; amount=$4; depth=$5
    [[ $order =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ ]] || fail '无效订单号'
    python3 -c 'import re,sys; a,d=sys.argv[1:]; sys.exit(0 if re.fullmatch(r"[1-9][0-9]{0,18}",a) and int(a)<=10**18 and re.fullmatch(r"[1-9][0-9]?",d) and int(d)<=64 else "要求 1..10^18 wei 和 1..64 次确认")' "$amount" "$depth"
    M05_DB=$(python3 -c 'import json,sys; r=json.load(sys.stdin); sys.exit("必须从尚未付款的部署块开始") if r["state"]!=0 or r["readBlockHash"]!=r["deploymentBlockHash"] else print("m05_desk"+r["deploymentBlockHash"][2:26])' <<< "$reading")
    export M05_DB
    if ! docker inspect m05-course-postgres >/dev/null 2>&1; then bash "$m05/db.sh" start; fi
    printf 'CREATE DATABASE %s;\n' "$M05_DB" | M05_DB=m05 bash "$m05/db.sh" sql
    bash "$m05/db.sh" sql < "$m05/schema.sql"
    bash "$m05/db.sh" sql < "$m05/orders.sql"
    bash "$m05/run.sh" Scan
    bash "$m05/run.sh" OrderIntent create "$order" native:31337 "$amount" "$depth"
    printf '%s\n' "$M05_DB" > "$work/desk-db"
    printf '%s\n' "$order" > "$work/desk-order"
else
    IFS= read -r M05_DB < "$work/desk-db"; export M05_DB
    IFS= read -r order < "$work/desk-order"
    [[ $M05_DB =~ ^m05_[a-z0-9]+$ && $order =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ ]] || fail '无效的本地交接记录'
fi
pids=()
cleanup() { for pid in ${pids[@]+"${pids[@]}"}; do kill "$pid" 2>/dev/null || :; done; wait || :; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
bash "$m05/run.sh" OrderApp > "$work/order-app.log" 2>&1 & api=$!; pids+=("$api")
for ((i=0; i<60; i++)); do
    kill -0 "$api" 2>/dev/null || fail "OrderApp 启动失败，查看 $work/order-app.log"
    if snapshot=$(curl --noproxy '*' --connect-timeout 1 --max-time 4 -fsS "http://127.0.0.1:18020/orders/$order" 2>/dev/null); then break; fi
    sleep .5
done
[[ -n ${snapshot:-} ]] || fail "订单未就绪，查看 $work/order-app.log"
quote=$(python3 -c 'import json,sys; r=json.load(sys.stdin); i=r["intent"]; m=json.load(open(sys.argv[2])); sys.exit("意图与清单/订单不符") if i["id"]!=sys.argv[1] or not i["active"] or i["asset"]!="native:31337" or i["release"]["deployHash"]!=m["deploymentBlockHash"].lower() else print(i["expectedUnits"])' "$order" "$M05_MANIFEST" <<< "$snapshot")
env -u M05_DB -u M05_MANIFEST python3 "$here/payer.py" "$work" "$order" "$quote" & pids+=("$!")
python3 "$here/desk.py" "$order" & pids+=("$!")
printf '订单 %s，专库 %s；Ctrl-C 只停本终端的服务，保留 A 和数据库。\n' "$order" "$M05_DB"
while :; do
    for pid in "${pids[@]}"; do kill -0 "$pid" 2>/dev/null || fail '一个本轮服务已退出；请查看错误后用 resume 重启。'; done
    sleep 1
done
