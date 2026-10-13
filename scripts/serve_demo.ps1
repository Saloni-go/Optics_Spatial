# Host the Track 3 interactive viewer on this PC and reach it from any device, anywhere.
#
#   .\scripts\serve_demo.ps1                 # 2000 x 2000 map, port 8988
#   .\scripts\serve_demo.ps1 -Size 4000      # full 16 M-cell map
#
# 1. starts the viewer as a web server (corridor.interactive --web): the PC does all the computing;
# 2. if cloudflared is installed (winget install Cloudflare.cloudflared), opens a free Cloudflare quick
#    tunnel and prints a public https://....trycloudflare.com link that works on any network and device.
# Anyone with the link can use the viewer while this window is open. Ctrl+C stops everything.
param([int]$Size = 2000, [int]$Port = 8988)

$root = Split-Path $PSScriptRoot -Parent
Write-Host "Starting the viewer (map $Size x $Size) on port $Port ..."
$viewer = Start-Process -FilePath "$root\run.bat" -WorkingDirectory $root -PassThru -WindowStyle Minimized `
          -ArgumentList "-m corridor.interactive --web --size $Size --port $Port"

# wait until the server answers (precompute takes a few seconds)
$ok = $false
foreach ($i in 1..120) {
    try { Invoke-WebRequest "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 2 | Out-Null; $ok = $true; break }
    catch { Start-Sleep -Seconds 1 }
}
if (-not $ok) { Write-Host "The viewer did not start; run '.\run.bat -m corridor.interactive --web' to see the error."; exit 1 }
Write-Host "Viewer is up:  http://127.0.0.1:$Port  (this PC)"

$cf = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cf) {
    $cand = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Cloudflare.cloudflared*\cloudflared.exe", `
                          "C:\Program Files*\cloudflared\cloudflared.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cand) { $cf = $cand.FullName } else { $cf = $null }
} else { $cf = $cf.Source }
if (-not $cf) {
    Write-Host ""
    Write-Host "cloudflared is not installed, so the viewer is only reachable on this network."
    Write-Host "Install it once with:   winget install Cloudflare.cloudflared   and run this script again."
    Write-Host "Press Ctrl+C to stop the viewer."
    try { Wait-Process -Id $viewer.Id } finally { Stop-Process -Id $viewer.Id -ErrorAction SilentlyContinue }
    exit 0
}

Write-Host ""
Write-Host "Opening a public tunnel. Look for the line with  https://....trycloudflare.com  below:"
Write-Host "open that link on any phone / laptop. Keep this window open; Ctrl+C stops it."
Write-Host ""
try { & $cf tunnel --url "http://127.0.0.1:$Port" }
finally {
    # stop the viewer (run.bat starts python as a child process)
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match "corridor.interactive" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}
