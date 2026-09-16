# Plan C step 2d: read $Bitmap content at LCN 784086 and map USED clusters
# Pure ASCII. READ ONLY on G:.
$ErrorActionPreference = 'Continue'
$out = 'C:\Users\weido\.trae-cn\work\6aaa8ef0b3e31b7643bdb0d0\bitmap_result.txt'
$lines = New-Object System.Collections.ArrayList
function W($s) { [void]$lines.Add([string]$s) }

$sig = @'
using System; using System.Runtime.InteropServices;
public class DK4 {
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
$bitmapLcn = 784086L
$bitmapClusters = 2344L
$bitmapBytes = 9600000
$totalClusters = 76800000L

$hd = [DK4]::OpenRead('\\.\PhysicalDrive1')
if ($hd.ToInt64() -eq -1) { W "FAIL open"; [System.IO.File]::WriteAllLines($out,$lines,(New-Object System.Text.UTF8Encoding($false))); 'FAIL'; exit }

$physOff = $volOffset + ($bitmapLcn * $clusterSize)
W ("bitmap physical offset = " + $physOff)
W ("expected byte size = " + $bitmapBytes + " (clusters=" + $bitmapClusters + ")")

# read whole bitmap in chunks
$bm = New-Object byte[] $bitmapBytes
$totalGot = 0
$chunk = 1048576
$pos = 0
while ($pos -lt $bitmapBytes) {
  $len = [math]::Min($chunk, $bitmapBytes - $pos)
  $buf = New-Object byte[] $len
  $g = 0
  if ([DK4]::ReadAt($hd, $physOff + $pos, $buf, $len, [ref]$g) -and $g -gt 0) {
    [Array]::Copy($buf, 0, $bm, $pos, $g)
    $totalGot += $g
    $pos += $g
    if ($g -lt $len) { W ("short read at " + $pos + " got=" + $g); break }
  } else { W ("read FAIL at pos=" + $pos + " err=" + [Runtime.InteropServices.Marshal]::GetLastWin32Error()); break }
}
W ("bitmap bytes read = " + $totalGot)

if ($totalGot -gt 0) {
  # count set bits
  $usedCount = 0L
  $firstByteNonZero = -1
  for ($i = 0; $i -lt $totalGot; $i++) {
    $b = $bm[$i]
    if ($b -ne 0) {
      if ($firstByteNonZero -lt 0) { $firstByteNonZero = $i }
      for ($bit=0; $bit -lt 8; $bit++) { if (($b -band (1 -shl $bit)) -ne 0) { $usedCount++ } }
    }
  }
  W ("used bits(total clusters in use) = " + $usedCount + " (" + [math]::Round($usedCount*$clusterSize/1GB,2) + " GB)")
  W ("first non-zero bitmap byte index = " + $firstByteNonZero + " -> first used LCN ~ " + ($firstByteNonZero*8))

  # Build merged ranges of used clusters
  $ranges = New-Object System.Collections.ArrayList
  $runStart = -1L
  for ($byteIdx = 0; $byteIdx -lt $totalGot; $byteIdx++) {
    $b = $bm[$byteIdx]
    if ($b -eq 0) {
      if ($runStart -ge 0) { [void]$ranges.Add([pscustomobject]@{Start=$runStart;End=($byteIdx*8-1)}); $runStart = -1 }
      continue
    }
    if ($b -eq 255) {
      if ($runStart -lt 0) { $runStart = $byteIdx*8 }
      continue
    }
    # partial byte
    for ($bit=0; $bit -lt 8; $bit++) {
      $lcn = $byteIdx*8 + $bit
      if (($b -band (1 -shl $bit)) -ne 0) { if ($runStart -lt 0) { $runStart = $lcn } }
      else { if ($runStart -ge 0) { [void]$ranges.Add([pscustomobject]@{Start=$runStart;End=($lcn-1)}); $runStart = -1 } }
    }
  }
  if ($runStart -ge 0) { [void]$ranges.Add([pscustomobject]@{Start=$runStart;End=($totalGot*8-1)}) }

  W ("merged used ranges = " + $ranges.Count)
  W ""
  W "===== used LCN ranges (top 60 by size) ====="
  $sorted = $ranges | Sort-Object { $_.End - $_.Start } -Descending | Select-Object -First 60
  foreach ($r in $sorted) {
    $mb = [math]::Round((($r.End-$r.Start+1)*$clusterSize)/1MB,1)
    W ("  LCN " + $r.Start + " - " + $r.End + "  = " + $mb + " MB")
  }

  W ""
  W "===== all ranges summary ====="
  $tot = 0L
  foreach ($r in $ranges) { $tot += ($r.End-$r.Start+1) }
  W ("total ranges=" + $ranges.Count + " total used clusters=" + $tot)
}
[void][DK4]::CloseHandle($hd)
[System.IO.File]::WriteAllLines($out, $lines, (New-Object System.Text.UTF8Encoding($false)))
'BITMAP_DONE'
