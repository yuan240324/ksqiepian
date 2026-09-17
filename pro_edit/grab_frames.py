# -*- coding: utf-8 -*-
"""抽帧写 jpg，用于人工核对成片。

用法: python grab_frames.py <video> <outdir> <t1> <t2> ...
"""
import os
import sys

import av
from fractions import Fraction
from PIL import Image


def main():
    src, outdir = sys.argv[1], sys.argv[2]
    ts = [float(x) for x in sys.argv[3:]]
    os.makedirs(outdir, exist_ok=True)
    want = sorted(ts)
    got = set()
    c = av.open(src)
    st = c.streams.video[0]
    for fr in c.decode(st):
        t = float(fr.pts * fr.time_base)
        for w in want:
            if w not in got and t >= w:
                got.add(w)
                img = fr.to_image().convert("RGB")
                p = os.path.join(outdir, "t_%07.2f.jpg" % w)
                img.save(p, quality=88)
                print("saved", p)
        if len(got) == len(want):
            break
    c.close()


if __name__ == "__main__":
    main()
