"""Shared fresh, loopback-only Anvil for course experiments (Python standard library)."""
from contextlib import contextmanager
from http.client import HTTPConnection
from itertools import count
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


class RpcError(RuntimeError):
    """The node replied with a JSON-RPC error (distinct from result: null)."""


def send_mined(rpc, tx, *, success=True):
    """Send once; poll only that hash on the lab's auto-mining node."""
    tx_hash = rpc('eth_sendTransaction', tx)
    deadline = time.monotonic() + 5
    while (receipt := rpc('eth_getTransactionReceipt', tx_hash)) is None:
        if time.monotonic() >= deadline:
            raise TimeoutError(f'回执仍不可用，不能判定交易失败或重发: {tx_hash}')
        time.sleep(0.05)
    if receipt['transactionHash'] != tx_hash or int(receipt['status'], 16) != int(success):
        raise RuntimeError(f'回执不匹配: {tx_hash} expected={int(success)} status={receipt["status"]}')
    return receipt


@contextmanager
def anvil(port):
    host = '127.0.0.1'
    binary = shutil.which(os.environ.get('ANVIL', 'anvil'))
    if not binary or not shutil.which('lsof'):
        raise SystemExit('需要 Anvil 1.7.1（PATH 或 ANVIL）与 lsof；参见第 04 课工具准备。')
    ids = count(1)

    def rpc(method, *params):
        request_id = next(ids)
        body = json.dumps({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params})
        conn = HTTPConnection(host, port, timeout=5)  # Direct loopback; no proxy or redirects.
        try:
            conn.request('POST', '/', body, {'Content-Type': 'application/json'})
            response = conn.getresponse()
            if response.status != 200:
                raise OSError(f'{method}: HTTP {response.status}')
            msg = json.load(response)
            if msg.get('jsonrpc') != '2.0' or msg.get('id') != request_id:
                raise OSError(f'{method}: JSON-RPC version/id mismatch')
            if 'error' in msg:
                raise RpcError(f"{method}: {msg['error']}")
            return msg['result']
        finally:
            conn.close()

    with tempfile.TemporaryDirectory(prefix='anvil-course-') as home:
        cmd = [str(Path(binary).resolve()), '--host', host, '--port', str(port), '--chain-id', '31337',
               '--accounts', '2', '--balance', '10', '--mnemonic-random', '12', '--hardfork', 'cancun',
               '--block-base-fee-per-gas', '1000000000', '--no-cors', '--quiet']
        with subprocess.Popen(cmd, cwd=home, env={'HOME': home, 'PATH': os.defpath},
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as proc:
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        raise RuntimeError(f'Anvil 启动失败；检查版本与端口 {port}，不要连接已有服务。')
                    listener = subprocess.run(['lsof', '-nP', '-a', '-p', str(proc.pid), f'-iTCP:{port}',
                                               '-sTCP:LISTEN', '-Fn'], capture_output=True, text=True, timeout=5)
                    if f'n{host}:{port}' in listener.stdout.splitlines():
                        break
                    time.sleep(0.1)
                else:
                    raise TimeoutError(f'未确认本次 Anvil 正在监听 {host}:{port}')
                if (rpc('web3_clientVersion') != 'anvil/v1.7.1' or rpc('eth_chainId') != '0x7a69'
                        or rpc('eth_blockNumber') != '0x0'):
                    raise RuntimeError('需要全新 Anvil 1.7.1 / chainId 31337；不发送交易。')
                yield rpc
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
