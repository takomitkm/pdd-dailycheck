#!/usr/bin/env bash
# 部署 sandbox 全绿的 pdd.sh 到 debian Desktop：先备份，再装，再验。
# 用法：bash deploy.sh <远端上的待部署文件路径>   （默认 /tmp/pdd-deploy.sh）
set -e
REMOTE=${1:-/tmp/pdd-deploy.sh}
D=/home/user/Desktop
TS=$(date +%m%d-%H%M)

[ -s "$REMOTE" ] || { echo "待部署文件不存在或为空：$REMOTE"; exit 1; }
tr -d '\015' <"$REMOTE" >"$REMOTE.lf" && mv "$REMOTE.lf" "$REMOTE"
bash -n "$REMOTE" || { echo "语法不过，不部署"; exit 1; }

if [ -f "$D/pdd.sh" ]; then
  cp -f "$D/pdd.sh" "$D/pdd.sh.bak-$TS"
  echo "旧版已备份 -> $D/pdd.sh.bak-$TS  md5=$(md5sum <"$D/pdd.sh.bak-$TS" | cut -c1-8)"
fi
install -m 700 "$REMOTE" "$D/pdd.sh"
echo "新版 md5=$(md5sum <"$D/pdd.sh" | cut -c1-8)  行数=$(wc -l <"$D/pdd.sh")  权限=$(stat -c '%a %U:%G' "$D/pdd.sh")"

# 暂停天数文件：不存在就建一个 0，让行为确定（0 = 正常跑）
if [ -f "$D/pdd-pause" ]; then
  echo "暂停文件已存在，内容=$(head -1 "$D/pdd-pause")，不动它"
else
  printf '0\n' >"$D/pdd-pause"
  chmod 600 "$D/pdd-pause"
  echo "已创建 $D/pdd-pause = 0（0 表示正常跑）"
fi

systemctl --user list-timers --all 2>/dev/null | grep -E 'pdd|NEXT' | head -3
echo "--- 本地语法复查 ---"
bash -n "$D/pdd.sh" && echo OK
