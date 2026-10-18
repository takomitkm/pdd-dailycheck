#!/usr/bin/env bash
# 横幅窄条的预处理扫描：找出哪一档能把「滑动浏览当前页面10秒即可点亮」读出来
set -u
f=$1
python3 - "$f" <<'PY'
import sys
from PIL import Image, ImageOps, ImageStat
im = Image.open(sys.argv[1]).convert('RGB')
W, H = im.size
# 横幅那条粉底红字：按 1280 高算约 y=428..488
box = (int(0.02*W), 428, int(0.98*W), 488)
c = im.crop(box)
g = c.convert('L')
st = ImageStat.Stat(g)
print('crop', box, 'size', c.size, '灰度 mean=%.1f stddev=%.1f min=%d max=%d' % (st.mean[0], st.stddev[0], g.getextrema()[0], g.getextrema()[1]))
variants = {}
variants['raw1'] = c.convert('L')
for s in (2, 3, 4):
    variants['x%d' % s] = c.convert('L').resize((c.width*s, c.height*s), Image.LANCZOS)
a = ImageOps.autocontrast(c.convert('L'), cutoff=1)
for s in (2, 3):
    variants['ac_x%d' % s] = a.resize((a.width*s, a.height*s), Image.LANCZOS)
for th in (120, 170, 200, 225):
    t = c.convert('L').point(lambda p: 255 if p > th else 0)
    for s in (2, 3):
        variants['th%d_x%d' % (th, s)] = t.resize((t.width*s, t.height*s), Image.LANCZOS)
    ti = ImageOps.invert(t)
    variants['inv_th%d_x2' % th] = ti.resize((ti.width*2, ti.height*2), Image.LANCZOS)
for name, img in variants.items():
    img.save('/tmp/sw_%s.png' % name)
print(' '.join(variants.keys()))
PY
for v in $(ls /tmp/sw_*.png | sed 's#/tmp/sw_##; s#\.png##'); do
  for p in 7 11; do
    out=$(tesseract "/tmp/sw_$v.png" stdout -l chi_sim+eng --psm $p 2>/dev/null | tr -d ' \t\r')
    printf '%-14s psm%-3s %s\n' "$v" "$p" "$out"
  done
done
rm -f /tmp/sw_*.png
