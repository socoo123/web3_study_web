#!/usr/bin/env bash
# Agave may relink the rustup toolchain named 'solana'. Keep that alias in the course cache.
set -eu
host=$(rustc --print sysroot)
export RUSTUP_HOME="${XDG_CACHE_HOME:-$HOME/.cache}/web3-study/m08/rustup"
rustup toolchain link course-host "$host"
export RUSTUP_TOOLCHAIN=course-host
cd "$(dirname "$0")"
exec cargo-build-sbf --tools-version v1.48 "$@" -- --locked
