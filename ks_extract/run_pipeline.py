# -*- coding: utf-8 -*-
"""一键跑完提取链路 step 1-4 + step 6。

用法:
    python ks_extract/run_pipeline.py "<分享口令或短链>" [输出目录]

例:
    python ks_extract/run_pipeline.py "https://v.kuaishou.com/f/X56ZfKJb622Z1i7" "G:\\ksrec\\replay"

脚本会自动:
    1. 跟随 302 解析出回放页 URL
    2. 抓回放页 HTML
    3. 列出全部回放，自动选中 GameAvcHd 那一条
    4. 8 线程下载全部分片（断点续传）
    5. 二进制拼接成 merged.ts
    6. PyAV 透传重封装为 MP4
    7. 打印验证提示

依赖: pip install av
"""
import os
import re
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import av
except ImportError:
    sys.exit("缺少 PyAV，请先执行: python -m pip install -i "
             "https://pypi.tuna.tsinghua.edu.cn/simple av")

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
REF = "https://v.kuaishou.com/"
WORKERS = 8
CHUNK = 188  # MPEG-TS 包长


def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def http_get(url, retries=4, timeout=30, decode=True):
    """带重试的 GET。返回 bytes 或 str。"""
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Referer": REF,
                "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
                return data.decode("utf-8", "ignore") if decode else data
        except Exception as e:
            last = e
            time.sleep(1.2 * (i + 1))
    raise last


# ── step 1 ──────────────────────────────────────────────────────────
def step1_resolve(text):
    """从分享口令或短链解析出回放页 URL。"""
    log("step1 解析口令/短链 ...")

    # 分享口令形态: ##X56ZfKJb622Z1i7##
    m = re.search(r"##([A-Za-z0-9_\-]+)##", text)
    if m:
        token = m.group(1)
        url = "https://v.kuaishou.com/f/%s" % token
        log("  从口令提取 token = %s" % token)
    elif text.startswith("http"):
        url = text
    else:
        # 裸 token
        url = "https://v.kuaishou.com/f/%s" % text.strip()
        log("  按裸 token 处理 = %s" % text.strip())

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=25) as r:
            final = r.geturl()
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location") if e.headers else None
        if not loc:
            raise
        final = loc

    log("  FINAL = %s" % final[:160])
    pid = re.search(r"playback/(\d+)", final)
    if pid:
        log("  回放 ID = %s" % pid.group(1))
    if "LIVE_PLAYBACK" in final:
        log("  已确认 subBiz=LIVE_PLAYBACK（直播回放）")
    return final


# ── step 2 ──────────────────────────────────────────────────────────
def step2_scrape(page_url, outdir):
    log("step2 抓取回放页 ...")
    body = http_get(page_url, timeout=30)
    path = os.path.join(outdir, "playback_body.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    log("  HTML %d bytes -> %s" % (len(body), path))
    return body


# ── step 3 ──────────────────────────────────────────────────────────
def step3_pick(body):
    log("step3 提取并挑选 m3u8 ...")
    cands = []
    seen = set()
    for m in re.finditer(r'(https?://[^\s"\'<>\\]+\.m3u8[^\s"\'<>\\]*)', body):
        url = m.group(1).replace("\\u002F", "/").replace("\\/", "/")
        if url in seen:
            continue
        seen.add(url)
        ctx = body[max(0, m.start() - 1500):m.end() + 1500]
        item = {"url": url}
        for pat, key in [
            (r'"duration"\s*:\s*(\d+)', "duration_ms"),
            (r'"photoId"\s*:\s*"([^"]+)"', "photoId"),
            (r'"caption"\s*:\s*"([^"]{0,80})"', "caption"),
            (r'"livePlaybackClarityLevel"\s*:\s*"([^"]+)"', "clarity"),
        ]:
            mm = re.search(pat, ctx)
            if mm:
                item[key] = mm.group(1)
        cands.append(item)

    log("  找到 %d 条唯一 m3u8" % len(cands))
    for i, c in enumerate(cands, 1):
        d = c.get("duration_ms")
        dur = ("%.1f min" % (int(d) / 60000.0)) if d and str(d).isdigit() else "?"
        log("    [%d] dur=%s clarity=%s" % (i, dur, c.get("clarity", "?")))
        log("        %s" % c["url"][:150])

    if not cands:
        sys.exit("未找到任何 m3u8，回放可能已被删除或未开启")

    primary = next((c for c in cands if "GameAvcHd" in c["url"]), cands[-1])
    log("  选中: %s" % primary["url"][:150])
    return primary


# ── step 4 ──────────────────────────────────────────────────────────
def step4_download(m3u8_url, segdir):
    log("step4 下载分片 ...")
    os.makedirs(segdir, exist_ok=True)

    man = http_get(m3u8_url, timeout=30)
    base = m3u8_url.rsplit("/", 1)[0] + "/"
    segs = [ln.strip() for ln in man.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]
    total = len(segs)
    log("  manifest %d bytes, %d 分片" % (len(man), total))

    tasks = []
    for idx, name in enumerate(segs):
        path = os.path.join(segdir, "%05d.ts" % idx)   # 零填充，保证排序正确
        tasks.append((idx, name if name.startswith("http") else base + name, path))

    pending = [t for t in tasks
               if not (os.path.exists(t[2]) and os.path.getsize(t[2]) > 0)]
    log("  已有 %d，待下载 %d" % (total - len(pending), len(pending)))

    def worker(t):
        idx, url, path = t
        data = http_get(url, decode=False)
        tmp = path + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)          # 原子落盘
        return idx, len(data)

    fail = []
    if pending:
        done = 0
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(worker, t): t for t in pending}
            for fut in as_completed(futs):
                t = futs[fut]
                try:
                    fut.result()
                    done += 1
                    if done % 100 == 0 or done == len(pending):
                        el = max(time.time() - t0, 1e-6)
                        log("    %d/%d  (%.1f 片/秒)" % (done, len(pending), done / el))
                except Exception as e:
                    fail.append((t[0], repr(e)))
                    log("    FAIL idx=%d %r" % (t[0], e))

    missing = [t[0] for t in tasks
               if not (os.path.exists(t[2]) and os.path.getsize(t[2]) > 0)]
    total_bytes = sum(os.path.getsize(t[2]) for t in tasks if os.path.exists(t[2]))
    log("  完成 %d/%d，失败 %d，共 %.1f MB"
        % (total - len(missing), total, len(fail), total_bytes / 1048576.0))

    if missing:
        log("  缺失 %s —— 直接重跑本脚本即可续传" % missing[:20])
        sys.exit(1)

    # 抽检首片 TS 同步字
    with open(tasks[0][2], "rb") as f:
        head = f.read(CHUNK * 50)
    ok = sum(1 for i in range(50) if head[i * CHUNK] == 0x47)
    log("  首片 TS sync 抽检 = %d/50" % ok)
    return tasks


# ── step 5 ──────────────────────────────────────────────────────────
def step5_concat(tasks, workdir):
    log("step5 二进制拼接 ...")
    out = os.path.join(workdir, "merged.ts")
    n = 0
    t0 = time.time()
    with open(out, "wb") as fo:
        for idx, url, path in tasks:
            with open(path, "rb") as fi:
                while True:
                    buf = fi.read(8 << 20)
                    if not buf:
                        break
                    fo.write(buf)
            n += 1
    size = os.path.getsize(out)
    log("  拼接 %d 片 -> %s (%.1f MB, %.0fs)"
        % (n, out, size / 1048576.0, time.time() - t0))

    with open(out, "rb") as f:
        head = f.read(CHUNK * 20)
    ok = sum(1 for i in range(20) if head[i * CHUNK] == 0x47)
    log("  拼接结果 TS sync 抽检 = %d/20" % ok)
    return out


# ── step 6 ──────────────────────────────────────────────────────────
def step6_remux(src, dst):
    log("step6 PyAV 透传重封装 ...")
    t0 = time.time()
    cin = av.open(src)
    for i, s in enumerate(cin.streams):
        log("  [%d] %s %s tb=%s" % (i, s.type, s.codec_context.name, s.time_base))

    vst = next(s for s in cin.streams if s.type == "video")
    ast = next((s for s in cin.streams if s.type == "audio"), None)

    cout = av.open(dst, "w", format="mp4")
    vout = cout.add_stream_from_template(vst)      # 注意方法名，不是 add_stream
    aout = cout.add_stream_from_template(ast) if ast else None
    if aout:
        try:
            aout.codec_context.options = {"aac_adtstoasc": "1"}
        except Exception:
            pass                                   # PyAV 17 会自动处理

    vid_idx = vst.index
    aud_idx = ast.index if ast else -1
    cnt = {"v": 0, "a": 0}
    for pkt in cin.demux():
        if pkt.dts is None or pkt.size == 0:
            continue
        if pkt.stream.index == vid_idx:
            pkt.stream = vout
            cnt["v"] += 1
        elif pkt.stream.index == aud_idx:
            pkt.stream = aout
            cnt["a"] += 1
        else:
            continue
        cout.mux(pkt)

    cout.close()
    cin.close()
    log("  DONE v=%d a=%d %.0fs -> %.1f MB"
        % (cnt["v"], cnt["a"], time.time() - t0,
           os.path.getsize(dst) / 1048576.0))
    return dst


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)

    workdir = sys.argv[2] if len(sys.argv) > 2 else r"G:\ksrec\replay"
    segdir = os.path.join(workdir, "segs")
    os.makedirs(workdir, exist_ok=True)

    log("=" * 70)
    log("快手直播回放提取  workdir=%s" % workdir)
    log("=" * 70)

    page_url = step1_resolve(sys.argv[1])
    body = step2_scrape(page_url, workdir)
    primary = step3_pick(body)
    tasks = step4_download(primary["url"], segdir)
    merged = step5_concat(tasks, workdir)
    mp4 = step6_remux(merged, os.path.join(workdir, "replay_full.mp4"))

    log("=" * 70)
    log("提取完成: %s" % mp4)
    log("下一步验证:")
    log("  python verify/verify_full.py")
    log("  python verify/verify_audio.py")
    log("  python verify/verify_timeline.py")
    log("=" * 70)


if __name__ == "__main__":
    main()
