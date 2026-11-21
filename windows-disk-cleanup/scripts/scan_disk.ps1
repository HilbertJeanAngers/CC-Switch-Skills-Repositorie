#Requires -Version 5.1
<#
 windows-disk-cleanup :: scan_disk.ps1
 Read-only disk scanner. Never moves, renames or deletes anything.
 Output is pipe-delimited ASCII so it survives terminal encoding issues.
 Run: powershell -ExecutionPolicy Bypass -File scan_disk.ps1 -Drive C: -Deep
 Tags: DISK, DIRSIZE, USERSIZE, JUNK, BIG, LOCALAPP, ROAMING, TEMP, DONE
 A size of 0 may mean "empty" OR "access denied" - check the Denied flag.
#>
param(
  [string]$Drive = 'C:',
  [int]$BigFileMB = 100,
  [switch]$Deep
)

$ErrorActionPreference = 'SilentlyContinue'
$root = $Drive.TrimEnd('\') + '\'

function Measure-Tree {
  param([string]$Path)
  $errBefore = $Error.Count
  $m = Get-ChildItem -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue |
       Where-Object { -not $_.PSIsContainer } |
       Measure-Object -Property Length -Sum
  $sum = $m.Sum
  if ($null -eq $sum) { $sum = 0 }
  $denied = ($Error.Count -gt $errBefore)
  return [pscustomobject]@{
    MB     = [math]::Round($sum / 1MB, 1)
    Denied = $denied
  }
}

# ---------- 1. Disk summary ----------
$d = Get-WmiObject Win32_LogicalDisk -Filter ("DeviceID='" + $Drive + "'")
if ($d) {
  Write-Output ("DISK|total=" + [math]::Round($d.Size / 1GB, 1) + " GB|used=" + [math]::Round(($d.Size - $d.FreeSpace) / 1GB, 1) + " GB|free=" + [math]::Round($d.FreeSpace / 1GB, 1) + " GB")
} else {
  Write-Output ("DISK|drive not found: " + $Drive)
}

# ---------- 2. Known junk locations ----------
$junk = @(
  @{ n = 'WindowsTemp';        p = ($root + 'Windows\Temp') },
  @{ n = 'UserTemp';           p = (Join-Path $env:LOCALAPPDATA 'Temp') },
  @{ n = 'WindowsUpdateCache'; p = ($root + 'Windows\SoftwareDistribution\Download') },
  @{ n = 'Prefetch';           p = ($root + 'Windows\Prefetch') },
  @{ n = 'WER';                p = (Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\WER') },
  @{ n = 'RecycleBin';         p = ($root + '$Recycle.Bin') },
  @{ n = 'ChromeCache';        p = (Join-Path $env:LOCALAPPDATA 'Google\Chrome\User Data\Default\Cache') },
  @{ n = 'EdgeCache';          p = (Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\User Data\Default\Cache') },
  @{ n = 'INetCache';          p = (Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\INetCache') },
  @{ n = 'ThumbnailCache';     p = (Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\Explorer') },
  @{ n = 'WindowsInstaller';   p = ($root + 'Windows\Installer') },
  @{ n = 'PackageCache';       p = ($root + 'ProgramData\Package Cache') },
  @{ n = 'CrashDumps';         p = (Join-Path $env:LOCALAPPDATA 'CrashDumps') },
  @{ n = 'WindowsOld';         p = ($root + 'Windows.old') },
  @{ n = 'Downloads';          p = (Join-Path $env:USERPROFILE 'Downloads') },
  @{ n = 'NvidiaDownloader';   p = ($root + 'ProgramData\NVIDIA Corporation\Downloader') },
  @{ n = 'ThunderUpdate';      p = ($root + 'ProgramData\Thunder Network\XLLiveUD\Download') }
)
foreach ($j in $junk) {
  if (Test-Path -LiteralPath $j.p) {
    $r = Measure-Tree $j.p
    Write-Output ("JUNK|" + $j.n + "|" + $r.MB + " MB|denied=" + $r.Denied + "|" + $j.p)
  } else {
    Write-Output ("JUNK|" + $j.n + "|MISSING|-|" + $j.p)
  }
}

# ---------- 3. Root folders ----------
Get-ChildItem -LiteralPath $root -Directory -Force -ErrorAction SilentlyContinue | ForEach-Object {
  $r = Measure-Tree $_.FullName
  Write-Output ("DIRSIZE|" + $_.Name + "|" + $r.MB + "|denied=" + $r.Denied)
}

# ---------- 4. User profile folders ----------
Get-ChildItem -LiteralPath $env:USERPROFILE -Directory -Force -ErrorAction SilentlyContinue | ForEach-Object {
  $r = Measure-Tree $_.FullName
  Write-Output ("USERSIZE|" + $_.Name + "|" + $r.MB + "|denied=" + $r.Denied)
}

# ---------- 5. Big files ----------
Get-ChildItem -LiteralPath $root -Recurse -File -Force -ErrorAction SilentlyContinue |
  Where-Object { $_.Length -gt ($BigFileMB * 1MB) } |
  Sort-Object Length -Descending |
  Select-Object -First 40 |
  ForEach-Object {
    Write-Output ("BIG|" + [math]::Round($_.Length / 1MB, 0) + " MB|" + $_.FullName + "|" + $_.LastWriteTime.ToString('yyyy-MM-dd'))
  }

# ---------- 6. Deep: AppData + Temp detail ----------
if ($Deep) {
  Get-ChildItem -LiteralPath $env:LOCALAPPDATA -Directory -Force -ErrorAction SilentlyContinue | ForEach-Object {
    $r = Measure-Tree $_.FullName
    [pscustomobject]@{ N = $_.Name; MB = $r.MB }
  } | Sort-Object MB -Descending | Select-Object -First 25 | ForEach-Object {
    Write-Output ("LOCALAPP|" + $_.N + "|" + $_.MB)
  }
  Get-ChildItem -LiteralPath $env:APPDATA -Directory -Force -ErrorAction SilentlyContinue | ForEach-Object {
    $r = Measure-Tree $_.FullName
    [pscustomobject]@{ N = $_.Name; MB = $r.MB }
  } | Sort-Object MB -Descending | Select-Object -First 15 | ForEach-Object {
    Write-Output ("ROAMING|" + $_.N + "|" + $_.MB)
  }
  Get-ChildItem -LiteralPath (Join-Path $env:LOCALAPPDATA 'Temp') -Force -ErrorAction SilentlyContinue | ForEach-Object {
    $r = Measure-Tree $_.FullName
    [pscustomobject]@{ N = $_.Name; MB = $r.MB }
  } | Sort-Object MB -Descending | Select-Object -First 10 | ForEach-Object {
    Write-Output ("TEMP|" + $_.N + "|" + $_.MB)
  }
}

Write-Output "DONE"
