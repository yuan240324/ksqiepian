# -*- coding: utf-8 -*-
"""Fetch the Kuaishou live-playback page and extract playable video URLs."""
import re, json, urllib.request, urllib.error

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")

URL = ("https://v.kuaishou.com/fw/playback/1499544558?cc=share_copylink"
       "&kpf=ANDROID_PHONE&shareMethod=token&kpn=KUAISHOU&subBiz=LIVE_PLAYBACK"
       "&shareId=19115508202223&shareToken=X56ZfKJb622Z1i7&shareMode=app"
       "&shareObjectId=5228679375865664634")

req = urllib.request.Request(URL, headers={
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
})
with urllib.request.urlopen(req, timeout=30) as r:
    final = r.geturl()
    body = r.read().decode("utf-8", "ignore")

print("FINAL URL: %s" % final)
print("BODY LEN : %d" % len(body))
print()

# Save raw body for inspection
with open(r"C:\Users\weido\.trae-cn\work\6aaa8ef0b3e31b7643bdb0d0\playback_body.html", "w", encoding="utf-8") as f:
    f.write(body)
print("saved -> playback_body.html")
print()

# --- Search for media URLs ---
patterns = [
    (r'https?://[^\s"\'<>\\]+\.m3u8[^\s"\'<>\\]*', "M3U8"),
    (r'https?://[^\s"\'<>\\]+\.mp4[^\s"\'<>\\]*', "MP4"),
    (r'https?://[^\s"\'<>\\]+\.flv[^\s"\'<>\\]*', "FLV"),
    (r'https?://[^\s"\'<>\\]+\.ts[^\s"\'<>\\]*', "TS"),
    (r'"srcNoMark"\s*:\s*"([^"]+)"', "srcNoMark"),
    (r'"playUrl"\s*:\s*"([^"]+)"', "playUrl"),
    (r'"playUrls"\s*:\s*\[([^\]]*)\]', "playUrls"),
    (r'"url"\s*:\s*"(https?://[^"]+)"', "url"),
    (r'"photoId"\s*:\s*"([^"]+)"', "photoId"),
    (r'"caption"\s*:\s*"([^"]{0,120})"', "caption"),
    (r'"duration"\s*:\s*(\d+)', "duration"),
    (r'"poster"\s*:\s*"([^"]+)"', "poster"),
]

seen = set()
for pat, label in patterns:
    hits = list(re.finditer(pat, body))
    if not hits:
        continue
    print("--- %s : %d hit(s) ---" % (label, len(hits)))
    for m in hits[:6]:
        val = m.group(1) if m.groups() else m.group(0)
        val = val.replace("\\u002F", "/").replace("\\/", "/")
        if val in seen and label not in ("photoId", "caption", "duration"):
            continue
        seen.add(val)
        disp = val if len(val) <= 220 else val[:220] + " ..."
        print("   %s" % disp)
    print()

# --- Look for embedded JSON blobs ---
m = re.search(r'window\.__APOLLO_STATE__\s*=\s*(\{.*?\});?\s*</script>', body, re.S)
if m:
    print("FOUND __APOLLO_STATE__ (%d chars)" % len(m.group(1)))
    with open(r"C:\Users\weido\.trae-cn\work\6aaa8ef0b3e31b7643bdb0d0\apollo.json", "w", encoding="utf-8") as f:
        f.write(m.group(1))
    print("saved -> apollo.json")

m2 = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});?\s*</script>', body, re.S)
if m2:
    print("FOUND __INITIAL_STATE__ (%d chars)" % len(m2.group(1)))
    with open(r"C:\Users\weido\.trae-cn\work\6aaa8ef0b3e31b7643bdb0d0\initial.json", "w", encoding="utf-8") as f:
        f.write(m2.group(1))
    print("saved -> initial.json")
