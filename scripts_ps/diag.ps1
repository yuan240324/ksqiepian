# Plan C step 2c: DIAGNOSE bitmap run parsing - dump raw run bytes and resolved LCNs
# Pure ASCII. READ ONLY.
$ErrorActionPreference = 'Continue'
$out = 'C:\Users\weido\.trae-cn\work\6aaa8ef0b3e31b7643bdb0d0\diag_result.txt'
$lines = New-Object System.Collections.ArrayList
function W($s) { [void]$lines.Add([string]$s) }

$sig = @'
using System; using System.Runtime.InteropServices;
public class DK3 {
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

$bps = 512
$volOffset = [int64]1685824995328
$clusterSize = 4096
$mftLcn = 786432

$hd = [DK3]::OpenRead('\\.\PhysicalDrive1')
if ($hd.ToInt64() -eq -1) { W "FAIL open"; [System.IO.File]::WriteAllLines($out,$lines,(New-Object System.Text.UTF8Encoding($false))); 'FAIL'; exit }

# Determine MFT record size from $MFT record (entry 0)
$mftPhys = $volOffset + ([int64]$mftLcn * $clusterSize)
$rec0 = New-Object byte[] 1024; $got=0
[void][DK3]::ReadAt($hd, $mftPhys, $rec0, 1024, [ref]$got)
W ("MFT rec0 magic=" + [System.Text.Encoding]::ASCII.GetString($rec0,0,4))
# record size flag: offset 28 (0x1C) in MFT record: bit 0 = 1 -> 4096 else 1024
$flags = [BitConverter]::ToUInt16($rec0, 22)
W ("rec0 flags=0x" + ('{0:X4}' -f $flags))
# Use $MFT's own DATA attr to get record size: non-resident realSize/clusters
$off0 = [BitConverter]::ToUInt16($rec0, 20)
W ("rec0 attrs start=" + $off0)
$off = $off0
while ($off -gt 0 -and $off + 8 -lt 1024) {
  $type = [BitConverter]::ToUInt32($rec0, $off)
  if ($type -eq 4294967295) { break }
  $alen = [BitConverter]::ToUInt32($rec0, $off + 4)
  if ($alen -eq 0) { break }
  if ($type -eq 128) {
    $nres = $rec0[$off + 8]
    W ("  MFT DATA nonResident=" + $nres)
    if ($nres -eq 1) {
      $allocSz = [BitConverter]::ToInt64($rec0, $off + 40)
      $realSz = [BitConverter]::ToInt64($rec0, $off + 48)
      W ("  allocSize=" + $allocSz + " realSize=" + $realSz + " -> recSize guess=" + ([math]::Round($allocSz / 310272.0, 0)))
    }
  }
  if ($type -eq 48) {
    # ATTRIBUTE_LIST present -> $Bitmap entry may have attribute list extension
    W ("  ATTRIBUTE_LIST present! nonRes=" + $rec0[$off+8])
  }
  $off += $alen
}

# Read $Bitmap entry (6). Try both record sizes.
foreach ($rs in @(1024, 4096)) {
  W ""
  W ("===== try MFT record size = " + $rs + " =====")
  $rec = New-Object byte[] $rs
  [void][DK3]::ReadAt($hd, $mftPhys + (6 * $rs), $rec, $rs, [ref]$got)
  W ("  $Bitmap magic=" + [System.Text.Encoding]::ASCII.GetString($rec,0,4) + " got=" + $got)
  if ([System.Text.Encoding]::ASCII.GetString($rec,0,4) -ne 'FILE') { continue }

  $off = [BitConverter]::ToUInt16($rec, 20)
  W ("  attrs start=" + $off)
  while ($off -gt 0 -and $off + 8 -lt $rs) {
    $type = [BitConverter]::ToUInt32($rec, $off)
    if ($type -eq 4294967295) { break }
    $alen = [BitConverter]::ToUInt32($rec, $off + 4)
    if ($alen -eq 0) { break }
    W ("    attr type=0x" + ('{0:X8}' -f $type) + " len=" + $alen)
    if ($type -eq 128) {
      $nres = $rec[$off + 8]
      W ("      DATA nonResident=" + $nres)
      if ($nres -eq 1) {
        $startVcn = [BitConverter]::ToInt64($rec, $off + 16)
        $lastVcn = [BitConverter]::ToInt64($rec, $off + 24)
        $runOff = [BitConverter]::ToUInt16($rec, $off + 32)
        $allocSz = [BitConverter]::ToInt64($rec, $off + 40)
        $realSz = [BitConverter]::ToInt64($rec, $off + 48)
        W ("      startVcn=" + $startVcn + " lastVcn=" + $lastVcn + " runOff=" + $runOff)
        W ("      allocSize=" + $allocSz + " realSize=" + $realSz)
        $rp = $off + $runOff
        W ("      raw run bytes (hex): " + (($rec[$rp..([math]::Min($rp+63, $rs-1))] | ForEach-Object { '{0:X2}' -f $_ }) -join ' '))
        # parse
        $p = $rp; $lcn = 0L; $n = 0
        while ($p -lt $rs -and $n -lt 40) {
          $hdr = $rec[$p]
          if ($hdr -eq 0) { break }
          $lenBytes = $hdr -band 0x0F
          $ofsBytes = ($hdr -shr 4) -band 0x0F
          $p++
          $runLen = 0L
          for ($i=0; $i -lt $lenBytes; $i++) { $runLen = $runLen -bor ([int64]$rec[$p+$i] -shl ($i*8)) }
          $p += $lenBytes
          if ($ofsBytes -eq 0) { W ("      run sparse len=" + $runLen); $n++; continue }
          $val = 0L
          for ($i=0; $i -lt $ofsBytes; $i++) { $val = $val -bor ([int64]$rec[$p+$i] -shl ($i*8)) }
          if ($rec[$p+$ofsBytes-1] -ge 0x80) { $val = $val - ([int64]1 -shl ($ofsBytes*8)) }
          $p += $ofsBytes
          $lcn += $val
          W ("      run#" + $n + " lcn=" + $lcn + " len=" + $runLen + " clusters")
          $n++
        }
        W ("      total runs=" + $n)
      }
    }
    $off += $alen
  }
}

[void][DK3]::CloseHandle($hd)
[System.IO.File]::WriteAllLines($out, $lines, (New-Object System.Text.UTF8Encoding($false)))
'DIAG_DONE'
