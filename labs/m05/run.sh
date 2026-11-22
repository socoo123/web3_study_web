#!/usr/bin/env bash
set -euo pipefail
base=$(cd "$(dirname "$0")" && pwd)
if [[ ! -s $base/target/classpath.txt ]]; then echo '先用 JDK 21 运行 bash labs/m05/build.sh' >&2; exit 2; fi
main=${1:?用法: run.sh ClassName [args...]}; shift
exec java -cp "$base/target/classes:$(cat "$base/target/classpath.txt")" "course.m05.$main" "$@"
