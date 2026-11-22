#!/usr/bin/env bash
set -eu
umask 077
for tool in python3 bitcoind bitcoin-cli anvil lsof; do
  command -v "$tool" >/dev/null || { echo "缺少 $tool；请先按第 04 课准备环境。" >&2; exit 2; }
done

# 参数只改变新建 Anvil 的链号；客户端的允许值和回环端点不可由调用方更改。
exec python3 -I -u - "$@" <<'PY'
import http.client
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

HOST = '127.0.0.1'
BTC_PORT, EVM_PORT = 19443, 18546
EXPECTED_BTC, EXPECTED_EVM = 'regtest', '0x7a69'


@contextmanager
def owned_node(name, directory, port, args):
    directory.mkdir()
    binary = Path(shutil.which(name)).resolve()
    env = {'HOME': str(directory), 'PATH': os.defpath, 'LC_ALL': 'C'}
    proc = subprocess.Popen([str(binary), *args], cwd=directory, env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        # 不探测现有 HTTP 服务：先从操作系统确认监听者就是本次启动的子进程。
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise ValueError(f'{name} 启动退出；请检查版本和 {HOST}:{port} 是否已被占用')
            listing = subprocess.run(['lsof', '-nP', '-a', '-p', str(proc.pid),
                                      f'-iTCP:{port}', '-sTCP:LISTEN', '-Fn'],
                                     capture_output=True, text=True, timeout=5)
            if f'n{HOST}:{port}' in listing.stdout.splitlines():
                break
            time.sleep(0.15)
        else:
            raise ValueError(f'未确认 {name} 占有 {HOST}:{port}；不连接')
        yield proc
        if proc.poll() is not None:
            raise ValueError(f'{name} 在读数期间退出；丢弃本次结果')
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def evm_read(method, request_id):
    body = json.dumps({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': []})
    conn = http.client.HTTPConnection(HOST, EVM_PORT, timeout=5)  # 直连，不读取代理配置。
    try:
        conn.request('POST', '/', body, {'Content-Type': 'application/json'})
        resp = conn.getresponse()
        if resp.status != 200:
            raise ValueError(f'{method}: HTTP {resp.status}')
        data = json.load(resp)
        if (data.get('jsonrpc') != '2.0' or data.get('id') != request_id
                or 'error' in data or 'result' not in data):
            raise ValueError(f'{method}: 无有效 JSON-RPC 结果')
        return data['result']
    finally:
        conn.close()


def inspect(directory, launch_id):
    core_dir = directory / 'core'
    common = ['-regtest', f'-datadir={core_dir}', f'-rpcport={BTC_PORT}']
    core_args = [*common, f'-rpcbind={HOST}', f'-rpcallowip={HOST}', '-disablewallet',
                 '-networkactive=0', '-listen=0', '-dnsseed=0', '-fixedseeds=0', '-listenonion=0']
    anvil_args = ['--host', HOST, '--port', str(EVM_PORT), '--chain-id', str(launch_id),
                  '--accounts', '0', '--hardfork', 'cancun', '--no-mining', '--no-cors', '--quiet']
    cli = [str(Path(shutil.which('bitcoin-cli')).resolve()), *common, f'-rpcconnect={HOST}',
           '-rpcwait', '-rpcwaittimeout=15', '-rpcclienttimeout=3']

    def btc_read(method):
        reply = subprocess.run([*cli, method], env={'HOME': str(core_dir), 'LC_ALL': 'C'},
                               capture_output=True, text=True, timeout=20)
        if reply.returncode:
            raise ValueError(f'{method}: 临时目录的 RPC 未就绪或认证失败')
        return json.loads(reply.stdout)

    with owned_node('bitcoind', core_dir, BTC_PORT, core_args) as btc:
        chain = btc_read('getblockchaininfo')
        net = btc_read('getnetworkinfo')
        print(f"BTC endpoint={HOST}:{BTC_PORT} pid={btc.pid} version={net['version']} "
              f"chain={chain['chain']} height={chain['blocks']} peers={net['connections']}")
        if (net['version'] != 300500 or chain['chain'] != EXPECTED_BTC or chain['blocks'] != 0
                or net['networkactive'] is not False or net['connections'] != 0):
            raise ValueError('不是指定版本的全新、断开 P2P 的 regtest')
        with owned_node('anvil', directory / 'anvil', EVM_PORT, anvil_args) as evm:
            version = evm_read('web3_clientVersion', 1)
            chain_id = evm_read('eth_chainId', 2)
            print(f'EVM endpoint={HOST}:{EVM_PORT} pid={evm.pid} client={version} eth_chainId={chain_id}')
            if version != 'anvil/v1.7.1':
                raise ValueError('不是指定版本的 Anvil')
            return chain_id


if len(sys.argv) > 2 or (len(sys.argv) == 2 and not re.fullmatch(r'[0-9]{5}', sys.argv[1])):
    sys.exit('用法：bash networks.sh [本地 Anvil 链号 31337–31399]')
launch_id = int(sys.argv[1]) if len(sys.argv) == 2 else 31337
if not 31337 <= launch_id <= 31399:
    sys.exit('仅允许本课本地实验链号 31337–31399')
for sig in (signal.SIGHUP, signal.SIGTERM):
    signal.signal(sig, signal.default_int_handler)
try:
    with tempfile.TemporaryDirectory(prefix='network-lab-') as directory:
        actual = inspect(Path(directory), launch_id)
except KeyboardInterrupt:
    sys.exit('已中断实验。')
except (OSError, ValueError, KeyError, http.client.HTTPException, subprocess.SubprocessError) as err:
    sys.exit(f'ERROR {err}')

if actual != EXPECTED_EVM:
    print(f'STOP expected={EXPECTED_EVM} actual={actual} before_sign=true before_send=true')
    sys.exit(3)
print(f'PASS chain={EXPECTED_BTC} eth_chainId={actual} read_only=true')
PY
