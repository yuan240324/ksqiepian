# -*- coding: utf-8 -*-
"""视觉特效库：震屏、推近/拉远、闪白/闪黑、缩放脉冲、镜头漂移。

所有函数只操作"内容层"图像（9:16 里的原始画面区），返回变换后的图像。
设计原则：
  1) 变换围绕内容区中心，不越界（用 resize + crop 实现，不产生黑边）
  2) 时间参数 t 为全局秒，方便和音频节拍对齐
  3) 缓动统一用 ease-out，落地更自然
"""
from PIL import Image


def ease_out_cubic(p):
    p = max(0.0, min(1.0, p))
    return 1 - (1 - p) ** 3


def ease_out_back(p, s=1.70158):
    p = max(0.0, min(1.0, p))
    return 1 + (s + 1) * (p - 1) ** 3 + s * (p - 1) ** 2


def shake_offset(t, t0, dur=0.4, amp=18, freq=42, decay=7.0):
    """震屏位移： (dx, dy)。t0 起震，按指数衰减，两轴不同频避免规律感。"""
    import math
    dt = t - t0
    if dt < 0 or dt > dur:
        return 0.0, 0.0
    e = math.exp(-decay * dt)
    dx = amp * e * math.sin(2 * math.pi * freq * dt)
    dy = amp * e * math.cos(2 * math.pi * freq * 0.87 * dt)
    return dx, dy


def apply_shake(img, dx, dy):
    """对内容层做位移：平移后把露出的边用图像自身边缘拉伸填补。"""
    if abs(dx) < 0.5 and abs(dy) < 0.5:
        return img
    w, h = img.size
    ox, oy = int(round(dx)), int(round(dy))
    # 先整体平移到一个略大的画布，再用边缘像素补边
    big = Image.new(img.mode, (w + 2 * abs(ox), h + 2 * abs(oy)))
    src = img
    # 边缘拉伸：按方向复制边条
    if ox > 0:
        left = img.crop((0, 0, 1, h)).resize((ox, h))
        src = Image.new(img.mode, (w + ox, h))
        src.paste(left, (0, 0))
        src.paste(img, (ox, 0))
    elif ox < 0:
        right = img.crop((w - 1, 0, w, h)).resize((-ox, h))
        src = Image.new(img.mode, (w - ox, h))
        src.paste(img, (0, 0))
        src.paste(right, (w, 0))
    if oy > 0 or oy < 0:
        sw, sh = src.size
        if oy > 0:
            top = src.crop((0, 0, sw, 1)).resize((sw, oy))
            s2 = Image.new(src.mode, (sw, sh + oy))
            s2.paste(top, (0, 0))
            s2.paste(src, (0, oy))
        else:
            bot = src.crop((0, sh - 1, sw, sh)).resize((sw, -oy))
            s2 = Image.new(src.mode, (sw, sh - oy))
            s2.paste(src, (0, 0))
            s2.paste(bot, (0, sh))
        src = s2
    # 裁回内容层大小（以中心对齐）
    sw, sh = src.size
    cx, cy = (sw - w) // 2, (sh - h) // 2
    return src.crop((cx, cy, cx + w, cy + h))


def push_in(img, p, amount=0.13):
    """推近：p 从 0→1 时内容放大约 amount 倍，中心对齐无黑边。"""
    k = 1.0 + amount * ease_out_cubic(p)
    return zoom(img, k)


def zoom(img, k):
    """按系数 k 缩放并中心裁剪回原尺寸（无黑边）。"""
    if abs(k - 1.0) < 0.002:
        return img
    w, h = img.size
    nw, nh = max(w, int(w * k + 0.5)), max(h, int(h * k + 0.5))
    big = img.resize((nw, nh), Image.BILINEAR)
    x, y = (nw - w) // 2, (nh - h) // 2
    return big.crop((x, y, x + w, y + h))


def flash(img, strength):
    """闪白：strength 0~1 叠加白色。"""
    if strength <= 0.004:
        return img
    s = min(1.0, float(strength))
    white = Image.new(img.mode, img.size, (255, 255, 255))
    return Image.blend(img, white, s)


def flash_black(img, strength):
    """闪黑：转场用。"""
    if strength <= 0.004:
        return img
    s = min(1.0, float(strength))
    black = Image.new(img.mode, img.size, (0, 0, 0))
    return Image.blend(img, black, s)


def vignette(img, strength=0.30, cy=0.0, chh=1.0):
    """暗角，让视线聚焦中心。cy/chh 用来把焦点对齐内容层中心。"""
    if strength <= 0.004:
        return img
    w, h = img.size
    # 生成径向渐变遮罩（缓存到函数属性，避免每帧重算）
    key = (w, h, round(cy, 3), round(chh, 3))
    if getattr(vignette, "_k", None) != key:
        import numpy as np
        yy, xx = np.mgrid[0:h, 0:w]
        cx, yc = w / 2.0, cy + chh / 2.0
        r = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - yc) / (chh / 2.0)) ** 2)
        m = np.clip((r - 0.58) / 0.72, 0, 1) ** 1.5
        vignette._k = key
        vignette._m = (m * 255).astype("uint8")
    dark = Image.new(img.mode, (w, h), (0, 0, 0))
    alpha = Image.fromarray(vignette._m, "L").point(lambda v: int(v * strength))
    return Image.composite(dark, img, alpha)


def vignette_mask(size, strength=0.30):
    """生成可复用的暗角 RGBA 叠加层，直接用 alpha_composite 叠加。"""
    if strength <= 0.004:
        return None
    w, h = size
    import numpy as np
    yy, xx = np.mgrid[0:h, 0:w]
    cx, yc = w / 2.0, h / 2.0
    r = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - yc) / yc) ** 2)
    m = np.clip((r - 0.58) / 0.72, 0, 1) ** 1.5
    alpha = Image.fromarray((m * 255).astype("uint8"), "L").point(
        lambda v: int(v * strength))
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    overlay.putalpha(alpha)
    return overlay


def saturate(img, k=1.12):
    """提高饱和度，让画面更"跳"。"""
    if abs(k - 1.0) < 0.01:
        return img
    from PIL import ImageEnhance
    return ImageEnhance.Color(img).enhance(k)


def contrast(img, k=1.06):
    if abs(k - 1.0) < 0.01:
        return img
    from PIL import ImageEnhance
    return ImageEnhance.Contrast(img).enhance(k)
