# -*- coding: utf-8 -*-
"""文字特效：渐变填充大字、硬投影、描边、压缩字、打字机、逐字弹跳。

相对第一版的增强点：
  1) 渐变填充（垂直双色）——快手爆款标题的标配
  2) 多层硬投影（offset 双层）——字从画面里"立"起来
  3) 粗描边 + 内描边 —— 任何底色上都清晰
  4) 逐字弹跳（每个字独立相位）——比整行弹入更有节奏
  5) 压缩字：用 PIL 的 resize 横向压到 0.92，模拟超粗窄体
"""
import math
from PIL import Image, ImageDraw, ImageFont, ImageFilter

F_HEI = r"C:\Windows\Fonts\simhei.ttf"
F_YAHEI = r"C:\Windows\Fonts\msyhbd.ttc"
F_SONG = r"C:\Windows\Fonts\msyh.ttc"

_fc = {}


def font(path, size):
    k = (path, int(size))
    if k not in _fc:
        _fc[k] = ImageFont.truetype(path, int(size))
    return _fc[k]


def ease_out_back(p, s=1.70158):
    p = max(0.0, min(1.0, p))
    return 1 + (s + 1) * (p - 1) ** 3 + s * (p - 1) ** 2


def clamp01(x):
    return max(0.0, min(1.0, x))


def text_size(txt, fnt, stroke=0):
    d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    b = d.textbbox((0, 0), txt, font=fnt, stroke_width=stroke)
    return b[2] - b[0], b[3] - b[1], b


def _grad_fill(size, c_top, c_bot):
    """生成垂直渐变图（用于文字遮罩填充）。"""
    w, h = size
    g = Image.new("RGB", (1, max(1, h)))
    px = g.load()
    for y in range(max(1, h)):
        p = y / float(max(1, h - 1))
        px[0, y] = (int(c_top[0] + (c_bot[0] - c_top[0]) * p),
                    int(c_top[1] + (c_bot[1] - c_top[1]) * p),
                    int(c_top[2] + (c_bot[2] - c_top[2]) * p))
    return g.resize((max(1, w), max(1, h)))


def big_text(txt, size, fill=((255, 246, 120), (255, 138, 20)),
             stroke=(255, 255, 255), sw=7, proj=True, shadow=(0, 0, 0),
             squash=0.94, fnt_path=F_HEI, proj_off=(6, 8)):
    """返回一张 RGBA 大字（带渐变填充 + 白描边 + 硬投影）。"""
    fnt = font(fnt_path, size)
    tw, th, b = text_size(txt, fnt, sw)
    pad = sw + 14 + (max(proj_off) if proj else 0)
    W, H = tw + pad * 2, th + pad * 2
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    # 1) 硬投影（双层，外层更虚）
    if proj:
        for (ox, oy, al, bl) in [(proj_off[0] + 3, proj_off[1] + 4, 110, 6),
                                 (proj_off[0], proj_off[1], 190, 0)]:
            sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(sh).text((pad - b[0] + ox, pad - b[1] + oy), txt,
                                    font=fnt, fill=shadow + (al,),
                                    stroke_width=sw, stroke_fill=shadow + (al,))
            if bl:
                sh = sh.filter(ImageFilter.GaussianBlur(bl))
            lay = Image.alpha_composite(lay, sh)

    # 2) 文字本体：先做白色描边层（粗描边打底）
    body = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(body)
    bd.text((pad - b[0], pad - b[1]), txt, font=fnt,
            fill=(255, 255, 255, 255), stroke_width=sw,
            stroke_fill=stroke + (255,))

    # 3) 用渐变填充替换字芯：把渐变图按"字芯 mask"直接贴到描边层上
    #    （不能用 alpha_composite——渐变层的透明区会把已画好的描边挖掉）
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).text((pad - b[0], pad - b[1]), txt, font=fnt, fill=255)
    grad = _grad_fill((W, H), fill[0], fill[1]).convert("RGBA")
    body.paste(grad, (0, 0), mask)

    lay = Image.alpha_composite(lay, body)

    # 4) 横向压缩，模拟超粗窄体
    if abs(squash - 1.0) > 0.01:
        nw = max(1, int(W * squash))
        lay = lay.resize((nw, H), Image.BILINEAR)
    return lay


def paste_center(img, lay, cx, cy, alpha=1.0):
    if alpha < 0.995:
        a = lay.getchannel("A").point(lambda v: int(v * max(0.0, alpha)))
        lay = lay.copy()
        lay.putalpha(a)
    img.alpha_composite(lay, (int(cx - lay.width / 2), int(cy - lay.height / 2)))


def paste_at(img, lay, x, y, alpha=1.0):
    if alpha < 0.995:
        a = lay.getchannel("A").point(lambda v: int(v * max(0.0, alpha)))
        lay = lay.copy()
        lay.putalpha(a)
    img.alpha_composite(lay, (int(x), int(y)))


def per_char_bounce(img, txt, size, cx, cy, t0, t, dur=0.5, stagger=0.045,
                    fill=((255, 250, 160), (255, 150, 30)), stroke=(255, 255, 255, 255),
                    sw=6, hop=26, fnt_path=F_YAHEI, squash=0.95, spacing=0.0):
    """逐字弹跳：每个字按 stagger 依次弹出，并带一次向上跳跃。"""
    if t < t0:
        return
    chars = list(txt)
    if not chars:
        return
    fnt = font(fnt_path, size)
    # 预备每字宽
    widths = []
    for ch in chars:
        tw, th, b = text_size(ch, fnt, sw)
        widths.append(max(tw, int(size * 0.5)))
    gap = spacing
    total = sum(widths) + gap * (len(chars) - 1)
    x = cx - total / 2.0
    for i, ch in enumerate(chars):
        dt = t - (t0 + i * stagger)
        if dt < 0:
            x += widths[i] + gap
            continue
        p = clamp01(dt / dur)
        s = ease_out_back(p)
        # 跳跃：sin 半周期，随弹出完成落回
        jp = clamp01(dt / (dur * 1.7))
        hop_y = -hop * math.sin(math.pi * min(1.0, jp)) if jp < 1.0 else 0.0
        scale = max(0.05, s)
        lay = big_text(ch, size, fill=fill, stroke=stroke[:3], sw=sw,
                       proj=True, squash=squash, fnt_path=fnt_path)
        if abs(scale - 1.0) > 0.01:
            lay = lay.resize((max(1, int(lay.width * scale)),
                              max(1, int(lay.height * scale))), Image.BILINEAR)
        al = clamp01(dt / max(0.06, dur * 0.5))
        w0 = widths[i] * squash
        paste_at(img, lay, x + (w0 - lay.width) / 2.0, cy - lay.height / 2.0 + hop_y, al)
        x += widths[i] + gap


def typewriter(img, txt, size, cx, cy, t0, t, cps=13.0, fnt_path=F_YAHEI,
               fill=(255, 255, 255), stroke=(0, 0, 0), sw=4):
    """打字机：按 cps 字/秒把前 n 个字绘制到 img 上，返回已写字数。"""
    if t < t0:
        return 0
    n = min(len(txt), max(0, int((t - t0) * cps)))
    if n <= 0:
        return 0
    fnt = font(fnt_path, size)
    d = ImageDraw.Draw(img)
    b = d.textbbox((0, 0), txt, font=fnt, stroke_width=sw)
    d.text((cx - (b[2] - b[0]) / 2.0 - b[0], cy - (b[3] - b[1]) / 2.0 - b[1]),
           txt[:n], font=fnt, fill=fill, stroke_width=sw, stroke_fill=stroke)
    return n
