#!/usr/bin/env bash
# Install release binaries only; no node is started and no wallet is opened.
set -euo pipefail
umask 077
cache=${XDG_CACHE_HOME:-$HOME/.cache}/chain-course/m09/lightning
mkdir -p "$cache"
case "$(uname -s)/$(uname -m)" in
  Darwin/arm64) b=arm64-apple-darwin; l=darwin-arm64; bh=4c69d3519af2dafe94b695a8c128dd7756a8ded73799fae609085f2e4aeb5a9e; lh=7285680ddda27e6c640b4608d2ec089a1690ba6fd2cafa98e2a0964c4f0b2024;;
  Darwin/x86_64) b=x86_64-apple-darwin; l=darwin-amd64; bh=02b315c0eac29b2a0e677d232579f5a49ba9b48c55d1c7e4266530223bb2f463; lh=8074ff97f4f6ff3a8ec9c7b48300ccad9c7a0c7000f1924816b4ca9aec2fa952;;
  Linux/aarch64) b=aarch64-linux-gnu; l=linux-arm64; bh=161b769e91c1d18c87de3d9e059b45bace1c56d2e95c29ff04260b424b2e85ae; lh=ff7dc069a0b04f20163fa8c5201753684403c31fa62426f0999f5bc115153bc1;;
  Linux/x86_64) b=x86_64-linux-gnu; l=linux-amd64; bh=593de13690ea3ef15e7ac3a695cc60ca9c2d576a184aeec69c69f458c7707568; lh=4910a14801e10164ca2ea67f5935e2486874331d56bbd0638a68c6158a8e82c9;;
  *) echo '需要受支持的 macOS、Linux 或 WSL2 平台。' >&2; exit 2;;
esac
work=$(mktemp -d "$cache/setup.XXXXXXXX")
trap 'rm -rf "$work"' EXIT
cd "$work"
fetch() {
  local url=$1 sha=$2 dir=$3; shift 3
  curl -fLsS --retry 2 -o archive "$url"
  if command -v sha256sum >/dev/null; then
    printf '%s  archive\n' "$sha" | sha256sum -c -
  else
    printf '%s  archive\n' "$sha" | shasum -a 256 -c -
  fi
  tar -xzf archive "$@"
  for member in "$@"; do install -m 700 "$member" "$cache/$dir/${member##*/}"; done
}
mkdir -p "$cache/bitcoin-30.5/bin" "$cache/lnd-v0.21.8-beta/bin"
if [[ ! -x "$cache/bitcoin-30.5/bin/bitcoind" || ! -x "$cache/bitcoin-30.5/bin/bitcoin-cli" ]]; then
  if [[ $(bitcoind --version 2>/dev/null) == *'v30.5.0'* && $(bitcoin-cli --version 2>/dev/null) == *'v30.5.0'* ]]; then
    echo '沿用当前 PATH 中第 06 课的 Bitcoin Core。'
  else
    fetch "https://bitcoincore.org/bin/bitcoin-core-30.5/bitcoin-30.5-$b.tar.gz" "$bh" 'bitcoin-30.5/bin' bitcoin-30.5/bin/bitcoind bitcoin-30.5/bin/bitcoin-cli
  fi
fi
lnd_dir=lnd-$l-v0.21.8-beta
if [[ ! -x "$cache/lnd-v0.21.8-beta/bin/lnd" || ! -x "$cache/lnd-v0.21.8-beta/bin/lncli" ]]; then
  fetch "https://github.com/lightningnetwork/lnd/releases/download/v0.21.8-beta/$lnd_dir.tar.gz" "$lh" 'lnd-v0.21.8-beta/bin' "$lnd_dir/lnd" "$lnd_dir/lncli"
fi
printf '工具目录：%s（不含节点数据）\n' "$cache"
