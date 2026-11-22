"""Compare two accounts at the same block on a fresh local Anvil chain."""

import argparse
from dataclasses import dataclass
from time import monotonic, sleep

from anvil_lab import RpcError, anvil


DUE_WEI = 125
GAS_PRICE_WEI = 2_000_000_000


@dataclass(frozen=True)
class Account:
    balance_wei: int
    nonce: int
    code: str
    slot0: str


def snapshot(rpc, block, addresses):
    height = int(block["number"], 16)
    at = {"blockHash": block["hash"], "requireCanonical": True}
    print(f"BLOCK height={height} hash={block['hash']} parent_hash={block['parentHash']} "
          f"tx_count={len(block['transactions'])}")
    accounts = []
    for role, address in zip(("A", "B"), addresses, strict=True):
        state = Account(
            int(rpc("eth_getBalance", address, at), 16),
            int(rpc("eth_getTransactionCount", address, at), 16),
            rpc("eth_getCode", address, at),
            rpc("eth_getStorageAt", address, "0x0", at),
        )
        print(f"ACCOUNT role={role} height={height} address={address} "
              f"balance_wei={state.balance_wei} nonce={state.nonce} "
              f"code={state.code} slot0={state.slot0}")
        if state.code != "0x" or state.slot0 != "0x" + "00" * 32:
            raise RuntimeError("本实验的两账户应无代码且 0 号槽为零")
        accounts.append(state)
    return accounts


def show_tags(rpc):
    for tag in ("latest", "safe", "finalized"):
        try:
            block = rpc("eth_getBlockByNumber", tag, False)
        except RpcError as exc:
            print(f"LOCAL_TAG tag={tag} rpc_error={exc}")
            continue
        if block is None:
            print(f"LOCAL_TAG tag={tag} result=null")
        else:
            print(f"LOCAL_TAG tag={tag} height={int(block['number'], 16)} hash={block['hash']}")


def run(rpc, value_wei):
    chain_id = int(rpc("eth_chainId"), 16)
    before = rpc("eth_getBlockByNumber", "latest", False)
    if chain_id != 31337 or before["number"] != "0x0":
        raise RuntimeError("只在新启动的 31337 链、创世块上开始")
    addresses = rpc("eth_accounts")
    sender, receiver = addresses
    print(f"ORDER chain_id={chain_id} payer={sender} payee={receiver} due_wei={DUE_WEI}")
    a0, b0 = snapshot(rpc, before, addresses)

    tx_hash = rpc("eth_sendTransaction", {
        "from": sender, "to": receiver, "value": hex(value_wei),
        "gas": hex(21_000), "gasPrice": hex(GAS_PRICE_WEI),
    })
    deadline = monotonic() + 5
    while (receipt := rpc("eth_getTransactionReceipt", tx_hash)) is None:
        if monotonic() >= deadline:
            raise RuntimeError(f"本地回执尚不可用 tx={tx_hash}，不判付款失败")
        sleep(0.05)

    after = rpc("eth_getBlockByNumber", receipt["blockNumber"], True)
    if (after["parentHash"] != before["hash"] or after["hash"] != receipt["blockHash"]
            or len(after["transactions"]) != 1):
        raise RuntimeError("回执与单笔付款块、创世父块未对上，不归因账户差额")
    tx = after["transactions"][0]
    value = int(tx["value"], 16)
    if (tx["hash"] != tx_hash or receipt["transactionHash"] != tx_hash
            or tx["from"].lower() != sender.lower() or tx["to"].lower() != receiver.lower()
            or value != value_wei or int(receipt["status"], 16) != 1):
        raise RuntimeError("入块交易未匹配本次成功的直转")
    used = int(receipt["gasUsed"], 16)
    price = int(receipt["effectiveGasPrice"], 16)
    fee = used * price
    print(f"TX hash={tx_hash} block_hash={after['hash']} from={tx['from']} to={tx['to']} "
          f"value_wei={value} status=1 gas_used={used} price_wei_per_gas={price} fee_wei={fee}")
    a1, b1 = snapshot(rpc, after, addresses)
    da, db = a1.balance_wei - a0.balance_wei, b1.balance_wei - b0.balance_wei
    dna, dnb = a1.nonce - a0.nonce, b1.nonce - b0.nonce
    print(f"DELTA A_wei={da} B_wei={db} A_nonce={dna} B_nonce={dnb}")
    if (da, db, dna, dnb) != (-value - fee, value, 1, 0):
        raise RuntimeError("快照差额不符合单笔直转，不判断订单金额")
    show_tags(rpc)
    matched = db == DUE_WEI
    print(f"{'MATCH_AMOUNT' if matched else 'HOLD_AMOUNT'} due_wei={DUE_WEI} received_wei={db}")
    return 0 if matched else 3


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--value-wei", type=int, default=DUE_WEI,
                        help="本次交易的十进制 wei 数；不修改订单应收")
    args = parser.parse_args()
    if not 0 <= args.value_wei < 2**256:
        parser.error("value 必须是 uint256 范围内的十进制 wei 数")
    with anvil(18549) as rpc:
        raise SystemExit(run(rpc, args.value_wei))
