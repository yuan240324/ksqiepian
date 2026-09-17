# -*- coding: utf-8 -*-
"""逐区域扫描：找素材里纯黑矩形块的真实边界。"""
import av
import numpy as np

def scan(src, ts=24.0):
    c = av.open(src)
    v = c.streams.video[0]
    for fr in c.decode(v):
        if fr.pts is None:
            continue
        t = float(fr.pts * fr.time_base)
        if t < ts:
            continue
        a = np.asarray(fr.to_image().convert("L")).astype(np.float32)
        H, W = a.shape
        dark = a < 12
        print("== %s %dx%d t=%.1f" % (src.split("\\")[-1], W, H, t))
        # 按 100 行分带，找每带里连续暗列
        for y0 in range(0, H, 150):
            band = dark[y0:y0+150]
            colfrac = band.mean(axis=0)
            segs = []
            i = 0
            while i < W:
                if colfrac[i] > 0.85:
                    j = i
                    while j < W and colfrac[j] > 0.85:
                        j += 1
                    if j - i >= 20:
                        segs.append((i, j))
                    i = j
                else:
                    i += 1
            if segs:
                print("   y%4d-%4d 暗列段: %s" % (y0, y0+149, segs))
        c.close()
        return

scan(r"G:\trea\切片\clips\raw_0913_0130.mp4")
