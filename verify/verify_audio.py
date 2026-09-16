import av, os

p = r"G:\ksrec\replay\replay_full.mp4"
c = av.open(p)
ast = next(s for s in c.streams if s.type == "audio")
print("audio stream:", ast.codec_context.name, ast.codec_context.sample_rate,
      ast.codec_context.layout, ast.codec_context.format.name)

# Full audio decode pass, sample-count integrity check
total = 0
n = 0
sr = ast.codec_context.sample_rate
first = None
for f in c.decode(ast):
    if first is None:
        first = f
        print("first audio frame:", f.samples, "samples, rate", f.sample_rate,
              "layout", f.layout, "pts", f.pts)
    total += f.samples
    n += 1
print("audio frames decoded:", n)
print("total samples:", total)
print("audio duration sec = %.3f" % (total / sr))
c.close()
print("AUDIO_OK")
