# ════════════════════════════════════════════════════════
# TrustLayer — Setup Script (PowerShell)
# تشغيل من مجلد trustlayer/
# ════════════════════════════════════════════════════════

Write-Host "🚀 TrustLayer Setup" -ForegroundColor Cyan

# 1. Create virtual environment
Write-Host "`n[1/4] Creating virtual environment..." -ForegroundColor Yellow
python -m venv trustlayer_env
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: Python not found!" -ForegroundColor Red; exit 1 }

# 2. Activate
Write-Host "[2/4] Activating virtual environment..." -ForegroundColor Yellow
& .\trustlayer_env\Scripts\Activate.ps1

# 3. Install dependencies
Write-Host "[3/4] Installing dependencies..." -ForegroundColor Yellow
pip install --upgrade pip
pip install -r requirements.txt

# 4. Copy .env if not exists
Write-Host "[4/4] Setting up .env file..." -ForegroundColor Yellow
if (-Not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host ".env created from template. Edit it with your credentials." -ForegroundColor Green
} else {
    Write-Host ".env already exists." -ForegroundColor Green
}

Write-Host "`n✅ Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Edit .env with your ACP credentials"
Write-Host "  2. Run: python test_live.py   (test without ACP wallet)"
Write-Host "  3. Run: python -m agent.acp_agent   (full agent)"
Write-Host ""
