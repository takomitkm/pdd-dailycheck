# 桩沙箱：怎么跑、断言什么、坑在哪

沙箱的目的只有一个：**不碰手机、不推通知、不碰真账本**，把 `pdd.sh` 的分支矩阵全跑一遍。
它靠 `PATH` 隔离做到这一点——工具农场把 `/usr/bin` 等目录逐个软链，但**排除掉
`adb` / `tesseract` / `curl` / `scrcpy`**，所以被测脚本能看到的这三个命令永远是桩。

## 跑

```sh
bash scripts/run-sandbox.sh                        # 默认 720x1280，全 37 例，约 5 分钟
SBX_SIZE=1440x2560 bash scripts/run-sandbox.sh     # 同一份标定数据换一块屏
ONLY=happy-ocr bash scripts/run-sandbox.sh         # 只跑一例（sbx.sh 直接接受 ONLY）
bash scripts/negative-control.sh                   # 负对照
```

验收口径：末行 `失败用例数: 0`，并且头行打印的 `屏=` 是你指定的那块。

**不能并发跑。** 两跑共用 `/tmp/pddsandbox/run` 和 `$SBX_EVENTS`，会撞出一堆假失败。
`scripts/run-sandbox.sh` 开头已经检查 `ps -eo args | grep -c "[s]bx\.sh"`，非 0 就停。
注意这个计数会把你自己那条 ssh 命令行算进去，看到 1 先别当证据，等它回 0。

## 三个桩各自回什么

| 桩 | 行为 | 由什么控制 |
| --- | --- | --- |
| `bin/adb` | `devices` / `connect` 回在线状态；`input tap|swipe|keyevent` 一律只往 `$SBX_EVENTS` 追加一行；`uiautomator dump` 回成功；`exec-out screencap` 吐出 `$SBX_SHOT`；`exec-out cat` 吐出 `$SBX_XML`；`dumpsys window` 回可控的前台 activity；`wm size` 回 `$SBX_SIZE` | `SBX_OFFLINE` `SBX_WAKE` `SBX_LOCK` `SBX_FPKG` `SBX_FACT` `SBX_SIZE` `SBX_SHOT` `SBX_XML` `SBX_DEV` |
| `bin/tesseract` | 按**输入文件名**路由：`*cand.png` 给整页 TSV，`*band.png` 给 band 档，`*pill-1/2.png` 给胶囊两档，`*count.png` / `*pend.png` 按序号给进度行和天数行 | `tsvfile` / `countfile` 两个 helper 写内容 |
| `bin/curl` | 只把推送正文落到文件，不出网 | `SBX_PUSH` |

点击事件的计数就来自 `$SBX_EVENTS`——这是"到底点了几下、点了什么"的唯一证据源，
不是日志文本。

## 断言的是行为，不是文本

每个用例给 `run_case 名称 期望退出码 期望lit 期望标记`，再加可选的 `EXPECT_*`：

- 退出码和 `lit`（本轮判定出来的状态，见 [states-and-exit-codes.md](states-and-exit-codes.md)）
- 今天标记写没写、账本写成什么数
- `$SBX_EVENTS` 里 tap / swipe / keyevent 各有几条
- app 关没关
- 日志里**必须出现某一行具体几何**，例如：
  - `happy-ocr` → `下滑 x=540 1200->700`
  - `count-unreadable-coord` → `light 用 coord 点 598 285`
  - `bag-right-slot` → `bag 用 ocr 点 435 524`

这三条位置钉是 10-18 去像素化时新加的，作用是：**光看 rc 和 lit 是测不出坐标准不准的**，
必须把"点了哪个像素"钉进断言。

## SBX_SIZE：换分辨率怎么测

用例里的几何一律按 720x1280 那套写死，跑别的尺寸时由 `sx()` / `sy()` 折算过去：

```sh
RSX=$(awk -v w="$SBX_W" 'BEGIN{printf "%.6f", w/720}')
```

桩截图也按 `SBX_SIZE` 现生成，桩 `adb` 报的点空间也用它。于是"同一份标定数据换一块屏"
必须给出**完全相同**的判定（rc / lit / 点几下 / BACK 几下），且期望日志里的像素跟着翻。
选 1440x2560 是因为它是整 2 倍，折算全是整数，比对没有取舍歧义。

## 三条硬自检（`sbx.sh` 的 `base()`）

改沙箱之前先看这三条，它们全是 `exit 1` 级的：

```sh
grep -q 'PUSH_URL=http://stub.push/send' "$dir/pdd.sh"   # 没换掉 → 37 例往真实 ServerChan 推 37 条
grep -q "^PAUSE_FILE=$dir/pause$"        "$dir/pdd.sh"   # 没换掉 → 读写真实兑换账本
grep -q 'SWIPE_COUNT=2 '                 "$dir/pdd.sh"   # sed 没锚上 → 按真实时长跑，一遍十几分钟
```

第一条 sed 的锚点很脆（靠 `SWIPE_DUR=300 SWIPE_COUNT=20 SWIPE_WAIT=1` 这一串字面匹配）。
10-18 把 `SWIPE_*` 改成比例后那串一度变了，锚点差点断掉——断了的后果是 37 条真推送和
真实账本被改。所以自检不是洁癖，是门禁。**动了配置区那一片文字，先确认锚点还在。**

## 负对照

`scripts/negative-control.sh` 把源码里的一条判据改成恒假，然后只跑那一条用例：

```sh
sed -i 's#text_present bag; then#false; then#' "$NEG/in/pdd.sh"
```

改完立刻 `grep -q 'false; then'` 确认改上了（改不上就 `NEG_PATCH_FAILED` 退出，
否则"没挂"会被误读成"测试没用"）。用例挂了就证明它真的在钉那段代码。

另一路负对照是**旧字节对照**：10-18 拿 10-18 11:34 那版还是像素的 `pdd.sh`（md5 `91c857e9`）
在 1440x2560 上跑，结果恰好挂 2 条坐标/滑动的钉、OCR 命中那条照绿——
这既证明了新测试有牙，也证明了哪些东西本来就跟分辨率无关。
