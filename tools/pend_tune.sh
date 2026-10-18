#!/usr/bin/env bash
# 离线调 pend 那一档的天数读数：只吃已经存下的证据截图，不碰手机、不装任何东西。
# 用法（debian 上）：bash /tmp/pend_tune.sh ~/Desktop/pdd-runs/2026-10-12/100100/*-pend-1.png ...
# 每个变体输出一行：变体名 | 抄到的整句 | 抠出的 N | 有没有命中现有那条 [0-9]{1,2}天后
set -u
LANG_OCR=${LANG_OCR:-chi_sim+eng}
REGION_pend=${REGION_pend:-0,0.08,1,0.45}
PILL_TH=${PILL_TH:-120}
PEND_LINE_RE='任务已完成|待兑换|天后可'
PEND_DAYS_RE='[0-9]{1,2}天后'
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT

mk_band() { # mk_band 源图 输出 [invert=1]
  BAND_PNG=$1 BAND_OUT=$2 BAND_SPEC=$REGION_pend BAND_INV=${3:-0} python3 - <<'PY'
from PIL import Image, ImageOps
import os
im = Image.open(os.environ["BAND_PNG"])
W, H = im.size
x1, y1, x2, y2 = [float(t) for t in os.environ["BAND_SPEC"].split(",")]
pad_x, pad_y = 0.02, 0.015
x0 = max(0, int((x1 - pad_x) * W)); x2 = min(W, int((x2 + pad_x) * W))
y0 = max(0, int((y1 - pad_y) * H)); y2 = min(H, int((y2 + pad_y) * H))
g = im.crop((x0, y0, x2, y2)).convert("L")
if os.environ["BAND_INV"] == "1":
    g = ImageOps.invert(g).point(lambda v: 0 if v < 120 else 255)
else:
    g = ImageOps.autocontrast(g, cutoff=1)
g.resize((g.width * 3, g.height * 3), Image.LANCZOS).save(os.environ["BAND_OUT"])
PY
}

mk_pill() { # mk_pill 源图 输出 放大档
  PILL_PNG=$1 PILL_OUT=$2 PILL_SPEC=$REGION_pend PILL_DIV=$3 PILL_TH=$PILL_TH python3 - <<'PY'
from PIL import Image, ImageOps
import os
im = Image.open(os.environ["PILL_PNG"]).convert("L")
W, H = im.size
x1, y1, x2, y2 = [float(t) for t in os.environ["PILL_SPEC"].split(",")]
x0 = max(0, int(x1 * W)); y0 = max(0, int(y1 * H))
xb = min(W, int(x2 * W)); yb = min(H, int(y2 * H))
g = im.crop((x0, y0, xb, yb))
k = int(os.environ["PILL_TH"]); d = int(os.environ["PILL_DIV"])
bw = ImageOps.invert(g).point(lambda v: 0 if v < k else 255)
if d > 1:
    bw = bw.resize((bw.width * d, bw.height * d), Image.LANCZOS)
bw.save(os.environ["PILL_OUT"])
PY
}

read_line() { # read_line 图片 psm 变体名
  local txt line days
  txt=$(tesseract "$1" stdout -l "$LANG_OCR" --psm "$2" 2>/dev/null | tr -d ' \t\r')
  line=$(printf '%s\n' "$txt" | grep -E -e "$PEND_LINE_RE" | head -2 | tr '\n' ' ')
  line=${line% }
  days=$(printf '%s' "$line" | grep -E -o "$PEND_DAYS_RE" | head -1 | tr -dc '0-9')
  printf '  %-14s N=%-3s %s\n' "$3" "${days:-无}" "${line:-（这三组词一个都没读到）}"
}

for png in "$@"; do
  echo "== $png"
  [ -s "$png" ] || { echo "  文件不在，跳过"; continue; }
  read_line "$png" 6  page6现状
  read_line "$png" 11 page11
  mk_band "$png" "$WORK/band.png" 0 \
    && { read_line "$WORK/band.png" 7 band7; read_line "$WORK/band.png" 6 band6; } \
    || echo "  band 裁不出来"
  mk_band "$png" "$WORK/bandinv.png" 1 \
    && { read_line "$WORK/bandinv.png" 7 bandinv7; read_line "$WORK/bandinv.png" 6 bandinv6; } \
    || echo "  bandinv 裁不出来"
  for d in 1 2 3; do
    mk_pill "$png" "$WORK/pill$d.png" "$d" && read_line "$WORK/pill$d.png" 7 "pill-x$d" \
      || echo "  pill-x$d 裁不出来"
  done
done
