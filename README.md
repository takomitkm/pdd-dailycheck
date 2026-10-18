# pdd-dailycheck

每天 10:00 用无线 adb（Android Debug Bridge，走 TCP 而非 USB）在真机上跑一遍拼多多的
百亿补贴日常任务，跑完往手机推一条通知。整套只有一个 bash 文件，不装框架、不起服务进程。

被自动化的链是固定的四步：**百亿补贴入口 → 抽福袋格子 → 立即点亮胶囊 → 滑动浏览 10 秒**，
外加每轮 20 次下滑。成功与否不靠"点没点到"判断，靠屏幕上的字判断（见
[docs/states-and-exit-codes.md](docs/states-and-exit-codes.md)）。

## 仓库结构

| 路径 | 是什么 |
| --- | --- |
| `pdd.sh` | 现役交付物，单文件 1840 行，直接放到跑自动化的那台 Debian 的 `~/Desktop/` |
| `systemd/pdd.service`、`systemd/pdd.timer` | 触发用的一次性服务和日历定时器（从主机上原样抄回） |
| `sandbox/sbx.sh` | 桩沙箱：不碰手机，把 `pdd.sh` 的分支矩阵跑一遍，37 个用例 |
| `sandbox/bin/{adb,tesseract,curl}` | 三个桩，只回话不执行；所有 `input` 事件记进 `$SBX_EVENTS` |
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
- 脚本本体：`~/Desktop/pdd.sh`，权限 700（文件里带推送 token，见下面"凭据"一节）
- 证据目录：`~/Desktop/pdd-runs/<日期>/<时分秒>/`，保留 7 天

部署（在主机上执行）：

```sh
scp pdd.sh deb-h61:/tmp/pdd-deploy.sh
ssh deb-h61 'bash -s /tmp/pdd-deploy.sh' < scripts/deploy.sh
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
[pdd.sh:257](pdd.sh#L257)），不会默默点到 `(0,0)`。标定方法见
[docs/calibration.md](docs/calibration.md)。

## 定位顺序

`uiautomator` XML → 整页 OCR（psm 11 稀疏文字，再 psm 6 整块）→ band 裁片档（裁区域 +
autocontrast + ×3）→ pill 反色档（裁胶囊 + 反色 + 硬阈值 120 + ×1/×2）→ `COORD_*` 比例兜底（分数 0）。
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

- 真实凭据只有推送地址一个，全库只出现在 **[pdd.sh:246](pdd.sh#L246)** 一处。它带 ServerChan 的
  send token，等于凭据，所以脚本权限保持 700，仓库保持私有。要换掉或清空，改这一行即可，
  清空后不推送但流程照跑。
- 沙箱会先把它换成 `http://stub.push/send` 再跑，且有自检：换不成功直接 `exit 1`，
  绝不往真实端点推（见 [docs/sandbox-testing.md](docs/sandbox-testing.md)）。
- 文件里另有无线 adb 地址（内网 IP）和主机路径，不含口令。SSH 免密用的公钥不在本仓库。

## 已知残留

1. `COORD_bag` 是这颗胶囊唯一的坐标兜底，非恢复路径上认不到字时会按它盲点。同一颗「抽福袋」
   胶囊实测在两个版式之间跳：`(111,894)` 和 `(435,524)`，而 `0.13889,0.69922` 只覆盖前者。
   10-16 那次它落空、点到的是一整张商品卡。现在没有任何位置判别器能区分"抽福袋"和
   "邀好友抽福袋"。
2. 恢复路径上 subsidy 那一枪会白烧约 90 秒（`FIND_RETRY_bag=12 × 3s`），因为它先要把轮播扫完
   才退到兜底。
3. `pick()` 取的是文件顺序里第一个落在区域内的命中，**不是最高分**。所以任何全局调 psm
   的改动都可能把深底胶囊那两档挤掉；要调只按 key 单独加 `OCR_PSM_BAND_<key>`。
4. `find <key>` 超时时会打印出半截前缀（例如 `bag  subsidy  coord 90 600`），是没闭合的
   printf，不是定位错。

## 当前版本

- `pdd.sh`：1840 行，md5 前缀 `69e05f4e`，2026-10-18 14:01 部署到主机 `~/Desktop/pdd.sh`
- 沙箱：720x1280 与 1440x2560 各 37/37 绿；负对照在旧像素版上如期挂 2 条
- 本机（Windows）不是运行环境，只是开发与取证的地方；真正跑的是上面那台 Debian
