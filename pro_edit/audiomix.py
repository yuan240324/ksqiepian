# -*- coding: utf-8 -*-
"""音轨混合器：decode 原声 -> 叠 BGM -> 爆点音效 -> 原声闪避 -> 限幅 -> 重编码。

用法（作为模块被 render_pro.py 调用）：
    mix = AudioMixer(src_path, dur)
    mix.bgm("variety")
    mix.sfx("boom", 3.2)
    mix.sfx("ding", 5.0, gain=0.7)
    mix.duck(3.0, 3.5, amount=0.45)   # 该区间原声压低
    mix.write(dst_path)

核心思路：
  1) 解码整条原声到 numpy（单声道求和后做处理，最后复制回立体声）
  2) BGM 全程铺底，但音量由包络控制（片头轻、正文抬、结尾收）
  3) 爆点处：原声 brief 闪避（让音效穿透）+ 音效叠加
  4) 最后统一限幅，避免叠加后削波爆音
"""
import numpy as np
import av
import sfx
from fractions import Fraction

SR = 44100


def decode_audio(path, sr=SR):
    """解码音频为 float32 单声道，返回 (array, 时长秒)。"""
    c = av.open(path)
    st = next(s for s in c.streams if s.type == "audio")
    res = av.AudioResampler(format="fltp", layout="mono", rate=sr)
    chunks = []
    for fr in c.decode(st):
        for rf in res.resample(fr):
            a = rf.to_ndarray()
            chunks.append(a.reshape(-1))
    # flush
    for rf in res.resample(None):
        a = rf.to_ndarray()
        chunks.append(a.reshape(-1))
    c.close()
    if not chunks:
        return np.zeros(1, dtype=np.float32), 0.0
    y = np.concatenate(chunks).astype(np.float32)
    return y, len(y) / float(sr)


def _smooth(arr, win_sec=0.06):
    """滑动平均平滑，避免增益突变的咔哒声。"""
    k = max(1, int(SR * win_sec))
    ker = np.ones(k, dtype=np.float32) / k
    return np.convolve(arr, ker, mode="same").astype(np.float32)


def _seg_env(n, points):
    """按 (时间秒, 增益) 控制点生成分段线性包络。"""
    if not points:
        return np.ones(n, dtype=np.float32)
    pts = sorted(points)
    xs = np.array([p[0] for p in pts], dtype=np.float32)
    ys = np.array([p[1] for p in pts], dtype=np.float32)
    t = np.arange(n, dtype=np.float32) / SR
    return np.interp(t, xs, ys).astype(np.float32)


def _add(dst, src, t0, gain=1.0):
    i = int(SR * t0)
    if i >= len(dst):
        return
    if i < 0:
        src = src[-i:]
        i = 0
    j = min(len(dst), i + len(src))
    dst[i:j] += src[:j - i] * gain


class AudioMixer:
    def __init__(self, src, dur=None, verbose=True):
        self.orig, self.odur = decode_audio(src)
        self.dur = float(dur if dur else self.odur)
        n = int(SR * self.dur)
        if len(self.orig) < n:
            self.orig = np.pad(self.orig, (0, n - len(self.orig)))
        else:
            self.orig = self.orig[:n]
        self.n = n
        self.bgm_style = None
        self.sfx_list = []
        self.duck_list = []
        self.verbose = verbose

    def bgm(self, style, gain=1.0):
        self.bgm_style = (style, gain)
        return self

    def sfx(self, name, t, gain=1.0, **kw):
        self.sfx_list.append((name, float(t), float(gain), kw))
        return self

    def duck(self, t0, t1, amount=0.5):
        """原声在 [t0, t1] 区间压低到 (1-amount)。"""
        self.duck_list.append((float(t0), float(t1), float(amount)))
        return self

    def render(self):
        n = self.n
        orig = self.orig.copy()

        # ---- 1) 原声增益包络：加淡入淡出，正常 1.0
        orig_env = np.ones(n, dtype=np.float32)
        fade = int(SR * 0.06)
        if n > 2 * fade:
            orig_env[:fade] = np.linspace(0, 1, fade)
            orig_env[-fade:] = np.linspace(1, 0, fade)

        # ---- 2) 闪避：把每个 duck 区间做成平滑凹陷
        duck_env = np.ones(n, dtype=np.float32)
        for (t0, t1, amt) in self.duck_list:
            i0 = max(0, int((t0 - 0.12) * SR))
            i1 = min(n, int((t1 + 0.12) * SR))
            if i1 <= i0:
                continue
            target = 1.0 - amt
            var = np.ones(i1 - i0, dtype=np.float32)
            # 0.12s 斜坡进入、保持、0.12s 斜坡退出
            k = min(int(SR * 0.12), (i1 - i0) // 2)
            if k > 0:
                var[:k] = np.linspace(1, target, k)
                var[-k:] = np.linspace(target, 1, k)
                var[k:-k] = target
            else:
                var[:] = target
            duck_env[i0:i1] = np.minimum(duck_env[i0:i1], var)
        duck_env = _smooth(duck_env, 0.03)
        orig_eff = orig * orig_env * duck_env

        # ---- 3) BGM：铺底 + 自带起伏
        bgm_track = np.zeros(n, dtype=np.float32)
        if self.bgm_style:
            style, g = self.bgm_style
            b = sfx.make_bgm(style, self.dur)
            if len(b) < n:
                b = np.pad(b, (0, n - len(b)))
            else:
                b = b[:n]
            # BGM 包络：片头 0.55 起 -> 0.9s 抬到 1.0 -> 结尾 2.5s 收到 0.35
            pts = [(0.0, 0.35), (0.7, 1.0), (max(0.8, self.dur - 2.5), 1.0),
                   (self.dur, 0.30)]
            benv = _seg_env(n, pts)
            bgm_track = b.astype(np.float32) * benv * g

        # ---- 4) 音效
        sfx_track = np.zeros(n, dtype=np.float32)
        for (name, t, g, kw) in self.sfx_list:
            a = sfx.make(name, **kw) if kw else sfx.make(name)
            _add(sfx_track, a.astype(np.float32), t, g)

        mix = orig_eff + bgm_track + sfx_track

        # ---- 5) 限幅：软膝压限，避免削波
        peak = float(np.max(np.abs(mix))) or 1.0
        if peak > 0.95:
            # 用 tanh 软限幅保留动态
            drive = 0.95 / peak
            mix = np.tanh(mix * drive * 1.25) / 1.25
        # 再做一次峰值归一，留 -1.5dB 余量
        pk2 = float(np.max(np.abs(mix))) or 1.0
        if pk2 > 0:
            mix = mix / pk2 * 0.84

        if self.verbose:
            print("  AUDIO mix: orig %.3f bgm %.3f sfx %.3f -> peak %.3f" % (
                float(np.sqrt((orig_eff ** 2).mean())),
                float(np.sqrt((bgm_track ** 2).mean())),
                float(np.sqrt((sfx_track ** 2).mean())),
                float(np.max(np.abs(mix)))))
        return mix.astype(np.float32)

    def write(self, dst):
        """把混合结果编码为 aac 写入 dst（dst 为仅音频的中间文件）。"""
        mix = self.render()
        out = av.open(dst, "w")
        st = out.add_stream("aac", rate=SR)
        st.layout = "stereo"
        st.bit_rate = 192000
        # 立体声复制（轻微展宽：左右各偏一点，避免完全单声道）
        L = mix
        R = np.roll(mix, int(SR * 0.0006))
        stereo = np.stack([L, R], axis=1).astype(np.float32)
        # 分块喂入，每块 0.1s
        step = int(SR * 0.1)
        pts = 0
        for i in range(0, len(stereo), step):
            blk = stereo[i:i + step]          # (samples, 2)
            arr = np.ascontiguousarray(blk.T)  # fltp planar -> (2, samples)
            fr = av.AudioFrame.from_ndarray(arr, format="fltp", layout="stereo")
            fr.sample_rate = SR
            fr.pts = pts
            fr.time_base = Fraction(1, SR)
            pts += blk.shape[0]
            for p in st.encode(fr):
                out.mux(p)
        for p in st.encode(None):
            out.mux(p)
        out.close()
        return dst
