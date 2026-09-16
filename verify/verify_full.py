import av, os

p = r"G:\ksrec\replay\replay_full.mp4"
print("size MB = %.1f" % (os.path.getsize(p) / 1048576))

c = av.open(p)
print("format:", c.format.name, "duration(sec) =", (c.duration or 0) / 1_000_000)
print("bit_rate:", c.bit_rate)
print("streams:", len(c.streams))
for i, s in enumerate(c.streams):
    cc = s.codec_context
    dur = (s.duration or 0) * s.time_base if s.duration else None
    line = f"  [{i}] {s.type:5} {cc.name:8} tb={s.time_base} dur={dur}"
    if s.type == "video":
        line += f" {cc.width}x{cc.height} fps={cc.framerate} pix={cc.pix_fmt}"
    else:
        line += f" rate={cc.sample_rate} ch={cc.channels} layout={cc.layout} fmt={cc.format.name}"
    print(line)

# decode a few frames from each stream to prove playability
for s in c.streams:
    n = 0
    for f in c.decode(s.index):
        n += 1
        if n == 1:
            if s.type == "video":
                print(f"  [{s.index}] first video frame {f.width}x{f.height} pts={f.pts}")
            else:
                print(f"  [{s.index}] first audio frame samples={f.samples} rate={f.sample_rate} ch={f.channels} pts={f.pts}")
        if n >= 30:
            break
    print(f"  [{s.index}] {s.type}: decoded {n} frames OK")
    c.seek(0)
c.close()
print("VERIFY_OK")
