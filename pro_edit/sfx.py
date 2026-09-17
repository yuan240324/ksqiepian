# -*- coding: utf-8 -*-
"""音效合成库：用 numpy 纯合成短视频常用音效，不依赖外部素材。

音效设计目标（快手切片常用）：
  whoosh   转场/花字入场  白噪声 + 带通扫频
  ding     花字出现        高频正弦 + 指数衰减（清脆叮）
  boom     笑点爆点        低频正弦下扫 + 噪声冲击（咚）
  wow      震惊/名场面     双音上滑 + 合唱感（哇哦）
  clap     掌声            多段噪声脉冲（鼓掌）
  drumroll 铺垫/倒数       重复短脉冲 + 渐强
  rise     情绪抬升        频率渐升的噪声 +
  sub      重低音          极低频正弦，做节奏地基

每个函数统一返回 float32 单声道数组，值域约 [-1, 1]，采样率 SR。
"""
import numpy as np

SR = 44100


def _t(dur):
    return np.arange(int(SR * dur)) / float(SR)


def _env(a, attack=0.005, decay=1.0):
    """攻击 + 指数衰减包络。"""
    n = len(a)
    at = max(1, int(SR * attack))
    e = np.ones(n)
    e[:at] = np.linspace(0, 1, at)
    tail = np.exp(-decay * np.linspace(0, 6, n - at))
    e[at:] = tail
    return a * e


def _fade(a, ms=8):
    n = len(a)
    k = max(1, int(SR * ms / 1000.0))
    if 2 * k >= n:
        return a
    a = a.copy()
    a[:k] *= np.linspace(0, 1, k)
    a[-k:] *= np.linspace(1, 0, k)
    return a


def _norm(a, peak=0.9):
    m = float(np.max(np.abs(a))) or 1.0
    return (a / m * peak).astype(np.float32)


def whoosh(dur=0.55, f0=380, f1=4200, seed=0):
    """白噪声 + 扫频带通，模拟"咻"的转场声。"""
    rng = np.random.default_rng(seed)
    n = int(SR * dur)
    noise = rng.standard_normal(n)
    # 用一阶 IIR 近似扫频带通：截止频率随时间上升
    y = np.zeros(n)
    prev = 0.0
    for i in range(n):
        f = f0 + (f1 - f0) * (i / float(n)) ** 1.6
        al = np.exp(-2 * np.pi * f / SR)
        prev = al * prev + (1 - al) * noise[i]
        y[i] = prev
    e = np.linspace(0, 1, n) ** 2 * np.exp(-2.2 * np.linspace(0, 1, n))
    return _norm(_fade(y * e), 0.75)


def ding(f=2100, dur=0.85, partials=(1.0, 2.01, 3.03), amps=(1.0, 0.42, 0.18)):
    """清脆叮声：多个非整数倍泛音 + 指数衰减。"""
    t = _t(dur)
    a = np.zeros_like(t)
    for p, am in zip(partials, amps):
        a += am * np.sin(2 * np.pi * f * p * t) * np.exp(-6.5 * p * t)
    return _norm(_fade(a), 0.68)


def boom(f0=150, f1=42, dur=1.15, seed=1):
    """重低音"咚"：正弦下扫 + 短噪声冲击，用于笑点/爆点。"""
    t = _t(dur)
    n = len(t)
    # 频率指数下扫
    fr = f0 * (f1 / f0) ** (t / dur)
    ph = 2 * np.pi * np.cumsum(fr) / SR
    a = np.sin(ph) * np.exp(-4.2 * t)
    # 起始冲击噪声
    rng = np.random.default_rng(seed)
    imp = rng.standard_normal(n) * np.exp(-70 * t) * 0.5
    return _norm(_fade(a + imp, 5), 0.95)


def wow(dur=1.1, f0=380, f1=900, vib=5.5):
    """"哇哦"式起伏音：双音上滑带颤音。"""
    t = _t(dur)
    fr = f0 * (f1 / f0) ** (t / dur)
    fr = fr * (1 + 0.02 * np.sin(2 * np.pi * vib * t))
    ph = 2 * np.pi * np.cumsum(fr) / SR
    a = np.sin(ph) + 0.55 * np.sin(2 * ph) + 0.2 * np.sin(3 * ph)
    env = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 0.7
    return _norm(_fade(a * env), 0.62)


def clap(dur=0.75, nclap=7, seed=3):
    """掌声：多段带通噪声脉冲。"""
    rng = np.random.default_rng(seed)
    n = int(SR * dur)
    out = np.zeros(n)
    for i in range(nclap):
        pos = int(n * (0.03 + 0.9 * i / float(nclap)) * rng.uniform(0.85, 1.15))
        if pos >= n:
            continue
        ln = int(SR * 0.045)
        seg = rng.standard_normal(min(ln, n - pos)) * np.exp(-45 * np.linspace(0, 1, min(ln, n - pos)))
        out[pos:pos + len(seg)] += seg * rng.uniform(0.6, 1.0)
    k = int(SR * 0.004)
    if k * 2 < n:
        out = np.convolve(out, np.ones(k) / k, mode="same")
    return _norm(_fade(out), 0.55)


def drumroll(dur=1.4, rate=22, seed=5):
    """鼓点铺垫：短脉冲密集重复并渐强。"""
    rng = np.random.default_rng(seed)
    n = int(SR * dur)
    out = np.zeros(n)
    step = SR / float(rate)
    i = 0.0
    while i < n:
        p = int(i)
        amp = 0.25 + 0.75 * (i / float(n))
        ln = int(SR * 0.05)
        seg = rng.standard_normal(min(ln, n - p)) * np.exp(-38 * np.linspace(0, 1, min(ln, n - p)))
        out[p:p + len(seg)] += seg * amp
        i += step * rng.uniform(0.94, 1.06)
    return _norm(_fade(out), 0.6)


def rise(dur=0.9, f0=200, f1=3000, seed=7):
    """情绪抬升：噪声 + 音调渐升的正弦，做 hook 前的铺垫。"""
    rng = np.random.default_rng(seed)
    t = _t(dur)
    noise = rng.standard_normal(len(t))
    k = int(SR * 0.006)
    if k * 2 < len(t):
        noise = np.convolve(noise, np.ones(k) / k, mode="same")
    fr = f0 * (f1 / f0) ** (t / dur)
    ph = 2 * np.pi * np.cumsum(fr) / SR
    tone = np.sin(ph) * 0.5
    env = (t / dur) ** 1.5
    return _norm(_fade((noise * 0.55 + tone) * env), 0.62)


def sub(dur=0.35, f=58):
    """重低音脉冲，垫在节拍上做地基。"""
    t = _t(dur)
    return _norm(_fade(np.sin(2 * np.pi * f * t) * np.exp(-9 * t), 4), 0.85)


def tick(dur=0.09, f=1400):
    """极短点击，用于打字机/字幕逐字。"""
    t = _t(dur)
    a = np.sin(2 * np.pi * f * t) * np.exp(-55 * t)
    return _norm(_fade(a), 0.4)


SFX = {
    "whoosh": whoosh, "ding": ding, "boom": boom, "wow": wow,
    "clap": clap, "drumroll": drumroll, "rise": rise, "sub": sub, "tick": tick,
}


def make(name, **kw):
    return SFX[name](**kw)


# ---------------------------------------------------------------- BGM 合成

def _chord(freqs, dur, detune=0.004):
    """把一组频率叠成和弦，带轻微失谐制造合唱感。"""
    t = _t(dur)
    a = np.zeros_like(t)
    for f in freqs:
        for d in (-detune, 0.0, detune):
            a += np.sin(2 * np.pi * f * (1 + d) * t)
    return a / max(1, len(freqs) * 3)


def bgm_uplifting(dur, bpm=112, seed=11):
    """轻松上扬的底乐，适合综艺花字风。

    C 大调级进：C - Am - F - G，八分音符琶音 + 柔和 pad。
    """
    rng = np.random.default_rng(seed)
    n = int(SR * dur)
    out = np.zeros(n)
    beat = 60.0 / bpm
    prog = [
        [261.63, 329.63, 392.00],   # C
        [220.00, 261.63, 329.63],   # Am
        [174.61, 261.63, 349.23],   # F
        [196.00, 246.94, 392.00],   # G
    ]
    bar = beat * 4
    nbar = int(np.ceil(dur / bar))
    for bi in range(nbar):
        ch = prog[bi % len(prog)]
        t0 = bi * bar
        # pad：整小节铺底
        seg_d = min(bar, dur - t0)
        if seg_d <= 0:
            continue
        pad = _chord(ch, seg_d) * 0.30
        e = np.sin(np.pi * np.clip(np.linspace(0, 1, len(pad)), 0, 1)) ** 0.5
        _add(out, pad * e, t0)
        # 琶音：每半拍一个音，上行
        for k in range(8):
            ts = t0 + k * (beat / 2)
            if ts >= dur:
                break
            f = ch[k % len(ch)] * (2 if k >= 6 else 1)
            ln = beat / 2 * 1.5
            tt = _t(min(ln, dur - ts))
            if len(tt) == 0:
                break
            note = np.sin(2 * np.pi * f * tt) * np.exp(-5.5 * tt) * 0.16
            _add(out, note, ts)
        # 轻打点
        for k in range(4):
            ts = t0 + k * beat
            if ts >= dur:
                break
            _add(out, sub(0.22) * 0.5, ts)
    return _norm(_fade(out, 40), 0.30)


def bgm_cinematic(dur, bpm=92, seed=13):
    """沉稳推进的底乐，适合解说盘点风。

    A 小调：Am - F - G - Em，长音 pad + 低音脉冲推进。
    """
    n = int(SR * dur)
    out = np.zeros(n)
    beat = 60.0 / bpm
    prog = [
        [220.00, 261.63, 329.63],
        [174.61, 220.00, 261.63],
        [196.00, 246.94, 293.66],
        [164.81, 196.00, 246.94],
    ]
    bar = beat * 4
    nbar = int(np.ceil(dur / bar))
    for bi in range(nbar):
        ch = prog[bi % len(prog)]
        t0 = bi * bar
        seg_d = min(bar, dur - t0)
        if seg_d <= 0:
            continue
        pad = _chord(ch, seg_d, detune=0.006) * 0.34
        e = np.sin(np.pi * np.clip(np.linspace(0, 1, len(pad)), 0, 1)) ** 0.4
        _add(out, pad * e, t0)
        # 低音：每拍一次，沉稳推进
        for k in range(4):
            ts = t0 + k * beat
            if ts >= dur:
                break
            ln = min(beat * 0.9, dur - ts)
            tt = _t(ln)
            b = np.sin(2 * np.pi * ch[0] / 2 * tt) * np.exp(-3.2 * tt) * 0.42
            _add(out, b, ts)
    return _norm(_fade(out, 40), 0.30)


def bgm_rustic(dur, bpm=126, seed=17):
    """土味喜庆底乐：五声音阶 + 弹跳感，适合土味老铁风。

    五声音阶 C D E G A，快速上下跳进 + 打点，喜庆热闹。
    """
    n = int(SR * dur)
    out = np.zeros(n)
    beat = 60.0 / bpm
    penta = [261.63, 293.66, 329.63, 392.00, 440.00, 523.25]
    pat = [0, 2, 4, 3, 5, 4, 2, 1]
    nhalf = int(np.ceil(dur / (beat / 2)))
    for k in range(nhalf):
        ts = k * (beat / 2)
        if ts >= dur:
            break
        idx = pat[k % len(pat)]
        f = penta[idx]
        ln = min(beat / 2 * 1.3, dur - ts)
        tt = _t(ln)
        if len(tt) == 0:
            break
        # 方波感（喜庆唢呐味）：奇次谐波叠加
        note = (np.sin(2 * np.pi * f * tt) + 0.4 * np.sin(2 * np.pi * f * 3 * tt)
                + 0.2 * np.sin(2 * np.pi * f * 5 * tt)) * np.exp(-4.5 * tt) * 0.18
        _add(out, note, ts)
        if k % 2 == 0:
            _add(out, sub(0.18, 62) * 0.55, ts)
    return _norm(_fade(out, 40), 0.30)


def _add(dst, src, t0):
    """把 src 叠加到 dst 的 t0 秒处，越界自动裁剪。"""
    i = int(SR * t0)
    if i >= len(dst):
        return
    if i < 0:
        src = src[-i:]
        i = 0
    j = min(len(dst), i + len(src))
    dst[i:j] += src[:j - i]


BGM = {"variety": bgm_uplifting, "commentary": bgm_cinematic, "rustic": bgm_rustic}


def make_bgm(style, dur):
    return BGM[style](dur)
