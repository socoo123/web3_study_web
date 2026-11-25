#!/usr/bin/env bash
# Install into a dedicated user cache, not the site tree or the global npm prefix.
set -euo pipefail
: "${ZK35_TOOLS:?export ZK35_TOOLS to a dedicated absolute cache path}"
lab=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$ZK35_TOOLS"
if [[ -n $(ls -A "$ZK35_TOOLS") ]] && ! cmp -s "$lab/package.json" "$ZK35_TOOLS/package.json"; then
    echo 'Refusing to install in a nonempty, unrelated cache directory' >&2
    exit 2
fi
cp "$lab/package.json" "$lab/package-lock.json" "$ZK35_TOOLS/"
# Optional npm argument: --offline (requires all locked tarballs in npm's cache).
npm ci --prefix "$ZK35_TOOLS" --ignore-scripts --no-audit --no-fund "$@"
