# ═══════════════════════════════════════════════════════════════════════════
# TrustLayer — Start ACP Seller Runtime
# يفترض تشغيل setup.ps1 أولاً.  يشغّل وكيل البيع (WebSocket) لقبول الوظائف.
# ═══════════════════════════════════════════════════════════════════════════

$Root   = Split-Path $PSScriptRoot -Parent
$AcpDir = "$Root\acp-runtime"

if (-not (Test-Path $AcpDir)) {
    Write-Host "ERROR: acp-runtime not found. Run setup.ps1 first." -ForegroundColor Red
    exit 1
}

Write-Host "`n══════════════════════════════════════════" -ForegroundColor Green
Write-Host "  TrustLayer ACP Seller — Starting..." -ForegroundColor Green
Write-Host "══════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host "  Make sure the Python API is running first:" -ForegroundColor Yellow
Write-Host "  .\launch.ps1 -Mode api" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Starting ACP seller runtime (WebSocket)..." -ForegroundColor White
Write-Host "  Listening for trustScore jobs on ACP..." -ForegroundColor White
Write-Host "  Press Ctrl+C to stop." -ForegroundColor Gray
Write-Host ""

Push-Location $AcpDir
$acpExists = Get-Command acp -ErrorAction SilentlyContinue
if ($acpExists) {
    acp serve start
} else {
    npx tsx bin/acp.ts serve start
}
Pop-Location
