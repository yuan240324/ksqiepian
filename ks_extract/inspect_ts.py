# -*- coding: utf-8 -*-
"""Inspect TS packets in segment 0: which PIDs carry data, and do AAC ADTS headers exist?"""
import os

P = r"G:\ksrec\replay\segs\00000.ts"
data = open(P, "rb").read()
print("segment size: %d bytes" % len(data))

# find phase
phase = None
for ph in range(188):
    cnt = sum(1 for p in range(ph, min(len(data), ph + 188 * 200), 188) if data[p] == 0x47)
    if cnt > 180:
        phase = ph
        break
print("TS phase: %s" % phase)

pids = {}
pcr_pids = {}
for p in range(phase, len(data) - 188, 188):
    if data[p] != 0x47:
        continue
    b1, b2, b3 = data[p+1], data[p+2], data[p+3]
    pid = ((b1 & 0x1F) << 8) | b2
    pusi = (b1 >> 6) & 1
    afc = (b3 >> 4) & 3
    pids.setdefault(pid, 0)
    pids[pid] += 1
    if afc in (2, 3):
        aflen = data[p+4]
        if aflen >= 7:
            flags = data[p+5]
            if (flags >> 4) & 1:
                pcr_pids[pid] = pcr_pids.get(pid, 0) + 1

print("\nPID distribution (top 10):")
for pid, c in sorted(pids.items(), key=lambda x: -x[1])[:10]:
    print("  PID 0x%04X : %d packets" % (pid, c))
print("\nPCR-carrying PIDs: %s" % {("0x%04X" % k): v for k, v in pcr_pids.items()})

# Inspect audio PID payloads for ADTS sync (0xFFFx)
AUDIO_PID = 0x0101
payloads = []
for p in range(phase, len(data) - 188, 188):
    if data[p] != 0x47:
        continue
    b1, b2, b3 = data[p+1], data[p+2], data[p+3]
    pid = ((b1 & 0x1F) << 8) | b2
    if pid != AUDIO_PID:
        continue
    pusi = (b1 >> 6) & 1
    afc = (b3 >> 4) & 3
    off = 4
    if afc in (2, 3):
        off += 1 + data[p+4]
    if off >= 188:
        continue
    if pusi:
        payloads.append(data[p+off: p+188])
    if len(payloads) >= 6:
        break

print("\nAudio payload (PID 0x%04X) first bytes with PUSI:" % AUDIO_PID)
for i, pl in enumerate(payloads[:6]):
    head = pl[:12]
    print("  [%d] %s  (ADTS sync? %s)" % (
        i, " ".join("%02X" % b for b in head),
        "YES" if len(pl) >= 2 and pl[0] == 0xFF and (pl[1] & 0xF0) == 0xF0 else "no"))
    if len(pl) >= 7 and pl[0] == 0xFF and (pl[1] & 0xF0) == 0xF0:
        # parse ADTS header
        profile = (pl[2] >> 6) & 3
        sf_idx = (pl[2] >> 2) & 0xF
        ch = ((pl[2] & 1) << 2) | ((pl[3] >> 6) & 3)
        sf_table = [96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050,
                    16000, 12000, 11025, 8000, 7350, 0, 0, 0]
        print("      -> ADTS: profile=%d sampleRate=%d ch=%d" % (
            profile + 1, sf_table[sf_idx], ch))
