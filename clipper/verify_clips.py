# -*- coding: utf-8 -*-
"""Verify every produced clip: decode video + audio, check duration and A/V sync.

NOTE: PyAV's demuxer is single-pass — calling decode(video) drains the shared
packet queue, so a later decode(audio) on the SAME container returns nothing.
Each stream must therefore be decoded from its own av.open() handle.
"""
import av
import glob
import os
import numpy as np

OUTDIR = r"G:\trea\切片\clips"

files = sorted(glob.glob(os.path.join(OUTDIR, "*.mp4")))
print("found %d file(s) in %s\n" % (len(files), OUTDIR))

bad = 0
total = 0.0
for p in files:
    name = os.path.basename(p)
    size_mb = os.path.getsize(p) / 1048576.0
    try:
        # ── video pass ──────────────────────────────────────────────
        c = av.open(p)
        vst = next((s for s in c.streams if s.type == "video"), None)
        st_v = vst.start_time or 0
        nv = 0
        vf = vl = None
        for fr in c.decode(vst):
            if fr.pts is not None:
                t = float(fr.pts * vst.time_base)
                vf = t if vf is None else vf
                vl = t
            nv += 1
        c.close()

        # ── audio pass (own handle) ─────────────────────────────────
        c = av.open(p)
        ast = next((s for s in c.streams if s.type == "audio"), None)
        st_a = (ast.start_time or 0) if ast else 0
        na = 0
        af = al = None
        peak = 0.0
        if ast:
            for fr in c.decode(ast):
                if fr.pts is not None:
                    t = float(fr.pts * ast.time_base)
                    af = t if af is None else af
                    al = t
                if na < 200:
                    peak = max(peak, float(np.abs(fr.to_ndarray()).max()))
                na += 1
        c.close()

        vdur = (vl - vf) if vl is not None else 0.0
        adur = (al - af) if al is not None else 0.0
        drift = abs(vdur - adur) if ast else 0.0
        total += vdur
        flag = "OK "
        if nv == 0:
            flag = "NO-VIDEO"
        elif ast and na < 100:
            flag = "NO-AUDIO"
        elif ast and peak < 0.001:
            flag = "SILENT"
        elif st_v > 1000 or st_a > 1000:
            flag = "START-NZ"
        elif drift > 1.5:
            flag = "DRIFT"
        if flag != "OK ":
            bad += 1
        print("[%s] %-24s %6.1fMB v=%5d(%5.1fs) a=%5d(%5.1fs) pk=%.3f drift=%.2fs"
              % (flag, name, size_mb, nv, vdur, na, adur, peak, drift))
    except Exception as ex:
        bad += 1
        print("[FAIL] %-24s %r" % (name, ex))

print("\nfiles=%d  bad=%d  total=%.0fs (%.1f min)" % (len(files), bad, total, total / 60.0))
print("VERIFY_DONE")
