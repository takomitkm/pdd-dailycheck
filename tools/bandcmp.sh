#!/usr/bin/env bash
# 对同一帧试两种 band 裁片：现状 REGION_browse(0.30..0.45) vs 收紧到横幅那一条
set -u
f=$1
python3 - "$f" <<'PY'
import sys
from PIL import Image, ImageOps
im = Image.open(sys.argv[1]).convert('RGB')
W, H = im.size
def crop(y1, y2, tag, scale):
    px1, py1, px2, py2 = 0, int(y1*H), W, int(y2*H)
    pw, ph = px2-px1, py2-py1
    pad_x, pad_y = int(pw*0.02), int(ph*0.015)
    box = (max(0,px1-pad_x), max(0,py1-pad_y), min(W,px2+pad_x), min(H,py2+pad_y))
    c = im.crop(box).convert('L')
    c = ImageOps.autocontrast(c, cutoff=1)
    if scale != 1:
        c = c.resize((c.width*scale, c.height*scale), Image.LANCZOS)
    p = '/tmp/bc_%s_%d.png' % (tag, scale)
    c.save(p)
    return p, box, c.size
for tag, y1, y2 in (('wide', 0.30, 0.45), ('tight', 0.325, 0.400), ('mid', 0.315, 0.415)):
    for s in (1, 2, 3):
        p, box, sz = crop(y1, y2, tag, s)
        for psm in (6, 7, 11):
            out = __import__('subprocess').run(
                ['tesseract', p, 'stdout', '-l', 'chi_sim+eng', '--psm', str(psm)],
                capture_output=True, text=True).stdout.replace(' ', '').replace('\n', '|')
            print('%-6s x%d box=%s %-9s psm%-2s %s' % (tag, s, box, sz, psm, out[:90]))
PY
