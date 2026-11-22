#!/usr/bin/env bash
set -eu
umask 077
if [ "$#" -ne 0 ]; then
  echo '本实验不接受地址、网络、钱包或数据目录参数。' >&2
  exit 2
fi
command -v python3 >/dev/null || { echo '缺少 python3；请按第 06 课准备环境。' >&2; exit 2; }
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
exec python3 -u "$here/bitcoin_payment.py"
