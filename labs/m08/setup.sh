#!/usr/bin/env bash
# Run from the course root. Installs tools in the user cache, not in the wallet config.
set -euo pipefail
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) arch=aarch64-apple-darwin; sha=b2045f2c2ca8c97b82733bada6c9c11b46196c1acd8f00e33742a7d2c2060a12 ;;
  Darwin-x86_64) arch=x86_64-apple-darwin; sha=18016b352fdfcd2dbfe3a03874ef2fc56b2270f8780d474f7a585c80a3b9050d ;;
  Linux-x86_64) arch=x86_64-unknown-linux-gnu; sha=c43539ebdf6942472e8b87635d6ea55f428a51e3d0219f7b6f720fc6b19fade0 ;;
  *) echo '需要 macOS arm64/x86_64 或 Linux x86_64 上的 Agave 2.3.13。' >&2; exit 1 ;;
esac
cache=${XDG_CACHE_HOME:-$HOME/.cache}/web3-study/m08
mkdir -p "$cache/programs"
work=$(mktemp -d "$cache/download.XXXXXX")
trap 'rm -rf "$work"' EXIT
checked_download() {
  local dest=$1 url=$2 digest=$3
  if [[ ! -f $dest ]] || ! printf '%s  %s\n' "$digest" "$dest" | shasum -a 256 -c - >/dev/null; then
    curl -fLsS --retry 2 "$url" -o "$work/asset"
    printf '%s  %s\n' "$digest" "$work/asset" | shasum -a 256 -c -
    mv "$work/asset" "$dest"
  fi
}
archive=$cache/agave-v2.3.13.tar.bz2
checked_download "$archive" "https://github.com/anza-xyz/agave/releases/download/v2.3.13/solana-release-$arch.tar.bz2" "$sha"
tar -xjf "$archive" -C "$cache"
base=https://raw.githubusercontent.com/anza-xyz/agave/v2.3.13/program-test/src/programs
checked_download "$cache/programs/spl_token-3.5.0.so" "$base/spl_token-3.5.0.so" 18264f491c7e0ad056dd36f42f8de6d1fedf9f044d1f521e714b4dc6b61594b6
checked_download "$cache/programs/spl_associated_token_account-1.1.1.so" "$base/spl_associated_token_account-1.1.1.so" e5e7aed11ad3969eea2aa76c8b4d2e73ea25be7e6b5cce989b7710cf5452496e
python3 -m venv "$cache/venv"
"$cache/venv/bin/python" -m pip install --disable-pip-version-check 'solders==0.26.0'
"$cache/solana-release/bin/agave-validator" --version
printf '在当前 shell 执行 source labs/m08/env.sh。第 31 课首次编译还需联网安装 SBF 工具和 Rust 依赖。\n'
