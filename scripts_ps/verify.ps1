# Plan C step 3: VERIFY candidate data block at LCN 31573815 (READ ONLY on G:)
# Checks MPEG-TS sync pattern, packet continuity, and extracts PCR/PTS timestamps if present.
$ErrorActionPreference = 'Continue'
$out = 'C:\Users\weido\.trae-cn\work\6aaa8ef0b3e31b7643bdb0d0\verify_result.txt'
$lines = New-Object System.Collections.ArrayList
function W($s) { [void]$lines.Add([string]$s) }

$sig = @'
using System; using System.Runtime.InteropServices;
public class DK5 {
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
  public static extern IntPtr CreateFileW(string n, uint a, uint s, IntPtr sec, uint d, uint f, IntPtr t);
  [DllImport("kernel32.dll", SetLastError=true)] public static extern bool ReadFile(IntPtr h, byte[] b, uint n, out uint r, IntPtr ov);
  [DllImport("kernel32.dll", SetLastError=true)] public static extern bool SetFilePointerEx(IntPtr h, long d, out long np, uint m);
  [DllImport("kernel32.dll", SetLastError=true)] public static extern bool CloseHandle(IntPtr h);
  public static IntPtr OpenRead(string p) { return CreateFileW(p, 2147483648, 3, IntPtr.Zero, 3, 0, IntPtr.Zero); }
  public static bool ReadAt(IntPtr h, long off, byte[] buf, int len, out int got) {
    long np; got = 0;
    if (!SetFilePointerEx(h, off, out np, 0)) return false;
    uint r; if (!ReadFile(h, buf, (uint)len, out r, IntPtr.Zero)) return false;
    got = (int)r; return true;
  }
}
'@
Add-Type -TypeDefinition $sig -ErrorAction SilentlyContinue

$volOffset = [int64]1685824995328
$clusterSize = 4096

# Candidate ranges to verify (LCN start, cluster count)
$cands = @(
  @{ Name='cand_A'; Lcn=31573815L; Clusters=414691L; Note='1619.9MB - primary candidate' }
)

$hd = [DK5]::OpenRead('\\.\PhysicalDrive1')
if ($hd.ToInt64() -eq -1) { W "FAIL open"; [System.IO.File]::WriteAllLines($out,$lines,(New-Object System.Text.UTF8Encoding($false))); 'FAIL'; exit }

foreach ($c in $cands) {
  W ("===== " + $c.Name + " : LCN " + $c.Lcn + " clusters=" + $c.Clusters + " (" + [math]::Round($c.Clusters*$clusterSize/1MB,1) + " MB) =====")
  $phys = $volOffset + ([int64]$c.Lcn * $clusterSize)
  W ("physical offset = " + $phys)

  # Read first 8 MB for analysis
  $probeLen = 8 * 1048576
  $buf = New-Object byte[] $probeLen
  $got = 0
  if (-not [DK5]::ReadAt($hd, $phys, $buf, $probeLen, [ref]$got) -or $got -le 0) {
    W "read FAIL"; continue
  }
  W ("read " + $got + " bytes")
  W ("first 16 bytes hex: " + (($buf[0..15] | ForEach-Object { '{0:X2}' -f $_ }) -join ' '))

  # Find best 188-byte alignment phase
  $bestPhase = -1; $bestCount = 0
  for ($phase = 0; $phase -lt 188; $phase++) {
    $cnt = 0; $tot = 0
    for ($p = $phase; $p -lt $got; $p += 188) { $tot++; if ($buf[$p] -eq 0x47) { $cnt++ } }
    if ($tot -gt 100 -and $cnt -gt $bestCount) { $bestCount = $cnt; $bestPhase = $phase }
  }
  W ("best 188-align phase = " + $bestPhase + " sync hits = " + $bestCount)

  if ($bestPhase -ge 0) {
    # Verify sync continuity in this phase
    $expected = 0; $found = 0
    for ($p = $bestPhase; $p -lt $got; $p += 188) { $expected++; if ($buf[$p] -eq 0x47) { $found++ } }
    $pct = [math]::Round($found * 100.0 / [math]::Max(1,$expected), 2)
    W ("sync continuity at phase " + $bestPhase + ": " + $found + "/" + $expected + " = " + $pct + "%")

    # Parse a few TS packets: PID + payload_unit_start + PCR/PTS
    W ""
    W "first 5 TS packet headers (phase-aligned):"
    $pktCount = 0
    for ($p = $bestPhase; $p + 188 -lt $got -and $pktCount -lt 5; $p += 188) {
      if ($buf[$p] -ne 0x47) { continue }
      $b1 = $buf[$p+1]; $b2 = $buf[$p+2]; $b3 = $buf[$p+3]
      $tei = ($b1 -shr 7) -band 1
      $pusi = ($b1 -shr 6) -band 1
      $tp = ($b1 -shr 5) -band 1
      $pid = (($b1 -band 0x1F) -shl 8) -bor $b2
      $sc = ($b3 -shr 6) -band 3
      $afc = ($b3 -shr 4) -band 3
      $cc = $b3 -band 0x0F
      W ("  pkt" + $pktCount + ": pusi=" + $pusi + " pid=0x" + ('{0:X4}' -f $pid) + " scrambling=" + $sc + " adapCtrl=" + $afc + " cc=" + $cc)
      $pktCount++
    }

    # Extract PCR from packets with adaptation field (PID 0x100.. typical for video)
    W ""
    W "attempt PCR extraction (adaptation field, PCR flag):"
    $pcrFound = 0
    for ($p = $bestPhase; $p + 188 -lt $got; $p += 188) {
      if ($buf[$p] -ne 0x47) { continue }
      $b3 = $buf[$p+3]
      $afc = ($b3 -shr 4) -band 3
      if ($afc -ne 2 -and $afc -ne 3) { continue }
      $afLen = $buf[$p+4]
      if ($afLen -lt 7) { continue }
      $afFlags = $buf[$p+5]
      $pcrFlag = ($afFlags -shr 4) -band 1
      if ($pcrFlag -eq 1) {
        # PCR: 33-bit base + 6 reserved + 9-bit ext
        $p0=$buf[$p+6]; $p1=$buf[$p+7]; $p2=$buf[$p+8]; $p3=$buf[$p+9]; $p4=$buf[$p+10]; $p5=$buf[$p+11]
        $base = ([int64]$p0 -shl 25) -bor ([int64]$p1 -shl 17) -bor ([int64]$p2 -shl 9) -bor ([int64]$p3 -shl 1) -bor (([int64]$p4 -shr 7) -band 1)
        $ext = ((([int64]$p4 -band 1) -shl 8) -bor $p5)
        $sec = $base / 90000.0
        W ("  PCR base=" + $base + " ext=" + $ext + " -> " + [math]::Round($sec,3) + " s")
        $pcrFound++
        if ($pcrFound -ge 8) { break }
      }
    }
    if ($pcrFound -eq 0) { W "  no PCR found (may use different PID or no adaptation PCR)" }
  }
  W ""
}

[void][DK5]::CloseHandle($hd)
[System.IO.File]::WriteAllLines($out, $lines, (New-Object System.Text.UTF8Encoding($false)))
'VERIFY_DONE'
