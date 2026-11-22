#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
cpfile=../../m05/target/classpath.txt
if [[ ! -s $cpfile ]]; then echo '先用 JDK 21 运行 bash labs/m05/build.sh' >&2; exit 2; fi
exec java --class-path "$(cat "$cpfile")" SiweLab.java "${1:?选择 login 或 signer}"
