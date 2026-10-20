# pdd-dailycheck

每天 10:00 用无线 adb（Android Debug Bridge，走 TCP 而非 USB）在真机上跑一遍拼多多的
百亿补贴日常任务，跑完往手机推一条通知。整套只有一个 bash 文件，不装框架、不起服务进程。

被自动化的链是固定的四步：**百亿补贴入口 → 抽福袋格子 → 立即点亮胶囊 → 滑动浏览 10 秒**，
外加每轮 20 次下滑。成功与否不靠"点没点到"判断，靠屏幕上的字判断（见
[docs/states-and-exit-codes.md](docs/states-and-exit-codes.md)）。

## 仓库结构

| 路径 | 是什么 |
| --- | --- |
| `pdd.sh` | 现役交付物，单文件 1854 行，直接放到跑自动化的那台 Debian 的 `~/Desktop/` |
| `systemd/pdd.service`、`systemd/pdd.timer` | 触发用的一次性服务和日历定时器（从主机上原样抄回） |
| `sandbox/sbx.sh` | 桩沙箱：不碰手机，把 `pdd.sh` 的分支矩阵跑一遍，37 个用例 |
| `sandbox/bin/{adb,tesseract,curl}` | 三个桩，只回话不执行；所有 `input` 事件记进 `$SBX_EVENTS` |
| `githooks/pre-commit`、`githooks/pre-push`、`githooks/patterns.sh` | 凭据门禁，两道：提交前扫暂存区、推送前扫真要传上去的 blob |
| `scripts/deploy.sh` | 备份 → `install -m 700` → 复查语法，在主机上跑 |
| `scripts/run-sandbox.sh` | 把沙箱推到主机 `/tmp/pddsandbox/in` 并跑全矩阵 |
| `scripts/negative-control.sh` | 负对照三条：故意把源码改坏一处，验证对应那条用例真会挂 |
| `tools/` | 离线标定与取证用的小脚本，都只读已存下的证据，不碰手机 |
| `docs/` | 标定配方、定位通道、沙箱验收、状态与退出码、失败取证 |

## 运行环境

- 主机：Debian 13（本机代号 `deb-h61`，`ssh deb-h61` 免密），用户级 systemd 定时器
- 依赖：`adb`、`tesseract` + `chi_sim` 语言包、`python3` + Pillow、`curl`
- 手机：ZTE A2020U Pro，无线 adb `192.168.1.110:16132`，`wm size` override 720x1280
  （override 后的点空间与截图尺寸一致，所以 OCR 读到的坐标可以直接当点击坐标用）
- 脚本本体：`~/Desktop/pdd.sh`，权限 700
- 推送端点：`~/Desktop/pdd-push.url`，权限 600，全库唯一一处真凭据，不在仓库里（见"凭据"一节）
- 证据目录：`~/Desktop/pdd-runs/<日期>/<时分秒>/`，保留 7 天

部署（在主机上执行）：

```sh
scp pdd.sh deb-h61:/tmp/pdd-deploy.sh
ssh deb-h61 'bash -s /tmp/pdd-deploy.sh' < scripts/deploy.sh
```

第一次装（或轮换 token 之后）要把端点写进那个文件，只写第一行，脚本运行时读它：

```sh
ssh deb-h61 'umask 077; printf "%s\n" "<ServerChan 的 send 端点>" > ~/Desktop/pdd-push.url'
```

定时器只在第一次安装时需要 enable：

```sh
ssh deb-h61 'mkdir -p ~/.config/systemd/user && cp /tmp/pdd.service /tmp/pdd.timer ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now pdd.timer'
```

## 子命令

```
pdd.sh run             完整流程；今天已完成过就直接成功退出
pdd.sh run force       忽略"今天已完成"标记，强制再跑一遍
pdd.sh probe           只抓界面：dump + 截图 + 打印可直接粘贴的 COORD_* 比例行
pdd.sh find <key>      解析一个目标但不点
pdd.sh point <x> <y>   裸坐标点一下（这里收的是像素，不是比例）
pdd.sh shot            存一张截图并打印路径
pdd.sh status          设备 / 依赖 / 标记 / 证据目录概览
pdd.sh replay <目录>   拿存下来的证据离线重跑判定，不碰手机
```

退出码：`0` 成功 / `2` 设备连不上 / `3` 手机锁屏 / `5` 卡在某一步没找到 /
`6` 点完了但进度数字没变或读不到 / `7` 前台不是拼多多 / `69` 没有 adb / `78` 配置缺或没有 tesseract。
完整语义和 `lit` 状态见 [docs/states-and-exit-codes.md](docs/states-and-exit-codes.md)。

## 坐标一律写屏幕比例，不写像素

`COORD_*`、`SWIPE_X/Y1/Y2`、`BROWSE_X`、`TOP_SWIPE_Y1/Y2` 都是 `0..1` 的屏幕比例，
运行时乘上当前的点空间才变成像素；`REGION_*` 和 `PILL_*` 本来就是比例。
所以换分辨率（改 `wm size`，或换一台机）不用重校，页面布局没变的情况下 OCR/XML 通道也不受影响。

比例给 **5 位小数**：3 位在 1440 宽的屏上有约 0.7px 的系统偏差，5 位折回像素才一个不差。
写成越界值、写成像素、或多一段，脚本启动时直接 `exit 78` 并打印原值（校验在
[pdd.sh:275](pdd.sh#L275)），不会默默点到 `(0,0)`。标定方法见
[docs/calibration.md](docs/calibration.md)。

## 定位顺序

`uiautomator` XML → 整页 OCR（psm 11 稀疏文字，再 psm 6 整块）→ band 裁片档（裁区域 +
autocontrast + ×3）→ pill 胶囊档（裁紧框，默认反色 + 硬阈值 120 + ×1/×2，靠颜色分开的控件
用 `PILL_MODE_<key>=color` 走"什么都不预处理、直接裁"）→ `COORD_*` 比例兜底（分数 0）。
第六档不是每个 key 都有：五颗要点的控件都配了——`subsidy` / `bag` / `light` / `take` / `dialog`；
只有 `exchange`（立即兑换）按口径永远不配，那一枪必须由她手动打。`bag` 和 `take` 这两颗
10-20 14:31 删过、15:15 又补回来，删与改各验了一遍，账目见 [docs/calibration.md](docs/calibration.md)。
psm 是 tesseract 的 page segmentation mode，页面分割模式，决定它把图当成一栏还是一堆散字。
每一档是怎么量出来的、为什么不能改全局值，写在 [docs/locate-channels.md](docs/locate-channels.md)。

## 验收：改任何东西之前先跑沙箱

```sh
bash scripts/run-sandbox.sh                                   # 720x1280，约 5 分钟
SBX_SIZE=1440x2560 bash scripts/run-sandbox.sh                # 同一份标定数据换一块屏
bash scripts/negative-control.sh                              # 三条负对照，每条都应当挂
```

沙箱靠桩 `adb` 把点击事件记进文件，用例断言的是**点了什么、点几下、退出码、标记写没写、
app 关没关**，屏幕几何全部按 `SBX_SIZE` 折算。判据是 rc=0 且 `失败用例数: 0`。
换分辨率必须两遍都绿；细节和踩过的坑在 [docs/sandbox-testing.md](docs/sandbox-testing.md)。

## 凭据

这仓库是公开的，所以仓库里不许有任何真凭据。

- 真凭据只有一个：ServerChan 的推送端点。地址本身就带 send token，等于口令，
  所以它只写在主机的 `~/Desktop/pdd-push.url` 第一行（权限 600），脚本运行时读
  （[pdd.sh:249](pdd.sh#L249)）。读不到 = 没配推送：一条都不推，流程照跑。
- 轮换 token 只动那个文件，不改脚本、不进 git：
  `ssh deb-h61 'umask 077; printf "%s\n" "<新端点>" > ~/Desktop/pdd-push.url'`
- 环境变量 `PUSH_URL` 优先于文件，沙箱和临时覆盖走这条。
- 两道提交门禁，启用一次 `git config core.hooksPath githooks` 就都生效：
  `pre-commit` 扫暂存区，`pre-push` 扫这次真要传上去的每个 blob。命中凭据形态就拒绝；
  **扫不动也拒绝**（`git grep` 用法错、`cat-file` 挂了，都当失败处理，不当"没扫到"）。
  绕过是 `--no-verify`，只在确认那条命中是文档里的"形态描述"而不是真值时用。
- 沙箱里还有第三道独立的：被测的 `pdd.sh` 本体里有真凭据形态就直接 `exit 1`，
  绕过钩子也跑不起来（见 [docs/sandbox-testing.md](docs/sandbox-testing.md)）。
- 文件里另有无线 adb 地址（内网 IP）和主机路径，不含口令。SSH 免密用的公钥不在本仓库。

## 已知残留

1. 「抽福袋」那颗坐标兜底（`COORD_bag=0.13889,0.69922` ＝老版式那一格 `(100,895)`）10-20 14:31
   删过、15:15 又恢复。翻全部保留 run.log 数出来的账：**这一枪一共开火 8 次，4 次点的正是那一格、
   当场进对页面**（10-14 读到终态、10-17 读到 5 次、10-18 10:07 读到 4 次、10-19 读到 3 次），
   另外 4 次落在轮播的另一帧上（10-16 三次、10-18 11:00 一次）。
   **公开更正**：我 10-20 中午写进注释和本文的「点错了什么也没报」是错的——那 4 次每次日志都是
   `[FAIL] bag 点完读不到进度行，多半停在轮播的另一帧`，`PROVE_KEY=bag` 拦住了，从没把点错报成成功。
   它还盖不住 `(435,524)` 那一侧的版式，也仍然没有位置判别器能区分"抽福袋"和"邀好友抽福袋"。
   核实/恢复那条路照旧禁坐标（`RECOVERY_NO_COORD`），所以这颗只在主线第一枪开火。
2. 恢复路径上 subsidy 那一枪会白烧约 90 秒（`FIND_RETRY_bag=12 × 3s`），因为它先要把轮播
   扫完 12 帧才收手。
3. `pick()` 取的是文件顺序里第一个落在区域内的命中，**不是最高分**。所以任何全局调 psm
   的改动都可能把深底胶囊那两档挤掉；要调只按 key 单独加 `OCR_PSM_BAND_<key>`。
4. `find <key>` 超时时会打印出半截前缀（例如 `bag  subsidy  coord 90 600`），是没闭合的
   printf，不是定位错。
5. BACK 从消费券浏览页落在哪一页**不确定**：10-19 落在活动页，10-17/10-18/10-20 落在频道页。
   日志那句「BACK 落在频道页」不是页面判别结果，它真正的条件是"原地读不到进度行、且屏幕上
   认到了 `bag` 的字"——在活动页上也会打这句（10-19 那次就是）。
6. `PILL_bag` 只在 720x1280 上量过。换屏只保证框按比例跟着走，字放大后还够不够 tesseract
   认，没测。
7. 点前的进度行读不到时（10-20 10:07:24 就是），核实退化成「这一枪点的是认到的字就算过」，
   「N 变小」那层对比实际上没做成。这条不影响今天的结论，但它把误报成功的门留在那儿。
8. `COORD_take`（`0.49861,0.58750` ＝ `(359,752)`）只有一个来源：10-10 那帧粉色胶囊量的中心
   `108,708..611,796`。保留的 11 份 run.log 里「奖励浮层 → 开心收下」这一路一次都没开过火，
   所以这颗中心没有第二次实测。它只在浮层那两行字被读到之后才可能打出（`take_prize_overlay`
   的唯一调用点被 `text_present prize` 挡着），浮层改版、按钮挪走的话这一枪会打在浮层底下那一屏，
   日志会写成「按量好的中心收」而不是「认到」，出得来这条就看得到它是盲的。

## 当前版本

- `pdd.sh`：1884 行，md5 前缀 `c9da6422`，2026-10-20 15:15 部署到主机 `~/Desktop/pdd.sh`（700），
  上一版 `16331810` 存为 `pdd.sh.bak-1020-1515`；本地 / `/tmp/pdd-deploy.sh` / `~/Desktop/pdd.sh`
  三方 md5 相等（都是 `c9da642247a365cbbe9382e73606e9c1`）
- 这一版按她的「既然胶囊有用，那你恢复一下？还有没有兜底的？你补上」做三件事：
  **恢复** `COORD_bag`（14:31 那版删掉的），**新增** `COORD_take`（10-10 量过、10-11 按她
  「读不到就不点」删掉的那颗中心），把 `take_prize_overlay` 的日志分成「认到字点它」和
  「按量好的中心收（分数=0）」两条 —— 以前只要 `resolve` 返回 0 就打「认到」，兜底开火时
  那句是假话。核实/恢复那条路的 `RECOVERY_NO_COORD=true` 一个字没动，`exchange` 照旧不配坐标
- 沙箱（跑的就是部署那份字节）：720x1280 与 1440x2560 各 **37/37 绿，失败用例数 0**。
  跟着改的四条用例：`bag-not-found` 现在断言 `bag 用 coord 点 100 895`（1440 屏上是 `200 1790`）
  且 tap=2，`prize-take-unreadable` 改名 `prize-take-coord` 并断言 `按量好的中心收 359 752`
  且 tap=4，`prize-take-ocr` 的 `EXPECT_NOLOG` 从「什么都不点」换成「中心收」（两条都是四枪，
  不这么按就分不清是胶囊档认到的还是兜底蒙的），`recovery-coord-ban` 不用再 sed 注入坐标
- 负对照 `scripts/negative-control.sh` 从 1 条扩到 3 条，三条全咬住：判据改恒假 →
  `browse-reenter-venue` 挂（点击=3 应 4）；删 `COORD_bag` → `bag-not-found` 挂（点击=1 应 2、
  日志里没有「bag 用 coord 点 100 895」）；删 `COORD_take` → `prize-take-coord` 挂（点击=3 应 4、
  日志里没有「按量好的中心收 359 752」）
- 比例闸门这次是白捡的：`compgen -v COORD_` 现取名单，新恢复/新增的两颗自动过检。实测把
  `COORD_take=359,752`、`COORD_bag=100,895` 分别写成像素，两次都 `exit 78` 并点名是哪个变量
- 今天**没有**重跑那 42 帧真图重放。14:31 那版量到的是"三条认字路线在 42 帧上全部命中"，
  兜底只在认字全空时才开火，所以恢复它不改这些帧的判定 —— 这是从上一次实测推出来的，
  不是今天新测的
- 推送链路：这一版没动通知。部署后在 transient unit 里跑 `pdd.sh status`，仍报
  `来自 file:/home/user/Desktop/pdd-push.url，长度 70`（值不打印），设备 `192.168.1.110:16132` 在线
- `pdd.timer`（用户级）active，NEXT **Wed 2026-10-21 10:02:35 CST** —— 那是这一版第一次真机跑
- 本机（Windows）不是运行环境，只是开发与取证的地方；真正跑的是上面那台 Debian
