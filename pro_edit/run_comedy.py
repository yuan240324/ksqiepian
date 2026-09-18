# -*- coding: utf-8 -*-
"""喜剧版批量渲染：三条素材 -> 三条"真的好笑"的成片。

与 run_native.py 的区别：
  * 用的是 plan_com_*.json（新增抖字/盖章/圈重点/箭头 + 喜剧音效 + 喜剧底乐）
  * style 走 "comedy" 分支，BGM 为 bgm_comedy
"""
import os
import subprocess
import sys
import time

WS = os.path.dirname(os.path.abspath(__file__))
OUT = r"g:\trea\切片\快手三风格"

JOBS = [
    ("01_憋笑挑战_搞笑版.mp4", r"G:\trea\切片\clips\raw_0913_0130.mp4", "plan_com_variety.json"),
    ("02_嘴硬翻车_搞笑版.mp4", os.path.join(WS, "raw_0916_0713.mp4"), "plan_com_commentary.json"),
    ("03_开播事故_搞笑版.mp4", os.path.join(WS, "raw_0916_0129.mp4"), "plan_com_rustic.json"),
]

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    only = sys.argv[1:] if len(sys.argv) > 1 else None
    t_all = time.time()
    for name, src, plan in JOBS:
        if only and not any(o in name for o in only):
            continue
        if not os.path.exists(src):
            print("SKIP (no src) %s" % src)
            continue
        dst = os.path.join(OUT, name)
        print("\n=== %s ===\n  src=%s\n  plan=%s" % (name, src, plan))
        t0 = time.time()
        r = subprocess.run([sys.executable, os.path.join(WS, "render_native.py"),
                            src, dst, os.path.join(WS, plan)],
                           cwd=WS)
        if r.returncode != 0:
            print("FAILED %s (rc=%d)" % (name, r.returncode))
            continue
        mb = os.path.getsize(dst) / 1024.0 / 1024.0
        print("OK %s  %.1f MB  %.1fs" % (name, mb, time.time() - t0))
    print("\nALL_DONE %.1fs" % (time.time() - t_all))
