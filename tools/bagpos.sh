#!/usr/bin/env bash
# 离线比对：同一活动页的不同帧里，「抽福袋」这类字都出现在哪些坐标
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
pat='福|袋|抽|奖|点亮|天内|必得'
for f in "$@"; do
  echo "== $(basename "$f")"
  bash "$HERE/tsvdump.sh" "$f" 2>/dev/null | grep -E "$pat"
done
