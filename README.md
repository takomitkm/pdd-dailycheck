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
| `scripts/negative-control.sh` | 负对照：故意把一条判据改成恒假，验证测试真会挂 |
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
第六档不是每个 key 都有：现在只有 `subsidy` / `light` / `dialog` 三颗配了坐标，
`bag`（抽福袋）和 `take`（开心收下）没有，前五档全空就是这一步 FAIL。
psm 是 tesseract 的 page segmentation mode，页面分割模式，决定它把图当成一栏还是一堆散字。
每一档是怎么量出来的、为什么不能改全局值，写在 [docs/locate-channels.md](docs/locate-channels.md)。

## 验收：改任何东西之前先跑沙箱

```sh
bash scripts/run-sandbox.sh                                   # 720x1280，约 5 分钟
SBX_SIZE=1440x2560 bash scripts/run-sandbox.sh                # 同一份标定数据换一块屏
bash scripts/negative-control.sh                              # 测试自己有没有牙
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

1. 「抽福袋」这颗胶囊**已经没有坐标兜底**了（`COORD_bag` 10-20 删，原来写的是
   `0.13889,0.69922` ＝老版式那一格 `(100,895)`）。删的理由是同一颗胶囊实测在两个版式之间跳：
   `(111,894)` 和 `(435,524)`，固定点只盖得住一侧，10-16 那次它落空、点到的是一整张商品卡。
   代价是认不到字就当场 `rc=5` 报错、一个点都不盲下；10-20 拿当天 42 帧真图重放过，
   新版 42 帧全部认得到字（旧版只有 2 帧认到，其余 40 帧全靠那个盲点），所以这个代价
   目前付得起 —— 重放表和口径写在 [docs/calibration.md](docs/calibration.md)。
   仍然没有位置判别器能区分"抽福袋"和"邀好友抽福袋"。
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

## 当前版本

- `pdd.sh`：1869 行，md5 前缀 `16331810`，2026-10-20 14:31 部署到主机 `~/Desktop/pdd.sh`（700），
  上一版 `69cb69f4` 存为 `pdd.sh.bak-1020-1431`；本地 / `/tmp/pdd-deploy.sh` / `~/Desktop/pdd.sh`
  三方 md5 相等
- 这一版删掉了 `COORD_bag`（抽福袋那颗固定坐标）。它是 10-09 加进来的，理由是「subsidy 和
  light 都有兜底，就它没有」；10-20 反过来把它删了，因为同一颗胶囊会在两个版式之间跳
  （`(111,894)` / `(435,524)`），固定点只盖得住一侧，而 10-16 那晚它落在了一整张商品卡上。
  现在这颗只走认字三条路，认不到就 `rc=5`。
  背景：10-17、10-18、10-20 三天同一个 `rc=6` —— BACK 从消费券浏览页落回**频道页**时，那颗
  胶囊一直在屏幕上，但整页 psm 6 和 band 那套灰度+autocontrast 都读不出它，`text_present bag`
  扫满 12 轮无果，备用路线又因为频道页左上的「百亿补贴」是艺术字而一起失败，两条路只剩固定
  坐标 —— 而核实路线禁盲点。治法是上一版（`69cb69f4`）加的 `PILL_bag` + `PILL_MODE_bag=color`
  （紧框原色彩，不转灰度不反色），这一版把那个已经用不上的盲点删掉同一版还有两处：比例闸门改成按前缀
  `compgen -v COORD_` 现取名单（写死的名单在删掉一颗之后会留下一个不存在的名字，
  也会让将来新加的那颗漏检），以及 `replay_frame` 补上 `band` 分支——之前胶囊档明明认到了字，
  重放表却把它印成「认不到且无兜底」，修复被读成没修复
- 沙箱（跑的就是部署那份字节）：720x1280 与 1440x2560 各 **37/37 绿，失败用例数 0**；
  两条负对照都咬住了：把 `browse-reenter-venue` 的判据改恒假 → 挂 1 条；把 `COORD_bag`
  注回配置 → `bag-not-found` 挂 1 条（它现在按的是"一次都不点坐标"，只看 rc=5 是钉不住的）
- 真帧重放：10-20 那一轮 42 张 `*-bag-*.png`，旧版（`pdd.sh.bak-1020-1207`）40 帧退到
  `coord 100 895 分数=0`、2 帧整页 OCR；这一版 **42 帧全部认到字**，命中点都落在 `111 895 抽 福 袋 分数=3`，
  没有一帧判成"认不到且无兜底"。表与口径见 [docs/calibration.md](docs/calibration.md)
- 推送链路：`notify()` 真推过一条是 12:07 那版验的（日志 `[PUSH] 已推送` 只在响应
  `"code":0` 时才打）；这一版没动通知，部署后重跑 `pdd.sh status`，在 transient unit 里仍报
  `来自 file:/home/user/Desktop/pdd-push.url`，明早 10:00 的 `pdd.service` 用的就是这个文件
- 本机（Windows）不是运行环境，只是开发与取证的地方；真正跑的是上面那台 Debian
