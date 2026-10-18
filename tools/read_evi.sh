#!/usr/bin/env bash
# 只读取证：把今天的证据 PNG 用 tesseract 读一遍，看卡在哪个画面。不碰手机。
D=${1:-/home/user/Desktop/pdd-runs/2026-10-11/100316}
echo "== 目录 $D 内容 =="
ls -1 "$D" | sed 's/^/  /'
echo
for p in "$D"/*.png; do
  [ -e "$p" ] || continue
  echo "---- $(basename "$p")"
  timeout 90 tesseract "$p" stdout -l chi_sim+eng --psm 6 2>/dev/null |
    grep -vE '^[[:space:]]*$' | head -28 | sed 's/^/   /'
done
