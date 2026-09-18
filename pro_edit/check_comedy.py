# -*- coding: utf-8 -*-
"""原比例版构图预检（增强版）：竖屏/横屏 + 喜剧元素（抖字/盖章/圈重点/箭头）。

相比 check_native.py，这个脚本按素材尺寸自动选画布，并把新增的
jitters / stamps / circles / arrows 一并纳入越界检查。
"""
import json
import sys

CANVAS = {
    "portrait_1440x1800": (1440, 1800, {
        "black_right": 168,
        "watermark_bottom": 24,
        "safe_top": 96,
    }),
    "landscape_1280x960": (1280, 960, {
        "black_right": 0,
        "watermark_bottom": 24,
        "safe_top": 96,
    }),
}

# plan 文件名 -> 画布键（plan 名字里没有 0913/0713/0129 这类素材标签，
# 所以必须按 plan 名显式映射，否则会被误判成横屏）
PLAN_CANVAS = {
    "plan_com_variety": "portrait_1440x1800",
    "plan_n_variety": "portrait_1440x1800",
    "plan_variety": "portrait_1440x1800",
    "plan_com_commentary": "landscape_1280x960",
    "plan_n_commentary": "landscape_1280x960",
    "plan_commentary": "landscape_1280x960",
    "plan_com_rustic": "landscape_1280x960",
    "plan_n_rustic": "landscape_1280x960",
    "plan_rustic": "landscape_1280x960",
}


def check(name, W, H, lim, plan):
    print("\n===== %s  %dx%d =====" % (name, W, H))
    errs = []

    for it in plan.get("segments", []):
        size = it.get("size", 56)
        cy = int(H * it.get("cy", 0.13))
        est_w = 54 + int(len(it["txt"]) * size * 1.05) + 68
        print("  segment %-14s cy=%.3f y=%4d est_right=%4d" %
              (it["txt"][:14], it.get("cy", 0.13), cy, est_w))
        if est_w > W - lim["black_right"]:
            errs.append("segment '%s' 压到右黑边 (est_right=%d)" % (it["txt"], est_w))
        if cy - 40 < lim["safe_top"]:
            errs.append("segment '%s' 压到顶部状态栏" % it["txt"])

    for key in ("pops", "jitters"):
        for it in plan.get(key, []):
            size = it.get("size", 90)
            cy = int(H * it.get("cy", 0.42))
            amp = it.get("amp", 0.0)
            est_w = int(len(it["txt"]) * size * 1.05) + int(amp * 2)
            cx = int(W * it.get("cx", 0.5))
            left, right = cx - est_w // 2, cx + est_w // 2
            print("  %-7s %-14s cy=%.3f y=%4d x=[%4d,%4d] size=%d" %
                  (key, it["txt"][:14], it.get("cy", 0.42), cy, left, right, size))
            if right > W - lim["black_right"]:
                errs.append("%s '%s' 压到右黑边 (right=%d)" % (key, it["txt"], right))
            if left < 0:
                errs.append("%s '%s' 压到左边界 (left=%d)" % (key, it["txt"], left))
            if cy - size // 2 < lim["safe_top"]:
                errs.append("%s '%s' 压到顶部状态栏 (top=%d)" %
                            (key, it["txt"], cy - size // 2))

    for it in plan.get("stamps", []):
        size = it.get("size", 76)
        x, y = int(W * it.get("x", 0.5)), int(H * it.get("y", 0.6))
        est_w = int(len(it["txt"]) * size * 1.05) + 40
        print("  stamp   %-14s x=%4d y=%4d est_w=%4d" % (it["txt"][:14], x, y, est_w))
        if x + est_w // 2 > W - lim["black_right"]:
            errs.append("stamp '%s' 压到右黑边" % it["txt"])
        if x - est_w // 2 < 0:
            errs.append("stamp '%s' 压到左边界" % it["txt"])
        if y + size // 2 > H - lim["watermark_bottom"]:
            errs.append("stamp '%s' 压到底部 (bottom=%d)" % (it["txt"], y + size // 2))

    for it in plan.get("circles", []):
        r = it.get("r", 130)
        x, y = int(W * it.get("x", 0.5)), int(H * it.get("y", 0.58))
        print("  circle  x=%4d y=%4d r=%d -> [%4d,%4d]x[%4d,%4d]" %
              (x, y, r, x - r, x + r, y - int(r * 0.92), y + int(r * 0.92)))
        if x + r > W - lim["black_right"]:
            errs.append("circle 压到右黑边 (right=%d)" % (x + r))
        if x - r < 0:
            errs.append("circle 压到左边界")
        if y - int(r * 0.92) < lim["safe_top"]:
            errs.append("circle 压到顶部状态栏")
        if y + int(r * 0.92) > H - lim["watermark_bottom"]:
            errs.append("circle 压到底部")

    for it in plan.get("arrows", []):
        size = it.get("size", 100)
        x, y = int(W * it.get("x", 0.3)), int(H * it.get("y", 0.44))
        R = int(size * 1.2)
        print("  arrow   x=%4d y=%4d size=%d ang=%s" % (x, y, size, it.get("ang")))
        if x + R > W - lim["black_right"]:
            errs.append("arrow 压到右黑边")
        if x - R < 0:
            errs.append("arrow 压到左边界")
        if y - R < lim["safe_top"]:
            errs.append("arrow 压到顶部状态栏")
        if y + R > H - lim["watermark_bottom"]:
            errs.append("arrow 压到底部")

    for it in plan.get("subs", []):
        size = it.get("size", 46)
        est_w = int(len(it["txt"]) * size * 1.06) + 90
        y = H - int(H * it.get("cy_off", 0.075))
        print("  sub     %-18s est_tray_w=%4d  y=%4d  tray_bottom=%4d" %
              (it["txt"][:18], est_w, y, y + 44))
        if est_w > W - lim["black_right"]:
            errs.append("sub '%s' 托盘压到右黑边 (%d)" % (it["txt"], est_w))
        if y + 44 > H - lim["watermark_bottom"]:
            errs.append("sub '%s' 托盘超出底部 (bottom=%d)" % (it["txt"], y + 44))

    for it in plan.get("titles", []):
        size = it.get("size", 84)
        cy = int(H * it.get("cy", 0.215))
        est_w = int(len(it["txt"]) * size * 1.05)
        print("  title   %-16s cy=%.3f y=%4d est_w=%4d" %
              (it["txt"][:16], it.get("cy", 0.215), cy, est_w))
        if est_w > W - lim["black_right"]:
            errs.append("title '%s' 压到右黑边 (%d)" % (it["txt"], est_w))
        if cy - size // 2 < lim["safe_top"]:
            errs.append("title '%s' 压到顶部状态栏" % it["txt"])

    en = plan.get("end")
    if en:
        print("  end     t=%.1f l1=%s" % (en["t"], en["l1"]))
    print("  -> %s" % ("全部通过" if not errs else "问题:\n     - " + "\n     - ".join(errs)))
    return errs


if __name__ == "__main__":
    allerr = []
    for p in sys.argv[1:]:
        base = p.split("\\")[-1].split("/")[-1]
        # 1) 文件名里若直接带画布键（如 plan_com_variety_1440x1800.json）优先
        key = None
        for ck in CANVAS:
            if ck in base:
                key = ck
                break
        # 2) 否则按 plan 名映射
        if key is None:
            stem = base[:-5] if base.endswith(".json") else base
            for pre in ("plan_com_", "plan_n_", "plan_"):
                if stem.startswith(pre):
                    stem = stem[len(pre):]
                    break
            for tag, ck in (("variety", "portrait_1440x1800"),
                            ("commentary", "landscape_1280x960"),
                            ("rustic", "landscape_1280x960")):
                if tag in stem:
                    key = ck
                    break
        # 3) 最后按素材标签兜底
        if key is None:
            key = "portrait_1440x1800" if "0913" in base else "landscape_1280x960"
        W, H, lim = CANVAS[key]
        plan = json.load(open(p, encoding="utf-8"))
        allerr += check("%s [%s]" % (base, key), W, H, lim, plan)
    print("\nPRE_OK" if not allerr else "\nPRE_FAIL %d" % len(allerr))
