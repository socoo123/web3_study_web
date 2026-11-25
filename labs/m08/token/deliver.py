"""Create a worthless classic mint, then settle a single local delivery."""
import argparse
import json
from pathlib import Path
import struct
import sys

from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.system_program import ID as SYSTEM, CreateAccountParams, create_account
from solders.token import ID as TOKEN
from solders.transaction import VersionedTransaction

from review import ATA_PROGRAM, DECIMALS, ata, binary, review

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from localnet import Validator


def meta(key, *, signer=False, writable=False):
    return AccountMeta(key, signer, writable)


def create_ata(payer, wallet, mint):
    return Instruction(ATA_PROGRAM, b"\x00", [  # Create, not a token transfer
        meta(payer, signer=True, writable=True), meta(ata(wallet, mint), writable=True),
        meta(wallet), meta(mint), meta(SYSTEM), meta(TOKEN),
    ])


def save_receipt(net, instructions, signers=(), *, skip_preflight=False):
    live = net.send(instructions, list(signers), skip_preflight=skip_preflight)
    signature = live["transaction"]["signatures"][0]
    # Read the very same signature on the same ledger, this time with signed bytes.
    raw = net.rpc("getTransaction", [signature, {"commitment": "confirmed", "encoding": "base64",
                                                "maxSupportedTransactionVersion": 0}])
    if raw is None or (raw["slot"], raw["meta"]) != (live["slot"], live["meta"]):
        raise RuntimeError(f"receipt mismatch: {signature}; do not resubmit")
    if str(VersionedTransaction.from_bytes(binary(raw["transaction"])).signatures[0]) != signature:
        raise RuntimeError(f"wrong signed transaction returned for {signature}")
    return raw


def run(net, issued, due, sent):
    payer = net.payer.pubkey()
    new_mint, issuer, sender = Keypair(), Keypair(), Keypair()
    mint, src_owner, dst_owner = new_mint.pubkey(), sender.pubkey(), Keypair().pubkey()
    src, dst = ata(src_owner, mint), ata(dst_owner, mint)
    account_order = list(map(str, [mint, src, dst]))
    receipts, snapshots = {}, {}
    evidence = {
        "genesisHash": net.rpc("getGenesisHash", []), "validator": net.rpc("getVersion", []),
        "commitment": "confirmed", "programs": {"token": str(TOKEN), "associatedToken": str(ATA_PROGRAM)},
        "roles": dict(payer=str(payer), mint=str(mint), mintAuthority=str(issuer.pubkey()),
                      sourceOwner=str(src_owner), destinationOwner=str(dst_owner),
                      sourceAta=str(src), destinationAta=str(dst)),
        "order": {"issueRaw": str(issued), "dueRaw": str(due), "sendRaw": str(sent)},
        "accountOrder": account_order, "receipts": receipts, "snapshots": snapshots,
    }

    def snapshot(step):
        snapshots[step] = net.rpc("getMultipleAccounts", [account_order, {
            "encoding": "base64", "commitment": "confirmed", "minContextSlot": receipts[step]["slot"],
        }])

    rent = net.rpc("getMinimumBalanceForRentExemption", [82, {"commitment": "confirmed"}])
    create = create_account(CreateAccountParams(from_pubkey=payer, to_pubkey=mint, owner=TOKEN,
                                                space=82, lamports=rent))
    init = Instruction(TOKEN, bytes([20, DECIMALS]) + bytes(issuer.pubkey()) + b"\x00",
                       [meta(mint, writable=True)])  # InitializeMint2; no freeze authority
    receipts["mint"] = save_receipt(net, [create, init], [new_mint])
    receipts["accounts"] = save_receipt(net, [create_ata(payer, src_owner, mint), create_ata(payer, dst_owner, mint)])
    snapshot("accounts")

    issue = Instruction(TOKEN, struct.pack("<BQB", 14, issued, DECIMALS), [  # MintToChecked
        meta(mint, writable=True), meta(src, writable=True), meta(issuer.pubkey(), signer=True),
    ])
    receipts["issue"] = save_receipt(net, [issue], [issuer])
    snapshot("issue")

    accounts = [meta(src, writable=True), meta(mint), meta(dst, writable=True), meta(src_owner, signer=True)]
    for step, decimals in (("rejected", DECIMALS - 1), ("delivery", DECIMALS)):
        transfer = Instruction(TOKEN, struct.pack("<BQB", 12, sent, decimals), accounts)
        receipts[step] = save_receipt(net, [transfer], [sender], skip_preflight=(step == "rejected"))
        snapshot(step)
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="new directory for public evidence")
    parser.add_argument("--issue-raw", type=int, default=2_500_000)
    parser.add_argument("--due-raw", type=int, default=1_250_001)
    parser.add_argument("--send-raw", type=int, help="default: due-raw")
    args = parser.parse_args()
    sent = args.due_raw if args.send_raw is None else args.send_raw
    if not (0 < sent <= args.issue_raw < 2**64 and 0 < args.due_raw < 2**64):
        parser.error("expect 0 < send <= issue < 2^64 and 0 < due < 2^64 (raw units)")
    args.out.mkdir()  # Never mix two ledgers' evidence or copy a validator working directory.
    with Validator() as net:
        evidence = run(net, args.issue_raw, args.due_raw, sent)
    with (args.out / "evidence.json").open("x", encoding="utf-8") as file:
        json.dump(evidence, file, indent=2)
        file.write("\n")
    return review(evidence)


if __name__ == "__main__":
    sys.exit(main())
