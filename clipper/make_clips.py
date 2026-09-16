# -*- coding: utf-8 -*-
"""Cut highlight clips out of the playback video (stream-copy, correct ts rebase).

Reads analysis.json to score candidate windows, then cuts each selected window
into its own MP4 using stream-copy (no re-encode).

Key correctness points:
  * seek on the VIDEO stream, to the keyframe at/before the target start
  * demux ALL streams together, dispatch on the ORIGINAL stream index
  * rebase every timestamp to the first kept video packet -> clean 0-based clip
  * drop audio packets before the rebase origin so A/V stay aligned

Usage:
    python make_clips.py              # auto-pick highlights
    python make_clips.py --list       # only print the plan, do not cut
"""
import av
import json
import os
import sys
import time

import numpy as np
from PIL import Image

SRC = r"G:\trea\切片\快手直播回放_YyXx-828924_20260916.mp4"
ANALYSIS = r"C:\Users\weido\.trae-cn\work\6aaa8ef0b3e31b7643bdb0d0\analysis.json"
OUTDIR = r"G:\trea\切片\clips"

# ── slicing parameters ──────────────────────────────────────────────
CLIP_LEN = 45.0        # target clip length in seconds
PRE_ROLL = 6.0         # seconds of lead-in before a detected event
MIN_GAP = 90.0         # minimum distance between two clip start points
MAX_CLIPS = 12         # cap on number of clips
TOP_N_EVENTS = 60      # how many candidate events to consider
MAX_PER_ZONE = 1       # at most this many clips per ZONE_SEC block
ZONE_SEC = 600.0       # 10-minute zone used to spread clips across the stream
DUP_FRAME_DIFF = 0.04  # frame-signature diff below this = visually same screen


def load_analysis():
    with open(ANALYSIS, encoding="utf-8") as f:
        return json.load(f)


def _frame_signature(src, sec):
    """Decode one frame near `sec` and return a tiny grayscale signature.

    Used to reject windows that land on the same static screen (shop /
    inventory / lobby) even when they sit in different zones.
    """
    c = av.open(src)
    vst = next(s for s in c.streams if s.type == "video")
    dur = float(vst.duration * vst.time_base) if vst.duration else 0.0
    sec = min(max(0.0, sec), max(0.0, dur - 0.5))
    c.seek(int(sec / vst.time_base), stream=vst)
    sig = None
    for fr in c.decode(vst):
        nd = fr.to_ndarray(format="gray")
        h, w = nd.shape
        sig = Image.fromarray(nd[::max(1, h // 36), ::max(1, w // 48)])
        break
    c.close()
    if sig is None:
        return np.zeros((36, 48), dtype=np.float32)
    return np.asarray(sig.resize((48, 36)), dtype=np.float32) / 255.0


def pick_windows(report, src=SRC):
    """Score events and turn them into non-overlapping clip windows.

    Strategy: keep at most the best event per ZONE_SEC block, and reject any
    candidate whose frame signature is too close to an already-picked window.
    A single long static screen (shop / inventory / settings) can emit several
    high-diff "scene changes" or loud runs minutes apart that all look
    identical; zoning + signature dedup forces the selection to cover visually
    distinct moments across the whole stream instead.
    """
    dur = report["duration_sec"]
    scenes = report.get("scene_changes", [])
    loud = set(report.get("loud_seconds", []))

    # ── build candidate events ──────────────────────────────────────
    events = []

    # (a) scene changes, boosted by nearby loud seconds
    for sc in scenes:
        s = sc["sec"]
        near_loud = sum(1 for k in range(int(s) - 2, int(s) + 3) if k in loud)
        events.append((sc["diff"] * 1.0 + near_loud * 0.25, s))

    # (b) sustained loud runs (>=3s) - the strongest signal of a real peak
    loud_sorted = sorted(loud)
    run = []
    runs = []
    for s in loud_sorted:
        if run and s - run[-1] <= 1:
            run.append(s)
        else:
            if len(run) >= 3:
                runs.append(run)
            run = [s]
    if len(run) >= 3:
        runs.append(run)
    for r in runs:
        events.append((0.6 + 0.05 * len(r), r[0] + len(r) / 2.0))

    events.sort(key=lambda x: -x[0])

    # ── pick best event per zone, avoiding same-looking screens ────
    windows = []
    used_zones = set()
    sigs = []

    def try_pick(score, ev, check_zone=True):
        start = max(0.0, ev - PRE_ROLL)
        end = min(dur, start + CLIP_LEN)
        start = max(0.0, end - CLIP_LEN)
        if any(abs(start - w[0]) < MIN_GAP for w in windows):
            return False
        if check_zone:
            zone = int(start // ZONE_SEC)
            if zone in used_zones and MAX_PER_ZONE <= 1:
                return False
        sg = _frame_signature(src, start + CLIP_LEN * 0.5)
        if sigs and min(float(np.abs(sg - s).mean()) for s in sigs) < DUP_FRAME_DIFF:
            return False
        windows.append((start, end, round(score, 3)))
        if check_zone:
            used_zones.add(zone)
        sigs.append(sg)
        return True

    for score, ev in events:
        if len(windows) >= MAX_CLIPS:
            break
        try_pick(score, ev)

    # ── backfill if zoning left us short (zone cap ignored here) ────
    if len(windows) < MAX_CLIPS:
        for score, ev in events:
            if len(windows) >= MAX_CLIPS:
                break
            try_pick(score, ev, check_zone=False)

    windows.sort(key=lambda x: x[0])
    return windows


def cut(src, start, end, dst):
    """Stream-copy [start, end) into dst with timestamps rebased to zero.

    Stream-copy keeps B-frames, so packet order follows DTS, not PTS.  We
    therefore key every decision off DTS (monotonic) and only shift, never
    reorder.  The first packet the muxer sees must be a video keyframe, so the
    origin is chosen as the keyframe at/before `start`.
    """
    cin = av.open(src)
    vst = next(s for s in cin.streams if s.type == "video")
    ast = next((s for s in cin.streams if s.type == "audio"), None)
    vtb = vst.time_base
    atb = ast.time_base if ast else None

    # Seek on the video stream: lands on the keyframe at/before `start`.
    cin.seek(int(start / vtb), stream=vst)

    cout = av.open(dst, "w", format="mp4")
    vout = cout.add_stream_from_template(vst)
    aout = cout.add_stream_from_template(ast) if ast else None
    if aout:
        try:
            aout.codec_context.options = {"aac_adtstoasc": "1"}
        except Exception:
            pass

    NOPTS = -(1 << 63)
    vshift = None      # set from the first video packet's DTS
    ashift = None
    cnt = {"v": 0, "a": 0}
    started = False

    for pkt in cin.demux():          # all streams, dispatched by original index
        if pkt.size == 0 or pkt.dts is None:
            continue
        if pkt.stream.index == vst.index:
            if not started:
                # First video packet after the seek == the origin keyframe.
                vshift = -pkt.dts
                if atb is not None:
                    ashift = -int(round(float(-vshift * vtb) / float(atb)))
                started = True
            pkt.pts = pkt.pts + vshift if pkt.pts is not None else NOPTS
            pkt.dts = pkt.dts + vshift
            if pkt.dts != NOPTS and pkt.dts * vtb > end - start + 1.0:
                break             # past the window -> we are done
            pkt.stream = vout
            cnt["v"] += 1
        elif ast is not None and pkt.stream.index == ast.index:
            if not started:
                continue          # wait for the video origin to be known
            pkt.pts = pkt.pts + ashift if pkt.pts is not None else NOPTS
            pkt.dts = pkt.dts + ashift
            if pkt.dts != NOPTS and pkt.dts * atb > end - start + 0.5:
                continue
            pkt.stream = aout
            cnt["a"] += 1
        else:
            continue
        cout.mux(pkt)

    cout.close()
    cin.close()

    # Normalise start_time so every player shows the clip beginning at 0.
    # (The muxer stores the first packet's PTS; with B-frames that is slightly
    # larger than the first DTS, leaving a small dead offset.)
    _normalize_start(dst)
    return cnt


def _normalize_start(path):
    """Shift all timestamps so the container start_time becomes 0."""
    c = av.open(path)
    st = c.streams[0].start_time or 0
    tb = c.streams[0].time_base
    if st <= 0:
        c.close()
        return
    base_us = int(round(float(st * tb) * 1_000_000))
    try:
        c.close()
    except Exception:
        pass
    # Re-open and rewrite with the shift applied through a temp file.
    tmp = path + ".tmp.mp4"
    cin = av.open(path)
    cout = av.open(tmp, "w", format="mp4")
    outs = {}
    for s in cin.streams:
        outs[s.index] = cout.add_stream_from_template(s)
    NOPTS = -(1 << 63)
    for pkt in cin.demux():
        if pkt.size == 0:
            continue
        o = outs.get(pkt.stream.index)
        if o is None:
            continue
        shift = int(round(base_us / (float(pkt.stream.time_base) * 1_000_000)))
        if pkt.pts is not None and pkt.pts != NOPTS:
            pkt.pts -= shift
        if pkt.dts is not None and pkt.dts != NOPTS:
            pkt.dts -= shift
        pkt.stream = o
        cout.mux(pkt)
    cout.close()
    cin.close()
    os.replace(tmp, path)

def fmt(sec):
    sec = int(sec)
    return "%02d:%02d:%02d" % (sec // 3600, (sec % 3600) // 60, sec % 60)


def main():
    list_only = "--list" in sys.argv
    report = load_analysis()
    windows = pick_windows(report)

    print("=" * 72)
    print("源       : %s" % os.path.basename(SRC))
    print("时长     : %.2f min" % report["duration_min"])
    print("场景变化 : %d 处 / 高能量秒 %d 个"
          % (len(report["scene_changes"]), report["loud_count"]))
    print("计划切片 : %d 段 x %.0fs" % (len(windows), CLIP_LEN))
    print("=" * 72)
    for i, (s, e, sc) in enumerate(windows, 1):
        print("  [%02d] %s ~ %s  (%.0fs, score=%.3f)"
              % (i, fmt(s), fmt(e), e - s, sc))
    if list_only or not windows:
        print("\n(仅预览，未切割)")
        return

    os.makedirs(OUTDIR, exist_ok=True)
    t0 = time.time()
    ok = 0
    for i, (s, e, sc) in enumerate(windows, 1):
        name = "clip_%02d_%s.mp4" % (i, fmt(s).replace(":", ""))
        dst = os.path.join(OUTDIR, name)
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            if "--force" not in sys.argv:
                print("  [%02d] 已存在，跳过 %s" % (i, name), flush=True)
                ok += 1
                continue
        try:
            cnt = cut(SRC, s, e, dst)
            mb = os.path.getsize(dst) / 1048576.0
            print("  [%02d] %s  v=%d a=%d  %.1f MB"
                  % (i, name, cnt["v"], cnt["a"], mb), flush=True)
            ok += 1
        except Exception as ex:
            print("  [%02d] FAIL %r" % (i, ex), flush=True)

    print("")
    print("完成 %d/%d，用时 %.0fs" % (ok, len(windows), time.time() - t0))
    print("输出目录: %s" % OUTDIR)
    print("CLIP_DONE")


if __name__ == "__main__":
    main()
