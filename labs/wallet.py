"""Offline address check. Public BIP84 test vectors only; never fund them."""

import sys

from embit import bip32, bip39, script
from embit.networks import NETWORKS

# Source: https://github.com/bitcoin/bips/blob/master/bip-0084.mediawiki#test-vectors
PUBLIC_MNEMONIC = "abandon " * 11 + "about"
ACCOUNT_PATH = "m/84'/0'/0'"
PUBLIC_ACCOUNT_ZPUB = (
    "zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH"
    "1r1ADqtfSdVCToUG868RvUUkgDKf31mGDtKsAYz2oz2AGutZYs"
)
FIRST_RECEIPT = "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"
SECOND_RECEIPT = "bc1qnjg0jd8228aq7egyzacy8cys3knf9xvrerkf9g"
# (branch, index, address on the order); wrong-branch keeps order 1 unchanged.
CASES = {
    "first": (0, 0, FIRST_RECEIPT),
    "second": (0, 1, SECOND_RECEIPT),
    "wrong-branch": (1, 0, FIRST_RECEIPT),
}


def main(args: list[str]) -> int:
    if len(args) > 1 or (args and args[0] not in CASES):
        print("usage: wallet.py [first|second|wrong-branch]", file=sys.stderr)
        return 2
    branch, index, receipt = CASES[args[0] if args else "first"]
    path = f"{ACCOUNT_PATH}/{branch}/{index}"

    seed = bip39.mnemonic_to_seed(PUBLIC_MNEMONIC, password="")
    root = bip32.HDKey.from_seed(seed)
    pubkey = root.derive(path).key.get_public_key()
    address = script.p2wpkh(pubkey).address(NETWORKS["main"])

    # Independent watch-only calculation: the published account public key suffices.
    account_pub = bip32.HDKey.from_base58(PUBLIC_ACCOUNT_ZPUB)
    watch_pubkey = account_pub.derive([branch, index]).key
    watch_address = script.p2wpkh(watch_pubkey).address(NETWORKS["main"])
    watch_matches = watch_address == address
    receipt_matches = receipt == address

    print(f"path={path}")
    print(f"address={address}")
    print(f"watch_only_matches={watch_matches}")
    print(f"receipt_matches={receipt_matches}")
    return 0 if watch_matches and receipt_matches else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
