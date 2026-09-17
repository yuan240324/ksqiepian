# -*- coding: utf-8 -*-
"""Build a labeled contact sheet from grabbed thumbs.
Usage: python sheet.py <dir> <out.jpg> [cols]
"""
import glob, math, os, re, sys
from PIL import Image, ImageDraw, ImageFont

d, out = sys.argv[1], sys.argv[2]
cols = int(sys.argv[3]) if len(sys.argv) > 3 else 6
files = sorted(glob.glob(os.path.join(d, "*.jpg")))
if not files:
    print("NO_THUMBS %s" % d)
    sys.exit(1)

tw = 250
rows = math.ceil(len(files) / cols)
label_h = 38
cell_w, cell_h = tw + 10, int(tw * 1.25) + label_h + 10
sheet = Image.new("RGB", (cols * cell_w + 10, rows * cell_h + 10), (24, 24, 30))
dr = ImageDraw.Draw(sheet)
fnt = ImageFont.truetype(r"C:\Windows\Fonts\msyhbd.ttc", 26)

for i, f in enumerate(files):
    r, c = divmod(i, cols)
    x0, y0 = 10 + c * cell_w, 10 + r * cell_h
    im = Image.open(f)
    w0, h0 = im.size
    im = im.resize((tw, max(1, int(tw * h0 / w0))))
    sheet.paste(im, (x0, y0))
    m = re.search(r"t_([\d.]+)\.jpg", os.path.basename(f))
    lab = ("t=%ss" % int(float(m.group(1)))) if m else os.path.basename(f)
    dr.text((x0 + 4, y0 + im.height + 6), lab, font=fnt, fill=(255, 220, 80))

sheet.save(out, quality=88)
print("SHEET_DONE %s  %dx%d  %d thumbs" % (out, sheet.width, sheet.height, len(files)))
