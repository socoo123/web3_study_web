#!/usr/bin/env bash
set -euo pipefail
: "${ZK35_TOOLS:?use prepare.sh to install the locked tools first}"
if [[ $# != 3 ]]; then echo "usage: bash $0 KEYS_DIR A|B NEW_EVIDENCE_DIR" >&2; exit 2; fi
keys=$(cd "$1" && pwd)
snark=$(cd "$ZK35_TOOLS/node_modules/.bin" && pwd)/snarkjs
vk="$keys/verification_key.json"
# Pairs and registered commitments are circomlib 2.0.5's two independent test vectors.
case "$2" in
    A) pair='["1","2"]'; expected=7853200120776062878684798364095072458815029376092732009249414926327459813530 ;;
    B) pair='["3","4"]'; expected=14763215145315200506921711489642608356394854266165572616578112107564877678998 ;;
    *) echo 'expected fixture A or B' >&2; exit 2 ;;
esac
umask 077
mkdir "$3"
cd "$3"
private=$(mktemp -d)
trap 'rm -rf "$private"' EXIT
printf '{"inputs":%s}\n' "$pair" > "$private/input.json"
"$snark" wtns calculate "$keys/poseidon3_test_js/poseidon3_test.wasm" "$private/input.json" "$private/witness.wtns"
"$snark" wtns check "$keys/poseidon3_test.r1cs" "$private/witness.wtns"
"$snark" groth16 prove "$keys/proving.zkey" "$private/witness.wtns" proof.json public.json

# Check against the registered commitment, not whatever value came with the proof.
node - "$expected" <<'JS'
const fs = require('node:fs');
const [expected] = process.argv.slice(2);
const signals = JSON.parse(fs.readFileSync('public.json', 'utf8'));
if (!Array.isArray(signals) || signals.length !== 1 || signals[0] !== expected) {
    throw new Error('public signals do not match the registered vector');
}
const next = (BigInt(expected) + 1n).toString(); // Both fixture values are < p-1.
fs.writeFileSync('changed.json', JSON.stringify([next]) + '\n');
JS
"$snark" groth16 verify "$vk" public.json proof.json > accept.log 2>&1
grep -F 'OK!' accept.log
rc=0
"$snark" groth16 verify "$vk" changed.json proof.json > reject.log 2>&1 || rc=$?
if [[ $rc != 1 ]] || ! grep -F 'Invalid proof' reject.log; then
    cat reject.log >&2
    echo "expected a pairing rejection (exit 1), got exit $rc" >&2
    exit 1
fi
node - "$vk" "$rc" <<'JS' | tee receipt.txt
const crypto = require('node:crypto'), fs = require('node:fs');
const digest = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
console.log(`vk.sha256=${digest(process.argv[2])}\nproof.sha256=${digest('proof.json')}`);
console.log(`public=${JSON.parse(fs.readFileSync('public.json'))[0]} ACCEPT exit=0`);
console.log(`changed=${JSON.parse(fs.readFileSync('changed.json'))[0]} REJECT exit=${process.argv[3]}`);
JS
