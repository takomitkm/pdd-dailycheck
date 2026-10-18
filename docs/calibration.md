# 标定：坐标怎么写、怎么改、怎么验

## 什么时候要重新标定

| 情况 | 要动的东西 |
| --- | --- |
| PDD 改了文案（字变了，位置没变） | 只改 `ALIAS_<key>`，加一段还能对满 `MIN_OVERLAP` 个字的旧写法 |
| PDD 改了版式（字还在，位置跳了） | 改 `REGION_<key>` / `PILL_<key>` 的比例，必要时改 `COORD_<key>` |
| 换手机、或改过 `wm size` | **什么都不用改**。区域和坐标全是比例 |
| 某个控件整页 OCR 认不到 | 加一档 band/pill，见 [locate-channels.md](locate-channels.md) |

## 一、现场抓一份界面

```sh
~/Desktop/pdd.sh probe
```

它会 dump 当前界面的 uiautomator XML、存一张截图，然后打印：

1. `点空间 WxH` —— 当前点击坐标系的尺寸，同时也是截图尺寸（override 生效后两者一致）
2. 所有带文字的节点，格式 `x  y  可点  文字`
3. 每个 key 的解析结果，后面紧跟一行**已经折成 0..1 比例**的 `COORD_<key>=fx,fy`

第 3 项就是可以直接抄回配置区的行。比例是 5 位小数，抄的时候不要截断。

## 二、单个目标复验（不点）

```sh
~/Desktop/pdd.sh find light
~/Desktop/pdd.sh find bag
```

输出一行 `来源<TAB>x y<TAB>标签<TAB>分数`，来源是 `xml` / `ocr` / `band` / `pill` / `coord` 之一。
`coord` 那档分数恒为 0，看到它就是兜底开火了，不是认到了字。

## 三、真要手点

```sh
~/Desktop/pdd.sh point 598 285
```

`point` 收的是**像素**，不是比例——它是给人手动验证用的，不参与配置。

## 四、改完之后：先离线筛，再上真机

改文案、改区域，先拿存下的证据帧重放，比每次烧十分钟真机便宜得多：

```sh
~/Desktop/pdd.sh replay ~/Desktop/pdd-runs/2026-10-18/105503 --ocr
~/Desktop/pdd.sh replay <证据目录> --label bag 抽福袋 去抢购
~/Desktop/pdd.sh replay <证据目录> --scan          # 每帧试所有 key，慢，用来翻资产
~/Desktop/pdd.sh replay --all                      # 扫全部保留的证据
```

replay 有两处抄不动线上，读结果时必须记住：

1. 线上有 `FIND_RETRY` 重试，replay 只跑一轮。"这一帧认不到"不等于"线上 12 轮也认不到"。
2. TSV 中间结果没有留在证据里，`--ocr` 是拿存下的 PNG **重跑一次** tesseract，
   不是重放当初那次识别的输出。

## 五、启动即校验

[pdd.sh:266](../pdd.sh#L266) 逐个检查 `COORD_subsidy COORD_bag COORD_light COORD_dialog
SWIPE_X SWIPE_Y1 SWIPE_Y2 BROWSE_X TOP_SWIPE_Y1 TOP_SWIPE_Y2`：必须是 1 或 2 段
`0..1` 之间的数。越界、写成像素、写成三段，当场：

```
COORD_light 要写成 0..1 的屏幕比例，现在是「598,285」
```

并 `exit 78`。这一条是故意做硬的：像素值当比例用会乘出屏幕外，点在 `(0,0)` 上还不报错。

`REGION_*` 和 `PILL_*` 不在这里验，由 `band_pass` / `pill_pass` 自己处理（它们本来就是比例，
历史上就没出过这类错）。

## 六、为什么是 5 位小数

`frac_x` 用 `f*W+0.5` 取整。3 位小数时 `0.831 × 1440 + 0.5 = 1197`，而基准像素 598 翻倍应是
1196，出现 1px 系统偏差。5 位（`0.83056`）在 720x1280 和 1440x2560 两块屏上折回像素完全一致，
这也是沙箱双分辨率验收能量出"逐位相同"的前提。

对 720 宽的屏，`.125` / `.46875` / `.69922` 这类精确值优先写全；不能整除的取 5 位四舍五入。

## 七、换分辨率后的实测口径

10-18 那次去像素化的验收方式，改坐标后可以照抄：

- 沙箱 `SBX_SIZE=1440x2560` 跑全矩阵，断言里带几何的三条必须跟着折算过去
  （`light 用 coord 点 1196 570`、`下滑 x=1080 2400->1400`、`bag 用 ocr 点 870 1048`）
- 负对照：把旧像素版在同一块屏上跑，前两条要挂、第三条（OCR 命中）不该挂——
  挂了说明测试没牙，绿了说明改动真的在钉代码
- 真机只读校验：`find light` / `find subsidy` / `find dialog` 三枪在 720x1280 上
  应与旧像素版逐位相同（598 285 / 90 600 / 617 222）
