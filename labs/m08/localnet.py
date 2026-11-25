"""Fresh, single-validator course ledger. No external RPC, faucet, or wallet config."""
import base64
import json
import os
import random
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

from solders.hash import Hash
from solders.keypair import Keypair
from solders.transaction import Transaction

CACHE = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'web3-study/m08'
BIN = CACHE / 'solana-release/bin'
CLASSIC_PROGRAMS = (
    ('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA', 'spl_token-3.5.0.so'),
    ('ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL', 'spl_associated_token_account-1.1.1.so'),
)


class Validator:
    def __init__(self, programs=()):
        self.programs = programs
        self.payer = Keypair()
        self.http = build_opener(ProxyHandler({}))
        self.process = None

    def rpc(self, method, params):
        body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}).encode()
        req = Request(self.url, body, {'Content-Type': 'application/json'})
        with self.http.open(req, timeout=5) as response:
            reply = json.load(response)
        if 'error' in reply:
            raise RuntimeError(f'{method}: {reply["error"]}')
        return reply['result']

    def latest(self):
        v = self.rpc('getLatestBlockhash', [{'commitment': 'confirmed'}])['value']
        return Hash.from_string(v['blockhash']), v['lastValidBlockHeight']

    def send(self, instructions, signers=None, *, skip_preflight=False):
        blockhash, _ = self.latest()
        tx = Transaction.new_signed_with_payer(instructions, self.payer.pubkey(),
                                              [self.payer, *(signers or ())], blockhash)
        signature = str(tx.signatures[0])
        try:
            answer = self.rpc('sendTransaction', [base64.b64encode(bytes(tx)).decode(), {
                'encoding': 'base64', 'skipPreflight': skip_preflight, 'preflightCommitment': 'confirmed'}])
            if answer != signature:
                raise RuntimeError(f'RPC returned another signature: {answer}')
            end = time.monotonic() + 60
            while time.monotonic() < end:
                receipt = self.rpc('getTransaction', [signature, {'encoding': 'json', 'commitment': 'confirmed',
                                                                   'maxSupportedTransactionVersion': 0}])
                if receipt is not None:
                    return receipt  # meta.err is a business-relevant result, not a transport error.
                time.sleep(.2)
        except (OSError, RuntimeError) as exc:
            raise RuntimeError(f'{signature}: {exc}') from exc
        raise TimeoutError(f'no confirmed receipt yet: {signature}; not resubmitting')

    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory(prefix='course-agave-')
        try:
            self._start(Path(self.temp.name))
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def _start(self, directory):
        identity, vote, stake = Keypair(), Keypair(), Keypair()
        keyfile = directory / 'validator.json'
        keyfile.write_text(identity.to_json())  # Parent directory is private; removed on exit.
        ledger = directory / 'ledger'
        command = [BIN / 'solana-genesis', '--ledger', ledger, '--cluster-type', 'development',
                   '--bootstrap-validator', str(identity.pubkey()), str(vote.pubkey()), str(stake.pubkey()),
                   '--bootstrap-validator-stake-lamports', '100000000000',
                   '--target-signatures-per-slot', '0', '--target-lamports-per-signature', '5000',
                   '--faucet-pubkey', str(self.payer.pubkey()), '--faucet-lamports', '100000000000',
                   '--hashes-per-tick', 'sleep']
        for address, filename in CLASSIC_PROGRAMS:
            command += ['--bpf-program', address, 'BPFLoader2111111111111111111111111111111111',
                        CACHE / 'programs' / filename]
        for address, path in self.programs:
            command += ['--upgradeable-program', str(address), 'BPFLoaderUpgradeab1e11111111111111111111111',
                        Path(path).resolve(), 'none']
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
        port = random.randrange(16000, 48000, 64)
        self.url = f'http://127.0.0.1:{port}'
        log = directory / 'node.log'
        with log.open('wb') as output:
            self.process = subprocess.Popen([
                BIN / 'agave-validator', '--ledger', ledger, '--identity', keyfile,
                '--vote-account', str(vote.pubkey()), '--bind-address', '127.0.0.1',
                '--gossip-host', '127.0.0.1', '--gossip-port', str(port + 2),
                '--dynamic-port-range', f'{port + 2}-{port + 63}', '--rpc-bind-address', '127.0.0.1',
                '--rpc-port', str(port), '--allow-private-addr', '--full-rpc-api',
                '--enable-rpc-transaction-history', '--enable-extended-tx-metadata-storage',
                '--no-os-network-limits-test', '--no-poh-speed-test', '--no-wait-for-vote-to-start-leader',
                '--log', '-'], cwd=directory, stdout=output, stderr=subprocess.STDOUT)
        end = time.monotonic() + 75
        while self.process.poll() is None and time.monotonic() < end:
            try:
                observed = self.rpc('getIdentity', [])['identity']
                if observed != str(identity.pubkey()):
                    raise ValueError('RPC port belongs to another validator; no transaction sent')
                self.rpc('getHealth', [])
                return
            except (URLError, RuntimeError, TimeoutError):
                time.sleep(.2)
        raise RuntimeError('validator startup failed:\n' + log.read_text(errors='replace')[-4500:])

    def __exit__(self, *_):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.temp.cleanup()
