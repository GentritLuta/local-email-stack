# Generate-Icon.ps1
# Multi-resolution Windows .ico for LocalEmailStack.
# At 16/24/32 we render a SIMPLIFIED variant (envelope + spark only) so the
# taskbar icon stays crisp. At 48-256 we render the full orbit design.

[CmdletBinding()]
param(
  [string]$OutDir = "$PSScriptRoot\src-tauri\icons"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }

# All sizes Windows commonly asks for, including taskbar + jump list + Alt-Tab.
$Sizes = @(16, 24, 32, 48, 64, 96, 128, 256)

function New-Bg([int]$Size, $g) {
  $r = [Math]::Max(2, [int]($Size * 0.19))
  $rect = New-Object System.Drawing.Rectangle 0, 0, $Size, $Size
  $path = New-Object System.Drawing.Drawing2D.GraphicsPath
  $path.AddArc($rect.X, $rect.Y, $r*2, $r*2, 180, 90)
  $path.AddArc($rect.Right-$r*2, $rect.Y, $r*2, $r*2, 270, 90)
  $path.AddArc($rect.Right-$r*2, $rect.Bottom-$r*2, $r*2, $r*2, 0, 90)
  $path.AddArc($rect.X, $rect.Bottom-$r*2, $r*2, $r*2, 90, 90)
  $path.CloseFigure()
  $brush = New-Object System.Drawing.Drawing2D.LinearGradientBrush $rect,
    ([System.Drawing.Color]::FromArgb(255, 15, 23, 42)),
    ([System.Drawing.Color]::FromArgb(255, 2, 6, 23)),
    ([System.Drawing.Drawing2D.LinearGradientMode]::ForwardDiagonal)
  $g.FillPath($brush, $path)
  $brush.Dispose(); $path.Dispose()
}

function Draw-Envelope([int]$Size, $g, [double]$scale = 0.55) {
  $cx = $Size / 2.0; $cy = $Size / 2.0
  $ew = $Size * $scale
  $eh = $ew * 0.67
  $ex = $cx - $ew/2; $ey = $cy - $eh/2
  $brush = New-Object System.Drawing.Drawing2D.LinearGradientBrush `
    (New-Object System.Drawing.Rectangle ([int]$ex, [int]$ey, [int]$ew, [int]$eh)),
    ([System.Drawing.Color]::FromArgb(255, 226, 232, 240)),
    ([System.Drawing.Color]::FromArgb(255, 148, 163, 184)),
    ([System.Drawing.Drawing2D.LinearGradientMode]::Vertical)
  $pen = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(255, 15, 23, 42)), ([Math]::Max(1.0, $Size/85.0))
  $envR = [Math]::Max(1, [int]($Size * 0.04))
  $path = New-Object System.Drawing.Drawing2D.GraphicsPath
  $rect = New-Object System.Drawing.Rectangle ([int]$ex, [int]$ey, [int]$ew, [int]$eh)
  $path.AddArc($rect.X, $rect.Y, $envR*2, $envR*2, 180, 90)
  $path.AddArc($rect.Right-$envR*2, $rect.Y, $envR*2, $envR*2, 270, 90)
  $path.AddArc($rect.Right-$envR*2, $rect.Bottom-$envR*2, $envR*2, $envR*2, 0, 90)
  $path.AddArc($rect.X, $rect.Bottom-$envR*2, $envR*2, $envR*2, 90, 90)
  $path.CloseFigure()
  $g.FillPath($brush, $path); $g.DrawPath($pen, $path)
  $flapPen = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(255, 15, 23, 42)), ([Math]::Max(1.5, $Size/60.0))
  $flapPen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
  $g.DrawLines($flapPen, @(
    (New-Object System.Drawing.PointF ([float]$ex, [float]$ey)),
    (New-Object System.Drawing.PointF ([float]$cx, [float]($cy + $eh*0.32))),
    (New-Object System.Drawing.PointF ([float]($ex+$ew), [float]$ey))
  ))
  # Spark above flap
  $sparkR = [Math]::Max(1.5, $Size/22.0)
  $sb = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 163, 230, 53))
  $g.FillEllipse($sb, [single]($cx - $sparkR), [single]($cy - $eh*0.62 - $sparkR), [single]($sparkR*2), [single]($sparkR*2))
  $sb.Dispose(); $brush.Dispose(); $pen.Dispose(); $flapPen.Dispose(); $path.Dispose()
}

function Draw-Orbits([int]$Size, $g) {
  $cx = $Size/2.0; $cy = $Size/2.0
  $rxLarge = $Size*0.39; $ryLarge = $Size*0.195; $rCircle = $Size*0.35
  $thick = [Math]::Max(1.2, $Size/80.0)
  function E($g, $cx, $cy, $rx, $ry, $color, $thick, $angleDeg) {
    $g.TranslateTransform($cx, $cy); $g.RotateTransform($angleDeg)
    $pen = New-Object System.Drawing.Pen $color, $thick
    $g.DrawEllipse($pen, -$rx, -$ry, $rx*2, $ry*2)
    $pen.Dispose(); $g.ResetTransform()
  }
  E $g $cx $cy $rxLarge $ryLarge ([System.Drawing.Color]::FromArgb(217, 34, 211, 238)) $thick (-15)
  E $g $cx $cy $rCircle $rCircle ([System.Drawing.Color]::FromArgb(140, 163, 230, 53)) $thick 0
  E $g $cx $cy $rxLarge $ryLarge ([System.Drawing.Color]::FromArgb(217, 34, 211, 238)) $thick 75
  $nodeR = [Math]::Max(2.0, $Size/25.6)
  function N($g, $x, $y, $r, $color) {
    $b = New-Object System.Drawing.SolidBrush $color
    $g.FillEllipse($b, [single]($x-$r), [single]($y-$r), [single]($r*2), [single]($r*2))
    $b.Dispose()
  }
  N $g ($Size*0.879) ($Size*0.391) $nodeR ([System.Drawing.Color]::FromArgb(255, 163, 230, 53))
  N $g ($Size*0.195) ($Size*0.684) $nodeR ([System.Drawing.Color]::FromArgb(255, 34, 211, 238))
  N $g ($Size*0.742) ($Size*0.840) $nodeR ([System.Drawing.Color]::FromArgb(255, 14, 165, 233))
}

function Render-Bitmap([int]$Size) {
  $bmp = New-Object System.Drawing.Bitmap $Size, $Size, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
  $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
  New-Bg $Size $g
  # At <= 32 the orbits are noisy. Use simplified design: just the envelope + spark, but bigger.
  if ($Size -le 32) {
    Draw-Envelope $Size $g 0.72
  } else {
    Draw-Orbits $Size $g
    Draw-Envelope $Size $g 0.35
  }
  $g.Dispose()
  return $bmp
}

# Render
$bitmaps = @{}
foreach ($s in $Sizes) {
  Write-Host "  rendering ${s}x${s}$(if ($s -le 32) {' (simplified)'})"
  $bitmaps[$s] = Render-Bitmap $s
  $bitmaps[$s].Save((Join-Path $OutDir "${s}x${s}.png"), [System.Drawing.Imaging.ImageFormat]::Png)
}
$bitmaps[256].Save((Join-Path $OutDir "icon.png"), [System.Drawing.Imaging.ImageFormat]::Png)

# ─── Build multi-size ICO ───────────────────────────────────────────────────
# Use raw RGBA bitmap entries (the "BMP" format inside ICO) for sizes <= 48,
# and PNG-compressed entries for 64+. This matches how high-quality Windows
# icons are typically authored and ensures crisp small-size rendering.
$icoPath = Join-Path $OutDir "icon.ico"
$ms = New-Object System.IO.MemoryStream
$bw = New-Object System.IO.BinaryWriter $ms
$bw.Write([uint16]0); $bw.Write([uint16]1); $bw.Write([uint16]$Sizes.Count)

# Convert each bitmap to its on-disk representation
$blobs = @{}
foreach ($s in $Sizes) {
  if ($s -ge 64) {
    # PNG-compressed entry
    $mem = New-Object System.IO.MemoryStream
    $bitmaps[$s].Save($mem, [System.Drawing.Imaging.ImageFormat]::Png)
    $blobs[$s] = $mem.ToArray()
  } else {
    # DIB entry (BITMAPINFOHEADER + pixel data + AND-mask)
    # Reference: https://en.wikipedia.org/wiki/ICO_(file_format)
    $bmp = $bitmaps[$s]
    $w = $bmp.Width; $h = $bmp.Height
    $rect = New-Object System.Drawing.Rectangle 0, 0, $w, $h
    $bd = $bmp.LockBits($rect, [System.Drawing.Imaging.ImageLockMode]::ReadOnly, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $stride = [Math]::Abs($bd.Stride)
    $pixelBytes = New-Object byte[] ($stride * $h)
    [System.Runtime.InteropServices.Marshal]::Copy($bd.Scan0, $pixelBytes, 0, $pixelBytes.Length)
    $bmp.UnlockBits($bd)
    # Flip rows (ICO stores bottom-up); pixels are already BGRA in 32bpp ARGB on little-endian.
    $flipped = New-Object byte[] $pixelBytes.Length
    for ($row = 0; $row -lt $h; $row++) {
      $src = $row * $stride
      $dst = ($h - 1 - $row) * $stride
      [Array]::Copy($pixelBytes, $src, $flipped, $dst, $stride)
    }
    # BITMAPINFOHEADER: 40 bytes
    $dib = New-Object System.IO.MemoryStream
    $dw = New-Object System.IO.BinaryWriter $dib
    $dw.Write([uint32]40)            # biSize
    $dw.Write([int32]$w)             # biWidth
    $dw.Write([int32]($h*2))         # biHeight = 2x because XOR + AND masks
    $dw.Write([uint16]1)             # biPlanes
    $dw.Write([uint16]32)            # biBitCount
    $dw.Write([uint32]0)             # biCompression = BI_RGB
    $dw.Write([uint32]($pixelBytes.Length))
    $dw.Write([int32]0); $dw.Write([int32]0); $dw.Write([uint32]0); $dw.Write([uint32]0)
    $dw.Write($flipped)
    # AND mask: 1-bit per pixel, row-aligned to 32 bits, all zeros (fully opaque)
    $andStrideBytes = (($w + 31) -shr 5) * 4
    $andSize = $andStrideBytes * $h
    $andMask = New-Object byte[] $andSize
    $dw.Write($andMask)
    $dw.Flush()
    $blobs[$s] = $dib.ToArray()
    $dw.Dispose(); $dib.Dispose()
  }
}

# Directory entries
$headerSize = 6
$dirEntrySize = 16
$dataOffset = $headerSize + $dirEntrySize * $Sizes.Count
$current = $dataOffset
foreach ($s in $Sizes) {
  $bytes = $blobs[$s]
  $w = if ($s -ge 256) { 0 } else { [byte]$s }
  $h = $w
  $bw.Write([byte]$w); $bw.Write([byte]$h)
  $bw.Write([byte]0); $bw.Write([byte]0)
  $bw.Write([uint16]1); $bw.Write([uint16]32)
  $bw.Write([uint32]$bytes.Length)
  $bw.Write([uint32]$current)
  $current += $bytes.Length
}
foreach ($s in $Sizes) { $bw.Write($blobs[$s]) }
$bw.Flush()
[System.IO.File]::WriteAllBytes($icoPath, $ms.ToArray())
$bw.Dispose(); $ms.Dispose()
foreach ($s in $Sizes) { $bitmaps[$s].Dispose() }

Write-Host ""
Write-Host "[ok] $icoPath ($((Get-Item $icoPath).Length) bytes, $($Sizes.Count) sizes)"
Write-Host "[ok] $OutDir\icon.png"
