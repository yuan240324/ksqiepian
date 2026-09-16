import av, time

SRC = r"G:\ksrec\replay\merged.ts"
DST = r"G:\ksrec\replay\replay_full.mp4"

t0 = time.time()
cin = av.open(SRC)
print("OPEN %.2fs" % (time.time() - t0), flush=True)
for i, s in enumerate(cin.streams):
    cc = s.codec_context
    print(f"  [{i}] {s.type:5} {cc.name:8} tb={s.time_base}", flush=True)

vst = next(s for s in cin.streams if s.type == "video")
ast = next(s for s in cin.streams if s.type == "audio")

cout = av.open(DST, "w", format="mp4")

# Passthrough: copy codec parameters from the source streams.
vout = cout.add_stream_from_template(vst)
aout = cout.add_stream_from_template(ast)
print("out: v=%s(%s) a=%s(%s)" % (
    vout.type, vout.codec_context.name, aout.type, aout.codec_context.name), flush=True)

# AAC in TS carries ADTS headers; MP4 needs raw AAC + AudioSpecificConfig.
try:
    aout.codec_context.options = {"aac_adtstoasc": "1"}
except Exception as e:
    print("opt note:", e, flush=True)

VID_IDX, AUD_IDX = vst.index, ast.index
count = {"v": 0, "a": 0}
t0 = time.time()
last = t0
print("start remux ...", flush=True)
for pkt in cin.demux():
    if pkt.dts is None or pkt.size == 0:
        continue
    if pkt.stream.index == VID_IDX:
        pkt.stream = vout
        count["v"] += 1
    elif pkt.stream.index == AUD_IDX:
        pkt.stream = aout
        count["a"] += 1
    else:
        continue
    cout.mux(pkt)
    if time.time() - last > 20:
        last = time.time()
        print(f"  v={count['v']:>7} a={count['a']:>7} elapsed={time.time()-t0:.0f}s", flush=True)

cout.close()
cin.close()
print("DONE v=%d a=%d elapsed=%.0fs" % (count["v"], count["a"], time.time() - t0), flush=True)
