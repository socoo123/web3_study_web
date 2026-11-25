#!/usr/bin/env bash
# One local operator for both phases. Never use this setup for an application.
set -euo pipefail
: "${ZK35_TOOLS:?use prepare.sh to install the locked tools first}"
if [[ $# != 1 ]]; then echo "usage: bash $0 NEW_KEYS_DIR" >&2; exit 2; fi
bin=$(cd "$ZK35_TOOLS/node_modules/.bin" && pwd)
lib=$(cd "$ZK35_TOOLS/node_modules/circomlib" && pwd)
umask 077
mkdir "$1"
cd "$1"
# Keep the upstream relative includes intact and all WASI input/output below cwd.
mkdir -p test/circuits circuits
cp "$lib/test/circuits/poseidon3_test.circom" test/circuits/
cp "$lib/circuits/poseidon.circom" "$lib/circuits/poseidon_constants.circom" circuits/
"$bin/circom2" --version
"$bin/circom2" test/circuits/poseidon3_test.circom --r1cs --wasm --O2
r1cs=poseidon3_test.r1cs
snark="$bin/snarkjs"
"$snark" r1cs info "$r1cs" > circuit-info.log 2>&1
cat circuit-info.log
"$snark" powersoftau new bn128 10 pot0.ptau
"$snark" powersoftau contribute pot0.ptau pot1.ptau --name=local-phase-1 -e=teaching-only
"$snark" powersoftau prepare phase2 pot1.ptau prepared.ptau
"$snark" powersoftau verify prepared.ptau > ptau-check.log 2>&1
"$snark" groth16 setup "$r1cs" prepared.ptau initial.zkey
"$snark" zkey contribute initial.zkey proving.zkey --name=local-phase-2 -e=teaching-only
"$snark" zkey verify "$r1cs" prepared.ptau proving.zkey > key-check.log 2>&1
"$snark" zkey export verificationkey proving.zkey verification_key.json
printf 'SETUP_LOCAL_ONLY %s\n' "$PWD/verification_key.json"
