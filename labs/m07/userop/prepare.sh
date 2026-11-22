#!/usr/bin/env bash
# Print the path to one verified release archive. No npm install or lifecycle scripts.
set -euo pipefail
cache="${XDG_CACHE_HOME:-$HOME/.cache}/chain-course/m07"
pkg="$cache/contracts-0.7.0.tgz"
integrity='Bt/66ilu3u8I9+vFZ9fTd+cWs55fdb9J5YKfrhsrFafH1drkzwuCSL/xEot1GGyXXNJLQuXbMRztQPyelNbY1A=='
check() {
  [[ "$(openssl dgst -sha512 -binary < "$1" | openssl base64 -A)" == "$integrity" ]]
}
if [[ -f "$pkg" ]]; then
  check "$pkg" || { echo "完整性核验失败，停止；请隔离损坏的缓存 $pkg。" >&2; exit 1; }
else
  [[ ${1:-} != --offline ]] || { echo '请先在仓库根目录运行 bash labs/m07/userop/prepare.sh。' >&2; exit 1; }
  mkdir -p "$cache"
  tmp=$(mktemp "$cache/aa.XXXXXX")
  trap 'rm -f "$tmp"' EXIT
  curl -fLsS https://registry.npmjs.org/@account-abstraction/contracts/-/contracts-0.7.0.tgz -o "$tmp"
  check "$tmp" || { echo 'contracts@0.7.0 下载摘要不符。' >&2; exit 1; }
  mv "$tmp" "$pkg"
fi
printf '%s\n' "$pkg"
