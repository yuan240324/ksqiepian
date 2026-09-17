# -*- coding: utf-8 -*-
"""增强版成片渲染器：节拍驱动的 视觉特效 + 花字 + 音频混音。

用法:
    python render_pro.py <raw.mp4> <out.mp4> <plan.json>

plan.json 结构（节拍驱动，所有时间相对成片时间轴）:
{
  "style": "variety|commentary|rustic",
  "dur": 34.0,
  "bgm_gain": 1.0,
  "beats": [                         # 节拍点：驱动震屏/闪白/音效
    {"t": 3.2, "kind": "boom"},      # boom=爆点(震屏+闪白+咚)
    {"t": 5.0, "kind": "pop"},       # pop=花字出现(轻震+叮)
    {"t": 0.0, "kind": "whoosh"},
    {"t": 32.5, "kind": "end"}       # end=结尾卡(音乐收)
  ],
  "pops": [                          # 花字（逐字弹跳）
    {"txt":"绷不住了","t":3.2,"dur":2.6,"cx":0.5,"cy":0.30,"size":92,
     "fill":[[255,245,120],[255,140,20]],"sw":7}
  ],
  "titles": [                        # 大标题（渐变+投影，整行弹入）
    {"txt":"笑到失控","t":0.4,"dur":3.6,"cy":0.20,"size":104}
  ],
  "subs": [                          # 字幕条（打字机）
    {"txt":"对面血条瞬间见底","t":8.0,"dur":4.0,"hl":"见底"}
  ],
  "hook": {"txt":"...","t":0.0,"dur":1.4},
  "end":  {"t":32.5,"l1":"关注主播 不迷路","l2":"每天更新名场面"},
  "marquee": {"txt":"...","t0":2.0,"speed":300},
  "banner": {"txt":"...","t0":0.2,"t1":5.0},
  "chip":  {"t":"综艺名场面·第1期"},
  "chip2": {"t":"9月13日 直播回放"},
  "clock": {"t0":0.0,"src_off":8100},   # 右下直播时间戳
  "grade": {"sat":1.12,"con":1.06,"vig":0.28},
  "push": [[0.0,34.0,0.10]],            # 推近区间 [t0,t1,amount]
  "shakes": [[3.2,0.45,20]]             # 额外震屏 [t,时长,幅度]
}

设计要点：
  * 内容层（9:16 中的原画面）与装饰层分离：震屏/推近只作用于内容层，
    花字贴在最上层，这样画抖但字稳，符合快手观感
  * 所有花字按 beats 的节拍点出现，音画同步
"""
import json
import math
import os
import sys
from fractions import Fraction

import av
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import tex
import vfx
import audiomix

W, H, FPS = 1080, 1920, 30
US = Fraction(1, 1_000_000)
BG_STEP = 10      # 模糊背景复用间隔（帧）
BG_H = 1560       # 模糊背景的中间放大高度（盖住整屏后裁切）


class Geo:
    def __init__(self, cw, ch, cx, cy, scale=1.0, vh=1, crop_top=0, crop_bot=0,
                 crop_x=0):
        self.cw, self.ch, self.cx, self.cy = cw, ch, cx, cy
        self.scale = scale        # 内容层缩放系数（源像素 -> 内容层像素）
        self.vh = vh              # 裁边后的有效源高
        self.crop_top = crop_top
        self.crop_bot = crop_bot
        self.crop_x = crop_x      # 源横向裁切起点（源像素）

    def src_box(self, sw, sh):
        """内容层对应的源裁切框。"""
        vw = int(round(self.cw / self.scale))
        vh = int(round(self.ch / self.scale))
        x0 = min(max(0, self.crop_x), max(0, sw - vw))
        y0 = min(max(0, self.crop_top), max(0, sh - self.crop_bot - vh))
        return (x0, y0, x0 + min(vw, sw), y0 + min(vh, sh - self.crop_bot))


def fit_blur_bg(src_img, geo, cache, i):
    """构造 9:16 画布：背景用放大模糊的原画面，内容按 geo 贴放。

    性能优化：模糊背景每 BG_STEP 帧才重算一次并复用（背景已被强模糊 +
    压暗，帧间差异肉眼不可见），这是整条渲染最大的开销项。
    """
    cw, ch, cy = geo.cw, geo.ch, geo.cy
    sw, sh = src_img.size
    box = geo.src_box(sw, sh)
    if cache.get("bg") is None or i % BG_STEP == 0:
        # 背景放大到盖住整屏再模糊，避免边缘出现拉伸条纹
        bh = int(BG_H)
        bg = src_img.resize((max(1, int(sw * bh / float(sh))), bh), Image.BILINEAR)
        bw = bg.width
        bg = bg.crop((max(0, (bw - W) // 2), max(0, (bh - H) // 2),
                      max(0, (bw - W) // 2) + W, max(0, (bh - H) // 2) + H))
        bg = bg.filter(ImageFilter.GaussianBlur(26))
        bg = vfx.saturate(bg, 0.78)
        cache["bg"] = Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), 0.42)
    base = cache["bg"].copy()
    content = src_img.crop(box).resize((cw, ch), Image.LANCZOS)
    base.paste(content, (geo.cx, cy))
    return base, content


def detect_crop(img, dark=26, ratio=0.985):
    """探测素材自带的信箱黑边，返回 (top, bottom) 像素。

    直播回放里 9:13 竖屏源上下各有一条黑边，不裁掉的话内容区白白矮一截，
    模糊延展带就被撑得很高，成片看着"没填满"。
    """
    w, h = img.size
    px = img.convert("L").load()
    x0, x1 = int(w * 0.18), int(w * 0.82)

    def row_max(y):
        step = max(1, (x1 - x0) // 90)
        return max(px[x, y] for x in range(x0, x1, step))

    top = 0
    while top < h // 4 and row_max(top) <= dark:
        top += 1
    bot = h
    while bot > h - h // 4 and row_max(bot - 1) <= dark:
        bot -= 1
    # 只认"成规模的黑边"，零散暗角不动
    if top < h * 0.012 or (bot - h + top) < h * 0.012:
        return 0, 0
    if (h - (bot - top)) / float(h) < (1.0 - ratio):
        return 0, 0
    return top, h - bot


def layout(sw, sh, crop_top=0, crop_bot=0, fill=0.985, band=0.0):
    """算构图画布：铺满整个 9:16，不要模糊延展带（裁切优先）。

    按源比例自动挑方向，保证"不放大、少裁切"：
      * 源比 9:16 宽（横屏/方屏）-> 按高铺满，左右裁掉多余部分
      * 源比 9:16 瘦（竖屏）      -> 按宽铺满，上下裁掉一点
    两者都让 ch≈H、cw≈W，模糊带只剩 1~2%（仅 fill 的余量）。

    只有当"按高铺满"会丢掉超过六成源画面时（极端宽扁素材），
    才退回按宽铺满补模糊带。
    返回 (cw, ch, cx, cy, scale, vh, crop_x, crop_y)。
    """
    vh = sh - crop_top - crop_bot
    src_ar = sw / float(vh)
    # 允许的放大量：源本身小（如 1280x960）时上采样是必要的，
    # 但放大越多越糊，所以设个上限（Lanczos 放大 2x 内观感可接受）。
    MAXUP = 2.0
    if src_ar <= W / float(H):
        # 竖屏源：按宽铺满，上下裁一点
        s = (W * fill) / float(sw)
        cw = int(round(sw * s))
        ch = int(round(vh * s))
        if ch > H:
            # 太高：按高铺满并左右裁，但不超放大量
            s = min(MAXUP, (H * fill) / float(vh))
            ch = int(round(vh * s))
            cw = int(round(sw * s))
            crop_x = max(0, (sw - int(round(W / s))) // 2)
            return cw, ch, (W - cw) // 2, (H - ch) // 2, s, vh, crop_x, crop_top
        return cw, ch, (W - cw) // 2, (H - ch) // 2, s, vh, 0, crop_top
    # 横屏/方屏源：按高铺满、左右裁掉多余部分；超过 MAXUP 则改按宽铺
    s = (H * fill) / float(vh)
    vw = W / s
    if s > MAXUP or vw > sw:
        # 不放大：按宽铺满，余量给上下模糊带
        s = min(MAXUP, (W * fill) / float(sw))
        cw, chA = int(round(sw * s)), int(round(vh * s))
        return cw, chA, (W - cw) // 2, (H - chA) // 2, s, vh, 0, crop_top
    ch = int(round(H * fill))
    cw = int(round(W * fill))
    return (cw, ch, (W - cw) // 2, (H - ch) // 2, s, vh,
            max(0, int(round((sw - vw) / 2.0))), crop_top)


def grad_overlay(geo):
    """内容区上下渐变遮罩（按 geo 缓存，避免每帧重建）。"""
    key = (geo.cx, geo.cy, geo.cw, geo.ch)
    cache = getattr(grad_overlay, "_c", None)
    if cache is None or cache[0] != key:
        top = Image.new("L", (1, 260))
        px = top.load()
        for y in range(260):
            px[0, y] = int(150 * (1 - y / 260.0))
        bot = Image.new("L", (1, 300))
        px = bot.load()
        for y in range(300):
            px[0, y] = int(170 * (y / 300.0))
        band = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        band.paste((0, 0, 0, 255), (geo.cx, geo.cy), top.resize((geo.cw, 260)))
        band.paste((0, 0, 0, 255), (geo.cx, geo.cy + geo.ch - 300),
                   bot.resize((geo.cw, 300)))
        grad_overlay._c = (key, band)
        return band
    return cache[1]


def wrap2(txt, size, max_w, fnt_path=tex.F_YAHEI, sw=0):
    """超宽文字按字符折成两行（花字太长会被裁边）。"""
    fnt = tex.font(fnt_path, size)
    d0 = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    if d0.textbbox((0, 0), txt, font=fnt, stroke_width=sw)[2] <= max_w or len(txt) < 4:
        return [txt]
    n = len(txt)
    mid = (n + 1) // 2
    return [txt[:mid], txt[mid:]]


def draw_chip(img, txt, x, y, fnt_path=tex.F_YAHEI, size=38,
              fg=(255, 255, 255), bg=(230, 40, 60), pad=(18, 10)):
    fnt = tex.font(fnt_path, size)
    d0 = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    b = d0.textbbox((0, 0), txt, font=fnt)
    tw, th = b[2] - b[0], b[3] - b[1]
    w, h = tw + pad[0] * 2, th + pad[1] * 2
    lay = Image.new("RGBA", (w + 8, h + 8), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    ld.rounded_rectangle([4, 4, 4 + w, 4 + h], radius=h // 2, fill=bg + (238,),
                         outline=(255, 255, 255, 230), width=3)
    ld.text((4 + pad[0] - b[0], 4 + pad[1] - b[1] + 2), txt, font=fnt,
            fill=(0, 0, 0, 110))
    ld.text((4 + pad[0] - b[0], 4 + pad[1] - b[1]), txt, font=fnt, fill=fg)
    img.alpha_composite(lay, (int(x), int(y)))
    return w + 8


def draw_clock(img, t, src_off, y):
    """右下直播时间戳。"""
    total = int(src_off + t)
    hh, mm = (total // 3600) % 24, (total % 3600) // 60
    ss = total % 60
    txt = "%02d:%02d:%02d" % (hh, mm, ss)
    fnt = tex.font(tex.F_YAHEI, 34)
    d0 = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    b = d0.textbbox((0, 0), txt, font=fnt)
    tw = b[2] - b[0]
    lay = Image.new("RGBA", (tw + 28, 52), (0, 0, 0, 0))
    ImageDraw.Draw(lay).rounded_rectangle([0, 0, tw + 27, 51], radius=10,
                                          fill=(0, 0, 0, 150))
    ImageDraw.Draw(lay).text((14 - b[0], 8 - b[1]), txt, font=fnt,
                             fill=(255, 255, 255, 235))
    img.alpha_composite(lay, (W - tw - 46, int(y)))


def draw_marquee(img, txt, y, t, speed=300, h=72):
    fnt = tex.font(tex.F_HEI, 44)
    d0 = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    b = d0.textbbox((0, 0), txt, font=fnt)
    pad = 60
    tw = b[2] - b[0] + pad * 2
    # 画布宽度取"文本块"的整数倍，否则循环贴图会在接缝处把字切一半
    tile = max(W, tw)
    band = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    strip = Image.new("RGBA", (tile, h), (198, 24, 24, 234))
    sd = ImageDraw.Draw(strip)
    sd.rectangle([0, 0, tile, 5], fill=(255, 220, 60, 255))
    sd.rectangle([0, h - 5, tile, h], fill=(255, 220, 60, 255))
    # 文本在循环内居中；若文本长于屏宽，则整体左移贴住屏幕左边不被裁
    tx = (tile - tw) / 2.0 + pad - b[0]
    sd.text((tx, (h - (b[3] - b[1])) // 2 - b[1]), txt, font=fnt,
            fill=(255, 246, 190), stroke_width=3, stroke_fill=(120, 10, 10))
    off = int((t * speed) % tile)
    for x0 in range(-off, W + tile, tile):
        band.alpha_composite(strip, (x0, 0))
    img.alpha_composite(band.crop((0, 0, W, h)), (0, int(y)))


def main():
    src, dst, planp = sys.argv[1], sys.argv[2], sys.argv[3]
    plan = json.load(open(planp, encoding="utf-8"))
    style = plan.get("style", "variety")
    DUR = float(plan["dur"])
    N = int(round(DUR * FPS))

    cin = av.open(src)
    vst = cin.streams.video[0]
    ast = next((s for s in cin.streams if s.type == "audio"), None)
    sw, sh = vst.codec_context.width, vst.codec_context.height
    srate = float(vst.average_rate)

    # ---- 构图：先探测源自带黑边，再按 9:16 铺满（尽量少留模糊延展带）
    _c = av.open(src)
    _v = _c.streams.video[0]
    for _fr in _c.decode(_v):
        probe = _fr.to_image().convert("RGB")
        break
    _c.close()
    ct, cb = detect_crop(probe)
    cw, ch, cx, cy, scale, vh, crop_x, _ = layout(
        sw, sh, ct, cb, fill=plan.get("fill", 0.985))
    geo = Geo(cw, ch, cx, cy, scale, vh, ct, cb, crop_x)
    print("src %dx%d@%.0f crop=(x%d tb%d,%d) -> content %dx%d cx=%d cy=%d "
          "scale=%.3f bg_band=%.1f%% style=%s" %
          (sw, sh, srate, crop_x, ct, cb, cw, ch, cx, cy, scale,
           100.0 * (H - ch) / float(H), style))

    # ---- 预取帧：按 1/FPS 网格抽帧（源帧率可能 60 或 29.97）
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

    # ---- 预渲染静态文字层缓存（大标题/花字按需懒加载）
    title_cache, pop_cache = {}, {}

    def get_title(it):
        k = (it["txt"], it.get("size", 104), tuple(map(tuple, it.get("fill", [[255, 246, 120], [255, 138, 20]]))))
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

    # 震屏事件表：beats + shakes
    shakes = []
    for b in plan.get("beats", []):
        if b["kind"] == "boom":
            shakes.append((b["t"], 0.50, 22))
        elif b["kind"] == "pop":
            shakes.append((b["t"], 0.28, 11))
    for s in plan.get("shakes", []):
        shakes.append((s[0], s[1], s[2]))

    last_tick = -1
    bglayer = grad_overlay(geo)
    # 闪白时间窗预索引（避免每帧遍历全部 beats）
    boom_ts = [b["t"] for b in plan.get("beats", []) if b["kind"] == "boom"]
    cache_bg = {}
    for i in range(N):
        t = i / float(FPS)
        src_img = frames[i]

        # 1) 基础画布（模糊背景周期性复用 + 内容）
        canvas, content = fit_blur_bg(src_img, geo, cache_bg, i)

        # 2) 内容层做推近
        for (p0, p1, amt) in plan.get("push", []):
            if p0 <= t <= p1:
                k = (t - p0) / max(1e-6, (p1 - p0))
                content = vfx.push_in(content, k, amt)
        # 3) 震屏（只抖内容层，花字保持稳定）
        dx = dy = 0.0
        for (t0, sdur, amp) in shakes:
            ddx, ddy = vfx.shake_offset(t, t0, sdur, amp)
            dx += ddx
            dy += ddy
        if dx or dy:
            content = vfx.apply_shake(content, dx, dy)
        # 4) 调色只作用于内容层（背景已是压暗模糊，无需再处理）
        content = vfx.saturate(content, sat)
        content = vfx.contrast(content, con)
        canvas.paste(content, (geo.cx, cy))

        # 5) 暗角 + 内容区上下渐变（一次性合成，减少 RGBA 往返）
        if vig > 0.01:
            canvas = vfx.vignette(canvas, vig, cy / float(H), ch / float(H))
        img = canvas.convert("RGBA")
        img = Image.alpha_composite(img, bglayer)

        # 6) 闪白（爆点瞬间）
        for bt in boom_ts:
            dt = t - bt
            if 0 <= dt <= 0.16:
                s = 0.42 * (1 - dt / 0.16) ** 2
                img = vfx.flash(img.convert("RGB"), s).convert("RGBA")
                break

        # 7) hook 钩子（片头，逐字弹跳）
        hk = plan.get("hook")
        if hk and hk["t"] <= t < hk["t"] + hk.get("dur", 1.4):
            tex.per_char_bounce(img, hk["txt"], hk.get("size", 96), W // 2,
                                geo.cy + int(geo.ch * 0.16), hk["t"], t,
                                dur=0.42, stagger=0.05, hop=30, sw=8)

        # 8) 大标题
        for it in plan.get("titles", []):
            if it["t"] <= t < it["t"] + it.get("dur", 3.2):
                p = tex.clamp01((t - it["t"]) / 0.42)
                lay = get_title(it)
                sc = tex.ease_out_back(p)
                if abs(sc - 1.0) > 0.01:
                    lay = lay.resize((max(1, int(lay.width * sc)),
                                      max(1, int(lay.height * sc))), Image.BILINEAR)
                tex.paste_center(img, lay, W // 2,
                                 geo.cy + int(geo.ch * it.get("cy", 0.20)),
                                 tex.clamp01(p * 2))

        # 9) 花字（逐字弹跳；超宽自动折两行）
        for it in plan.get("pops", []):
            if it["t"] <= t < it["t"] + it.get("dur", 2.4):
                wrap = it.get("wrap", True)
                fl = it.get("fill", [[255, 250, 160], [255, 150, 30]])
                lines = wrap2(it["txt"], it.get("size", 90), W - 150,
                              sw=it.get("sw", 7)) if wrap else [it["txt"]]
                base_cy = geo.cy + int(geo.ch * it.get("cy", 0.32))
                for li, ln in enumerate(lines):
                    tex.per_char_bounce(
                        img, ln, it.get("size", 90),
                        int(W * it.get("cx", 0.5)),
                        base_cy + li * int(it.get("size", 90) * 1.25),
                        it["t"], t, dur=it.get("in", 0.45), stagger=0.05,
                        hop=it.get("hop", 26), sw=it.get("sw", 7),
                        fill=tuple(tuple(c) for c in fl),
                        squash=it.get("squash", 0.95))

        # 10) 字幕条（打字机）——贴在内容区底部内侧，别掉到模糊背景上
        for it in plan.get("subs", []):
            if it["t"] <= t < it["t"] + it.get("dur", 4.0):
                sub = it["txt"]
                size = it.get("size", 46)
                fnt = tex.font(tex.F_YAHEI, size)
                d0 = ImageDraw.Draw(Image.new("RGB", (8, 8)))
                # 太长就自动缩字号，绝不截断
                maxw = W - 140
                while size > 26 and d0.textbbox((0, 0), sub, font=fnt)[2] > maxw:
                    size -= 2
                    fnt = tex.font(tex.F_YAHEI, size)
                b = d0.textbbox((0, 0), sub, font=fnt)
                tw = b[2] - b[0]
                mq_on = (plan.get("marquee") and t >= plan["marquee"].get("t0", 0))
                y = geo.cy + geo.ch - (148 if mq_on else 48)
                tray_w = min(W - 40, tw + 76)
                bar = Image.new("RGBA", (tray_w, 88), (0, 0, 0, 0))
                ImageDraw.Draw(bar).rounded_rectangle(
                    [0, 0, tray_w - 1, 87], radius=16, fill=(8, 10, 18, 220),
                    outline=(255, 255, 255, 46), width=2)
                img.alpha_composite(bar, ((W - tray_w) // 2, y - 44))
                tex.typewriter(img, sub, size, W // 2, y, it["t"], t,
                               cps=it.get("cps", 14.0), fill=(255, 255, 255),
                               stroke=(0, 0, 0), sw=4)

        # 11) 跑马灯（压在内容区最底边，别盖住上面的字幕条）
        mq = plan.get("marquee")
        if mq and t >= mq.get("t0", 0):
            draw_marquee(img, mq["txt"], geo.cy + geo.ch - 76, t,
                         mq.get("speed", 300))

        # 12) 横幅
        bn = plan.get("banner")
        if bn and bn["t0"] <= t < bn["t1"]:
            p = tex.clamp01((t - bn["t0"]) / 0.4)
            lay = tex.big_text(bn["txt"], bn.get("size", 80),
                               fill=((255, 246, 130), (255, 140, 20)),
                               stroke=(255, 255, 255), sw=6, squash=0.95,
                               fnt_path=tex.F_HEI)
            sc = tex.ease_out_back(p)
            lay = lay.resize((max(1, int(lay.width * sc)), max(1, int(lay.height * sc))),
                             Image.BILINEAR) if abs(sc - 1) > 0.01 else lay
            tex.paste_center(img, lay, W // 2,
                             geo.cy + int(geo.ch * 0.09), tex.clamp01(p * 1.6))

        # 13) 角标（贴在内容区顶部内侧）
        c1 = plan.get("chip")
        if c1:
            draw_chip(img, c1["t"], 34, geo.cy + 20, size=38)
        c2 = plan.get("chip2")
        if c2:
            fnt = tex.font(tex.F_YAHEI, 34)
            d0 = ImageDraw.Draw(Image.new("RGB", (8, 8)))
            b = d0.textbbox((0, 0), c2["t"], font=fnt)
            tw = b[2] - b[0]
            draw_chip(img, c2["t"], W - tw - 80, geo.cy + 20, size=34,
                      bg=(28, 34, 52))

        # 14) 直播时间戳（贴在内容区底部内侧，和字幕条不打架）
        ck = plan.get("clock")
        if ck and t >= ck.get("t0", 0):
            draw_clock(img, t, ck.get("src_off", 0), geo.cy + geo.ch - 56)

        # 15) 结尾卡
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

        # ---- 输出（pts 量化到 1/30 网格，碰撞帧丢弃）
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

    # ---- 音频：原声 + BGM + 音效 + 闪避
    try:
        c = av.open(src)
        ad = float(c.duration) / 1000000.0 if c.duration else DUR
        c.close()
    except Exception:
        ad = DUR
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

    # 音视频合流
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
    print("STYLE_DONE %s" % dst)


if __name__ == "__main__":
    main()
