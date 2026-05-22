# TrustLayer — Trust Intelligence for ACP Agents

> **Before hiring any agent, know their trust score.**
> TrustLayer reads ERC-8004 on-chain data and gives you an instant **HIRE/AVOID** recommendation.

---

## Quick Start (Windows PowerShell)

```powershell
# 1. Install dependencies
cd trustlayer
python -m venv trustlayer_env
.\trustlayer_env\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Configure
copy .env.example .env
notepad .env   # fill in your credentials

# 3. Test core logic (no credentials needed)
python test_core.py

# 4. Start API server
python -m uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload

# 5. Start full ACP agent
python -m agent.acp_agent
```

---

## Architecture

```
trustlayer/
├── core/
│   ├── chain_reader.py   ← fetches ERC-8004 data from 8004scan API
│   ├── scorer.py         ← Trust Score algorithm (0-100)
│   └── database.py       ← SQLite persistence
├── api/
│   └── server.py         ← FastAPI on port 8000
├── agent/
│   └── acp_agent.py      ← ACP Provider (accepts USDC jobs)
├── test_core.py          ← core logic tests (no server needed)
├── test_live.py          ← full integration tests
├── register_acp.py       ← ACP registration guide & tx test
└── .env                  ← credentials (never commit)
```

---

## Trust Score Formula

| Component | Weight | Source |
|-----------|--------|--------|
| Job Success Rate | **35%** | avg_feedback_score |
| Response Reliability | **25%** | service_score |
| Peer Attestations | **20%** | engagement_score + feedback volume |
| Agent Longevity | **15%** | publisher_score |
| Dispute Penalty | **−5%** | (100 − compliance_score) |

### Trust Levels
| Score | Level | Recommendation |
|-------|-------|----------------|
| 81–100 | ⭐ ELITE | HIRE |
| 61–80 | 🟢 TRUSTED | HIRE |
| 41–60 | 🟡 NEUTRAL | VERIFY |
| 21–40 | 🟠 RISKY | AVOID |
| 0–20 | 🔴 DANGEROUS | AVOID |

---

## API Reference

```bash
# Get trust score
curl -X POST http://localhost:8000/trust \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "42220:1870"}'

# Leaderboard
curl http://localhost:8000/leaderboard?limit=20

# Compare agents
curl "http://localhost:8000/compare?agents=42220:1870&agents=8453:2"

# Alerts
curl http://localhost:8000/alerts/42220:1870

# Market stats
curl http://localhost:8000/stats

# Health
curl http://localhost:8000/health
```

---

## ACP Registration (Sandbox → Mainnet)

### Step 1 — Sandbox Testing
1. Go to: https://acpx.virtuals.gg
2. Create agent named **TrustLayer**
3. Add job offering: `trust-score` / price: `0.01 USDC` / SLA: `3 min`
4. Fill `.env` with your credentials
5. Run: `python register_acp.py --network testnet`

### Step 2 — Mainnet Launch
1. Go to: https://app.virtuals.io/acp
2. Repeat registration on mainnet
3. Run: `python register_acp.py --network mainnet`
4. Run agent: `python -m agent.acp_agent`

### agent_id Format
| Format | Example | Meaning |
|--------|---------|---------|
| `chain_id:token_id` | `42220:1870` | Celo, token #1870 |
| `chain_name:token_id` | `base:42` | Base chain |
| bare `token_id` | `1870` | Base chain (default) |

---

## Environment Variables

```env
WHITELISTED_WALLET_PRIVATE_KEY=  # dev wallet private key (no 0x)
AGENT_WALLET_ADDRESS=            # 0x... smart wallet from ACP dashboard
AGENT_ENTITY_ID=                 # numeric entity ID from ACP dashboard
NETWORK=testnet                  # testnet | mainnet
API_PORT=8000
TRUSTLAYER_SERVICE_PRICE_USDC=0.01
TRUSTLAYER_SLA_MINUTES=3
UPDATE_INTERVAL_MINUTES=15
```

---

## Data Sources

- **8004scan.io** — ERC-8004 agent registry explorer
  - `GET /api/v1/stats/agents/{chain_id}/{token_id}`
  - `GET /api/v1/feedbacks?chain_id=...&agent_token_id=...`
- **ACP SDK** — `virtuals-acp==0.3.23`
  - API: `https://acpx.virtuals.io/api` (mainnet)

---

## Growth Roadmap

1. **Webhooks** — push alerts to agents subscribing to score changes
2. **Bulk API** — batch scoring for agent marketplaces
3. **Historical charts** — trend visualisation endpoint
4. **ACP Resources** — expose leaderboard as a public Resource endpoint
5. **Staking** — agents stake to boost publisher score weight
