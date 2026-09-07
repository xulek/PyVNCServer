<#
.SYNOPSIS
    Smoke-test PyVNCServer with the real UltraVNC Viewer executable.

.DESCRIPTION
    Opens a fresh UltraVNC Viewer connection for each requested encoding and
    keeps it alive for a short observation window. A viewer that exits before
    the window ends is treated as a failed interoperability check.

    Run PyVNCServer separately before starting this script. The default target
    is the safe local listener at 127.0.0.1:5900 and the viewer is always
    launched in view-only mode.

.EXAMPLE
    .\scripts\ultravnc_smoke.ps1 `
      -ViewerPath 'C:\Program Files\uvnc bvba\UltraVNC\vncviewer.exe'

.EXAMPLE
    .\scripts\ultravnc_smoke.ps1 -Encodings raw,rre,hextile,zlib,tight -SecondsPerEncoding 5
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$ViewerPath = "$env:ProgramFiles\uvnc bvba\UltraVNC\vncviewer.exe",

    [Parameter(Mandatory = $false)]
    [string]$ServerHost = "127.0.0.1",

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 65535)]
    [int]$Port = 5900,

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 120)]
    [int]$SecondsPerEncoding = 4,

    [Parameter(Mandatory = $false)]
    [ValidateSet("raw", "rre", "corre", "hextile", "zlib", "zlibhex", "tight", "ultra")]
    [string[]]$Encodings = @("raw", "rre", "hextile", "zlib", "tight"),

    [Parameter(Mandatory = $false)]
    [string]$LogDirectory = (Join-Path $env:TEMP "pyvncserver-ultravnc")
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $ViewerPath -PathType Leaf)) {
    throw "UltraVNC Viewer not found: $ViewerPath"
}

New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null

# UltraVNC accepts host::port for an explicit TCP port. Keep the short host
# form for the standard 5900 port to match the most common local setup.
$Target = if ($Port -eq 5900) { $ServerHost } else { "${ServerHost}::${Port}" }
$Failures = @()

Write-Host "PyVNCServer / UltraVNC interoperability smoke test"
Write-Host "Viewer: $ViewerPath"
Write-Host "Target: $Target"
Write-Host "Encodings: $($Encodings -join ', ')"
Write-Host ""

foreach ($Encoding in $Encodings) {
    $Timestamp = Get-Date -Format "yyyyMMdd-HHmmssfff"
    $ViewerLog = Join-Path $LogDirectory "ultravnc-$Encoding-$Timestamp.log"
    $Arguments = @(
        "-connect", $Target,
        "-encoding", $Encoding,
        "-viewonly",
        "-nocursorshape",
        "-noremotecursor",
        "-loglevel", "10",
        "-logfile", $ViewerLog
    )

    Write-Host "[$Encoding] connecting..." -ForegroundColor Cyan
    $Process = Start-Process `
        -FilePath $ViewerPath `
        -ArgumentList $Arguments `
        -PassThru

    try {
        $Deadline = (Get-Date).AddSeconds($SecondsPerEncoding)
        $ExitedEarly = $false
        while ((Get-Date) -lt $Deadline) {
            Start-Sleep -Milliseconds 200
            $Process.Refresh()
            if ($Process.HasExited) {
                $ExitedEarly = $true
                break
            }
        }

        if ($ExitedEarly) {
            $ExitCode = $Process.ExitCode
            $Failures += $Encoding
            Write-Host "[$Encoding] FAILED: viewer exited early (code $ExitCode)" -ForegroundColor Red
            if (Test-Path -LiteralPath $ViewerLog) {
                Write-Host "[$Encoding] UltraVNC log: $ViewerLog"
            }
            continue
        }

        Write-Host "[$Encoding] OK: connection stayed alive for $SecondsPerEncoding s" -ForegroundColor Green
    }
    finally {
        $Process.Refresh()
        if (-not $Process.HasExited) {
            Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
            $Process.WaitForExit(3000) | Out-Null
        }
    }

    Start-Sleep -Milliseconds 400
}

Write-Host ""
if ($Failures.Count -gt 0) {
    Write-Host "FAILED encodings: $($Failures -join ', ')" -ForegroundColor Red
    Write-Host "Logs: $LogDirectory"
    exit 1
}

Write-Host "All UltraVNC smoke checks passed." -ForegroundColor Green
Write-Host "Logs: $LogDirectory"
exit 0
