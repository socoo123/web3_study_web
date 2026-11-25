"""Build a source-only, reproducible tar from reviewed paths, not a Git revision."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import argparse
import tarfile

ROOT = Path(__file__).resolve().parents[3]
FILES = {
    'labs/anvil_lab.py', 'labs/operations.md', 'assets/figures/m10/operations.svg',
    'labs/scope.md', 'assets/figures/m10/scope.svg',
    *(f'labs/m10/scope/{p}' for p in ('read-only.txt', 'user-confirmed.txt', 'change-order.txt')),
    'labs/payment-desk.md', 'assets/figures/m10/payment-desk.svg',
    'labs/hackathon.md', 'assets/figures/m10/hackathon.svg',
    'labs/m10/demo/witness.py', 'labs/m10/demo/jury-sheet.tsv',
    *(f'labs/m04/{p}' for p in ('setup.sh', 'deployment.py', 'handoff.py', 'foundry.toml', 'src/MilestoneEscrow.sol')),
    *(f'labs/m05/{p}' for p in ('pom.xml', 'schema.sql', 'orders.sql', 'db.sh', 'build.sh', 'run.sh')),
    *(f'labs/m05/src/main/java/course/m05/{p}.java' for p in ('Lab', 'ReceiptApi', 'Scan', 'Recover', 'OrderIntent', 'OrderApp')),
    *(f'labs/m10/desk/{p}' for p in ('run.sh', 'common.py', 'desk.py', 'payer.py', 'desk.css')),
    *(f'labs/m10/ops/{p}' for p in ('bundle.py', 'incident.py', 'outage.py', 'DEPENDENCIES.md')),
}


def put(archive, name, content):
    info = tarfile.TarInfo(name)  # Fixed mtime, uid/gid and mode, no local ownership metadata.
    info.size = len(content)
    archive.addfile(info, BytesIO(content))


def pack(output):
    sums = []
    # Fail before opening the destination if the declared inputs are missing or are symlinks.
    for name in FILES:
        path = ROOT / name
        if path.resolve(strict=True) != path or not path.is_file():
            raise ValueError(f'not a regular release source: {name}')
    with output.open('xb') as raw, tarfile.open(fileobj=raw, mode='w') as archive:
        intro = ('从本目录操作。先读 labs/m10/ops/DEPENDENCIES.md 安装或预热本机工具。\n'
                 '37：labs/scope.md 与 labs/m10/scope/ 两份范围报价和变更单供参考，样单不等于签署。\n'
                 '38：labs/payment-desk.md — 开对账台。39：labs/operations.md — 接手、断连、恢复。\n'
                 '40：labs/hackathon.md — 独立工单和评委核验。文中旧课 .html 是完整课程站导航。\n'
                 '不需要旧仓库、旧 target 或任何钱包。SHA256SUMS 校验内容，不证明授权或签发人。\n').encode()
        put(archive, 'START-HERE.txt', intro)
        sums.append(f'{sha256(intro).hexdigest()}  START-HERE.txt\n')
        for name in sorted(FILES):
            data = (ROOT / name).read_bytes()
            put(archive, name, data)
            sums.append(f'{sha256(data).hexdigest()}  {name}\n')
        put(archive, 'SHA256SUMS', ''.join(sums).encode('utf-8'))
    print(f'{sha256(output.read_bytes()).hexdigest()}  {output.name}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('new_tar', type=Path)
    pack(parser.parse_args().new_tar)
