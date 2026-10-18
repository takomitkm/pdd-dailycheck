#!/usr/bin/env bash
# 在 band 档的真裁片（L + autocontrast + x3）上跑 psm 6/7/11 的 tsv，列出命中别名的那几行
set -u
f=$1
python3 - "$f" <<'PY'
import sys
from PIL import Image, ImageOps
im = Image.open(sys.argv[1]).convert('RGB')
W, H = im.size
pad_x, pad_y = 0.02, 0.015
x1, y1, x2, y2 = 0.0, 0.30, 1.0, 0.45
x0 = max(0, int((x1 - pad_x) * W)); yy0 = max(0, int((y1 - pad_y) * H))
xx2 = min(W, int((x2 + pad_x) * W)); yy2 = min(H, int((y2 + pad_y) * H))
c = im.crop((x0, yy0, xx2, yy2)).convert('L')
c = ImageOps.autocontrast(c, cutoff=1)
c.resize((c.width*3, c.height*3), Image.LANCZOS).save('/tmp/band6.png')
print('crop box', (x0, yy0, xx2, yy2), '-> x3', c.size, 'full', (W, H))
PY
for p in 7 6 11; do
  echo "--- psm $p（conf>40 且含别名字）"
  tesseract /tmp/band6.png stdout -l chi_sim+eng --psm $p tsv 2>/dev/null \
    | awk -F'\t' 'NR>1 && $11>40 && $12 ~ /浏|亮|秒|页|面/ {printf "  x=%-5s y=%-5s w=%-5s h=%-4s conf=%-6s %s\n", $7,$8,$9,$10,$11,$12}'
done
