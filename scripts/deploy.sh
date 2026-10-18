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

# 端点外置之后，"没配推送"是一个会静默通过的状态：当场说清楚，别等明早 10:00 才发现一条都没推。
if [ -r "$D/pdd-push.url" ]; then
  echo "推送端点：$D/pdd-push.url 可读，第一行长度 $(head -1 "$D/pdd-push.url" | tr -d ' \t\r\n' | wc -c)（值不打印）"
else
  echo "推送端点：读不到 $D/pdd-push.url —— 流程照跑，但一条都不会推。"
  echo '  要推：主机上 umask 077 后把端点写成这个文件的第一行'
fi

systemctl --user list-timers --all 2>/dev/null | grep -E 'pdd|NEXT' | head -3
echo "--- 本地语法复查 ---"
bash -n "$D/pdd.sh" && echo OK
