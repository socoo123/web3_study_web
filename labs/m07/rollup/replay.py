"""Offline replay for ticket R-25. Nothing here dials an RPC or submits a transaction."""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TX = '0x73a8f37077852565f64ce046b2c18d936b7c42ba81761f2a265b784c7e394a94'
INBOX = '0xff00000000000000000000000000000011155420'
SYSTEM_CONFIG = '0x034edd2a225f7f429a63e0f1d2084b9e0a93b538'
L1_BLOCK = '0x4200000000000000000000000000000000000015'


class Hold(Exception):
    pass


def require(condition, reason):
    if not condition:
        raise Hold(reason)


def height(block):
    return int(block['number'], 16)


def check_inclusion(tx_hash, tx, receipt, block, layer):
    slot = int(receipt['transactionIndex'], 16)
    require(tx_hash == tx['hash'] == receipt['transactionHash']
            and tx['blockHash'] == receipt['blockHash'] == block['hash']
            and tx['blockNumber'] == receipt['blockNumber'] == block['number']
            and tx['transactionIndex'] == receipt['transactionIndex']
            and 0 <= slot < len(block['transactions'])
            and block['transactions'][slot] == tx_hash, layer + '_INCLUSION_MISMATCH')
    require(receipt['status'] == '0x1', layer + '_EXECUTION_NOT_SUCCESSFUL')


def check_path(start, path, end, layer):
    """Follow every recorded parentHash, including the link out of the target block."""
    prev = start
    for step in path:
        require(height(step) == height(prev) + 1 and step['parentHash'] == prev['hash'],
                layer + '_PATH_GAP_OR_FORK')
        prev = step
    require(prev['hash'] == end['hash'] and height(prev) == height(end), layer + '_HEAD_NOT_LINKED')


def check_publication(data, target):
    p = data.get('publication')
    require(p, 'PUBLICATION_MISSING')
    idx, batch = p['indexedBlock'], p['batch']
    pub, tx, config = p['numberedBlock'], p['transaction'], p['batcherConfig']
    require(idx['hash'] == target['hash'] and idx['height'] == height(target)
            and idx['batchNumber'] == batch['number']
            and batch['l2_start_block_number'] <= height(target) <= batch['l2_end_block_number'],
            'INDEX_LINK_MISMATCH')
    # This historical channel has one blob in one batcher transaction. Refuse other layouts.
    require(batch['batch_data_container'] == 'in_blob4844'
            and batch['l1_transaction_hashes'] == [tx['hash']]
            and len(batch['blobs']) == 1 and batch['blobs'][0]['l1_transaction_hash'] == tx['hash']
            and tx['type'] == '0x3' and tx['blobVersionedHashes'] == [batch['blobs'][0]['hash']],
            'BLOB_REFERENCE_MISMATCH')
    check_inclusion(tx['hash'], tx, p['receipt'], pub, 'L1')
    require(tx['to'].lower() == INBOX and config['address'].lower() == SYSTEM_CONFIG
            and config['l1BlockHash'] == pub['hash']
            and config['batcherHash'].lower() == '0x' + '00' * 12 + tx['from'][2:].lower(),
            'BATCHER_CONFIG_MISMATCH')
    print(f"PUBLICATION batch={batch['number']} range={batch['l2_start_block_number']}.."
          f"{batch['l2_end_block_number']} L1={height(pub)} hash={pub['hash']} blobRefs=1")
    print(f"LINK index+rpc batchTx={tx['hash']} blob={tx['blobVersionedHashes'][0]} "
          'independentBlobReplay=false')
    return pub


def audit(args):
    data = json.loads(args.input.read_text())
    require(int(data['l2ChainId'], 16) == 11155420 and int(data['l1ChainId'], 16) == 11155111,
            'WRONG_NETWORK')
    target, tx, receipt, heads = data['numberedBlock'], data['transaction'], data['receipt'], data['heads']
    check_inclusion(TX, tx, receipt, target, 'L2')
    print(f"RECEIPT L2={height(target)} hash={target['hash']} index={int(tx['transactionIndex'], 16)} "
          f"status={receipt['status']} valueWei={int(tx['value'], 16)} self={tx['from'] == tx['to']}")
    origin = data['origin']
    origin_height = int(origin['numberWord'], 16)
    require(origin['address'].lower() == L1_BLOCK and origin['l2BlockHash'] == target['hash']
            and origin_height == height(origin['l1NumberedBlock'])
            and origin['hashWord'] == origin['l1NumberedBlock']['hash'], 'ORIGIN_MISMATCH')
    print(f"ORIGIN L1={origin_height} hash={origin['hashWord']} notBatchReceipt=true")
    safe = heads['safe']
    print(f"HEADS utc={data['observedUtc']['l2Heads']} latest={height(heads['latest'])} safe={height(safe)}")
    require(height(heads['latest']) >= height(safe), 'INCONSISTENT_HEADS')
    require(args.omit != 'parent' and 'pathToSafe' in data, 'SAFE_PATH_MISSING')
    check_path(target, data['pathToSafe'], safe, 'SAFE')
    print(f"SAFE_PATH edges={len(data['pathToSafe'])} nodeReportsSafeCoverage=true")
    require(args.omit != 'publication', 'PUBLICATION_MISSING')
    pub = check_publication(data, target)
    require(args.omit != 'finalized' and heads.get('finalized') and data.get('l1Finalized'),
            'SAFE_FINALITY_UNKNOWN')
    lf, ef = heads['finalized'], data['l1Finalized']
    print(f"FINALIZED_HEADS L2={height(lf)} L1={height(ef)}")
    require(height(lf) <= height(safe), 'INCONSISTENT_HEADS')
    if height(lf) < height(target):
        print('RESULT SAFE_NOT_FINAL_AT_SAMPLE')
    else:
        # Height alone does not certify either ancestry; require both sets of links.
        check_path(target, data.get('pathToL2Finalized', []), lf, 'FINAL_L2')
        check_path(pub, data.get('pathToL1Finalized', []), ef, 'FINAL_L1')
        print('RESULT FINALIZED_AT_SAMPLE')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', type=Path, default=HERE / 'observation.json')
    ap.add_argument('--omit', choices=['publication', 'parent', 'finalized'],
                    help='withhold one evidence group; never modify the archived responses')
    try:
        audit(ap.parse_args())
    except Hold as exc:
        print('HOLD', exc)
        raise SystemExit(3)
    except (KeyError, TypeError, ValueError, OSError) as exc:
        print(f'HOLD UNREADABLE_EVIDENCE: {exc}')
        raise SystemExit(3)
