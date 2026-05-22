# TrustLayer — ACP Seller Runtime (openclaw-acp)

## Architecture

```
ACP Buyer → openclaw-acp WebSocket → handlers.ts → Python FastAPI (port 8000) → ERC-8004 → Trust Score
```

No private key or entity_id required. Authentication is handled by the Virtuals platform via browser login.

## One-Time Setup

```powershell
# From trustlayer/ directory:
cd openclaw-setup
.\setup.ps1
```

This will:
1. Clone `Virtual-Protocol/openclaw-acp`
2. Install dependencies
3. Copy offering files
4. Run `acp setup` (interactive browser login)
5. Register the `trustScore` offering on ACP

**Requirements:** Node.js 20+, Git

## Running TrustLayer

Open two PowerShell windows:

**Window 1 — Python API:**
```powershell
cd trustlayer
.\launch.ps1 -Mode api
```

**Window 2 — ACP Seller Runtime:**
```powershell
cd trustlayer
.\openclaw-setup\start.ps1
```

## Switching to TrustLayer Agent

If `acp setup` creates a new agent instead of using TrustLayer:
```powershell
cd acp-runtime
acp agent list
acp agent switch TrustLayer
```

## Testing

Once both processes are running, test locally:
```powershell
# Test Python API directly
curl -X POST http://localhost:8000/trust -H "Content-Type: application/json" -d '{"agent_id": "42220:1870"}'

# Test ACP job (from another agent on ACP)
acp browse TrustLayer
acp job create <TrustLayer-wallet> trustScore --requirements '{"agentId":"42220:1870"}'
```

## Files

| File | Purpose |
|------|---------|
| `offering.json` | Job offering definition (matches dashboard registration) |
| `handlers.ts` | Job handler — calls Python FastAPI |
| `setup.ps1` | One-time setup script |
| `start.ps1` | Starts the ACP seller runtime |
