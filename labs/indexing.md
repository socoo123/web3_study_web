# 第 18 课 · 从日志建索引：没人在线的三块，怎样补进账页？

交班时，数据库只记到**块 1**。索引器停着，付款方 A 向托管锁了 **125 wei**，随后同意结算；同事还挖了一个空块。现在节点报**块 4**，客服却没收到一条通知。要补的是 **3 个块、2 条业务日志**，不是三笔收款。即使补扫后再把同一页喂一次，B 也只应领 125 wei，实际提现仍是 0。我们用 PostgreSQL 区分三个数字：扫过几块、匹配几条、首次插入几条。

先修：[14 · 托管状态机](escrow.html)、[16 · 部署清单](deployment.html)、[17 · RPC 读端](rpc.html)。动手用[托管源码](m04/src/MilestoneEscrow.sol)、[Scan.java](m05/src/main/java/course/m05/Scan.java) 和[建表 SQL](m05/schema.sql)。本课索引是可重建的**观察记录**，不是订单入账，更不是付款指令。

## 一行索引取自哪里？

Java 应用日志里的 `INFO payment successful` 是程序写的文字；以太坊的日志属于交易执行回执，编码成「**发出日志的合约地址**、若干个 32 字节主题 `topics`、一段 `data`」。先核对部署，再用它的 ABI 分栏解码。搜到名字相同的事件，并不能证明是我方托管；`log.address` 不是付款人、也不保证等于外层交易的 `to`。

| 这个实例的事件 | `topics[1]` 是谁 | `data` 的一个 `uint256` 表示什么 |
| --- | --- | --- |
| `Locked` | 付款方 A | 本次入托管的原生 wei |
| `Settled` | 收款方 B | 从托管记为 B 应领的 wei，不是已转给 B |
| `Refunded` | 付款方 A | 到期后记为 A 应领的 wei，尚须领取 |
| `Withdrawn` | 实际领取人 | 从托管成功提取的 wei |

以 `event Locked(address indexed payer, uint256 amount)` 为例。非匿名事件的 `topics[0]` 是 **完整 32 字节** `Keccak-256("Locked(address,uint256)")`；不写参数名、`indexed` 或空格，也不截成函数 selector 的 4 字节。`indexed` 使 `payer` 单独占 `topics[1]`：12 字节零加 20 字节地址。`amount` 未标 indexed，在 `data` 中按 32 字节无符号大端数读取。125 的最后一字节为 `7d`，前 31 字节为零。代码先查字长和高位补零，再去掉十六进制前缀，以 `BigInteger` 解出非负整数，交给 `new BigDecimal(amount)` 和数据库 `numeric(78,0)`；没有 `double`，也不把 `uint256` 缩成 `long`。这是四个**静态**事件的解码器，不能用「取低 20 字节」反解 indexed 的字符串或数组。

一个过滤器只跟本轮 `contractAddress`。`new EthFilter(at(from), at(to), release.address)` 选闭区间；`addOptionalTopics(TOPICS)` 把四个签名放进**同一个** topic 位置，即 `topics=[[Locked签名,Settled签名,Refunded签名,Withdrawn签名]]`。在这个位置是「或」；把四个签名平铺到四个位置则要求同时满足四个不同栏位，意义全变。节点返回后再核地址、块号、块哈希、`removed=false`、主题个数与数据形状，不处理 Forge 测试夹具的断言事件。

## 为什么记「块 4 的哈希」，而不是「最后一条消息在块 3」？

<figure class="lesson-figure"><a href="../assets/figures/m05/indexing.svg"><img src="../assets/figures/m05/indexing.svg" alt="从部署块 1 的哈希开始，块 2 锁款 125 wei、块 3 给 B 记应领 125 wei、块 4 为空。第一次补扫描过三块并插入两行，第二次重读新增零行。"></a><figcaption>游标是「已完整读过的最后一个块」，用高度和整串哈希共同定位。它可以落在没有日志的第 4 块。</figcaption></figure>

**定起点。** 一库只跟一条链上的一份部署。`verifyRelease` 要求清单与节点的 chain ID 都是 31337、按高度取回的部署块哈希一致。块内必须只有清单那笔创建交易；它的成功回执须给出同一交易、块位置和合约地址，且没有日志。这个限制很重要：只知道「构造函数没发事件」不足以跳过一个还有其他交易的部署块。这里才可以把部署块作为空库首锚。清单须来自第 16 课已核对的发布方；索引器不替你鉴定来历不明的合约。

**定一页。** 启动时读一次数值链头 `head`，当前运行不追一边增长一边移动的 `latest`。从游标的下一高度开始，本实验每页至多 **3 块**，便于看见提交边界。读每个块的哈希和 `parentHash`；第一个父哈希须接上库中前一块，其余逐对相接。若从历史高度重放，还要逐高度与库中规范块比较。真实业务会按节点允许的范围和日志量调页长；超时、限额或无权限都不能解释成成功的 `[]`。

**防止把两条分支拼在一页。** 高度不是版本号。假设按高度取得块 3 的哈希 H，查范围日志时块 3 已被 H′ 取代。若返回一条 H′ 的日志，与保存的 H 比较即可拒绝；但 `[]` 不带块哈希。代码保留本页每个块的身份：对**有交易却没匹配到日志**的块，用同地址和主题改做一次 `blockHash=H` 的查询，不能同时带 `fromBlock/toBlock`。只有该原块也为空才接受；本轮没有交易的块本来就不可能发出这份托管的日志。提交前按高度再核对本页首尾哈希；哈希或父子关系不符即 `STOP branch mismatch`，本页回滚，转[第 19 课](reorg.html)。这依赖受信的本地节点按过滤器完整响应；最后一次 RPC 和数据库提交不是跨系统的原子操作，之后仍可能重组，下一次启动必须再验游标。

**把证据和书签一起提交。** `SELECT ... FOR UPDATE` 锁住已有游标行；同一个 JDBC 事务中先保存块，再插日志，再推进游标，最后 `commit()`。只保存日志而提前提交书签，宕机后会跳过缺行；先写业务增量再另存书签，重跑则可能重复加钱。这里不给余额做 `+=`，而是保存每个事实：主键为 `(chain_id, block_hash, tx_hash, log_index)`。一笔交易可以发多条日志，重新入块的同一笔交易也可以得到不同的块位置。重复插入同一把键时 `ON CONFLICT ... DO NOTHING`；要读当前规范链，查 `canonical_log`，而不是把所有分支的 `escrow_log` 相加。`if (to > cursor.height)` 才更新书签：重读旧页不能把书签倒拨。

## 终端 A：交一份尚未锁款的部署

从**仓库根目录**开两个终端。需要 JDK 21、Maven 3.9.x、Python 3.11、Docker（PostgreSQL 17.5 镜像）以及[第 13 课的工具](abi.html#m04-tools)：Foundry 1.7.1、solc 0.8.28、`lsof`。Maven 工程锁定 web3j 4.12.3，pgjdbc 依赖版本由 Spring Boot 3.5.8 管理。首次准备构件、镜像可能需联网；缓存齐后构建可加 `-o`。以下只用本机 18556 的 Anvil 和 18557 的教学库，不用真实钱包。

```bash
export PATH="${XDG_CACHE_HOME:-$HOME/.cache}/chain-course/m04/bin:$PATH"
export FOUNDRY_SOLC="${XDG_CACHE_HOME:-$HOME/.cache}/chain-course/m04/bin/solc"
unset ANVIL
WORK=$(mktemp -d)
python3 labs/m04/deployment.py --out "$WORK/release" --hold
```

等到 `HANDOFF ... deployBlock=1 readBlock=1 state=0`，记录 `ARCHIVE` 后面的绝对路径，不按回车。此处**不传 `--settle-wei`**：我们要先立游标，再让两笔交易在索引器不在线时发生。

## 终端 B：先立书签，再离线三块

若本课程的 Docker 集群尚未启动，先运行 `bash labs/m05/db.sh start`；已经在运行就复用集群，**为本轮新建空库**，不要覆盖其他课的库。建库名由下方固定格式和时间戳生成。如建库失败，不要继续。

```bash
export PATH="${XDG_CACHE_HOME:-$HOME/.cache}/chain-course/m04/bin:$PATH"
printf '粘贴终端 A 的 ARCHIVE 绝对路径：'; IFS= read -r R
export M05_MANIFEST="$R/manifest.json"
export M05_DB="m05_scan$(date +%s)"
printf 'CREATE DATABASE %s;\n' "$M05_DB" | M05_DB=m05 bash labs/m05/db.sh sql &&
bash labs/m05/db.sh sql < labs/m05/schema.sql &&
bash labs/m05/build.sh &&
bash labs/m05/run.sh Scan
```

无业务块可扫，预期 `CAUGHT_UP head=1 cursor=1`；进程随即退出，不存在常驻消费者。取公开的合约和付款方地址，随后只让本机节点使用它自己临时解锁的测试账户：

```bash
RPC=http://127.0.0.1:18556
field() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$M05_MANIFEST" "$1"; }
C=$(field contractAddress); A=$(field deployer)
```

整个演练可以**从不打开 WebSocket**。如果要演示「停止提示」，此刻可在终端 B 执行 `cast logs --rpc-url ws://127.0.0.1:18556 --address "$C" --subscribe`，随即按 **Ctrl-C**，在下面三块生成前确保已回到 shell。不停止终端 A 的节点。订阅只适合催促扫描器早点醒来：断开期间不会替你存历史，重连拿到的新 subscription ID 也不是数据库游标。

```bash
cast send --rpc-url "$RPC" --from "$A" --unlocked --json --value 125 "$C" 'lock()' > "$R/lock-18.json" &&
cast send --rpc-url "$RPC" --from "$A" --unlocked --json "$C" 'settle()' > "$R/settle-18.json" &&
cast rpc --rpc-url "$RPC" evm_mine &&
cast block-number --rpc-url "$RPC"
printf 'SELECT height AS before_scan FROM scan_cursor;\n' | bash labs/m05/db.sh sql
bash labs/m05/run.sh Scan
```

预期两个成功回执分别在 2、3；`evm_mine` 后链头为 4，SQL 中 `before_scan=1`。此时才重新启动 Java，预期 `PAGE 2..4 matched=2 inserted=2 cursor=4`。这是三块真的没有交给上一次进程，而不是故意丢掉一条已写入数据库的消息。若锁款/结算失败、回执状态不是成功或头高不是 4，先核对该轮清单与期限；别用新交易冒充补扫。

下面的快照函数按确定顺序打印完整事实键、角色、金额、块和游标。留一份首扫结果后**强制**再读 `[2,4]`，不能以「无参启动发现已经追平」偷换幂等测试。

```bash
snapshot() {
  bash labs/m05/db.sh sql <<'SQL'
SELECT height,hash,parent_hash,canonical FROM chain_block ORDER BY height,hash;
SELECT chain_id,block_hash,tx_hash,log_index,kind,address,actor,amount_wei
  FROM escrow_log ORDER BY block_hash,tx_hash,log_index;
SELECT id,chain_id,contract_address,deploy_height,deploy_hash,height,block_hash FROM scan_cursor;
SQL
}
snapshot > "$R/first-18.txt"
bash labs/m05/run.sh Scan 2 && snapshot > "$R/replay-18.txt" &&
cmp "$R/first-18.txt" "$R/replay-18.txt" && echo 'same rows, same cursor'
bash labs/m05/db.sh sql <<'SQL'
SELECT height,kind,log_index,amount_wei FROM canonical_log ORDER BY height,log_index;
SELECT c.height,c.block_hash=b.hash AS anchored FROM scan_cursor c
  JOIN chain_block b ON b.chain_id=c.chain_id AND b.height=c.height AND b.canonical;
SQL
```

预期重放行是 `PAGE 2..4 matched=2 inserted=0 cursor=4`，`cmp` 相等。明细依次为 `2 | Locked | 0 | 125` 和 `3 | Settled | 0 | 125`；两次 `log_index=0` 因为各自在**不同块**中是第一条日志。游标为 `4 | t`。快照里的 `address` 都是 C，两个 `actor` 则分别是 A 和 B。对照本轮两份 JSON 回执里的 `blockHash`、`transactionHash` 与 `logs[0].logIndex`，不要比屏幕上截短的哈希。**不能**把两条 `125` 求和说成收到了 250 wei，也不能把 `Settled` 当作一次提现。

## 只改变块内容：空结果也要交账

接着在同一节点单独出两个空块；还没有再次调用合约。先正常补至 6，再从 2 开始重读两页，最后试图从未来高度跳扫。

```bash
cast rpc --rpc-url "$RPC" evm_mine && cast rpc --rpc-url "$RPC" evm_mine &&
bash labs/m05/run.sh Scan && bash labs/m05/run.sh Scan 2
if bash labs/m05/run.sh Scan 9 > "$R/gap-18.txt" 2>&1; then
  echo '异常：竟然允许跳过块 7、8'
else
  grep 'STOP fromHeight would skip history' "$R/gap-18.txt"
fi
bash labs/m05/db.sh sql <<'SQL'
SELECT (SELECT count(*) FROM chain_block WHERE canonical) AS blocks,
       (SELECT count(*) FROM canonical_log) AS logs, height AS cursor FROM scan_cursor;
SQL
```

预期新增区间打印 `PAGE 5..6 matched=0 inserted=0 cursor=6`；重放 `[2,4]` 时是 `matched=2 inserted=0 cursor=6`，再重放 `[5,6]` 时游标仍为 6。最后一步应**因跳过历史**拒绝并非零退出，SQL 为 `6 | 2 | 6`。无结果有两种：`PAGE ... matched=0` 表示在真实块上完成了一次带过滤器的查询；`CAUGHT_UP` 表示没有新区间，不能据此声称查询过不存在的第 7 块。

## 独立作业：能找回第三张单据，又不多记一次吗？

交换操作员。仍在上述第 6 块、B 尚未提取的实例上，让 B 调一次 `withdraw()`，再挖一个空块。可用 `B=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["constructor"]["payee"])' "$M05_MANIFEST")` 从原件取公开地址；套用前面的 `cast send --unlocked` 形状，换发送者和调用签名，**不加 `--value`**。保留成功回执。不要启动订阅，自己选择正确的正常起点和重放起点，提交两次 `PAGE`、两份快照和一条查当前规范块数据的 SQL。

**判据：**第一遍只新增一条 `Withdrawn`，其高度 7、`actor=B`、`amount_wei=125`、`address=C` 四项齐全，游标落在没有交易的块 8；第二遍仍命中该条而新增为 0，快照不变。整份索引有 **8 个规范块、3 条业务日志**。三次事件不是三次进账：最初锁 125、结算时 B 应领 125、领取后 B 应领 0，托管向 B 实付 125（不等于扣除 B 自付 gas 后的钱包净差）。换一位同事只凭你提交的哈希和索引位置就能找回同一份回执才算通过。

结束后回终端 A 按回车关闭本轮 Anvil；`$R` 中的归档不等于在线节点。数据库是临时集群，需保留则先 `bash labs/m05/db.sh dump > "$R/scan-18.dump"`；`bash labs/m05/db.sh stop` 会清掉**整个教学集群**，仅在其他课也已留档并用完后执行。本课未模拟公网服务的日志截断、历史裁剪或最终性；遇到父哈希错误时不要手改游标，保留旧证据交给下一课。

## 查证原文

- [Solidity 0.8.28 ABI · Events](https://docs.soliditylang.org/en/v0.8.28/abi-spec.html#events)：非匿名事件的主题、indexed 参数与数据区。
- [Ethereum Execution APIs · filter](https://github.com/ethereum/execution-apis/blob/main/src/eth/filter.yaml)；[EIP-234](https://eips.ethereum.org/EIPS/eip-234)：按块哈希过滤，以及高度范围返回空集时缺少什么证据。
- [Geth · Real-time Events](https://geth.ethereum.org/docs/interacting-with-geth/rpc/pubsub)：订阅绑定连接，不补发历史，重组时还能重复提示。
- [PostgreSQL 17 · Transactions](https://www.postgresql.org/docs/17/tutorial-transactions.html)：一组操作何时全部可见，何时全部撤回。
