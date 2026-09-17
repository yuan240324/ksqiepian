# -*- coding: utf-8 -*-
"""Render Kuaishou 9:16 (1080x1920) styled clips from 4:5 raw footage.

The 4:5 source is letterboxed into 9:16 with a blurred fill; the top and
bottom bands host style furniture. Presets: variety / commentary / rustic.

Usage: python style_clip.py <src.mp4> <dst.mp4> <cfg.json>
"""
import av, json, math, sys
import numpy as np
from fractions import Fraction
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1080, 1920, 30
US = Fraction(1, 1_000_000)
F_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
F_REG = r"C:\Windows\Fonts\msyh.ttc"
F_HEI = r"C:\Windows\Fonts\simhei.ttf"

_FONTS = {}


def font(path, size):
    key = (path, size)
    if key not in _FONTS:
        _FONTS[key] = ImageFont.truetype(path, size)
    return _FONTS[key]


def clamp01(x):
    return min(max(x, 0.0), 1.0)


def ease_out_back(p, s=1.7):
    p = clamp01(p)
    c3 = s + 1.0
    return 1 + c3 * (p - 1) ** 3 + s * (p - 1) ** 2


def pop_text(img, center, txt, fnt, fill, stroke, sw, scale=1.0, angle=0.0):
    if scale <= 0.03 or not txt:
        return
    pad = sw + 14
    d0 = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    b = d0.textbbox((0, 0), txt, font=fnt, stroke_width=sw)
    tw, th = b[2] - b[0], b[3] - b[1]
    if tw <= 0 or th <= 0:
        return
    lay = Image.new("RGBA", (tw + 2 * pad, th + 2 * pad), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    ox, oy = pad - b[0], pad - b[1]
    ld.text((ox + 5, oy + 7), txt, font=fnt, fill=(0, 0, 0, 130),
            stroke_width=sw, stroke_fill=(0, 0, 0, 130))
    ld.text((ox, oy), txt, font=fnt, fill=fill, stroke_width=sw, stroke_fill=stroke)
    if angle:
        lay = lay.rotate(angle, expand=True, resample=Image.BICUBIC)
    if abs(scale - 1.0) > 0.01:
        lay = lay.resize((max(1, int(lay.width * scale)),
                          max(1, int(lay.height * scale))), Image.BILINEAR)
    img.paste(lay, (int(center[0] - lay.width / 2),
                    int(center[1] - lay.height / 2)), lay)


def chip(img, x, y, txt, size=40, fill=(0, 0, 0, 160), tcol=(255, 255, 255),
         font_path=F_BOLD, right_align=False):
    fnt = font(font_path, size)
    d0 = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    b = d0.textbbox((0, 0), txt, font=fnt)
    tw, th = b[2] - b[0], b[3] - b[1]
    pad_x, pad_y = 20, 10
    w, h = tw + 2 * pad_x, th + 2 * pad_y
    if right_align:
        x = x - w
    lay = Image.new("RGBA", (w + 4, h + 4), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    ld.rounded_rectangle([0, 0, w, h], radius=h // 2, fill=fill)
    ld.text((pad_x - b[0], pad_y - b[1]), txt, font=fnt, fill=tcol)
    img.paste(lay, (int(x), int(y)), lay)


_GRAD = {}


def gradient_bottom(img, hgt, a1=190):
    if hgt not in _GRAD:
        col = np.zeros((hgt, W, 4), dtype=np.uint8)
        col[:, :, 3] = np.linspace(0, a1, hgt).astype(np.uint8)[:, None]
        _GRAD[hgt] = Image.fromarray(col, "RGBA")
    img.paste(_GRAD[hgt], (0, H - hgt), _GRAD[hgt])


def split_kw(txt, kw):
    if not kw or kw not in txt:
        return [(txt, False)]
    i = txt.index(kw)
    out = []
    if i > 0:
        out.append((txt[:i], False))
    out.append((kw, True))
    if i + len(kw) < len(txt):
        out.append((txt[i + len(kw):], False))
    return out


def typewriter(txt, p):
    if p >= 1.0 or not txt:
        return txt
    return txt[:max(1, int(len(txt) * p + 1e-4))]


def compose(src_img, geo):
    content = src_img.resize((W, geo.ch), Image.LANCZOS)
    w0, h0 = src_img.size
    scale = max(W / float(w0), H / float(h0))
    bw = max(W, int(w0 * scale + 0.5))
    bh = max(H, int(h0 * scale + 0.5))
    bg = src_img.resize((bw, bh), Image.BILINEAR)
    bg = bg.crop(((bw - W) // 2, (bh - H) // 2,
                  (bw - W) // 2 + W, (bh - H) // 2 + H))
    bg = bg.resize((96, 171), Image.BILINEAR)
    bg = bg.filter(ImageFilter.GaussianBlur(3))
    bg = bg.resize((W, H), Image.BILINEAR)
    bg.paste(content, (0, geo.cy))
    return bg


def pt(xyf, geo):
    return int(W * xyf[0]), int(geo.cy + xyf[1] * geo.ch)


# ---------------------------------------------------------------- variety
SCHEMES = [
    ((255, 235, 90), (70, 45, 10)),
    ((255, 255, 255), (214, 40, 50)),
    ((150, 238, 140), (22, 96, 44)),
    ((255, 150, 60), (96, 32, 10)),
    ((130, 205, 255), (22, 52, 118)),
    ((255, 120, 190), (120, 20, 70)),
]


def style_variety(img, t, cfg, geo):
    hk = cfg.get("hook")
    if hk and hk["t0"] <= t < hk["t1"]:
        p = clamp01((t - hk["t0"]) / 0.25)
        sc = ease_out_back(p) * (1 + 0.05 * math.sin(t * 12))
        pop_text(img, (W // 2, geo.cy + 230), hk["txt"], font(F_BOLD, 92),
                 (255, 255, 255), (220, 30, 40), 8, scale=sc)

    ti = cfg.get("title")
    if ti and ti["t0"] <= t < ti["t1"]:
        p = clamp01((t - ti["t0"]) / 0.4)
        pop_text(img, (W // 2, 158), ti["txt"], font(F_BOLD, 96),
                 (255, 225, 60), (35, 45, 120), 8,
                 scale=ease_out_back(p), angle=-2.0)

    if t < cfg.get("chip_until", 1e9):
        chip(img, 26, 60, cfg.get("chip", "爆笑名场面"), size=34,
             fill=(214, 32, 32, 200), tcol=(255, 232, 80))

    for pp in cfg.get("pops", []):
        if not (pp["t0"] <= t < pp["t1"]):
            continue
        p = clamp01((t - pp["t0"]) / 0.35)
        fill, stroke = SCHEMES[pp.get("scheme", 0) % len(SCHEMES)]
        x, y = pt(pp["xy"], geo)
        pop_text(img, (x, y), pp["txt"], font(F_BOLD, pp.get("size", 72)),
                 fill, stroke, 7, scale=ease_out_back(p),
                 angle=pp.get("angle", 0.0))

    d = ImageDraw.Draw(img)
    fnt = font(F_REG, 46)
    for txt, s, e, yf, speed in cfg.get("danmaku", []):
        if not (s <= t < e):
            continue
        w = d.textlength(txt, font=fnt)
        x = W + 40 - (t - s) * speed
        if x < -w - 40:
            continue
        y = int(geo.cy + yf * geo.ch)
        d.text((x + 3, y + 3), txt, font=fnt, fill=(0, 0, 0),
               stroke_width=4, stroke_fill=(0, 0, 0))
        d.text((x, y), txt, font=fnt, fill=(255, 255, 255),
               stroke_width=4, stroke_fill=(48, 48, 58))

    ec = cfg.get("end")
    if ec and t >= ec["t0"]:
        gradient_bottom(img, 540)
        pop_text(img, (W // 2, H - 420), ec["txt1"], font(F_BOLD, 80),
                 (255, 225, 60), (40, 30, 10), 7,
                 scale=ease_out_back(clamp01((t - ec["t0"]) / 0.4)))
        pop_text(img, (W // 2, H - 295), ec.get("txt2", ""), font(F_REG, 46),
                 (255, 255, 255), (0, 0, 0), 4,
                 scale=ease_out_back(clamp01((t - ec["t0"] - 0.25) / 0.4)))


# ------------------------------------------------------------ commentary
def draw_subtitle(img, txt, kw):
    y0, bh = H - 305, 122
    fnt = font(F_REG, 50)
    segs = split_kw(txt, kw)
    d0 = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    widths = [d0.textlength(s, font=fnt) for s, _ in segs]
    total = sum(widths)
    if total > W - 120:
        fnt = font(F_REG, 42)
        widths = [d0.textlength(s, font=fnt) for s, _ in segs]
        total = sum(widths)
    bb = d0.textbbox((0, 0), "赞", font=fnt)
    th = bb[3] - bb[1]
    lay = Image.new("RGBA", (W, bh), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    ld.rounded_rectangle([(W - total) / 2 - 36, 2, (W + total) / 2 + 36, bh - 2],
                         radius=18, fill=(0, 0, 0, 172))
    img.paste(lay, (0, y0), lay)
    d = ImageDraw.Draw(img)
    x = (W - total) / 2
    ty = y0 + (bh - th) / 2 - bb[1]
    for s, hot in segs:
        d.text((x, ty), s, font=fnt,
               fill=(255, 220, 70) if hot else (255, 255, 255))
        x += d.textlength(s, font=fnt)


def style_commentary(img, t, cfg, geo):
    ec = cfg.get("end")
    end_t = ec["t0"] if ec else 1e9

    hk = cfg.get("hook")
    if hk and hk["t0"] <= t < hk["t1"]:
        p = clamp01((t - hk["t0"]) / 0.3)
        hy = geo.cy + 210 if geo.cy <= 420 else geo.cy - 200
        pop_text(img, (W // 2, hy), hk["txt"], font(F_BOLD, 88),
                 (255, 255, 255), (20, 20, 26), 8, scale=ease_out_back(p))

    if 0.35 <= t < end_t:
        slide = int((1 - clamp01((t - 0.35) / 0.35)) * 36)
        chip(img, 26 + slide, 56, cfg.get("chip", "名场面盘点"), size=36,
             fill=(0, 0, 0, 165), tcol=(255, 255, 255))
        if cfg.get("chip2"):
            chip(img, W - 26 - slide, 56, cfg["chip2"], size=36,
                 fill=(255, 210, 40, 210), tcol=(40, 30, 10), right_align=True)

    for sb in cfg.get("subs", []):
        if sb["t0"] <= t < sb["t1"]:
            p = clamp01((t - sb["t0"]) / 0.6)
            draw_subtitle(img, typewriter(sb["txt"], p), sb.get("kw"))
            break

    if cfg.get("src_off") is not None and 0.35 <= t < end_t - 0.5:
        ts = cfg["src_off"] + t
        chip(img, W - 22, geo.cy + geo.ch - 74,
             "直播 %02d:%02d" % (int(ts // 60), int(ts % 60)), size=32,
             fill=(0, 0, 0, 150), tcol=(255, 235, 120), right_align=True)

    if ec and t >= ec["t0"]:
        gradient_bottom(img, 560)
        pop_text(img, (W // 2, H - 400), ec["txt1"], font(F_BOLD, 78),
                 (255, 225, 60), (30, 30, 10), 7,
                 scale=ease_out_back(clamp01((t - ec["t0"]) / 0.4)))
        pop_text(img, (W // 2, H - 285), ec.get("txt2", ""), font(F_REG, 44),
                 (255, 255, 255), (0, 0, 0), 4,
                 scale=ease_out_back(clamp01((t - ec["t0"] - 0.2) / 0.4)))


# ----------------------------------------------------------------- rustic
def banner(img, center, txt, fnt, scale, angle=-2.5, max_w=None):
    if scale <= 0.03:
        return
    d0 = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    b = d0.textbbox((0, 0), txt, font=fnt, stroke_width=6)
    tw, th = b[2] - b[0], b[3] - b[1]
    pad = 28
    w, h = tw + 2 * pad, th + 2 * pad
    # 横条 + 星标的总宽，超出安全宽度时先整体缩小（避免文字溢出边框）
    total_w = w + 90
    if max_w and total_w > max_w:
        rf = max_w / float(total_w)
        nsz = max(24, int(fnt.size * rf))
        fnt = font(fnt.path if hasattr(fnt, "path") else F_HEI, nsz)
        b = d0.textbbox((0, 0), txt, font=fnt, stroke_width=6)
        tw, th = b[2] - b[0], b[3] - b[1]
        w, h = tw + 2 * pad, th + 2 * pad
        total_w = w + 90
    lay = Image.new("RGBA", (max(1, total_w), h + 60), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    ld.rounded_rectangle([45, 30, 45 + w, 30 + h], radius=22,
                         fill=(214, 32, 32, 244), outline=(255, 255, 255), width=5)
    ld.text((45 + pad - b[0] + 3, 30 + pad - b[1] + 4), txt, font=fnt,
            fill=(0, 0, 0, 130), stroke_width=6, stroke_fill=(110, 16, 16, 130))
    ld.text((45 + pad - b[0], 30 + pad - b[1]), txt, font=fnt,
            fill=(255, 232, 80), stroke_width=6, stroke_fill=(255, 255, 255))
    sf = font(F_HEI, max(30, int(h * 0.52)))
    ld.text((6, 30 + h / 2 - sf.size * 0.62), "★", font=sf, fill=(255, 214, 50))
    ld.text((45 + w - sf.size * 1.05, 30 + h / 2 - sf.size * 0.62), "★", font=sf,
            fill=(255, 214, 50))
    lay = lay.rotate(angle, expand=True, resample=Image.BICUBIC)
    if abs(scale - 1.0) > 0.01:
        lay = lay.resize((max(1, int(lay.width * scale)),
                          max(1, int(lay.height * scale))), Image.BILINEAR)
    img.paste(lay, (int(center[0] - lay.width / 2),
                    int(center[1] - lay.height / 2)), lay)


def draw_marquee(img, mq, t, geo=None):
    bh = 68
    y = int(geo.cy + geo.ch - bh) if geo else mq.get("y", 1752)
    fnt = font(F_HEI, 42)
    d = ImageDraw.Draw(img)
    d.rectangle([0, y, W, y + bh], fill=(214, 32, 32))
    d.rectangle([0, y, W, y + 4], fill=(255, 214, 50))
    d.rectangle([0, y + bh - 4, W, y + bh], fill=(255, 214, 50))
    txt = mq["txt"]
    tw = d.textlength(txt, font=fnt)
    period = tw + W
    x = W - (t * mq.get("speed", 150)) % period
    for xx in (x, x - period):
        d.text((xx, y + 13), txt, font=fnt, fill=(255, 232, 80))


def end_card_rustic(img, t, ec):
    sc = ease_out_back(clamp01((t - ec["t0"]) / 0.4)) * (1 + 0.025 * math.sin(t * 7))
    if sc <= 0.03:
        return
    fnt1 = font(F_HEI, 92)
    txt = ec["txt1"]
    d0 = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    b = d0.textbbox((0, 0), txt, font=fnt1, stroke_width=5)
    tw, th = b[2] - b[0], b[3] - b[1]
    w, h = tw + 150, th + 210
    lay = Image.new("RGBA", (w + 40, h + 40), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    ld.rounded_rectangle([20, 20, 20 + w, 20 + h], radius=30,
                         fill=(214, 32, 32, 242), outline=(255, 214, 50), width=6)
    ld.text((20 + 75 - b[0], 20 + 62 - b[1]), txt, font=fnt1,
            fill=(255, 232, 80), stroke_width=5, stroke_fill=(255, 255, 255))
    ld.text((20 + 75, 20 + 62 + th + 42), ec.get("txt2", ""),
            font=font(F_HEI, 50), fill=(255, 255, 255))
    if abs(sc - 1.0) > 0.01:
        lay = lay.resize((max(1, int(lay.width * sc)),
                          max(1, int(lay.height * sc))), Image.BILINEAR)
    img.paste(lay, (int(W / 2 - lay.width / 2), int(H / 2 - lay.height / 2)), lay)


def style_rustic(img, t, cfg, geo):
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W - 1, H - 1], outline=(214, 32, 32), width=10)
    d.rectangle([16, 16, W - 17, H - 17], outline=(255, 214, 50), width=4)

    bn = cfg.get("banner")
    if bn and bn["t0"] <= t < bn["t1"]:
        p = clamp01((t - bn["t0"]) / 0.4)
        banner(img, (W // 2, 168), bn["txt"], font(F_HEI, 86),
               ease_out_back(p), max_w=W - 130)

    hk = cfg.get("hook")
    if hk and hk["t0"] <= t < hk["t1"]:
        p = clamp01((t - hk["t0"]) / 0.25)
        sc = ease_out_back(p) * (1 + 0.05 * math.sin(t * 10))
        pop_text(img, (W // 2, geo.cy + 200), hk["txt"], font(F_HEI, 88),
                 (255, 255, 255), (214, 32, 32), 9, scale=sc)

    for pp in cfg.get("pops", []):
        if not (pp["t0"] <= t < pp["t1"]):
            continue
        p = clamp01((t - pp["t0"]) / 0.35)
        fill, stroke = SCHEMES[pp.get("scheme", 0) % len(SCHEMES)]
        x, y = pt(pp["xy"], geo)
        pop_text(img, (x, y), pp["txt"], font(F_HEI, pp.get("size", 76)),
                 fill, stroke, 7, scale=ease_out_back(p),
                 angle=pp.get("angle", 0.0))

    mq = cfg.get("marquee")
    if mq and t >= mq.get("t0", 0):
        draw_marquee(img, mq, t, geo)

    ec = cfg.get("end")
    if ec and t >= ec["t0"]:
        end_card_rustic(img, t, ec)


STYLES = {
    "variety": style_variety,
    "commentary": style_commentary,
    "rustic": style_rustic,
}


class Geo(object):
    def __init__(self, cy, ch):
        self.cy, self.ch = cy, ch


def main():
    src, dst, cfgpath = sys.argv[1], sys.argv[2], sys.argv[3]
    cfg = json.load(open(cfgpath, encoding="utf-8"))
    fn = STYLES[cfg["style"]]

    cin_v = av.open(src)
    vst = cin_v.streams.video[0]
    src_fps = float(vst.codec_context.framerate)
    step = max(1, int(round(src_fps / FPS)))
    sw, sh = vst.codec_context.width, vst.codec_context.height
    ch = min(H, int(round(W * sh / float(sw))))
    geo = Geo((H - ch) // 2, ch)
    print("src %dx%d@%.0ffps -> 1080x1920@30 content=%d cy=%d"
          % (sw, sh, src_fps, ch, geo.cy), flush=True)

    cin_a = av.open(src)
    ast = cin_a.streams.audio[0]

    cout = av.open(dst, "w")
    vout = cout.add_stream("libx264", rate=FPS)
    vout.width, vout.height = W, H
    vout.pix_fmt = "yuv420p"
    vout.options = {"preset": "veryfast", "crf": "20"}
    aout = cout.add_stream("aac", rate=ast.sample_rate)
    aout.layout = "stereo"
    aout.format = "fltp"
    aout.bit_rate = 128000

    n = kept = 0
    last_tick = -1
    TB_FPS = Fraction(1, FPS)
    for fr in cin_v.decode(vst):
        if n % step != 0:
            n += 1
            continue
        t = float(fr.pts * fr.time_base)
        tick = int(round(t * FPS))
        if tick <= last_tick:
            n += 1
            continue
        last_tick = tick
        img = compose(fr.to_image().convert("RGB"), geo)
        fn(img, t, cfg, geo)
        arr = np.asarray(img)
        nf = av.VideoFrame.from_ndarray(arr, format="rgb24").reformat(
            width=W, height=H, format="yuv420p")
        nf.time_base = TB_FPS
        nf.pts = tick
        for pkt in vout.encode(nf):
            cout.mux(pkt)
        kept += 1
        n += 1
        if kept % 300 == 0:
            print("  video %d frames (t=%.0fs)" % (kept, t), flush=True)
    for pkt in vout.encode(None):
        cout.mux(pkt)
    print("video done: %d frames" % kept, flush=True)

    na = 0
    a_sec = 0.0
    rs = av.AudioResampler(format="fltp", layout="stereo", rate=ast.sample_rate)
    for fr in cin_a.decode(ast):
        for af in rs.resample(fr):
            af.time_base = US
            af.pts = int(round(a_sec * 1_000_000))
            a_sec += af.samples / float(af.sample_rate or ast.sample_rate)
            for pkt in aout.encode(af):
                cout.mux(pkt)
            na += 1
    for af in rs.resample(None):
        af.time_base = US
        af.pts = int(round(a_sec * 1_000_000))
        a_sec += af.samples / float(af.sample_rate or ast.sample_rate)
        for pkt in aout.encode(af):
            cout.mux(pkt)
        na += 1
    for pkt in aout.encode(None):
        cout.mux(pkt)
    print("audio done: %.1fs" % a_sec, flush=True)

    cout.close()
    cin_v.close()
    cin_a.close()
    print("STYLE_DONE %s -> %s" % (cfg["style"], dst), flush=True)


if __name__ == "__main__":
    main()
