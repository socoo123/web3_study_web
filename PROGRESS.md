# 链上课程 · 批次交接

**下一关键词：`链上续写 M10`**

主线 M01–M06 及本次指定的选修 M07 已完成。可从[第 25 课的 Rollup 回执](labs/rollup.html)开始，或直接接手[卷末工单 X-728](labs/withdrawal.html#m07-checkout)。当前无进行中批次；下一批回到主线 M10（37–40 课），不以 M08、M09 为先修。

## 零基础入口返修（已完成）

[首页](index.html)和[入门四课目录](plan.html#m01)从同一张「应收 2 张券、凭条只有 1 张」的订单起步。四位作者分别修订 `labs/ledger.md`、`labs/crypto.md`、`labs/wallet.md`、`labs/networks.md`。每课在第一个代码块前给出可以独立判断的例子、改变条件后的答案和下一课入口；原理、实验与卷末工单保留。只调整入门卷，不增课。

- **阅读路径。** `python3 tools/build.py` 构建静态页。离线 Chrome 在 1280 和 375 px 从首页进入计划的 M01 目录，也从首页顺读 01→04，再从纸上例子的末尾进入 05，不必穿过代码块。首页、计划、前四课没有页面横向溢出；四课共八幅图均能离线放大、收起并返回原图链接焦点。第 06 课的比特币凭证仍在首页实验区，可展开切换单位。
- **核对例子。** `cd labs` 后执行 `java MerkleLab.java` 得 `matches.trusted=true`；`java IntentLab.java` 验得原件 `true`、改金额 `false`。用 `embit==0.8.0` 运行 `python wallet.py second` 与 `wrong-branch`，第二单完整地址匹配，找零地址不匹配。回到根目录，`bash labs/networks.sh` 读到 31337 并放行；加参数 `31338` 则在签名前停止、退出 3。未使用真实钱包或资金。

## 批次表

默认先完成主线（M01–M06、M10），再进入选修（M07–M09）；课号始终与 `PLAN.md` 一致。用户可调整选修顺序。

| 关键词 | 课号 | 本批交付 | 状态 |
| --- | --- | --- | --- |
| `链上续写 M01` | 01–04 | 账本证明、哈希/签名/加密、钱包派生与恢复、本地节点网络核验 | 已完成（图文版） |
| `链上续写 M02` | 05–08 | 比特币确认、UTXO 对账、花费条件、PSBT 签名前核对 | 已完成（四课、七图、regtest 实验与卷末工单） |
| `链上续写 M03` | 09–12 | EVM 账户、交易序号、Gas 验算、回执与最终性 | 已完成（四课、四图、本地实验与卷末工单） |
| `链上续写 M04` | 13–16 | Solidity、托管状态机、Foundry 测试、部署清单 | 已完成（四课、四图、离线测试与部署交接工单） |
| `链上续写 M05` | 17–20 | Java RPC、日志索引、重组恢复、订单对账 | 已完成（四课、四图、本地服务与备份恢复工单） |
| `链上续写 M06` | 21–24 | 钱包登录、资产授权、AMM、价格与借贷 | 已完成（四课、四图、本地签名与链上实验、四联工单） |
| `链上续写 M10` | 37–40 | 接单范围、收款对账台、移交演练、黑客松 | 待开始 |
| `链上续写 M07` | 25–28 | L2、费用、智能账户、跨层状态 | 已完成（四课、四图、测试网历史归档、本地代付实验与卷末工单） |
| `链上续写 M08` | 29–32 | Rust、Solana 账户、Anchor、SPL Token | 待开始 |
| `链上续写 M09` | 33–36 | Lightning、专用索引、零知识应用、Move | 待开始 |

## M07 分工

25 `labs/rollup.md` 与 `labs/m07/rollup/`：由执行回执追到安全头与最终头；26 `labs/l2-fees.md` 与 `labs/m07/fees/`：分网部署清单、执行费和数据费；27 `labs/userop.md` 与 `labs/m07/userop/`：受控操作、外层交易与代付预算；28 `labs/withdrawal.md` 与 `labs/m07/withdrawal/`：用既有公共测试网证据跟踪官方桥消息，并交付独立卷末工单。四位作者各负责一课与 `assets/figures/m07/` 下同名配图；主 agent 负责课序、首屏、建站及实验验收。先修为 M03、M04、M06；本批不提前编写 M10。

## M07 验收记录

从仓库根目录运行，CPython 3.11.8、Forge/Cast/Anvil 1.7.1、solc 0.8.28。公共测试网记录按观察时间与块哈希解释；本地写操作各用新建的回环链，不复用钱包或交易哈希。

- **25 · 有执行、有发布，尚未最终化。** `python3 labs/m07/rollup/replay.py`：OP Sepolia 自转交易位于 L2 块 **51,764,054**，沿 44 条父哈希连到当时的 `safe` 头；`finalized` 头仅到 **51,763,623**。批次 3,631,439 指向 Sepolia 块 **12,187,164** 内的 blob 交易，不是 L2 合约给出的 L1 origin 块 **12,187,150**。与批次索引的 L2 范围、L1 交易哈希及 blob 引用对读相符。分别加 `--omit publication`、`--omit parent`、`--omit finalized` 均退出 3，未晋升为已最终化。没有自行下载 blob、验证 KZG 或运行派生节点。
- **26 · 预算不是实付，缺字段也不是零。** `python3 labs/m07/fees/fee_book.py local --out <新目录>`：M04 托管合约在 31337 的创建输入、运行时代码均核对相符；本轮实际 **451,424 gas × 2 gwei/gas = 902,848,000,000,000 wei**，等于付款人余额差。`history` 单独复算 Base Sepolia 块 22,000,000 的历史交易，执行 **116,808,693,467 wei** 加数据费 **6,327,662,798 wei** 得 **123,136,356,265 wei**；该块早于 Isthmus。去掉归档中的 `l1Fee`，总额不可报；本地启动时错用 `--expect base-sepolia`，则在发送前停止。两者都退出 3。历史交易不是本课程合约的公网部署。
- **27 · 同一个成功状态，可能是两种业务结果。** `bash labs/m07/userop/prepare.sh` 核验官方 0.7.0 包；`python3 labs/m07/userop/run.py` 的操作 `0xe40366814052d7683a4a8218f925ee23931084b7af1be2cc7be2511301ea7aba` 经入口日志定位到交易 `0x7e51fccbe1dd680f86b1dac65f49a0a72816d6a4137340b4651ff57cdd435630`。27 号已登记，代付存款从 800,000,000,000,000 降至 495,018,000,000,000 wei。换 `--mode held`，外层仍成功，操作失败、登记值为 0，实扣 **270,744,000,000,000 wei**。改 `--budget-wei 799999999999999` 是 `AA31`，改 `--ticket 28` 是 `AA33/OutsideVoucher`；两轮都退出 3，操作事件 0 条，未提交操作的外层交易。
- **28 · 能领取不等于已到账。** `python3 labs/m07/withdrawal/track.py --view <视图>` 对同一笔 0.3 测试 ETH 的提款重放：`source-only` 只报处理中；`proof` 找到证明但尚未成熟；`ready` 在 L1 块 **11,353,458** 核对未暂停、未领取且模拟成功；`full` 在下一块用提款哈希、消息哈希连起 Portal、Messenger 和标准桥的付款事件，才报 `COMPLETED`。`without-payment` 保留前两层成功与正的余额差，仍因缺桥付款证据而报 `PROCESSING`。
- **卷末 X-728 · 独立签两联。** `track.py --case B --view <视图>`：另一笔 **0.2 测试 ETH** 提款在 Sepolia 块 11,334,819 可领取，11,334,820 才有三联付款证据；遮去桥事件结果退回处理中。B 的源链回执另读到执行费 151,165,782,000 wei、数据费 19,211,488,249 wei。S 从账面余额扣掉另一张工单的预留，`run.py --budget-wei 799999999999963`，可用额比预付门槛少 **37 wei**，返回 `AA31`、退出 3，无外层操作交易。两张单不能共用一个成功标记。
- **公开原件复核。** 分别向 OP Sepolia、Sepolia 的 RPC 只读查 A 的发起与领取交易，两笔的状态、块高、块哈希和各自的 5 条原始日志都与归档一致。目标地址在领取块末的净增额为 598,830,284,543,880,678 wei，不是这一单桥付款的 0.3 测试 ETH。
- **取证工具与边界。** 第 25 课复算了 KZG 承诺的版本化哈希；篡改一条父链接但不改高度，读端报 `SAFE_PATH_GAP_OR_FORK`。`python3 labs/m07/rollup/lookup.py` 向执行 RPC 发起 15 次只读请求，重新取得两层回执和发布块的 batcher 配置。独立读取浏览器的块与批次记录相符；自动读取索引时曾遇 HTTP 403，因此在线命令把按哈希查原件与可选的 `--index` 分开。第 26 课没有在公网部署托管，第 27 课没有运行公共 bundler、Safe 或 7702；没有公网写入、真实资产或自行验证的共识证明。
- **站点。** `python3 tools/build.py` 成功。首页、计划及 24–28 课共 **318** 个本地链接、资源与片段可解析。Chrome 离线从首页／第 24 课进入 25→28 并返回 M10 计划；四课在 1280 / 375 px 下均无横向溢出，桌面凭条与导语并排，手机先看凭条。正文图宽 736 / 359 px，四图均能放大、关闭并返回原链接焦点；代码明暗对比度分别为 10.61:1、9.96:1。

## M06 分工

四位作者分课交付：21 `labs/siwe.md` 与 `labs/m06/login/`（非托管签名与 Java 会话）；22 `labs/allowance.md`、`labs/m06/allowance.py` 与 `LabToken.sol`（两种精度的资产与限额）；23 `labs/swap.md`、`labs/m06/swap.py` 与 `CoursePool.sol`（复用 22 的代币，对比报价、成交与拒绝）；24 `labs/health.md`、`labs/m06/health.py` 与 `RiskView.sol`（价格时效、健康度与独立卷末工单）。Solidity 源码归 `labs/m06/src/`，配图归 `assets/figures/m06/`。主 agent 接入共享 Anvil、ABI 与回执工具，维护卷目录、首屏与阅读导航，运行验证并记录边界。

## M06 验收记录

环境：JDK 21.0.2、web3j 4.12.3、CPython 3.11.8、Cast / Anvil 1.7.1、solc 0.8.28（Cancun）。命令均从仓库根目录运行；链上实验每轮使用全新回环节点，不跨轮复用地址和哈希。

- **21 · 登录不发交易。** `bash labs/m06/login/run.sh login`、`bash labs/m06/login/run.sh signer` 各启一个回环进程。干净 Chrome 从独立窗口拒签：`4001`，服务端仍 `200 ANONYMOUS`。确认同一份 SIWE 原文后 Java 验签，状态为 `AUTHENTICATED`；页面再次提交原挑战得到 `409 NO_CHALLENGE`。已登录时换账户、等待签名时换账户或切到 31338，旧身份均清除；错网禁签，重开页面不自动请求钱包。以 `SIWE_TTL_SECONDS=5` 重启登录端，过期后再确认得到 `410 EXPIRED`，未建会话。
- **22 · 授权与到账。** `python3 labs/m06/allowance.py --out <新目录> --hold`：分别授权 2.5 LAB6、2.5 LAB18 时收款余额均为 0。实际扣款分别为 **1.234567 LAB6** 和 **1.234567000000000001 LAB18**；再次请求比剩余额度多 1 个最小单位，两轮都得到 `status=0x0`，额度和双方余额未变。用 375 px Chrome 打开、关闭并重开本轮 `voucher.html`；按凭单中的 LAB6 失败交易哈希 `0x6afc1471e0884faea8d20e6f3c90702f329ef2731b62bb5cde336bd6a245bc98` 向同一活节点调用 `eth_getTransactionReceipt`，状态和块哈希与归档一致。
- **23 · 报价与成交。** `python3 labs/m06/swap.py`：在块 7 的同一储备，10、100 A18 分别报价 **19.743160、181.322178 B6**。小单要求至少 19.743161 B6，块 8 回滚，0 条日志，代币余额及额度未动，仍实付 46,405,345,602,450 wei 执行费。在该块重报价后把下限改为 19.644445 B6，块 9 实收 19.743160 B6，额度归零，两笔 `Transfer` 与池的 `Swap` 对上。此时再询 10 A18 只报 19.356609 B6，没有第二笔成交。
- **24 · 估值不是可借承诺。** `python3 labs/m06/health.py`：同一块哈希上，合约读数与 Python 整数复算一致：抵押 400 Q、负债 250 Q，清算阈值 75%，健康度 **1.2**；按 65% LTV 算出的余量只有 **10 Q**。分别追加 `--coll-age 301`、`--missing debt`，返回 `HOLD_STALE`、`HOLD_MISSING`，无估值、退出 3；`--debt-raw 0` 得到 `NO_DEBT`，健康度不适用。四轮均 `executableQuote=false`。
- **卷末 D-624 · 四联不能合成一个执行许可。** 第一联在登录台拒签、会话匿名。`allowance.py --spend6 2.499999 --spend18 2.499999999999999999`：两种资产各剩 1 个自己的最小单位，各再扣 2 都真实回滚。`swap.py --trade-in 40`：要求 76,701,158 B6 最小单位失败；下限改为 76,317,652 后实收 **76,701,157**，与两笔代币转移及 `Swap` 对平。风险联用 3.25 COL、128 Q/COL、240 NOTE，价龄 300 秒时合约与离线读端都是抵押 416 Q、负债 300 Q、健康度 **1.04**、余量 **0 Q**；301 秒时两端均拒报，**余量不可用**。四联分别归属于自己的签名会话或回环部署，不能拼成同一笔业务的收条。
- **登录交接作业。** 以 `SIWE_TTL_SECONDS=45` 启动最终验证方。A 登录后切 B，查询为匿名；B 拒绝第一次挑战，再确认第二次。两份 nonce 不同，时窗均为 45 秒。再次提交得到 409，原 B 会话仍已认证；另一份空浏览器上下文始终只读到匿名。
- **站点。** `python3 tools/build.py` 成功。首页、计划和第 20–24 课共 302 个本地链接、片段及资源引用可解析。Chrome 离线从首页进入第 21 课，也从第 20 课顺读到第 24 课再转 M10 计划。1280 / 375 px 下四课均无页面横向溢出：桌面凭条与导语并排，手机先凭条后导语；四图宽 736 / 359 px，可放大、收起并返回原图链接焦点。代码块明暗对比度分别为 10.61:1、9.96:1。
- **边界。** 签名实测使用独立回环进程中的临时 EOA，不是第三方钱包兼容性测试。链上实测仅限自建代币、单向教学池、固定仓位和本地价格源；ERC-721、ERC-1155、permit、集中流动性及真实借贷协议仅作对照。没有连接公网、兑换真实资产或发出借款，临时服务均已停止。

## M05 分工

四课分开执笔：17 `labs/rpc.md`（只读回执 API）；18 `labs/indexing.md`（按部署与日志范围补扫）；19 `labs/reorg.md`（共同祖先、事务回退与重放）；20 `labs/reconciliation.md`（Spring Boot 查款、outbox、备份恢复与卷末工单）。程序共用 `labs/m05/` Maven 工程、独立教学数据库和第 16 课部署清单；配图归 `assets/figures/m05/`。主 agent 维护工程入口、共享数据库约定及站点导航，实跑后登记证据。

## M05 验收记录

环境：macOS arm64，JDK 21.0.2、Maven 3.9.11、web3j 4.12.3、Spring Boot 3.5.8、pgjdbc 42.7.8、PostgreSQL 17.5、Python 3.11.8。按第 16 课配置 Forge/Cast/Anvil 1.7.1、solc 0.8.28。以下从仓库根目录执行；`bash labs/m05/build.sh` 编译六个 Java 源文件。RPC 和两个 Java 服务只监听回环地址。不同演练用新部署、新库或新库名，不跨轮复用哈希。

- **17 · 区分未见、执行失败与观察中断。** `--settle-wei 9007199254740993 --hold` 部署后，用 `bash labs/m05/run.sh ReceiptApi raw "$LOCK"` 与 `/receipts/{hash}` 对读：块 2 的日志和 HTTP 200 都给出 **9,007,199,254,740,993 wei**（`0.009007199254740993 ETH`）；块 3 的结算成功但没有 `lockedWei`。全零哈希得到 `404 NO_RECEIPT`；`python3 labs/m05/reverted_receipt.py` 产生真正的块 4 失败回执，`200 REVERTED`、`status=0x0`、耗气 23,443 gas。直接漏传 RPC 参数得到错误码 −32602；仅停节点后重查原锁款为 `503 RPC_UNAVAILABLE`，不是未付款。
- **18 · 补扫不是累加入账。** `bash labs/m05/run.sh Scan` 先锚定块 1。在没有订阅和扫描进程时锁入 125 wei、结算、挖空块。随后 `Scan` 报 `PAGE 2..4 matched=2 inserted=2 cursor=4`，`Scan 2` 重放报 `inserted=0`，首扫、重读两份 SQL 快照经 `cmp` 相同。再挖两空块，游标到 6，仍仅有 2 条日志；`Scan 9` 因跳过历史而拒绝。由 B 领取后扫到块 8，只新增 `Withdrawn@7` 的 125 wei，强制重放新增 0。
- **19 · 旧账保留，按新分支核算。** `python3 labs/m05/reorg_lab.py --out <新目录>`：37 wei 原在 A3 结算给收款方，A4 是空块。提交前中断，数据库仍与 A4 快照相同；正常修正退到共同块 2，保留两块旧历史、记一张修正单。B4 规范支有锁款、退款、提款三条事件，付款方应领 **0**、从托管实收 **37 wei**。以 `--wei 9007199254740993 --leave-credit` 再跑一轮，新头仅到 B3：付款方应领全部、实收 **0**。两轮均核对链上 `credit`；再投喂 B 支后规范账、原始行和修正单均不变。
- **20 · 订单差异。** `Scan` 和 `OrderApp` 接上 125 wei 的部署后，`python3 labs/m05/order_drill.py 125` 实际读到以下结果。这里核销的是受益人的托管应领，不是钱包到账。

| 意图或故障 | 节点头 / 游标 | 可比差额（wei） | 实际判断 |
| --- | --- | --- | --- |
| 要求 126 wei，实见 125 wei | 3 / 3 | 1 | `HOLD_AMOUNT` |
| 要求 125 美分，实见 125 wei | 3 / 3 | 不可比 | `HOLD_ASSET` |
| 要求 125 wei、2 次确认，只有 1 次 | 3 / 3 | 0 | `HOLD_DEPTH` |
| 已挖一个空块，扫描器未追平 | 4 / 3 | 未核 | `HOLD_LAG` |
| 追平后先 GET，再以两个键发三次回调 | 4 / 4 | 0 | `READY_TO_BOOK` → `BOOKED_AT_HEAD`；1 条应领流水、1 条 outbox |

- **卷末 E-520。** 付款前在块 1 创建意图并用 `db.sh dump` 备份。停扫期间实际锁款、结算；在 `m05_restored` 用 `db.sh restore` 恢复空库，读到头 3、游标 1、`HOLD_LAG`。`Recover` 补齐两块，只有 1 次确认；到头 5、3 次确认才核销 **9,007,199,254,741,019 wei**。结算交易 `0x6d47357349314c6e78adfcc60e31d339047817936bb8317b230c0100202b3ccb` 的原始回执与流水金额、块哈希匹配。再回到付款前快照，挖一个不同的块 2，`Recover` 得到 `old=5 ancestor=1 observed=2 orphanBlocks=4`。旧流水与 outbox 仍在，查询为 `HOLD_ORPHAN`、`mayNotifyAsOfHead=false`，没有另造负数退款。
- **站点。** `python3 tools/build.py` 成功。首页、计划和第 16–20 课的 288 个本地链接、片段与资源引用可解析。Chrome 离线从首页打开第 17 课，也从第 16 课连续读至第 20 课、进入 M06 计划。1280 / 375 px 下四课均无页面横向溢出，桌面图文并排，手机先凭据后导语；正文图宽 736 / 359 px，四图均能放大、收起并返回原焦点。代码块明、暗对比度分别为 10.61:1、9.96:1。
- **边界。** 实跑仅限单节点 Anvil、单写索引器和专用教学库。没有复现公网共识、生产节点限额或外部通知投递；outbox 行数不是已发送数，数据库备份也不能恢复已关闭的内存链。实验结束已停止临时服务。

## M04 分工

四课分开执笔，共用 `labs/m04/` Foundry 工程：13 `labs/abi.md`（金额登记与 Java/Cast 字节对照）；14 `labs/escrow.md`（唯一的 `src/MilestoneEscrow.sol` 与状态转移演练）；15 `labs/invariants.md`（对同一合约做 Forge 测试）；16 `labs/deployment.md`（部署、清单交接与卷末工单）。配图归 `assets/figures/m04/`。主 agent 负责锁定构建配置、接入导航、运行实验与浏览器验收。

## M04 验收记录

环境：macOS arm64，JDK 21.0.2、Python 3.11.8；`bash labs/m04/setup.sh` 核验并安装 Forge、Cast、Anvil 1.7.1 与 solc `0.8.28+commit.7893614a`。按第 13 课导出 `PATH`、`FOUNDRY_SOLC` 并清除旧 `ANVIL` 指向。共用构建目标 Cancun、优化 200 runs，无第三方 Solidity 库。

- **13 · 登记不是转账。** 从根目录运行 `python3 labs/m04/abi_lab.py`，Java 和 Cast 得到相同的 36 字节（selector `0x60fe47b1`），均解出 9,007,199,254,740,993。模拟后存储仍为零；交易在块 2 成功，getter 与槽 0 均为原数，合约实收 0 wei。用 `--amount-wei` 分别传 `2²⁵⁵ + 9`、`0` 的十进制文本：前者返回字的首尾字节为 `80`、`09`，两端均解为正数；后者回执成功而登记值前后都是 0。传 `2²⁵⁶` 的十进制文本，编码前 `STOP wei outside uint256`，退出 2，未启动节点。
- **14 · 截止边界。** 在 `labs/m04/` 运行 `forge test --offline -vvvv`，转移夹具 6 项通过。12,500 wei 在 D−1 结算后仍全部留在合约，B 应领 12,500；在 D 未调用时仍为 `Locked`，结算被拒，A 调退款后才应领 12,500。两支均在领取后清零，终态分别为 2、3。零入金、无权角色、无效初始条款、重复结算与重复领取均命中预期错误。
- **15 · 账本与反例。** 同一 Forge 运行，属性夹具 6 项通过，包括 64 轮金额 fuzz、32 × 16 次状态序列调用，512 次 handler 调用无意外回退（不等于 512 笔付款）。固定序列将 41 wei 结算与另一单 59 wei 退款记入同一本册，累计实收 100。按正文在临时工程把报表的 `<` 改为 `<=`，截止秒固定测试失败；以 `--fuzz-seed 0x15 -j 1` 捕获并保存 `raw=5276, atCutoff=true`（5,277 wei），重放仍报 `posting at cutoff`。仅还原测试报表公式，两个固定测试与 64 轮 fuzz 均恢复通过；业务合约没有改动。
- **16 · 清单交接。** 从根目录运行 `python3 labs/m04/deployment.py --reset --out <新目录>`：空目录复编的创建代码及 64 字节构造参数与链上输入一致；独立读端在链 31337 的块 1 读到状态 0、应领和余额均为 0。换一条同链号的空链，再用原清单，得到 `STOP chainId=31337 missing deployment block 1`、退出 3，而不是读到零余额。部署和登记共用 `labs/anvil_lab.py` 的 `send_mined`：只发一次，回执暂缺时只查原哈希。
- **卷末 E-416。** `python3 labs/m04/deployment.py --ttl 5400 --settle-wei 9007199254741017 --out <新目录> --hold`：创建、锁款、结算分别在块 1、2、3。按正文命令逐字节核对归档，并解码结算交易 `0x7d23325b5b2f958e0112458a369d433662bbddbd78054e28125c88dd0ad90fde` 的 `Settled` 日志：金额、块 3 的受益人应领与托管余额均为 **9,007,199,254,741,017 wei**；已付给受益人 0，应保留旧地址的领取入口。在同一活节点只把清单副本的截止时间加 1 秒，读端 `STOP constructor argument mismatch`、退出 3。
- **站点。** `python3 tools/build.py` 成功；首页、计划和第 12–16 课共 280 个本地链接、片段与资源引用可解析。Chrome 离线以 `file://` 从首页进入 M04，也从第 12 课顺读 13→16 并进入 M05 计划。四课在 1280 与 375 px 下均无页面横向溢出，桌面图文并排，手机先凭据后导语；正文图宽分别为 736、359 px，四图可放大、收起并返回原链接。代码块明暗对比度分别为 10.61:1、9.96:1。
- **边界。** 仅实跑 macOS arm64 上的本地 Forge 与回环 Anvil；未验证其他平台安装、公网部署、真实接收方合约或代理升级。本卷测试记录不是审计，不可据此承载客户资金。

## M03 分工

四位作者分课交付：09 `labs/accounts.md`、`labs/accounts.py`（同块账户状态）；10 `labs/nonce.md`、`labs/nonce.py`（争用发送序号与超时核对）；11 `labs/evm.md`、`labs/EvmTransfer.java`（升级原 Java 回执实验）；12 `labs/receipts.md`、`labs/receipts.py`（交易状态、最终性与卷末工单）。各课离线插图归 `assets/figures/m03/`。主 agent 负责 `labs/anvil_lab.py` 的共用回环节点接口、导航、实跑及浏览器验收。

## M03 验收记录

环境：macOS arm64、Python 3.11.8、Anvil 1.7.1（Cancun，chain ID 31337）、Gson 2.13.2。以下 Python 命令从根目录执行；`ANVIL` 指向已核验摘要的二进制。每轮独立启动回环节点，不跨轮复用地址或交易哈希。

- **09 · 同块快照。** `python3 labs/accounts.py`：按创世块和付款块各自的哈希读取双方状态；A 减少 42,000,000,000,125 wei、nonce 0→1；B 增加 125 wei、nonce 仍为 0，`MATCH_AMOUNT`。两个地址均无代码，0 号槽均为 32 字节零。付款后本节点给出的 `latest/safe/finalized` 高度为 `1/0/0`。分别追加 `--value-wei 0`、`--value-wei 124`，回执均成功，但实收 0 或 124 wei，均 `HOLD_AMOUNT`、退出 3。
- **10 · 超时后查原件。** `python3 labs/nonce.py`：两单同读 0；P 进池后 `latest=0 pending=1`，用广播前落库的哈希找回 P，签名恢复地址与付款方一致。Q 同费争号被拒。重播 P 原件得到 RPC 错误，但原哈希在块 1 中成功，商户仅增 7,000 wei；不是“重试报错所以没付款”。换 `--new-nonce` 后两份不同哈希同块成功，商户增 14,000 wei。两种策略各追加 `--amount-wei 12345`，实收分别为 12,345、24,690 wei。
- **11 · 执行费。** 启动正文指定的新 Anvil，以 `java --class-path "$LAB/gson.jar" labs/EvmTransfer.java` 从根目录运行。默认交易 `0xbe19af889c5dd28c658097cdba68f928ad023eda183973092481d0a4b4140b73` 用 21,000 gas，实价 2 gwei/gas：预算 90,000 gwei，只付 42,000 gwei；销毁与小费各 21,000 gwei。Bob 实收 0.01 ETH；Alice 扣款 10,042,000,000,000,000 wei。另起新链分别追加 `--max-fee-wei 1500000000`、`--max-fee-wei 4000000000`：前者实付 31,500 gwei，后者预算增至 120,000 gwei 但实付仍为 42,000 gwei。默认及降价轮用 JDK 21.0.2，升价轮用 JDK 17.0.10，三轮均 `PASS`。
- **12 · 回执的三种结果。** `python3 labs/receipts.py`：原交易先在池中可见而回执为 `null`，后在块 2 执行成功；确认数 1→2，`HOLD_DEPTH`→`READY_LOCAL`。`--reject` 生成真实 `status=0` 回执，付款方花费 39,459,774,847,360 wei、nonce 增 1，商户实收 0。`--order-id R-12B --replace-block` 令块 2 的哈希由 `0x82e08a98…` 换为 `0xad88b7f7…`，原回执消失，旧款与费用从新支的余额中撤销，转为 `HOLD_RECHECK`。各轮最后停掉本节点再查原哈希，均观察到 `ConnectionRefusedError`，保留上一状态、没有重发。
- **卷末 E-312。** `python3 labs/receipts.py --order-id E-312 --order-wei 9007199254740993`，分别带及不带 `--short-pay`，用正文 JShell 读取两份日志复算。两轮均 `status=1`、2 次确认、`feeWei=39420390091096 balanced=true`；少付轮 `shortageWei=1`，仍 `HOLD_AMOUNT`；足额轮 `shortageWei=0` 才 `READY_LOCAL`。
- **站点。** `python3 tools/build.py` 成功。首页、计划和第 08–12 课共 275 个本地链接、片段或资源引用均可解析。Chrome 以 `file://` 在 1280 和 375 px 由首页进入 M03 并顺读 09→12，卷末指向 M04 计划。四课均无横向溢出，桌面图文并排，窄屏先看凭据再读导语；四图均可离线放大、收起并返回原链接。窄屏图宽 344 px，代码块明、暗主题对比度分别为 10.61:1、9.96:1。
- **边界。** 未连接公测网、主网或 L2，未实测真实 PoS 最终化、验证者重组及 Linux/WSL2 安装。第 10 课忽略首次广播答复以演练恢复，并非人为制造网络超时；第 12 课确实停掉回环节点观察查询断连。快照换块只用于复核旧凭证，不等于复现公网共识。

## M02 分工

四位作者分课交付：05 `labs/confirmations.md`（用双钱包实验观察成熟度与订单门槛）；06 `labs/bitcoin.md`、`labs/bitcoin.sh`、`labs/bitcoin_payment.py`（原付款实验及两端证据）；07 `labs/scripts.md`、`labs/scripts.py`（两种输出与见证）；08 `labs/psbt.md`、`labs/psbt.py`（观察钱包和签名钱包、卷末独立工单）。各课的离线图放在 `assets/figures/m02/`。主 agent 提取 `labs/regtest.py` 供本卷复用，负责建站、实跑和验收。

## M02 验收记录

运行环境：macOS arm64、CPython 3.11.8、Bitcoin Core 30.5。以下节点均为临时 regtest，`version=300500`、`networkactive=False`、`peers=0`。金额单位为 sat；随机地址、交易号和块哈希不要求跨次运行相同。

- **05 · 何时放货。** 根目录 `bash labs/bitcoin.sh`：高度 100 的奖励仍为 `immature_sat=5000000000 selectable=0`，高度 101 变为 `trusted_sat=5000000000 selectable=1`。付款从 0 次确认到块 102 的 1 次，再到链尖 103 的 2 次。将这份日志送入第 05 课的门槛比较命令，最后分别得到 `required=2 RELEASE` 和 `required=3 HOLD`。分支重组图是纸上推演。
- **06 · 付款凭证。** 同一次运行，前序 `8755c11b13b21a9353c7d6845891782911bc4ac202dcab0db1c6109b9ae413e5:0` 的 5,000,000,000 分给 Bob 125,000,000、Alice 找零 4,874,999,000，差额 1,000。节点预检与复算一致，141 vB，对应 7.092 sat/vB；两个钱包回执均指向第 102 块 `5fa5a33cb3340d0c0873d6ec1dc883cdf1bafe0d302342ece73a252f9e760c87`。另在 `labs/` 运行 `python3 -c 'import bitcoin_payment as p; p.PAY_SAT=124_999_999; print(p.run(p.lab))'`：原订单未改，Bob 实收少 1，确认数 2 仍 `HOLD_SHORT`，手续费仍为 1,000。
- **07 · 花费条件。** 根目录 `python3.11 labs/scripts.py` 和 `python3.11 labs/scripts.py --explicit-all` 均将两笔花费纳入高度 103 的块；两类地址各改末位均 `isvalid=False`。默认运行 P2WPKH 的见证项为 71 和 33 字节。对同一 Taproot 草稿，默认签名为 64 字节、396 WU / 99 vB；显式 `ALL` 为 65 字节、397 WU / 100 vB，`same_base_txid=True same_wtxid=False`，实际入块的 wtxid 匹配后者。
- **08 · 签名前核对。** 根目录 `python3 labs/psbt.py`：只读端 `complete=false can_extract=false`；持钥端完成两个输入，最终交易付商户 60,000、找零 39,580、手续费 420。估算与实际均为 208 vB，对应 2.0192 sat/vB；两端查到同一付款、同一块，各 1 次确认。分别追加 `--short-pay`、`--fee-sat 700`、`--fee-sat 801`，依次因少付 1 sat、超过 3 sat/vB、超过 800 sat 在请求付款签名前停止，均退出 3，`broadcast=false mempool=0`。
- **卷末工单 C-208。** `python3 labs/psbt.py --order-sat 31250 --fee-sat 550 --change-first`：沿同一入金的输出 2、0 分别找到 70,000 和 30,000；付款交易的 `vout=0` 由内部找零描述符认领 68,200，商户收到输出 `76c5b3fa1b64865e5c621c68fcc1b61fc7beacc737aac02e0d2d0334b5ba4312:1` 的 31,250。两端均指向高度 103，实际费率为 550 / 208 ≈ 2.6442 sat/vB。只追加 `--short-pay` 另起一轮，`expected_sat=31250 proposed_sat=31249`，退出 3，未发起付款签名或广播。
- **站点。** `python3 tools/build.py` 成功。首页、计划及第 04–08 课的 269 个本地链接、片段或资源引用均可解析。用 Chrome 直接打开本地 HTML 检查四课：1280 px 与 375 px 均无横向溢出；七幅 SVG 在两种宽度下均能离线打开、收起并返回原图链接。375 px 下正文图宽约 344 px。代码块明、暗主题文字对比度分别为 10.61:1 与 9.96:1。
- **边界。** 实跑限 macOS arm64、自有 regtest；没有实跑 Linux/WSL2 安装、主网、真实重组、Taproot 脚本路径或硬件签名器。PSBT 使用同一 Core 实例中的独立钱包，未演练物理隔离或多人合签；这些不作为本卷的实测结论。

## M01 验收记录

实跑平台为 macOS arm64。下面给出各实验的工作目录、命令和观察结果；归档仅含合成消息、公开地址、回环节点版本与链标识。

- **01 · 账页证明。** 在 `labs/` 用 JDK 21.0.2 运行 `java MerkleLab.java` 和正文的三条 `verify` 命令：全页根为 `c2d6ba7ea2bb3bc0a5dec604403dc473df26c923b7e9cd81fefb8701f5ed290d`。位置 2 的凭条 `12030201` 按右、左两个兄弟重算得到同一根；仅改张数、仅改位置均返回 `matches.trusted=false`、退出码 1。
- **02 · 消息证据。** 执行 `labs/crypto.md` 的 JShell 块（JDK 21.0.2）：125 与 126 的 UTF-8 指令均为 51 字节，金额字节分别为 `313235`、`313236`，摘要前八位分别为 `7c2942bd`、`a56887c3`。在 `labs/` 运行原有的 `java IntentLab.java`：`original=true changed_amount=false`、`matches_original=true`、`altered_ciphertext=rejected`。
- **03 · 钱包恢复。** 在 CPython 3.11.8 独立环境安装 `embit==0.8.0`，从 `labs/` 运行 `python wallet.py first`、`second`、`wrong-branch` 三种模式。前两者与 BIP84 两个公开收款地址整串相符，均退出 0；改为 `/1/0` 得到规范的找零地址，`watch_only_matches=True` 但 `receipt_matches=False`，退出 1。未连接钱包或查询余额。
- **04 · 网络身份。** 在项目根目录用 `bash labs/networks.sh` 启动真实节点。Bitcoin Core 30.5 在 `127.0.0.1:19443` 报告 `version=300500 chain=regtest height=0 peers=0`；Anvil 1.7.1 在 `127.0.0.1:18546` 返回 `eth_chainId=0x7a69`，`PASS`、退出 0。再用 `bash labs/networks.sh 31338` 实际改变服务端链号，读到 `0x7a6a`，客户端报告 `STOP expected=0x7a69 actual=0x7a6a before_sign=true before_send=true`、退出 3。两次均未发交易。
- **卷末验收。** [异常付款工单 R-36](labs/networks.html#卷末验收接手一张异常付款工单)给出不同于正文的四条新记录。用 Python `hashlib.sha256` 独立重算检查点 `c3322a5de98353549cc1d77445b20caf80b355a63224466f6d3eead3b5f1dc08`；交换凭条 36 的付款方与收款方后，原证明不再匹配。原凭条本身是 B 付 A，并不能核销 B 的应收。
- **图文版站点。** `python3 tools/build.py` 生成四课阅读页。直接以 `file://` 从首页顺读 01→04，八幅 SVG 均加载。375 px 窄屏图宽 343 px，页面没有横向溢出，点图可离线打开原图。首页、计划和四课共 214 个本地链接、片段或资源引用均可解析。
- **边界。** 本批实跑覆盖上述正常与拒绝路径；未实跑 Linux/WSL2 安装步骤，未连接公测网或主网。私链标识一致不证明业务到账，公开派生向量不可收款。
- **图文返修 · 实验复核。** `java MerkleLab.java verify 0 10010203 L1 P23`（`L1`、`P23` 取整页输出的完整摘要）得到右、右两个兄弟并匹配可信根；只把收款方 B 改为 C，即 `10010303`，退出 1。重跑 `java IntentLab.java` 和钱包的三个模式，改金额、改密文及走错分支的结果与以上记录一致。重启两个本地节点，`bash labs/networks.sh` 放行，`bash labs/networks.sh 31338` 读到 `0x7a6a` 后停止并退出 3。
- **返修案例。** 用 JDK 21.0.2 的 JShell 对同一订单验原签名，得到 `retry=true lf=false reordered=false`：重试可能重复入账、加换行或换字段顺序则过不了原签名。第 03 课的 `50,000 − 36,000 − 500 = 13,500 sat` 找零与扫描窗口 `0..19` 漏掉索引 `20` 是纸上算例，不是链上转账记录。另实跑 `bash labs/networks.sh 31360`，读到 `0x7a80`、退出 3。

## 交接记录

- M01 成品：`labs/ledger.md` + `labs/MerkleLab.java`；`labs/crypto.md` + 原有 `labs/IntentLab.java`；`labs/wallet.md` + `labs/wallet.py`；`labs/networks.md` + `labs/networks.sh`。四课由子 agent 分课写作，主 agent 核对并整合至同名 `.html`、首页和计划目录；未开始后续卷正文。
- M01 图文返修：四位子 agent 分别重写一课并各交两幅 SVG，原实验接口不变。图源位于 `assets/figures/m01/`，随正文就地展示；主 agent 合并阅读样式、复核案例和图中的方向与数值、重建静态页。
- M02 成品：05–08 课的 Markdown 与同名 HTML 已接入首页和计划页；可从第 04 课连续读至第 08 课。第 06 课从样课升为正式课，保留 `bash labs/bitcoin.sh` 入口。
- M03 成品：09–12 课的 Markdown、同名 HTML、配套脚本与 SVG 已接入[本卷目录](plan.html#m03)。第 11 课沿用并扩展 `EvmTransfer.java`，第 12 课附独立工单；未开始 M04 正文。
- M04 成品：13–16 课 Markdown 和同名 HTML、`labs/m04/` 工程与 `assets/figures/m04/` 四图已接入[本卷目录](plan.html#m04)。后续索引使用 `MilestoneEscrow.sol` 的 `Locked`、`Settled`、`Refunded`、`Withdrawn` 四类业务事件，不采集 Forge 夹具的 `Ledger` 或 `Page`。未开始 M05 正文。
- M05 成品：17–20 课 Markdown 和同名 HTML、`labs/m05/` Java/SQL 工程与 `assets/figures/m05/` 四图已接入[本卷目录](plan.html#m05)。卷末可从付款前数据库恢复到同一部署；M06 正文未开始。
- M06 成品：21–24 课 Markdown 与同名 HTML、`labs/m06/` 签名台及合约实验、`assets/figures/m06/` 四图已接入[本卷目录](plan.html#m06)。卷末交付相互独立的登录、额度、成交和估值凭证。下一批转主线 M10，未开始后续正文。
- M07 成品：25–28 课的 Markdown 与同名 HTML、`labs/m07/` 的运行程序和公开测试网证据、`assets/figures/m07/` 四图已接入[本卷目录](plan.html#m07)。卷末分开签收一笔官方桥付款与一张本地代付拒单，未开始 M10 正文。
