# -*- coding: utf-8 -*-
"""Download all TS segments of a Kuaishou live-playback m3u8 to local disk (resumable)."""
import os, re, sys, time, json, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

M3U8 = ("http://alivod.a.yximgs.com/livedvr/flv2ts/gifshow/"
        "JsQSVN0Ra3Q_GameAvcHdL1Lto.1789558283798-5163925.0-16.m3u8"
        "?auth_key=1789826713-1566863167-0-feb9be284f667f5a403520801ef261c7"
        "&kpn=KUAISHOU_H5&caller=live-stream-playback-api")

OUTDIR = r"G:\ksrec\replay\segs"
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
REF = "https://v.kuaishou.com/"
WORKERS = 8


def fetch(url, retries=4, timeout=30):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Referer": REF,
                "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(1.2 * (i + 1))
    raise last


def main():
    os.makedirs(OUTDIR, exist_ok=True)

    # 1) fetch manifest
    man = fetch(M3U8).decode("utf-8", "ignore")
    lines = man.splitlines()
    base = M3U8.rsplit("/", 1)[0] + "/"

    segs = []
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        segs.append(ln)

    total = len(segs)
    print("manifest: %d segments" % total)

    # 2) download with resume
    done = 0
    fail = []
    tasks = []
    for idx, name in enumerate(segs):
        path = os.path.join(OUTDIR, "%05d.ts" % idx)
        tasks.append((idx, name, path))

    pending = [t for t in tasks if not (os.path.exists(t[2]) and os.path.getsize(t[2]) > 0)]
    print("already have: %d, to fetch: %d" % (total - len(pending), len(pending)))

    def worker(t):
        idx, name, path = t
        url = name if name.startswith("http") else base + name
        data = fetch(url)
        tmp = path + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        return idx, len(data)

    if pending:
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(worker, t): t for t in pending}
            for fut in as_completed(futs):
                t = futs[fut]
                try:
                    idx, n = fut.result()
                    done += 1
                    if done % 50 == 0 or done == len(pending):
                        el = time.time() - t0
                        rate = done / el if el > 0 else 0
                        eta = (len(pending) - done) / rate if rate > 0 else 0
                        print("  %d/%d  (%.1f seg/s, ETA %.0fs)" % (done, len(pending), rate, eta))
                except Exception as e:
                    fail.append((t[0], repr(e)))
                    print("  FAIL idx=%d : %r" % (t[0], e))

    # 3) verify
    ok = 0
    missing = []
    for idx, name, path in tasks:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            ok += 1
        else:
            missing.append(idx)

    print("")
    print("=" * 60)
    print("downloaded OK : %d / %d" % (ok, total))
    print("failed        : %d" % len(fail))
    print("missing idx   : %s" % (missing[:30] if missing else "none"))
    total_bytes = sum(os.path.getsize(t[2]) for t in tasks if os.path.exists(t[2]))
    print("total size    : %.1f MB" % (total_bytes / 1048576.0))

    # write concat list
    lst = os.path.join(r"G:\ksrec\replay", "concat.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for idx, name, path in tasks:
            if os.path.exists(path) and os.path.getsize(path) > 0:
                f.write("file '%s'\n" % path.replace("\\", "/"))
    print("concat list   -> %s" % lst)

    print("DL_DONE" if not missing else "DL_INCOMPLETE")


if __name__ == "__main__":
    main()
