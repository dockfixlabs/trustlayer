"""
TrustLayer — server.py
FastAPI on port 8000.

Endpoints:
  POST /trust              → compute/return trust score for agent_id
  GET  /leaderboard        → top agents by trust score
  GET  /compare            → compare multiple agents
  GET  /alerts/{agent_id}  → score change alerts
  GET  /stats              → market-wide statistics
  GET  /health             → service health check
"""

import os
import sys
import logging
import time
from typing import List, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.database import (
    init_db, get_latest_trust_score, get_leaderboard,
    get_alerts, get_market_stats,
)
from core.chain_reader import (
    fetch_agent, add_watched_agent, start_background_refresh,
)
from core.scorer import compute_trust_score

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("TrustLayer.API")

# ── App ───────────────────────────────────────────────────────────────────

app = FastAPI(
    title="TrustLayer",
    description=(
        "Trust Intelligence for ACP Agents. "
        "Reads ERC-8004 on-chain data and delivers instant HIRE/AVOID decisions."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_start_time = time.time()


@app.on_event("startup")
async def startup():
    init_db()
    start_background_refresh()
    logger.info("TrustLayer API started")


# ── Request / Response Models ─────────────────────────────────────────────

class TrustRequest(BaseModel):
    agent_id: str = Field(
        ...,
        example="8453:1870",
        description=(
            "Agent identifier. Formats accepted: "
            "'{chain_id}:{token_id}', '{chain_name}:{token_id}', or bare '{token_id}' (Base default)."
        ),
    )
    force_refresh: bool = Field(
        False,
        description="Force a fresh fetch from 8004scan instead of returning cached score.",
    )


class CompareRequest(BaseModel):
    agents: List[str] = Field(
        ..., min_length=2, max_length=10,
        example=["8453:1870", "42220:1200"],
        description="List of agent_ids to compare (2-10).",
    )


# ── Routes ────────────────────────────────────────────────────────────────

@app.post("/trust", summary="Get Trust Score for an agent")
async def get_trust(request: TrustRequest):
    """
    Returns the Trust Score, Level, Trend, Recommendation, and Red Flags
    for a given ACP/ERC-8004 agent.
    """
    agent_id = request.agent_id.strip()
    if not agent_id:
        raise HTTPException(400, "agent_id is required")

    # Normalise: convert pure wallet addresses or plain names
    composite_id = _normalise_id(agent_id)

    # Check cache first (unless force_refresh)
    if not request.force_refresh:
        cached = get_latest_trust_score(composite_id)
        if cached:
            return _format_trust_response(cached, source="cache")

    # Fetch fresh data from 8004scan
    raw = fetch_agent(composite_id)
    if raw is None:
        raise HTTPException(
            404,
            detail={
                "error": f"Agent '{agent_id}' not found on 8004scan.",
                "hint": "Use format 'chain_id:token_id' e.g. '8453:1870' for Base chain.",
            },
        )

    # Track this agent for background refresh
    add_watched_agent(composite_id)

    # Compute & persist trust score
    result = compute_trust_score(composite_id, raw_data=raw)

    return _format_trust_response(result, source="live")


@app.get("/leaderboard", summary="Top agents by Trust Score")
async def leaderboard(limit: int = Query(20, ge=1, le=100)):
    """
    Returns the top N agents sorted by TrustLayer score (highest first).
    """
    rows = get_leaderboard(limit=limit)
    return {
        "count":  len(rows),
        "agents": rows,
    }


@app.get("/compare", summary="Compare multiple agents side-by-side")
async def compare_agents(
    agents: List[str] = Query(
        ...,
        description="agent_id values to compare (repeat param for each).",
        example=["8453:1870", "42220:1200"],
    )
):
    """
    Compares 2-10 agents side-by-side. Fetches fresh data if not cached.
    """
    if len(agents) < 2:
        raise HTTPException(400, "Provide at least 2 agent IDs.")
    if len(agents) > 10:
        raise HTTPException(400, "Maximum 10 agents per comparison.")

    results = []
    for raw_id in agents:
        cid = _normalise_id(raw_id)
        cached = get_latest_trust_score(cid)
        if cached is None:
            raw = fetch_agent(cid)
            if raw:
                add_watched_agent(cid)
                cached = compute_trust_score(cid, raw_data=raw)
        if cached:
            results.append(_format_trust_response(cached))

    results.sort(key=lambda x: x["score"], reverse=True)
    return {
        "count":    len(results),
        "winner":   results[0]["agent_id"] if results else None,
        "compared": results,
    }


@app.get("/alerts/{agent_id}", summary="Score-change alerts for an agent")
async def get_agent_alerts(agent_id: str, limit: int = Query(10, ge=1, le=50)):
    """
    Returns alerts when an agent's trust score changed by ≥ 10 points.
    """
    composite_id = _normalise_id(agent_id)
    alerts = get_alerts(composite_id, limit=limit)
    return {
        "agent_id": composite_id,
        "alerts":   alerts,
        "count":    len(alerts),
    }


@app.get("/stats", summary="Market-wide TrustLayer statistics")
async def market_stats():
    """
    Returns aggregate statistics: total agents tracked, average score,
    and level distribution.
    """
    return get_market_stats()


@app.get("/health", summary="Health check")
async def health():
    uptime = round(time.time() - _start_time, 1)
    return {
        "status":  "ok",
        "service": "TrustLayer",
        "version": "1.0.0",
        "uptime_seconds": uptime,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


# ── Helpers ───────────────────────────────────────────────────────────────

def _normalise_id(raw: str) -> str:
    """
    Ensure agent_id is in 'chain_id:token_id' format.
    Falls back to '8453:{raw}' if bare integer given.
    """
    raw = raw.strip()
    if ":" in raw:
        return raw
    try:
        int(raw)
        return f"8453:{raw}"    # assume Base
    except ValueError:
        return raw              # wallet address or unknown format


def _format_trust_response(data: dict, source: str = "cache") -> dict:
    """Build the clean API response dict."""
    return {
        "agent_id":       data.get("agent_id") or data.get("id"),
        "score":          data.get("score") or data.get("trust_score", 0),
        "level":          data.get("level") or data.get("trust_level", "UNKNOWN"),
        "emoji":          data.get("emoji", ""),
        "trend":          data.get("trend", "Stable"),
        "recommendation": data.get("recommendation", "VERIFY"),
        "red_flags":      data.get("red_flags", []),
        "breakdown":      data.get("breakdown", {}),
        "last_updated":   data.get("last_updated") or data.get("computed_at"),
        "_source":        source,
    }


# ── Run ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("API_PORT", 8000))
    host = os.getenv("API_HOST", "0.0.0.0")
    uvicorn.run("api.server:app", host=host, port=port, reload=False)
