# -*- coding: utf-8 -*-
"""原比例版构图预检：算出竖屏/横屏两种素材下各文字元素的实际像素位置。

关注: 文字是否压到右侧黑边、是否压到平台水印、是否互相重叠。
"""
import json

CANVAS = {
    "portrait_1440x1800": (1440, 1800, {
        "black_right": 168,          # 右侧 160px 纯黑 + 8px 余量
        "watermark_bottom": 24,      # 底部无平台UI，仅留 24px 呼吸
        "safe_top": 96,              # 顶部平台状态栏
    }),
    "landscape_1280x960": (1280, 960, {
        "black_right": 0,
        "watermark_bottom": 24,
        "safe_top": 96,
    }),
}


def check(name, W, H, lim, plan):
    print("\n===== %s  %dx%d =====" % (name, W, H))
    errs = []
    # 分段小标题：左侧起点 54px
    for it in plan.get("segments", []):
        size = it.get("size", 56)
        cy = int(H * it.get("cy", 0.13))
        est_w = 54 + int(len(it["txt"]) * size * 1.05) + 68
        print("  segment %-12s cy=%.3f y=%4d est_right=%4d" %
              (it["txt"][:12], it.get("cy", 0.13), cy, est_w))
        if est_w > W - lim["black_right"]:
            errs.append("segment '%s' 压到右黑边 (est_right=%d)" % (it["txt"], est_w))
        if cy - 40 < lim["safe_top"]:
            errs.append("segment '%s' 压到顶部状态栏" % it["txt"])

    for it in plan.get("pops", []):
        size = it.get("size", 90)
        cy = int(H * it.get("cy", 0.42))
        est_w = int(len(it["txt"]) * size * 1.05)
        cx = int(W * it.get("cx", 0.5))
        left, right = cx - est_w // 2, cx + est_w // 2
        print("  pop     %-12s cy=%.3f y=%4d x=[%4d,%4d] size=%d" %
              (it["txt"][:12], it.get("cy", 0.42), cy, left, right, size))
        if right > W - lim["black_right"]:
            errs.append("pop '%s' 压到右黑边 (right=%d)" % (it["txt"], right))
        if left < 0:
            errs.append("pop '%s' 压到左边界" % it["txt"])

    for it in plan.get("subs", []):
        size = it.get("size", 46)
        est_w = int(len(it["txt"]) * size * 1.06) + 90
        y = H - int(H * it.get("cy_off", 0.075))
        print("  sub     %-16s est_tray_w=%4d  y=%4d  tray_bottom=%4d" %
              (it["txt"][:16], est_w, y, y + 44))
        if est_w > W - lim["black_right"]:
            errs.append("sub '%s' 托盘压到右黑边 (%d)" % (it["txt"], est_w))
        if y + 44 > H - lim["watermark_bottom"]:
            errs.append("sub '%s' 托盘超出底部 (bottom=%d)" % (it["txt"], y + 44))

    en = plan.get("end")
    if en:
        print("  end     t=%.1f l1=%s" % (en["t"], en["l1"]))
    print("  -> %s" % ("全部通过" if not errs else "问题:\n     - " + "\n     - ".join(errs)))
    return errs


if __name__ == "__main__":
    import sys
    W, H, lim = CANVAS["portrait_1440x1800"]
    allerr = []
    for p in sys.argv[1:]:
        plan = json.load(open(p, encoding="utf-8"))
        allerr += check("portrait " + p.split("\\")[-1], W, H, lim, plan)
    print("\nPRE_OK" if not allerr else "\nPRE_FAIL %d" % len(allerr))
