# ═══════════════════════════════════════════════════════════════════════════
# TrustLayer — OpenClaw ACP Seller Setup (PowerShell)
# يُشغَّل مرة واحدة لإعداد كل شيء.  ثم شغّل start.ps1 لتشغيل الوكيل.
# ═══════════════════════════════════════════════════════════════════════════

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent   # trustlayer/
$AcpDir = "$Root\acp-runtime"              # where openclaw-acp will live

Write-Host "`n══════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  TrustLayer — ACP Seller Setup" -ForegroundColor Cyan
Write-Host "══════════════════════════════════════════`n" -ForegroundColor Cyan

# ── 1. Check Node.js ────────────────────────────────────────────────────────
Write-Host "Checking Node.js..." -ForegroundColor Yellow
try {
    $nodeVer = node --version 2>&1
    Write-Host "  OK  Node.js $nodeVer" -ForegroundColor Green
} catch {
    Write-Host "  FAIL  Node.js not found!" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Install Node.js 20+ from: https://nodejs.org/" -ForegroundColor Yellow
    Write-Host "  Then re-run this script." -ForegroundColor Yellow
    exit 1
}

# ── 2. Clone / update openclaw-acp ─────────────────────────────────────────
Write-Host "`nSetting up openclaw-acp runtime..." -ForegroundColor Yellow
if (Test-Path "$AcpDir\.git") {
    Write-Host "  Updating existing openclaw-acp..." -ForegroundColor Gray
    Push-Location $AcpDir
    git pull --quiet
    Pop-Location
} else {
    Write-Host "  Cloning openclaw-acp..." -ForegroundColor Gray
    git clone https://github.com/Virtual-Protocol/openclaw-acp.git $AcpDir --quiet
}
Write-Host "  OK  openclaw-acp ready at $AcpDir" -ForegroundColor Green

# ── 3. Install npm dependencies ─────────────────────────────────────────────
Write-Host "`nInstalling npm dependencies..." -ForegroundColor Yellow
Push-Location $AcpDir
npm install --silent
Write-Host "  OK  Dependencies installed" -ForegroundColor Green

# ── 4. Link acp CLI globally ─────────────────────────────────────────────────
Write-Host "`nLinking acp CLI..." -ForegroundColor Yellow
npm link --silent 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  WARN  npm link failed — will use npx tsx bin/acp.ts instead" -ForegroundColor Yellow
    $global:UseNpx = $true
} else {
    Write-Host "  OK  'acp' command available globally" -ForegroundColor Green
    $global:UseNpx = $false
}
Pop-Location

# ── 5. Copy offering files ───────────────────────────────────────────────────
Write-Host "`nCopying TrustLayer offering files..." -ForegroundColor Yellow
$OfferingDir = "$AcpDir\src\seller\offerings\trustScore"
New-Item -ItemType Directory -Force -Path $OfferingDir | Out-Null
Copy-Item "$PSScriptRoot\offering.json" "$OfferingDir\offering.json" -Force
Copy-Item "$PSScriptRoot\handlers.ts"  "$OfferingDir\handlers.ts"  -Force
Write-Host "  OK  Offering files copied to $OfferingDir" -ForegroundColor Green

# ── 6. Run acp setup (interactive login) ────────────────────────────────────
Write-Host "`n══════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  STEP: Login to Virtuals Protocol" -ForegroundColor Cyan
Write-Host "══════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Running 'acp setup'..." -ForegroundColor Yellow
Write-Host "  - Login with your Virtuals account" -ForegroundColor White
Write-Host "  - When prompted for agent name, use: TrustLayer" -ForegroundColor White
Write-Host "  - If TrustLayer already exists, choose to use existing agent" -ForegroundColor White
Write-Host ""
Push-Location $AcpDir
if ($global:UseNpx) {
    npx tsx bin/acp.ts setup
} else {
    acp setup
}
Pop-Location

# ── 7. Register offering on ACP ───────────────────────────────────────────────
Write-Host "`n══════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  STEP: Register trustScore offering" -ForegroundColor Cyan
Write-Host "══════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Push-Location $AcpDir
if ($global:UseNpx) {
    npx tsx bin/acp.ts sell create trustScore
} else {
    acp sell create trustScore
}
Pop-Location
Write-Host "  OK  trustScore offering registered" -ForegroundColor Green

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host "`n══════════════════════════════════════════" -ForegroundColor Green
Write-Host "  SETUP COMPLETE!" -ForegroundColor Green
Write-Host "══════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor White
Write-Host "  1. Start Python API:   .\launch.ps1 -Mode api" -ForegroundColor Cyan
Write-Host "  2. Start ACP runtime:  .\openclaw-setup\start.ps1" -ForegroundColor Cyan
Write-Host ""
