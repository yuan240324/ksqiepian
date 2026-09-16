# -*- coding: utf-8 -*-
"""Quantify thumbnail diversity: report pairs of clips that look near-identical.

Downsample each thumbnail to a tiny grayscale grid and compare mean absolute
difference.  Two clips from the same static screen (e.g. the shop page) score
below the threshold; real gameplay moments score much higher.
"""
import glob
import os

import numpy as np
from PIL import Image

THUMBS = r"C:\Users\weido\.trae-cn\work\6aaa8ef0b3e31b7643bdb0d0\thumbs"
SIMILAR_BELOW = 0.08     # mean-abs-diff below this = suspiciously similar
DUPE_BELOW = 0.05        # below this = near-duplicate


def sig(p):
    im = Image.open(p).convert("L").resize((48, 36))
    a = np.asarray(im, dtype=np.float32) / 255.0
    return a


def main():
    files = sorted(glob.glob(os.path.join(THUMBS, "*.png")))
    sigs = {os.path.basename(f): sig(f) for f in files}
    names = sorted(sigs)
    print("共 %d 个缩略图，两两对比中 ..." % len(names))
    flags = {"ok": 0, "similar": 0, "dupe": 0}
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            d = float(np.abs(sigs[a] - sigs[b]).mean())
            if d < DUPE_BELOW:
                flags["dupe"] += 1
                print("  [近似重复] %s <-> %s  diff=%.4f" % (a, b, d))
            elif d < SIMILAR_BELOW:
                flags["similar"] += 1
                print("  [相似]    %s <-> %s  diff=%.4f" % (a, b, d))
            else:
                flags["ok"] += 1
    print("对比 %d 对: 正常 %d / 相似 %d / 近似重复 %d"
          % (sum(flags.values()), flags["ok"], flags["similar"], flags["dupe"]))
    print("DIVERSITY_DONE")


if __name__ == "__main__":
    main()
