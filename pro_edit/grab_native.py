# -*- coding: utf-8 -*-
"""抽原比例素材的帧，核对可视区（有没有水印/黑边）和文字安全区。"""
import sys, os
import av
from PIL import Image

def grab(src, outdir, ts):
    os.makedirs(outdir, exist_ok=True)
    want = sorted(ts)
    ci = 0
    c = av.open(src)
    v = c.streams.video[0]
    step = float(v.average_rate) / 2.0   # 每 0.5s 取一帧候选
    acc = 0.0
    for fr in c.decode(v):
        if fr.pts is None:
            continue
        t = float(fr.pts * fr.time_base)
        if ci >= len(want):
            break
        if t >= want[ci] - 1e-6:
            p = os.path.join(outdir, "t_%07.2f.jpg" % t)
            fr.to_image().convert("RGB").save(p, quality=92)
            print("  %s  %.2fs" % (os.path.basename(p), t))
            ci += 1
    c.close()

if __name__ == "__main__":
    src, outdir = sys.argv[1], sys.argv[2]
    ts = [float(x) for x in sys.argv[3:]]
    grab(src, outdir, ts)
