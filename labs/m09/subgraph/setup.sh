#!/usr/bin/env bash
# One-time downloads; the experiment itself uses only the local Docker engine/cache.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
cache=${XDG_CACHE_HOME:-$HOME/.cache}/chain-course/m09/subgraph
mkdir -p "$cache"
cp "$here/package.json" "$here/package-lock.json" "$cache/"
npm ci --prefix "$cache" --ignore-scripts --no-audit --no-fund
case "$(docker info --format '{{.Architecture}}')" in
  arm64|aarch64) arch=arm64; sha='ykHJmFOGdBR8+9smOKBm9ZZDCCCkLQctiHOAddLvmYx9mPeBDMfq6jP51hKYsO5MG8ClPLSlWe+JpiXPjoXgBQ==' ;;
  amd64|x86_64) arch=amd64; sha='+XmShybEaxfCrr0OUUZwYEy2OnYZt5pHH9TzBtLv3+VrK0O/ANuNSVEahqNhKHlgX7GRJ59383ofNhxkRWIYTg==' ;;
  *) echo 'need an arm64 or amd64 Linux container engine' >&2; exit 1 ;;
esac
pkg=anvil-linux-$arch
work=$(mktemp -d "$cache/download.XXXXXX")
trap 'rm -rf "$work"' EXIT
curl -fLsS "https://registry.npmjs.org/@foundry-rs/$pkg/-/$pkg-1.7.1.tgz" -o "$work/anvil.tgz"
[[ $(openssl dgst -sha512 -binary "$work/anvil.tgz" | openssl base64 -A) == "$sha" ]] || { echo 'Anvil digest mismatch' >&2; exit 1; }
tar -xzf "$work/anvil.tgz" -C "$work" package/bin/anvil
export M09_ANVIL="$cache/anvil-1.7.1"
install -m 755 "$work/package/bin/anvil" "$M09_ANVIL"
docker compose -f "$here/compose.yml" pull
