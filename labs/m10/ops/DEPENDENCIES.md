# 接包清单：需要安装什么，允许交出什么

这是源码包，不含编译器、JAR、容器层、用户目录、部署快照或凭据。`SHA256SUMS` 钉住本次实际交出的源字节（包括尚未提交的改动），不是声称它们都来自某个 Git 提交。不要用旧 `target/classpath.txt`：其中是发送方的**绝对路径**。先在接手人的空目录构建；用新部署生成自己的地址和回执。

## 运行基线

在 POSIX 的 macOS 或 Linux x86_64 上准备 Bash、`curl`、`tar`、`openssl`、`awk`、`ps`、`lsof`、`shasum`、Docker CLI 与可运行的本机引擎，使用可读取自己进程并发送 STOP/CONT 的普通账号。不要用 `sudo` 解决归属不符。Docker 访问本身是高权限，只给独占实验机管理员。Apple Silicon 的 M04 安装器取官方 macOS x86_64 solc，若系统无法执行该构件，须先配置受支持的转译环境。Windows 原生、远程 Docker 与受限容器不在本演练基线内。

| 组件 | 固定版本或基线 | 如何取得、留证 |
| --- | --- | --- |
| Python 标准库、Java、Maven | CPython 3.11.8、JDK 21.0.2、Maven 3.9.11 为复现基线 | 由接收方安装同版本与对应架构；记录 `python3 --version; java -version; mvn -version`，确保 Maven 也使用 JDK 21。Python 无 pip 依赖。 |
| Solidity 与开发链 | Forge/Cast/Anvil 1.7.1；solc 0.8.28+commit.7893614a；Cancun，优化 200 次 | 源码包内 `bash labs/m04/setup.sh` 按平台校验下载摘要；已有相同缓存可直接导出下方环境。编译不接受另一个 solc 猜测等价。 |
| Java 程序 | `labs/m05/pom.xml` 钉 Spring Boot parent 3.5.8、web3j core 4.12.3；pgjdbc 42.7.8 由该 BOM 管理 | `bash labs/m05/build.sh` 在接收方目录解析依赖、编译六份 Java 源码并写入**当地** classpath；预热相同 Maven 本地仓库后可 `bash labs/m05/build.sh -o`。保留实际解析树，不能只数直接依赖。 |
| PostgreSQL | Docker Official Image `postgres:17.5-bookworm`；`db.sh` 固定端口和标签 | 首次要能拉镜像。登记目标平台和镜像摘要；tag 不是不可变的内容签名。使用接手方审核的同平台摘要预热镜像；若检查到不同摘要，先处理版本差异。 |

从包根目录执行（联网仅用于取工具/构件；未准备的空缓存不能离线编译）：

```bash
bash labs/m04/setup.sh           # 已有核过的同版工具时跳过此下载
export PATH="${XDG_CACHE_HOME:-$HOME/.cache}/chain-course/m04/bin:$PATH"
export FOUNDRY_SOLC="${XDG_CACHE_HOME:-$HOME/.cache}/chain-course/m04/bin/solc"
unset ANVIL
forge --version; cast --version; anvil --version; "$FOUNDRY_SOLC" --version
python3 --version; java -version; mvn -version; docker version
bash labs/m05/build.sh
docker pull postgres:17.5-bookworm                  # 已预热同一镜像时跳过
docker image inspect postgres:17.5-bookworm --format '{{.Os}}/{{.Architecture}} {{.Id}} {{json .RepoDigests}}'
```

已建立本轮绝对路径 `WORK` 后，可在包根目录生成审查材料。不要把 Maven settings、环境变量转储或 Docker 配置导入包。

```bash
mvn -B -f labs/m05/pom.xml dependency:tree -Dscope=runtime -DoutputFile="$WORK/runtime-tree.txt"
python3 - "$WORK/jar-sha256.txt" <<'PY'
from hashlib import sha256
import os, pathlib, sys
from zipfile import ZipFile
jars = pathlib.Path('labs/m05/target/classpath.txt').read_text().strip().split(os.pathsep)
with open(sys.argv[1], 'x') as out:
    for item in jars:
        p = pathlib.Path(item)
        with ZipFile(p) as z:
            notices = [n for n in z.namelist() if n.upper().startswith(('META-INF/LICENSE','META-INF/NOTICE','LICENSE','NOTICE'))]
        print(sha256(p.read_bytes()).hexdigest(), p.name, ','.join(notices) or '查该版本 POM 与上游授权', file=out)
PY
```

## 授权边界（不等于对整包授予开源许可）

- `MilestoneEscrow.sol` 有 `SPDX-License-Identifier: MIT`。**仓库没有覆盖所有课文、图、Java、Python 或交付件的总 LICENSE**；组件的许可不能替这些材料授权。交给获准接收的人前，另按权利人书面授权核对使用范围。没有授权就不公开下载、不提交到公开比赛、不作可转授商品。包不附加自造的整体许可。
- [web3j 4.12.3](https://github.com/LFDT-web3j/web3j/blob/v4.12.3/LICENSE) 与 [Spring Boot 3.5.8](https://github.com/spring-projects/spring-boot/blob/v3.5.8/LICENSE.txt) 的主项目为 Apache-2.0；[pgjdbc 42.7.8](https://github.com/pgjdbc/pgjdbc/blob/REL42.7.8/LICENSE) 是 BSD 两条款；[PostgreSQL](https://www.postgresql.org/about/licence/) 使用 PostgreSQL License。数据库镜像还含 Debian 等组件，不能把数据库许可贴给所有层。
- Foundry 提供 [MIT](https://github.com/foundry-rs/foundry/blob/v1.7.1/LICENSE-MIT) 和 [Apache-2.0](https://github.com/foundry-rs/foundry/blob/v1.7.1/LICENSE-APACHE) 许可；Solidity 编译器的[许可文本](https://github.com/ethereum/solidity/blob/v0.8.28/LICENSE.txt)是 GPLv3。本包发安装脚本与配置，不发这些工具的二进制。JDK 许可须以实际发行版为准；Maven、Python、Docker/Desktop 也由接收方按其版本与使用条件安装。
- 若改成分发 fat JAR、镜像或装好工具的压缩包，这是**新的分发范围**。逐个审 `runtime-tree.txt`、插件/构建工具、镜像层、各构件中的 LICENSE/NOTICE 与源码提供义务；登记许可证原文位置、保留声明、授权人和审查日期，有未决项就暂不外发。摘要或 Maven 的一个 `<license>` 字段均不替代审查。
