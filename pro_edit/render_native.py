# -*- coding: utf-8 -*-
"""原比例成片渲染器：保持素材原始分辨率/比例，只加标题 + 分段小标题 + 花字。

与 render_pro.py 的区别：
  * **不裁切、不补边**：输出尺寸 = 素材尺寸（9/13 -> 1440x1800，9/16 -> 1280x960）
  * 文字量中等：1 个片头标题 + 2~3 个分段小标题 + 若干花字
  * 保留音效 + BGM + 原声混音

用法:
    python render_native.py <raw.mp4> <out.mp4> <plan.json>

plan.json 与 render_pro.py 同构，额外支持:
    "segments": [                      # 分段小标题（中等文字量的核心）
      {"txt":"第一波团战","t":6.0,"dur":2.6}
    ]
所有 cy 均为画面比例（0~1），cx 同理（0.5 = 居中）。
"""
import json
import os
import sys
from fractions import Fraction

import av
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import tex
import vfx
import audiomix

FPS = 30


def wrap2(txt, size, maxw, sw=0, fnt_path=None):
    """按宽度自动折两行（沿用 render_pro 的语义）。"""
    fnt_path = fnt_path or tex.F_HEI
    fnt = tex.font(fnt_path, size)
    d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    pad = size + sw * 2
    if d.textbbox((0, 0), txt, font=fnt)[2] <= maxw - pad:
        return [txt]
    # 找中点附近的切分位置
    best, bestdiff = None, None
    for i in range(1, len(txt)):
        a, b = txt[:i], txt[i:]
        wa = d.textbbox((0, 0), a, font=fnt)[2]
        wb = d.textbbox((0, 0), b, font=fnt)[2]
        diff = abs(wa - wb)
        if wa <= maxw - pad and wb <= maxw - pad and (bestdiff is None or diff < bestdiff):
            best, bestdiff = (a, b), diff
    return list(best) if best else [txt]


def draw_chip(img, txt, x, y, size=38, bg=(198, 30, 48)):
    """左上/右上角标小胶囊。"""
    fnt = tex.font(tex.F_YAHEI, size)
    d0 = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    b = d0.textbbox((0, 0), txt, font=fnt)
    tw, th = b[2] - b[0], b[3] - b[1]
    pad_x, pad_y = 22, 12
    w, h = tw + pad_x * 2, th + pad_y * 2 + 4
    lay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dl = ImageDraw.Draw(lay)
    dl.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=bg + (232,))
    dl.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2,
                         outline=(255, 255, 255, 70), width=2)
    dl.text((pad_x - b[0], pad_y - b[1] + 2), txt, font=fnt, fill=(255, 255, 255))
    img.alpha_composite(lay, (int(x), int(y)))


def draw_clock(img, t, src_off, x, y):
    """右下直播时间戳。"""
    total = src_off + t
    hh = int(total // 3600) % 24
    mm = int(total // 60) % 60
    ss = int(total) % 60
    s = "%02d:%02d:%02d" % (hh, mm, ss)
    fnt = tex.font(tex.F_YAHEI, 32)
    d0 = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    b = d0.textbbox((0, 0), s, font=fnt)
    tw = b[2] - b[0]
    lay = Image.new("RGBA", (tw + 28, 50), (0, 0, 0, 0))
    dl = ImageDraw.Draw(lay)
    dl.rounded_rectangle([0, 0, tw + 27, 49], radius=10, fill=(0, 0, 0, 150))
    dl.text((14 - b[0], 9 - b[1]), s, font=fnt, fill=(255, 255, 255))
    img.alpha_composite(lay, (int(x - tw - 28), int(y)))


def draw_segment(img, txt, W, y, t, t0, dur):
    """分段小标题：左侧色块 + 文字，从左侧滑入。"""
    p = tex.clamp01((t - t0) / 0.36)
    sc = tex.ease_out_back(p)
    size = 56
    lay = tex.big_text(txt, size, fill=((255, 252, 200), (255, 190, 60)),
                       stroke=(120, 40, 10), sw=5, squash=0.96,
                       fnt_path=tex.F_YAHEI)
    if abs(sc - 1.0) > 0.01:
        lay = lay.resize((max(1, int(lay.width * sc)),
                          max(1, int(lay.height * sc))), Image.BILINEAR)
    # 淡出
    alpha = tex.clamp01(p * 2)
    if t > t0 + dur - 0.4:
        alpha *= tex.clamp01((t0 + dur - t) / 0.4)
    # 底部小色条 + 文字
    bar_w = lay.width + 68
    bar = Image.new("RGBA", (bar_w, lay.height + 34), (0, 0, 0, 0))
    dl = ImageDraw.Draw(bar)
    dl.rounded_rectangle([0, 0, bar_w - 1, lay.height + 33], radius=12,
                         fill=(176, 26, 42, 226))
    dl.rounded_rectangle([0, 0, 12, lay.height + 33], radius=6,
                         fill=(255, 214, 80, 240))
    bar.alpha_composite(lay.convert("RGBA"), (52, 17))
    if alpha < 1.0:
        bar.putalpha(bar.getchannel("A").point(lambda v: int(v * alpha)))
    img.alpha_composite(bar, (54, int(y - (lay.height + 34) / 2)))


def main():
    src, dst, planp = sys.argv[1], sys.argv[2], sys.argv[3]
    plan = json.load(open(planp, encoding="utf-8"))
    style = plan.get("style", "variety")
    DUR = float(plan["dur"])
    N = int(round(DUR * FPS))

    cin = av.open(src)
    vst = cin.streams.video[0]
    W = vst.codec_context.width
    H = vst.codec_context.height
    srate = float(vst.average_rate)
    print("src %dx%d@%.0f -> 原比例输出 %dx%d style=%s" %
          (W, H, srate, W, H, style))

    # ---- 预取帧
    frames = []
    step = srate / float(FPS)
    acc = 0.0
    for fr in cin.decode(vst):
        t = float(fr.pts * fr.time_base) if fr.pts is not None else None
        if t is None:
            continue
        acc += 1.0
        if acc >= step - 1e-9:
            acc -= step
            frames.append(fr.to_image().convert("RGB"))
            if len(frames) >= N + 2:
                break
    print("  grabbed %d frames (need %d)" % (len(frames), N))
    while len(frames) < N:
        frames.append(frames[-1].copy())
    cin.close()

    title_cache = {}

    def get_title(it):
        k = (it["txt"], it.get("size", 104))
        if k not in title_cache:
            title_cache[k] = tex.big_text(
                it["txt"], it.get("size", 104),
                fill=tuple(tuple(c) for c in it.get("fill", [[255, 246, 120], [255, 138, 20]])),
                stroke=tuple(it.get("stroke", [255, 255, 255])),
                sw=it.get("sw", 8), squash=it.get("squash", 0.94),
                fnt_path=it.get("fnt", tex.F_HEI))
        return title_cache[k]

    out = av.open(dst, "w")
    ost = out.add_stream("libx264", rate=FPS)
    ost.width, ost.height, ost.pix_fmt = W, H, "yuv420p"
    ost.bit_rate = 5_000_000
    ost.options = {"preset": "veryfast", "crf": "20", "profile": "high",
                   "level": "4.2", "x264-params": "keyint=%d:scenecut=0" % FPS}
    ost.time_base = Fraction(1, FPS)

    g = plan.get("grade", {})
    vig = g.get("vig", 0.26)
    sat, con = g.get("sat", 1.12), g.get("con", 1.06)

    shakes = []
    for b in plan.get("beats", []):
        if b["kind"] == "boom":
            shakes.append((b["t"], 0.50, 22))
        elif b["kind"] == "pop":
            shakes.append((b["t"], 0.28, 11))
    for s in plan.get("shakes", []):
        shakes.append((s[0], s[1], s[2]))

    boom_ts = [b["t"] for b in plan.get("beats", []) if b["kind"] == "boom"]
    vign = vfx.vignette_mask((W, H), vig) if vig > 0.01 else None

    last_tick = -1
    for i in range(N):
        t = i / float(FPS)
        content = frames[i]

        # 1) 推近
        for (p0, p1, amt) in plan.get("push", []):
            if p0 <= t <= p1:
                k = (t - p0) / max(1e-6, (p1 - p0))
                content = vfx.push_in(content, k, amt)
        # 2) 震屏
        dx = dy = 0.0
        for (t0, sdur, amp) in shakes:
            ddx, ddy = vfx.shake_offset(t, t0, sdur, amp)
            dx += ddx
            dy += ddy
        if dx or dy:
            content = vfx.apply_shake(content, dx, dy)
        # 3) 调色
        content = vfx.saturate(content, sat)
        content = vfx.contrast(content, con)
        img = content.convert("RGBA")

        # 4) 暗角
        if vign is not None:
            img = Image.alpha_composite(img, vign)

        # 5) 闪白
        for bt in boom_ts:
            dt = t - bt
            if 0 <= dt <= 0.16:
                s = 0.42 * (1 - dt / 0.16) ** 2
                img = Image.alpha_composite(
                    vfx.flash(img.convert("RGB"), s).convert("RGBA"), img)
                break

        # 6) hook 钩子
        hk = plan.get("hook")
        if hk and hk["t"] <= t < hk["t"] + hk.get("dur", 1.4):
            tex.per_char_bounce(img, hk["txt"], hk.get("size", 96), W // 2,
                                int(H * hk.get("cy", 0.16)), hk["t"], t,
                                dur=0.42, stagger=0.05, hop=30, sw=8)

        # 7) 大标题
        for it in plan.get("titles", []):
            if it["t"] <= t < it["t"] + it.get("dur", 3.2):
                p = tex.clamp01((t - it["t"]) / 0.42)
                lay = get_title(it)
                sc = tex.ease_out_back(p)
                if abs(sc - 1.0) > 0.01:
                    lay = lay.resize((max(1, int(lay.width * sc)),
                                      max(1, int(lay.height * sc))), Image.BILINEAR)
                tex.paste_center(img, lay, W // 2,
                                 int(H * it.get("cy", 0.20)), tex.clamp01(p * 2))

        # 8) 分段小标题
        for it in plan.get("segments", []):
            if it["t"] <= t < it["t"] + it.get("dur", 2.6):
                draw_segment(img, it["txt"], W, int(H * it.get("cy", 0.13)),
                             t, it["t"], it.get("dur", 2.6))

        # 9) 花字
        for it in plan.get("pops", []):
            if it["t"] <= t < it["t"] + it.get("dur", 2.4):
                wrap = it.get("wrap", True)
                fl = it.get("fill", [[255, 250, 160], [255, 150, 30]])
                lines = wrap2(it["txt"], it.get("size", 90), W - 150,
                              sw=it.get("sw", 7)) if wrap else [it["txt"]]
                base_cy = int(H * it.get("cy", 0.42))
                for li, ln in enumerate(lines):
                    tex.per_char_bounce(
                        img, ln, it.get("size", 90),
                        int(W * it.get("cx", 0.5)),
                        base_cy + li * int(it.get("size", 90) * 1.25),
                        it["t"], t, dur=it.get("in", 0.45), stagger=0.05,
                        hop=it.get("hop", 26), sw=it.get("sw", 7),
                        fill=tuple(tuple(c) for c in fl),
                        squash=it.get("squash", 0.95))

        # 10) 字幕条（打字机）
        for it in plan.get("subs", []):
            if it["t"] <= t < it["t"] + it.get("dur", 4.0):
                sub = it["txt"]
                size = it.get("size", 46)
                fnt = tex.font(tex.F_YAHEI, size)
                d0 = ImageDraw.Draw(Image.new("RGB", (8, 8)))
                maxw = W - 140
                while size > 26 and d0.textbbox((0, 0), sub, font=fnt)[2] > maxw:
                    size -= 2
                    fnt = tex.font(tex.F_YAHEI, size)
                b = d0.textbbox((0, 0), sub, font=fnt)
                tw = b[2] - b[0]
                y = H - int(H * it.get("cy_off", 0.075))
                tray_w = min(W - 40, tw + 76)
                bar = Image.new("RGBA", (tray_w, 88), (0, 0, 0, 0))
                ImageDraw.Draw(bar).rounded_rectangle(
                    [0, 0, tray_w - 1, 87], radius=16, fill=(8, 10, 18, 220),
                    outline=(255, 255, 255, 46), width=2)
                img.alpha_composite(bar, ((W - tray_w) // 2, y - 44))
                tex.typewriter(img, sub, size, W // 2, y, it["t"], t,
                               cps=it.get("cps", 14.0), fill=(255, 255, 255),
                               stroke=(0, 0, 0), sw=4)

        # 11) 跑马灯
        mq = plan.get("marquee")
        if mq and t >= mq.get("t0", 0):
            draw_marquee(img, mq["txt"], H - int(H * mq.get("cy_off", 0.042)),
                         t, mq.get("speed", 300), W)

        # 12) 角标
        c1 = plan.get("chip")
        if c1:
            draw_chip(img, c1["t"], 34, 20, size=38)
        c2 = plan.get("chip2")
        if c2:
            fnt = tex.font(tex.F_YAHEI, 34)
            d0 = ImageDraw.Draw(Image.new("RGB", (8, 8)))
            b = d0.textbbox((0, 0), c2["t"], font=fnt)
            tw = b[2] - b[0]
            draw_chip(img, c2["t"], W - tw - 80, 20, size=34, bg=(28, 34, 52))

        # 13) 直播时间戳
        ck = plan.get("clock")
        if ck and t >= ck.get("t0", 0):
            draw_clock(img, t, ck.get("src_off", 0), W - 34,
                       H - int(H * ck.get("cy_off", 0.034)))

        # 14) 结尾卡
        en = plan.get("end")
        if en and t >= en["t"]:
            dt = t - en["t"]
            p = tex.clamp01(dt / 0.45)
            veil = Image.new("RGBA", (W, H), (6, 8, 16, int(200 * tex.clamp01(dt / 0.35))))
            img = Image.alpha_composite(img, veil)
            if p > 0.05:
                sc = tex.ease_out_back(p)
                lay = tex.big_text(en["l1"], 96, fill=((255, 250, 170), (255, 150, 26)),
                                   stroke=(255, 255, 255), sw=8, squash=0.94)
                lay = lay.resize((max(1, int(lay.width * sc)), max(1, int(lay.height * sc))),
                                 Image.BILINEAR) if abs(sc - 1) > 0.01 else lay
                tex.paste_center(img, lay, W // 2, int(H * 0.44), tex.clamp01(p * 1.4))
                if en.get("l2"):
                    tex.typewriter(img, en["l2"], 52, W // 2, int(H * 0.545),
                                   en["t"] + 0.3, t, cps=10.0,
                                   fill=(255, 226, 120), stroke=(0, 0, 0), sw=5)

        # ---- 输出
        tick = int(round(t * FPS))
        if tick <= last_tick:
            continue
        last_tick = tick
        fr = av.VideoFrame.from_image(img.convert("RGB"))
        fr.time_base = Fraction(1, FPS)
        fr.pts = tick
        for pkt in ost.encode(fr):
            out.mux(pkt)
        if tick % 300 == 0:
            print("  video %d frames (t=%ds)" % (tick, int(t)))

    for pkt in ost.encode(None):
        out.mux(pkt)
    out.close()
    print("video done: %d frames" % (last_tick + 1))

    # ---- 音频
    mix = audiomix.AudioMixer(src, dur=DUR)
    mix.bgm(style, gain=plan.get("bgm_gain", 1.0))
    for b in plan.get("beats", []):
        k = b["kind"]
        if k == "boom":
            mix.sfx("boom", b["t"], gain=b.get("gain", 1.0))
            mix.duck(b["t"], b["t"] + 0.45, 0.45)
        elif k == "pop":
            mix.sfx("ding", b["t"], gain=b.get("gain", 0.45))
        elif k == "whoosh":
            mix.sfx("whoosh", b["t"], gain=0.9)
        elif k == "wow":
            mix.sfx("wow", b["t"], gain=b.get("gain", 0.55))
            mix.duck(b["t"], b["t"] + 0.5, 0.4)
        elif k == "clap":
            mix.sfx("clap", b["t"], gain=b.get("gain", 0.5))
        elif k == "drum":
            mix.sfx("drumroll", b["t"], gain=b.get("gain", 0.4))
        elif k == "rise":
            mix.sfx("rise", b["t"], gain=b.get("gain", 0.5))
    for s in plan.get("sfx", []):
        mix.sfx(s["name"], s["t"], gain=s.get("gain", 0.6))
    tmp = dst + ".m4a"
    mix.write(tmp)

    vc = av.open(dst)
    vs = vc.streams.video[0]
    ac = av.open(tmp)
    as_ = ac.streams.audio[0]
    out2 = av.open(dst + ".final.mp4", "w")
    ov = out2.add_stream_from_template(vs)
    oa = out2.add_stream_from_template(as_)
    for pkt in vc.demux(vs):
        if pkt.dts is None:
            continue
        pkt.stream = ov
        out2.mux(pkt)
    for pkt in ac.demux(as_):
        if pkt.dts is None:
            continue
        pkt.stream = oa
        out2.mux(pkt)
    out2.close()
    ac.close()
    vc.close()
    import shutil
    shutil.move(dst + ".final.mp4", dst)
    os.remove(tmp)
    print("NATIVE_DONE %s" % dst)


def draw_marquee(img, txt, y, t, speed, W):
    """底部跑马灯。"""
    fnt = tex.font(tex.F_HEI, 44)
    d0 = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    b = d0.textbbox((0, 0), txt, font=fnt)
    tw = b[2] - b[0]
    th = 68
    lay = Image.new("RGBA", (W, th), (0, 0, 0, 0))
    dl = ImageDraw.Draw(lay)
    dl.rectangle([0, 0, W, th], fill=(178, 22, 40, 226))
    dl.rectangle([0, 0, W, 3], fill=(255, 214, 80, 240))
    tile = max(W, tw + 120)
    off = int(t * speed) % tile
    x = -off
    while x < W:
        dl.text((x + (tile - tw) // 2 - b[0], (th - (b[3] - b[1])) // 2 - b[1]),
                txt, font=fnt, fill=(255, 240, 190))
        x += tile
    img.alpha_composite(lay, (0, int(y)))


if __name__ == "__main__":
    main()
