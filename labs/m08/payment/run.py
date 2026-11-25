"""One local SOL transfer, reconciled by its pre-broadcast signature."""
import argparse
import base64
import json
import struct
import sys
import time
from pathlib import Path

from solders.keypair import Keypair
from solders.system_program import ID, TransferParams, transfer
from solders.transaction import Transaction

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from localnet import Validator

CONFIRMED = {"commitment": "confirmed"}
BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def record(out, name, value):
    with (out / name).open("x", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")


def require(test, reason):
    if not test:
        raise RuntimeError(reason)


def from_base58(text):
    n = 0
    for digit in text:
        n = n * 58 + BASE58.index(digit)
    zeros = len(text) - len(text.lstrip("1"))
    return b"\x00" * zeros + n.to_bytes((n.bit_length() + 7) // 8, "big")


def draft(net, amount, blockhash, last, genesis):
    payer = net.payer.pubkey()
    recipient = Keypair().pubkey()  # Only the throwaway receiving address is needed.
    ix = transfer(TransferParams(from_pubkey=payer, to_pubkey=recipient, lamports=amount))
    tx = Transaction.new_signed_with_payer([ix], payer, [net.payer], blockhash)
    ticket = {"genesisHash": genesis, "signature": str(tx.signatures[0]),
              "recentBlockhash": str(blockhash), "lastValidBlockHeight": last,
              "commitment": "confirmed", "payer": str(payer), "to": str(recipient),
              "lamports": amount}
    return ticket, base64.b64encode(bytes(tx)).decode("ascii")


def statuses(net, signatures):
    return net.rpc("getSignatureStatuses", [signatures, {"searchTransactionHistory": True}])


def receipt(net, sig):
    return net.rpc("getTransaction", [sig, {**CONFIRMED, "encoding": "json",
                                            "maxSupportedTransactionVersion": 0}])


def recover(net, ticket):
    require(net.rpc("getGenesisHash", []) == ticket["genesisHash"], "HOLD_WRONG_LEDGER")
    sig = ticket["signature"]
    until = time.monotonic() + 60
    while time.monotonic() < until:
        result = statuses(net, [sig])
        status = result["value"][0]
        if status and status["confirmationStatus"] in ("confirmed", "finalized"):
            tx = receipt(net, sig)
            if tx is not None:
                require(status["slot"] == tx["slot"] and status["err"] == tx["meta"]["err"],
                        "HOLD_STATUS_RECEIPT_MISMATCH")
                return result, tx
        time.sleep(0.35)
    raise RuntimeError(f"HOLD_UNKNOWN signature={sig}; lookup timed out, do not sign again")


def audit(ticket, tx, accounts):
    message, meta = tx["transaction"]["message"], tx["meta"]
    require(tx["version"] == "legacy" and meta["err"] is None, "HOLD_NOT_SUCCESSFUL_LEGACY")
    require(tx["transaction"]["signatures"] == [ticket["signature"]] and
            message["recentBlockhash"] == ticket["recentBlockhash"], "HOLD_WRONG_TRANSACTION")
    keys, header = message["accountKeys"], message["header"]
    require(keys == [ticket["payer"], ticket["to"], str(ID)], "HOLD_WRONG_ACCOUNTS")
    signed = header["numRequiredSignatures"]
    roles = []
    for i, key in enumerate(keys):
        signer = i < signed
        writable = (i < signed - header["numReadonlySignedAccounts"] if signer else
                    i < len(keys) - header["numReadonlyUnsignedAccounts"])
        info = accounts["value"][i]
        delta = meta["postBalances"][i] - meta["preBalances"][i]
        roles.append({"index": i, "pubkey": key, "signer": signer, "writable": writable,
                      "owner": info["owner"], "executable": info["executable"], "delta": delta})
    require([(r["signer"], r["writable"]) for r in roles] ==
            [(True, True), (False, True), (False, False)], "HOLD_WRONG_PERMISSIONS")
    require(all(r["owner"] == str(ID) and not r["executable"] for r in roles[:2]) and
            roles[2]["executable"], "HOLD_WRONG_ACCOUNT_TYPES")
    ix, = message["instructions"]
    require(keys[ix["programIdIndex"]] == str(ID) and ix["accounts"] == [0, 1],
            "HOLD_WRONG_INSTRUCTION")
    variant, amount = struct.unpack("<IQ", from_base58(ix["data"]))
    require(variant == 2 and amount == ticket["lamports"], "HOLD_WRONG_TRANSFER")
    require([r["delta"] for r in roles] == [-amount - meta["fee"], amount, 0],
            "HOLD_BALANCES_DO_NOT_MATCH")
    return {"state": "MATCH_CONFIRMED_OR_BETTER", "signature": ticket["signature"],
            "receiptSlot": tx["slot"], "ownerReadSlot": accounts["context"]["slot"],
            "feeLamports": meta["fee"], "transferLamports": amount, "roles": roles}


def expiry_drill(net, out, paid, held, held_wire, paid_receipt):
    print(f"Waiting for confirmed height > {held['lastValidBlockHeight']} (same live ledger)", flush=True)
    start = time.monotonic()
    while True:
        height = net.rpc("getBlockHeight", [CONFIRMED])
        if height > held["lastValidBlockHeight"]:
            validity = net.rpc("isBlockhashValid", [held["recentBlockhash"], CONFIRMED])
            if not validity["value"]:
                break
        if time.monotonic() - start >= 240:
            raise RuntimeError("HOLD_EXPIRY_NOT_OBSERVED; wall time is not a block height")
        time.sleep(0.8)

    # Never replace the hash; simulate is a read, not a late attempt to send B.
    simulation = net.rpc("simulateTransaction", [held_wire, {**CONFIRMED, "encoding": "base64",
                              "sigVerify": True, "replaceRecentBlockhash": False}])
    status = statuses(net, [paid["signature"], held["signature"]])
    again = receipt(net, paid["signature"])
    held_receipt = receipt(net, held["signature"])
    evidence = {"confirmedBlockHeight": height, "lastValidBlockHeight": held["lastValidBlockHeight"],
                "waitSeconds": round(time.monotonic() - start, 1), "validity": validity,
                "simulationB": simulation, "statusesAB": status, "receiptA": again,
                "receiptB": held_receipt, "sendCallsB": 0}
    record(out, "expiry.json", evidence)
    require(simulation["value"]["err"] == "BlockhashNotFound", "HOLD_NO_EXPIRY_ERROR")
    a, b = status["value"]
    require(a and a["confirmationStatus"] in ("confirmed", "finalized") and a["err"] is None and
            again and again["slot"] == a["slot"] == paid_receipt["slot"] and
            again["transaction"] == paid_receipt["transaction"] and
            all(again["meta"][k] == paid_receipt["meta"][k]
                for k in ("err", "fee", "preBalances", "postBalances")), "HOLD_CANNOT_RECOVER_A")
    require(b is None and held_receipt is None, "HOLD_UNEXPECTED_B")
    print(f"A=RECOVERED_AFTER_EXPIRY B=EXPIRED_UNSENT height={height} "
          f"last={held['lastValidBlockHeight']} simulationB=BlockhashNotFound")


def run(net, out, amount, wait_expiry):
    genesis = net.rpc("getGenesisHash", [])
    minimum = net.rpc("getMinimumBalanceForRentExemption", [0, CONFIRMED])
    record(out, "precheck.json", {"genesisHash": genesis, "lamports": amount,
                                  "dataBytes": 0, "rentExemptMinimum": minimum})
    if amount < minimum:
        print(f"HOLD_NEW_ACCOUNT_RENT requested={amount} minimum={minimum} signed=0 sent=0")
        return 3

    blockhash, last = net.latest()
    paid, wire = draft(net, amount, blockhash, last, genesis)
    record(out, "A-intent.json", paid)
    if wait_expiry:
        held, held_wire = draft(net, amount, blockhash, last, genesis)
        require(held["signature"] != paid["signature"], "drafts must be distinct")
        record(out, "B-held.json", held)

    height = net.rpc("getBlockHeight", [CONFIRMED])
    record(out, "before-send.json", {"confirmedBlockHeight": height, "lastValidBlockHeight": last})
    require(height <= last, "EXPIRED_BEFORE_FIRST_SEND; nothing submitted")
    # Ignore the send reply on purpose. Recovery receives only the saved ticket.
    try:
        net.rpc("sendTransaction", [wire, {"encoding": "base64", "preflightCommitment": "confirmed"}])
    except (OSError, RuntimeError) as e:
        record(out, "send-error.json", {"error": str(e), "action": "lookup original signature"})
    saved = json.loads((out / "A-intent.json").read_text(encoding="utf-8"))
    status, tx = recover(net, saved)
    record(out, "A-status.json", status)
    record(out, "A-receipt.json", tx)
    require(tx["meta"]["err"] is None, f"EXECUTION_FAILED signature={saved['signature']}")
    accounts = net.rpc("getMultipleAccounts", [tx["transaction"]["message"]["accountKeys"],
                       {**CONFIRMED, "encoding": "base64", "minContextSlot": tx["slot"]}])
    record(out, "A-accounts.json", accounts)
    summary = audit(saved, tx, accounts)
    record(out, "A-audit.json", summary)
    print(f"A={summary['state']} slot={tx['slot']} fee={summary['feeLamports']} "
          f"deltaPayer={summary['roles'][0]['delta']} deltaRecipient={summary['roles'][1]['delta']}")
    print(f"signature={saved['signature']}")
    if wait_expiry:
        expiry_drill(net, out, saved, held, held_wire, tx)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="a new evidence directory")
    parser.add_argument("--lamports", type=int, default=1_250_000)
    parser.add_argument("--wait-expiry", action="store_true", help="also sign but never submit draft B")
    args = parser.parse_args()
    if not 0 < args.lamports < 2**64:
        parser.error("--lamports must be a positive u64")
    if args.out.exists():
        parser.error("--out must be a new directory (never overwrite evidence)")
    args.out.mkdir(parents=True)
    with Validator() as net:
        return run(net, args.out, args.lamports, args.wait_expiry)


if __name__ == "__main__":
    sys.exit(main())
