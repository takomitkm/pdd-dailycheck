#!/usr/bin/env bash
# 离线标定 pend：把今天的福袋页截图改名成 replay 认得的证据名，再拿新配置重打分。
# 不碰手机：replay 只读文件。
set -e
SRC=/home/user/Desktop/pdd-runs/2026-10-11/100316
CAL=/tmp/pendcal
rm -rf "$CAL"; mkdir -p "$CAL"
i=1
for p in "$SRC"/*count-prove-bag.png; do
  printf -v stamp '%06d' $((120000 + i))
  cp -f "$p" "$CAL/${stamp}-pend-${i}.png"
  i=$((i + 1))
done
cp -f "$SRC/run.log" "$CAL/run.log" 2>/dev/null || true
ls -1 "$CAL"
echo "=== replay（整页 psm6 + band/胶囊档都走一遍）==="
bash /tmp/pdd-pend.sh replay "$CAL" --ocr --size 720x1280 2>&1 | tail -30
