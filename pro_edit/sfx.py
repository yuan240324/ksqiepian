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


def bumble(dur=0.65, seed=21):
    """喜剧"嗡嗡"下滑：卡通里摔倒/尴尬的标配长号声（wah-wah 感）。

    锯齿波做低音滑音 + 轻微颤音，尾巴向下掉音，听感滑稽。
    """
    t = _t(dur)
    n = len(t)
    # 音高：前 60% 稳住，后 40% 下滑一个半音阶
    k = np.clip(t / (dur * 0.6), 0, 1)
    fr = 220.0 * np.where(k < 1, 1.0, 1.0) * (0.84 ** np.clip((t - dur * 0.6) / (dur * 0.4), 0, 1))
    fr = fr * (1 + 0.035 * np.sin(2 * np.pi * 5.2 * t))
    ph = 2 * np.pi * np.cumsum(fr) / SR
    # 锯齿波：谐波递减叠加，模拟铜管
    saw = np.zeros(n)
    for h in range(1, 9):
        saw += (1.0 / h) * np.sin(h * ph)
    env = np.exp(-2.2 * t) * np.clip(t / 0.05, 0, 1)
    return _norm(_fade(saw * env), 0.55)


def slip(dur=0.42, f0=1500, f1=240, seed=23):
    """"呲溜"下滑哨音：打脸/翻车瞬间。"""
    t = _t(dur)
    fr = f0 * (f1 / f0) ** (t / dur)
    ph = 2 * np.pi * np.cumsum(fr) / SR
    a = np.sin(ph) * np.exp(-6.5 * t)
    rng = np.random.default_rng(seed)
    hiss = rng.standard_normal(len(t)) * np.exp(-26 * t) * 0.14
    return _norm(_fade(a + hiss), 0.5)


def hehe(dur=1.25, f=330, seed=25):
    """憋笑/偷笑：一串不规律的短促脉冲，像气声"嘿嘿嘿"。"""
    n = int(SR * dur)
    out = np.zeros(n)
    rng = np.random.default_rng(seed)
    gaps = [0.0, 0.19, 0.41, 0.58, 0.80, 1.02]
    for i, ts in enumerate(gaps):
        ln = 0.14
        tt = _t(ln)
        if len(tt) == 0:
            break
        fq = f * (1 + rng.uniform(-0.07, 0.09))
        tone = (np.sin(2 * np.pi * fq * tt) + 0.3 * np.sin(2 * np.pi * fq * 2 * tt))
        noise = rng.standard_normal(len(tt))
        # 气声成分：带通噪声近似（一阶低通后的噪声）
        y, prev = np.zeros(len(tt)), 0.0
        al = np.exp(-2 * np.pi * 1100 / SR)
        for j in range(len(tt)):
            prev = al * prev + (1 - al) * noise[j]
            y[j] = prev
        env = np.exp(-13 * tt) * np.clip(tt / 0.02, 0, 1)
        _add(out, (tone * 0.7 + y * 0.5) * env * 0.5, ts)
    return _norm(_fade(out, 15), 0.48)


def record(dur=1.15, seed=27):
    """唱片刮擦/急停："叽——"的高频噪声扫，用于"节目效果"突然反转。"""
    t = _t(dur)
    n = len(t)
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(n)
    y, prev = np.zeros(n), 0.0
    for i in range(n):
        f = 900 + 2600 * (1 - (i / float(n)) ** 0.7)
        al = np.exp(-2 * np.pi * f / SR)
        prev = al * prev + (1 - al) * noise[i]
        y[i] = prev
    env = np.clip(t / 0.03, 0, 1) * np.exp(-3.0 * t)
    return _norm(_fade(y * env), 0.5)


def tada(dur=1.25, seed=29):
    """反讽"当当当——"：三个下行和弦，用于"就这？"式收尾。

    与 rise 相反，这里刻意做成下行的"庆祝失败"感。
    """
    n = int(SR * dur)
    out = np.zeros(n)
    # 大三和弦根音下行：C -> A -> F（滑稽的"没救了"）
    notes = [(523.25, 392.00, 329.63), (440.00, 349.23, 261.63), (349.23, 261.63, 220.00)]
    for i, (a, b, c) in enumerate(notes):
        ts = i * 0.34
        ln = dur - ts
        tt = _t(ln)
        if len(tt) == 0:
            break
        tone = (np.sin(2 * np.pi * a * tt) + 0.8 * np.sin(2 * np.pi * b * tt)
                + 0.7 * np.sin(2 * np.pi * c * tt))
        env = np.exp(-3.4 * tt) * np.clip(tt / 0.012, 0, 1)
        _add(out, tone * env * 0.30, ts)
    return _norm(_fade(out, 20), 0.6)


SFX = {
    "whoosh": whoosh, "ding": ding, "boom": boom, "wow": wow,
    "clap": clap, "drumroll": drumroll, "rise": rise, "sub": sub, "tick": tick,
    "bumble": bumble, "slip": slip, "hehe": hehe, "record": record, "tada": tada,
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


def bgm_comedy(dur, bpm=118, seed=31):
    """喜剧底乐：大跳音程 + 停顿 + 滑音，专门给"搞笑切片"用。

    与 uplifting（一路欢快）不同，这里刻意制造"卡壳"感：
    旋律按"三连跳 + 突然停一拍 + 一个小下滑"循环，听起来更滑稽。
    另外加木鱼感的打点，强化喜剧节奏。
    """
    n = int(SR * dur)
    out = np.zeros(n)
    beat = 60.0 / bpm
    # 大跳：C4 - G4 - E4 - C5 - A4 - F4，跳进大、方向乱，制造笨拙感
    mel = [261.63, 392.00, 329.63, 523.25, 440.00, 349.23, 293.66, 466.16]
    rng = np.random.default_rng(seed)
    step = beat / 2.0
    k = 0
    ts = 0.0
    while ts < dur:
        # 每 6 个音后空一拍（喜剧的"停顿"）
        if k % 7 == 6:
            ts += step
            k += 1
            continue
        f = mel[k % len(mel)]
        # 最后一个音做下滑（吹奏走音感）
        slide = (k % 7 == 5)
        ln = min(step * (1.9 if slide else 1.15), dur - ts)
        tt = _t(ln)
        if len(tt) == 0:
            break
        if slide:
            fr = f * (1.0 - 0.16 * np.clip(tt / ln, 0, 1))
        else:
            fr = np.full(len(tt), f)
        ph = 2 * np.pi * np.cumsum(fr) / SR
        note = (np.sin(ph) + 0.35 * np.sin(2 * ph) + 0.12 * np.sin(3 * ph))
        note = note * np.exp(-5.0 * tt) * np.clip(tt / 0.012, 0, 1) * 0.20
        _add(out, note, ts)
        # 木鱼打点（每拍一下，短促噪声）
        if k % 2 == 0:
            click = rng.standard_normal(int(SR * 0.035)) * np.exp(
                -np.linspace(0, 26, int(SR * 0.035))) * 0.10
            _add(out, click, ts)
        if k % 4 == 0:
            _add(out, sub(0.16, 64) * 0.5, ts)
        ts += step
        k += 1
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


BGM = {"variety": bgm_uplifting, "commentary": bgm_cinematic,
       "rustic": bgm_rustic, "comedy": bgm_comedy}


def make_bgm(style, dur):
    return BGM[style](dur)
