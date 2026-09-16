# -*- coding: utf-8 -*-
"""Overlay title bar + danmaku-style comments onto a clip and re-encode.

Pipeline: decode video frames -> PIL draws text -> libx264 re-encode;
audio decoded from a SEPARATE handle (PyAV demuxer is single-pass) -> aac.

No drawtext filter exists in bundled PyAV, hence the PIL route.
"""
import av
import numpy as np
from fractions import Fraction
from PIL import Image, ImageDraw, ImageFont

SRC = r"G:\trea\切片\clips\raw_funny_00105.mp4"
DST = r"G:\trea\切片\搞笑名场面.mp4"
W, H, FPS = 1280, 960, 30
US = Fraction(1, 1_000_000)   # 统一微秒时间基准
FONT_TITLE = r"C:\Windows\Fonts\msyhbd.ttc"   # 微软雅黑 加粗
FONT_DANMAKU = r"C:\Windows\Fonts\msyh.ttc"
SIZE_TITLE = 76
SIZE_DANMAKU = 46
SIZE_END = 56

# (start_sec, end_sec, text, y_fraction, speed_px_per_sec)
DANMAKU = [
    (3.0, 9.0,  "哈哈哈哈哈哈哈",        0.16, 260.0),
    (12.0, 18.0, "主播这波我直接笑死",    0.30, 250.0),
    (21.0, 27.0, "这也太秀了吧 哈哈",    0.22, 260.0),
    (30.0, 36.0, "弹幕护体 笑不活了",    0.34, 250.0),
    (39.0, 45.0, "名场面预定！",         0.16, 260.0),
    (48.0, 54.0, "哈哈哈哈 再来一遍",    0.12, 250.0),
]
TITLE = ("搞笑名场面", 0.6, 4.0)          # (text, start, end) 顶部大字
ENDTXT = ("前5分钟 · 名场面回放", 55.0, 60.0)  # (text, start, end) 结尾卡


def _font(path, size):
    return ImageFont.truetype(path, size)


def _text_size(d, txt, fnt):
    b = d.textbbox((0, 0), txt, font=fnt)
    return b[2] - b[0], b[3] - b[1]


def overlay(img, t):
    """img: PIL RGB; t: seconds within clip. Returns new PIL image."""
    d = ImageDraw.Draw(img)

    # ── 顶部标题条 ─────────────────────────────────────────────
    if TITLE[1] <= t < TITLE[2]:
        txt, fnt = TITLE[0], _font(FONT_TITLE, SIZE_TITLE)
        w, h = _text_size(d, txt, fnt)
        x = (W - w) // 2
        y = 28
        d.rectangle([0, 12, W, y + h + 22], fill=(0, 0, 0, 180))
        d.text((x + 4, y + 4), txt, font=fnt, fill=(0, 0, 0))
        d.text((x, y), txt, font=fnt, fill=(255, 210, 40))
        d.text((x, y), txt, font=fnt, fill=(255, 220, 60), stroke_width=3,
               stroke_fill=(160, 60, 0))

    # ── 底部结尾卡片 ─────────────────────────────────────────────
    if ENDTXT[1] <= t < ENDTXT[2]:
        txt, fnt = ENDTXT[0], _font(FONT_TITLE, SIZE_END)
        w, h = _text_size(d, txt, fnt)
        x = (W - w) // 2
        y = H - h - 64
        d.rectangle([0, H - h - 96, W, H - 24], fill=(18, 18, 30))
        d.rectangle([0, H - h - 96, W, H - h - 88], fill=(255, 210, 40))
        d.text((x + 4, y + 4), txt, font=fnt, fill=(0, 0, 0))
        d.text((x, y), txt, font=fnt, fill=(255, 220, 60))
        d.text((x, y), txt, font=fnt, fill=(255, 220, 60), stroke_width=3,
               stroke_fill=(90, 50, 0))

    # ── 弹幕飘屏 ───────────────────────────────────────────────
    fnt = _font(FONT_DANMAKU, SIZE_DANMAKU)
    for s, e, txt, yf, speed in DANMAKU:
        if not (s <= t < e):
            continue
        w, h = _text_size(d, txt, fnt)
        span = W + w + 60.0
        x = W + 30 - (t - s) * speed
        if x < -w - 30:
            continue
        y = int(H * yf)
        # 深色描边，保证任何画面都清晰
        d.text((x + 3, y + 3), txt, font=fnt, fill=(0, 0, 0))
        d.text((x, y), txt, font=fnt, fill=(255, 255, 255))
        d.text((x, y), txt, font=fnt, fill=(255, 255, 255),
               stroke_width=3, stroke_fill=(40, 40, 40))
    return img


def main():
    # ── 视频：独立句柄 ──────────────────────────────────────────
    cin_v = av.open(SRC)
    vst = cin_v.streams.video[0]

    # ── 音频：独立句柄（同句柄先解视频会把包队列抽干） ──────────
    cin_a = av.open(SRC)
    ast = cin_a.streams.audio[0]

    cout = av.open(DST, "w")
    vout = cout.add_stream("libx264", rate=FPS)
    vout.width, vout.height = W, H
    vout.pix_fmt = "yuv420p"
    vout.options = {"preset": "veryfast", "crf": "20"}
    aout = cout.add_stream("aac", rate=ast.sample_rate)
    aout.layout = "stereo"
    aout.format = "fltp"
    aout.bit_rate = 128000

    n = 0
    for fr in cin_v.decode(vst):
        t = float(fr.pts * fr.time_base)
        img = fr.to_image().convert("RGB")
        img = overlay(img, t)
        arr = np.asarray(img)
        nf = av.VideoFrame.from_ndarray(arr, format="rgb24").reformat(
            width=W, height=H, format="yuv420p")
        nf.time_base = US
        nf.pts = int(round(t * 1_000_000))
        for pkt in vout.encode(nf):
            cout.mux(pkt)
        n += 1
        if n % 600 == 0:
            print("  video %d frames (t=%.0fs)" % (n, t), flush=True)
    for pkt in vout.encode(None):
        cout.mux(pkt)
    print("video done: %d frames" % n)

    na = 0
    a_sec = 0.0
    rs = av.AudioResampler(format="fltp", layout="stereo",
                           rate=ast.sample_rate)
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
    print("audio done: %d frames (%.1fs)" % (na, a_sec))

    cout.close()
    cin_v.close()
    cin_a.close()
    print("OVERLAY_DONE -> %s" % DST)


if __name__ == "__main__":
    main()
