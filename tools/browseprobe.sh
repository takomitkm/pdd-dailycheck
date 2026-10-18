#!/usr/bin/env bash
# 离线复现 text_present browse 的各通道读数：整页 psm11 / psm6 / band 档
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
f=$1
echo "--- psm11 tsv（只列带字的行）"
bash "$HERE/tsvdump.sh" "$f" | grep -E '浏|亮|秒|页|消费|券|精选'
echo "--- psm6 整页"
tesseract "$f" stdout -l chi_sim+eng --psm 6 2>/dev/null | tr -d ' \t' | grep -nE '浏览|即可点亮|秒|消费券'
echo "--- band 档（裁 REGION_browse=0,0.30,1,0.45 再放大 3x，psm7）"
python3 - "$f" <<'PY'
import sys
from PIL import Image, ImageOps
im = Image.open(sys.argv[1]).convert('RGB')
W, H = im.size
x1, y1, x2, y2 = 0, 0.30, 1, 0.45
px1, py1, px2, py2 = int(x1*W), int(y1*H), int(x2*W), int(y2*H)
pw, ph = px2-px1, py2-py1
pad_x, pad_y = int(pw*0.02), int(ph*0.015)
box = (max(0,px1-pad_x), max(0,py1-pad_y), min(W,px2+pad_x), min(H,py2+pad_y))
c = im.crop(box).convert('L')
c = ImageOps.autocontrast(c, cutoff=1)
c = c.resize((c.width*3, c.height*3), Image.LANCZOS)
c.save('/tmp/bandbr.png')
print('crop', box, '->', c.size)
PY
for p in 7 11; do
  echo "  psm $p: $(tesseract /tmp/bandbr.png stdout -l chi_sim+eng --psm $p 2>/dev/null | tr -d ' \t\r')"
done
