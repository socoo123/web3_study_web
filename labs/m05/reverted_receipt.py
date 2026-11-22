"""Submit once to our already-settled single-order escrow; print the mined failure hash."""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'm04'))
from handoff import require, rpc, selector, verify


def main():
    release = json.loads(Path(os.environ['M05_MANIFEST']).read_text())
    handoff = verify(release)  # checks our localhost:18556 Anvil, deployment, code and roles
    require(handoff['state'] == 2, 'expected a fresh --hold --settle-wei release in Settled')
    tx = {'from': handoff['payer'], 'to': handoff['contractAddress'], 'data': selector(rpc, 'settle()'),
          'gas': hex(100_000), 'value': '0x0'}
    # Keep submission separate from execution; preflight estimation would refuse this call.
    rpc('evm_setAutomine', False)
    try:
        tx_hash = rpc('eth_sendTransaction', tx)
        rpc('evm_mine')
    finally:
        rpc('evm_setAutomine', True)
    r = rpc('eth_getTransactionReceipt', tx_hash)
    require(r and r['transactionHash'] == tx_hash and r['status'] == '0x0' and not r['logs']
            and int(r['gasUsed'], 16) > 0, 'missing mined failure receipt; never resubmit automatically')
    print(tx_hash)


if __name__ == '__main__':
    main()
