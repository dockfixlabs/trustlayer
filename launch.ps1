# ════════════════════════════════════════════════════════
# TrustLayer — Launch Script (PowerShell)
# شغّل من مجلد trustlayer/ بعد setup.ps1
# ════════════════════════════════════════════════════════

param(
    [string]$Mode = "api",      # "api" | "agent" | "test"
    [string]$Network = "testnet" # "testnet" | "mainnet"
)

# Activate venv if exists
if (Test-Path ".\trustlayer_env\Scripts\Activate.ps1") {
    & .\trustlayer_env\Scripts\Activate.ps1
}

switch ($Mode) {
    "test" {
        Write-Host "Running live tests..." -ForegroundColor Cyan
        python test_live.py
    }
    "api" {
        Write-Host "Starting TrustLayer API on port 8000..." -ForegroundColor Green
        Write-Host "Docs: http://localhost:8000/docs" -ForegroundColor Yellow
        $env:NETWORK = $Network
        python -m uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload
    }
    "agent" {
        Write-Host "Starting TrustLayer ACP Agent ($Network)..." -ForegroundColor Green
        $env:NETWORK = $Network
        python -m agent.acp_agent
    }
    default {
        Write-Host "Usage: .\launch.ps1 -Mode [api|agent|test] -Network [testnet|mainnet]"
    }
}
