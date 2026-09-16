import av

SRC = r"G:\ksrec\replay\merged.ts"
P = r"G:\ksrec\replay\replay_full.mp4"

print("=== 1) merged.ts keyframe distribution (source timeline) ===")
c = av.open(SRC)
vst = next(s for s in c.streams if s.type == "video")
tb = vst.time_base
kf = []
for pkt in c.demux(vst):
    if pkt.size and pkt.is_keyframe:
        kf.append(float(pkt.pts * tb))
c.close()
print(f"keyframes: {len(kf)}  first={kf[0]:.2f}s  last={kf[-1]:.2f}s")
print(f"span: {kf[-1]-kf[0]:.2f}s = {(kf[-1]-kf[0])/60:.2f} min")
gaps = [(round(kf[i],1), round(kf[i+1]-kf[i],1)) for i in range(len(kf)-1) if kf[i+1]-kf[i] > 20]
print("keyframe gaps > 20s:", gaps if gaps else "NONE")

print()
print("=== 2) merged.ts sequential timeline by minute ===")
c = av.open(SRC)
vst = next(s for s in c.streams if s.type == "video")
ast = next(s for s in c.streams if s.type == "audio")
vtb, atb = vst.time_base, ast.time_base
seen = {}
lastv = lasta = None
for pkt in c.demux():
    if pkt.size == 0 or pkt.pts is None:
        continue
    if pkt.stream.index == vst.index:
        lastv = float(pkt.pts * vtb)
    elif pkt.stream.index == ast.index:
        lasta = float(pkt.pts * atb)
c.close()
print(f"video last pts = {lastv:.2f}s ({lastv/60:.2f} min)")
print(f"audio last pts = {lasta:.2f}s ({lasta/60:.2f} min)")
print(f"AV drift at tail = {abs(lastv-lasta):.2f}s")

print()
print("=== 3) MP4 VBR audio side (time_base-normalised duration) ===")
c = av.open(P)
ast2 = next(s for s in c.streams if s.type == "audio")
d = ast2.duration * ast2.time_base
print("mp4 audio stream duration = %.2fs (%.2f min)" % (d, d / 60))
vst2 = next(s for s in c.streams if s.type == "video")
dv = vst2.duration * vst2.time_base
print("mp4 video stream duration = %.2fs (%.2f min)" % (dv, dv / 60))
c.close()
