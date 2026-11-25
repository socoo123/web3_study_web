"""Check public files from one local run. No wallet, CLI or RPC needed."""
import argparse
import json
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text())


def review(folder, number, final):
    manifest = read(folder / 'run.json')
    a, b = manifest['addresses']['A'], manifest['addresses']['B']
    first, second = (b, a) if manifest['reverse'] else (a, b)
    oid, pkg = manifest['object'], manifest['package']
    typ = pkg + '::ticket::Ticket'
    require(a != b, 'roles must be distinct')

    def receipt(name, sender):
        tx = read(folder / (name + '.json'))
        require(tx['effects']['status']['status'] == 'success', name + ': not executed successfully')
        require(tx['digest'] == tx['effects']['transactionDigest'], name + ': digest mismatch')
        require(tx['transaction']['data']['sender'] == sender, name + ': unexpected signer')
        return tx

    release = receipt('publish', first)
    require(any(c['type'] == 'published' and c['packageId'] == pkg for c in release['objectChanges']),
            'wrong publication')

    def state(name):
        obj = read(folder / (name + '.json'))['data']
        fields = obj['content']['fields']
        require(obj['objectId'] == fields['id']['id'] == oid and obj['type'] == typ,
                name + ': wrong object or Move type')
        require(int(fields['number']) == number, name + ': wrong business number')
        return obj

    states = []
    for tx_name, state_name, signer, new_owner in (
            ('open', 'created', first, first), ('handoff', 'handed', first, second),
            ('return', 'returned', second, first)):
        tx, obj = receipt(tx_name, signer), state(state_name)
        data = tx['transaction']['data']
        command, = data['transaction']['transactions']
        call = command['MoveCall']
        require((call['package'], call['module'], call['function']) ==
                (pkg, 'ticket', 'handoff' if states else 'open'), tx_name + ': wrong Move entry')
        change, = [c for c in tx['objectChanges'] if c.get('objectId') == oid]
        require(change['type'] == ('created' if not states else 'mutated') and
                change['objectType'] == typ and change['owner'] == obj['owner'] == {'AddressOwner': new_owner},
                tx_name + ': change/owner mismatch')
        require(str(change['version']) == str(obj['version']) and change['digest'] == obj['digest'] and
                obj['previousTransaction'] == tx['digest'], tx_name + ': object reference mismatch')
        if states:
            ticket_ref, = [i for i in data['transaction']['inputs'] if i.get('objectId') == oid]
            old = states[-1]
            require(str(ticket_ref['version']) == str(old['version']) and ticket_ref['digest'] == old['digest'],
                    tx_name + ': spent a different version')
            gas_versions = [int(g['version']) for g in data['gasData']['payment']]
            require(int(obj['version']) == 1 + max(int(old['version']), *gas_versions),
                    tx_name + ': ticket/gas input versions do not explain output')
        states.append(obj)

    require(state('after-refusal') == states[1], 'refusal changed the object')
    refusal = read(folder / 'refusal.json')
    detail = refusal['detail'].lower()
    require(refusal['exitCode'] != 0 and refusal['sender'] == first and refusal['recipient'] == first and
            f'object {oid} is owned by account address {second}, but given owner/signer address is {first}' in detail,
            'missing specific ownership refusal (a generic RPC error is not evidence)')
    require(states[-1]['owner']['AddressOwner'] == manifest['addresses'][final], 'wrong final holder')
    print('MATCH_LOCAL number=%d final=%s versions=%s refused=UNCHANGED' %
          (number, final, ' → '.join(str(s['version']) for s in states)))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('folder', type=Path)
    p.add_argument('--expect-number', type=int, required=True)
    p.add_argument('--expect-final', choices=['A', 'B'], required=True)
    args = p.parse_args()
    try:
        review(args.folder, args.expect_number, args.expect_final)
    except (ValueError, KeyError, TypeError, OSError) as e:
        p.exit(3, f'HOLD: {e}\n')
