# -*- coding: utf-8 -*-
"""Follow Kuaishou short links and resolve the real target URL + extract IDs."""
import sys, re, json, urllib.request, urllib.error

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")


def resolve(url):
    print("=" * 72)
    print("INPUT : %s" % url)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            final = r.geturl()
            body = r.read().decode("utf-8", "ignore")
            status = r.status
    except urllib.error.HTTPError as e:
        final = e.geturl() if hasattr(e, "geturl") else url
        print("HTTPError %d -> %s" % (e.code, final))
        try:
            loc = e.headers.get("Location")
            if loc:
                print("Location header: %s" % loc)
        except Exception:
            pass
        return

    print("STATUS: %d" % status)
    print("FINAL : %s" % final)
    print("BODY  : %d bytes" % len(body))

    # Extract useful identifiers from final URL
    for pat, label in [
        (r"/profile/([A-Za-z0-9_\-]+)", "profile id"),
        (r"/live/([A-Za-z0-9_\-]+)", "live id"),
        (r"userId=([0-9]+)", "userId"),
        (r"principalId=([A-Za-z0-9_\-]+)", "principalId"),
        (r"/f/([A-Za-z0-9_\-]+)", "short code"),
    ]:
        m = re.search(pat, final)
        if m:
            print("  %-12s : %s" % (label, m.group(1)))

    # Extract IDs from body
    for pat, label in [
        (r'"userId"\s*:\s*"?([0-9]+)"?', "body userId"),
        (r'"principalId"\s*:\s*"([^"]+)"', "body principalId"),
        (r'"authorId"\s*:\s*"([^"]+)"', "body authorId"),
        (r'"id"\s*:\s*"([0-9]{15,})"', "body id(15+)"),
        (r'liveroom/([0-9A-Za-z_\-]+)', "body liveroom"),
    ]:
        for m in list(re.finditer(pat, body))[:3]:
            print("  %-14s : %s" % (label, m.group(1)))

    # Title
    m = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
    if m:
        print("  TITLE        : %s" % m.group(1).strip()[:120])


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("usage: python resolve_ks.py <url> [url2 ...]")
        sys.exit(0)
    for u in args:
        resolve(u)
