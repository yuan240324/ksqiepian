# -*- coding: utf-8 -*-
"""Small sanity test: download first 3 TS segments and verify they are real MPEG-TS."""
import os, re, time, urllib.request

M3U8 = ("http://alivod.a.yximgs.com/livedvr/flv2ts/gifshow/"
        "JsQSVN0Ra3Q_GameAvcHdL1Lto.1789558283798-5163925.0-16.m3u8"
        "?auth_key=1789826713-1566863167-0-feb9be284f667f5a403520801ef261c7"
        "&kpn=KUAISHOU_H5&caller=live-stream-playback-api")
OUTDIR = r"G:\ksrec\replay\segs"
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": "https://v.kuaishou.com/",
        "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


os.makedirs(OUTDIR, exist_ok=True)
man = fetch(M3U8).decode("utf-8", "ignore")
base = M3U8.rsplit("/", 1)[0] + "/"
segs = [l.strip() for l in man.splitlines() if l.strip() and not l.strip().startswith("#")]

print("total segments in manifest: %d" % len(segs))
print()
for i in range(3):
    name = segs[i]
    url = name if name.startswith("http") else base + name
    t0 = time.time()
    data = fetch(url)
    dt = time.time() - t0
    path = os.path.join(OUTDIR, "%05d.ts" % i)
    with open(path, "wb") as f:
        f.write(data)
    # verify TS sync
    syncs = sum(1 for p in range(0, min(len(data), 188 * 50), 188) if data[p] == 0x47)
    print("[%d] %d bytes in %.2fs  sync=%d/50  first4=%s" % (
        i, len(data), dt, syncs, " ".join("%02X" % b for b in data[:4])))

print()
print("TEST_DONE")
