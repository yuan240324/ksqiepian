# -*- coding: utf-8 -*-
"""Extract the full live-playback m3u8 URLs with metadata, pick candidates, and test-fetch."""
import re, json, urllib.request, subprocess, os

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")

BODY_PATH = r"C:\Users\weido\.trae-cn\work\6aaa8ef0b3e31b7643bdb0d0\playback_body.html"
OUT_JSON = r"C:\Users\weido\.trae-cn\work\6aaa8ef0b3e31b7643bdb0d0\replay_list.json"

body = open(BODY_PATH, encoding="utf-8").read()

# The page embeds structured JSON. Find all "livePlayback" style blocks with surrounding context.
# Strategy: locate each m3u8 URL and grab a window around it for duration / id extraction.
cands = []
for m in re.finditer(r'(https?://[^\s"\'<>\\]+\.m3u8[^\s"\'<>\\]*)', body):
    url = m.group(1).replace("\\u002F", "/").replace("\\/", "/")
    s = max(0, m.start() - 1500)
    e = min(len(body), m.end() + 1500)
    ctx = body[s:e]
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

# Dedup by url
seen = set()
uniq = []
for c in cands:
    if c["url"] in seen:
        continue
    seen.add(c["url"])
    uniq.append(c)

print("=== Found %d unique m3u8 URLs ===" % len(uniq))
for i, c in enumerate(uniq, 1):
    d = c.get("duration_ms")
    dur = ("%.1f min" % (int(d) / 60000.0)) if d and str(d).isdigit() else "?"
    print("\n[%d] dur=%s clarity=%s" % (i, dur, c.get("clarity", "?")))
    print("    caption : %s" % c.get("caption", "?"))
    print("    url     : %s" % c["url"][:200])

json.dump(uniq, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("\nsaved -> %s" % OUT_JSON)

# --- Pick the newest/longest "Game" one as primary target ---
primary = None
for c in uniq:
    if "GameAvcHd" in c["url"]:
        primary = c
        break
if primary is None and uniq:
    primary = uniq[-1]

print("\n" + "=" * 70)
print("PRIMARY TARGET:")
print(json.dumps(primary, ensure_ascii=False, indent=2))
print("=" * 70)

# --- Test fetch the m3u8 manifest ---
if primary:
    u = primary["url"]
    print("\nFetching m3u8 manifest ...")
    req = urllib.request.Request(u, headers={"User-Agent": UA, "Referer": "https://v.kuaishou.com/"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            man = r.read().decode("utf-8", "ignore")
        print("HTTP OK, manifest %d bytes" % len(man))
        print("--- first 1200 chars ---")
        print(man[:1200])
        segs = re.findall(r"^[^#\s].*\.ts.*$", man, re.M)
        print("\nsegments listed: %d" % len(segs))
        if segs:
            print("first seg: %s" % segs[0][:180])
            print("last  seg: %s" % segs[-1][:180])
    except Exception as e:
        print("MANIFEST ERR: %r" % e)
