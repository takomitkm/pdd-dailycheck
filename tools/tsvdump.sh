#!/usr/bin/env bash
# 离线看某张整页帧里所有带字的行及其中心坐标（点空间按 720x1280 换算）
set -u
f=$1
tesseract "$f" stdout -l chi_sim+eng --psm 11 tsv 2>/dev/null | awk -F'\t' '
  NR>1 && $11>20 && $12!="" {
    cx=($7+$9/2); cy=($8+$10/2);
    printf "%4d %4d  conf=%-3s %s\n", cx, cy, $11, $12
  }'
