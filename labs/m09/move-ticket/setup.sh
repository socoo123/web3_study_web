#!/usr/bin/env bash
# Download only release artifacts; no wallet, globally installed CLI or running node is required.
set -euo pipefail
version=1.53.2
tag="mainnet-v$version"
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) platform=macos-arm64; sum=4f2c65d55057110ff11033774d1b9778d6f49594d321ab776026194151386048 ;;
  Darwin-x86_64) platform=macos-x86_64; sum=72ce7503ecb8c44da436c5f29bd2c10a6ef42c75edd50fce04e7f509fd9899fb ;;
  Linux-x86_64) platform=ubuntu-x86_64; sum=e93ca7e2c884c3292e47788373b38e519b5eb486766d785963e2c63dfee86357 ;;
  Linux-aarch64) platform=ubuntu-aarch64; sum=03893d3cd234cd40ddd7228aa6066f82617d23c1be8e9bf591028534b7f01a41 ;;
  *) echo 'No pinned Sui release for this host.' >&2; exit 2 ;;
esac
cache="$HOME/.cache/chain-course/m09/sui-$version"
mkdir -p "$cache/bin"
cd "$cache"
tmp=$(mktemp -d "$cache/install.XXXXXXXX")
trap 'rm -rf "$tmp"' EXIT
get() {
  local url=$1 archive=$2 expected=$3 path=$2
  if [[ ! -f "$archive" ]]; then
    path="$tmp/$archive"
    curl -fL --retry 2 -o "$path" "$url"
  fi
  python3 - "$path" "$expected" <<'PY'
import hashlib, sys
h = hashlib.sha256()
with open(sys.argv[1], 'rb') as f:
    for chunk in iter(lambda: f.read(1 << 20), b''):
        h.update(chunk)
if h.hexdigest() != sys.argv[2]:
    sys.exit('SHA-256 mismatch: ' + sys.argv[1])
print(h.hexdigest(), sys.argv[1])
PY
  if [[ $path != "$archive" ]]; then mv "$path" "$archive"; fi
}
archive="sui-$tag-$platform.tgz"
get "https://github.com/MystenLabs/sui/releases/download/$tag/$archive" "$archive" "$sum"
get "https://codeload.github.com/MystenLabs/sui/tar.gz/refs/tags/$tag" source.tgz b32bc517e9cda7257386beacb1e38b3886949d6a5e88f312c9905dda10b92939
# Extract only the two native programs and the two Move libraries the ticket imports.
tar -tzf "$archive" > "$tmp/names"
cli=$(awk -F / '$NF=="sui"' "$tmp/names")
node=$(awk -F / '$NF=="sui-node"' "$tmp/names")
tar -xzf "$archive" -C "$tmp" "$cli" "$node"
install -m 755 "$tmp/$cli" "$cache/bin/sui"
install -m 755 "$tmp/$node" "$cache/bin/sui-node"
packages="sui-$tag/crates/sui-framework/packages"
mkdir -p "$cache/framework"
tar -xzf source.tgz -C "$cache/framework" --strip-components 4 "$packages/move-stdlib" "$packages/sui-framework"
"$cache/bin/sui" --version
