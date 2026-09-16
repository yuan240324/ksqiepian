# -*- coding: utf-8 -*-
"""Remove stale clips from a previous selection round.

A clip's name encodes its start time (clip_NN_HHMMSS.mp4).  The current plan is
the source of truth: any *.mp4 whose name is not in the plan is a leftover from
an earlier pick and is deleted (plus its thumbnail / preview leftovers).
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_clips import OUTDIR, SRC, load_analysis, pick_windows, fmt  # noqa: E402


def main():
    report = load_analysis()
    windows = pick_windows(report)
    keep = set()
    for i, (s, e, sc) in enumerate(windows, 1):
        keep.add("clip_%02d_%s.mp4" % (i, fmt(s).replace(":", "")))

    removed = 0
    for name in sorted(os.listdir(OUTDIR)):
        if not re.match(r"^clip_\d{2}_\d{6}\.mp4$", name):
            continue
        if name in keep:
            continue
        p = os.path.join(OUTDIR, name)
        os.remove(p)
        print("  删除陈旧切片 %s" % name)
        removed += 1

    print("保留 %d 个，删除 %d 个" % (len(keep), removed))
    print("CLEAN_DONE")


if __name__ == "__main__":
    main()
