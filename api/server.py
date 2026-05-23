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

Security hardening (2025-05):
  - CORS restricted to known origins
  - Rate limiting via slowapi (60/min global, 10/min on /trust, 5/min on /compare)
  - Strict agent_id input validation (regex + max length)
  - API docs disabled in production
  - Security response headers (X-Content-Type-Options, X-Frame-Options, CSP, etc.)
  - 64 KB request body limit
"""

import os
import re
import sys
import logging
import time
from typing import List, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

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

# ── Environment flags ─────────────────────────────────────────────────────
_ENV = os.getenv("ENVIRONMENT", "production").lower()
_IS_DEV = _ENV in ("development", "dev", "local")

# ── Rate limiter ──────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

# ── CORS allowed origins ──────────────────────────────────────────────────
_CORS_ORIGINS = [
    "https://app.virtuals.io",
    "https://virtuals.io",
    "https://trustlayer-d3rf.onrender.com",
]
if _IS_DEV:
    _CORS_ORIGINS += [
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
    ]

# ── Agent ID validation pattern ───────────────────────────────────────────
# Accepts: "8453:1870", "42220:1200", "1870", "0x1a2b3c..." (hex wallet)
_AGENT_ID_RE = re.compile(
    r"^(?:\d{1,10}:\d{1,10}|[a-zA-Z]+:\d{1,10}|\d{1,10}|0x[0-9a-fA-F]{40})$"
)
_AGENT_ID_MAX_LEN = 100

# ── App ───────────────────────────────────────────────────────────────────

app = FastAPI(
    title="TrustLayer",
    description=(
        "Trust Intelligence for ACP Agents. "
        "Reads ERC-8004 on-chain data and delivers instant HIRE/AVOID decisions."
    ),
    version="1.0.0",
    # Disable interactive docs in production to avoid leaking API structure
    docs_url="/docs" if _IS_DEV else None,
    redoc_url="/redoc" if _IS_DEV else None,
    openapi_url="/openapi.json" if _IS_DEV else None,
)

# Attach rate-limit error handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS middleware ───────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Accept"],
)


# ── Security headers middleware ───────────────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = "default-src 'none'"
        response.headers["Cache-Control"] = "no-store"
        return response

app.add_middleware(SecurityHeadersMiddleware)


# ── Request size limit middleware (64 KB max body) ────────────────────────
class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    _MAX_BYTES = 65_536  # 64 KB

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self._MAX_BYTES:
            return JSONResponse(
                status_code=413,
                content={"error": "Request body too large (max 64 KB)."},
            )
        return await call_next(request)

app.add_middleware(MaxBodySizeMiddleware)

_start_time = time.time()


@app.on_event("startup")
async def startup():
    init_db()
    start_background_refresh()
    logger.info("TrustLayer API started (env=%s)", _ENV)


# ── Request / Response Models ─────────────────────────────────────────────

class TrustRequest(BaseModel):
    agent_id: str = Field(
        ...,
        max_length=_AGENT_ID_MAX_LEN,
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

    @field_validator("agent_id")
    @classmethod
    def validate_agent_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("agent_id must not be empty")
        if len(v) > _AGENT_ID_MAX_LEN:
            raise ValueError(f"agent_id too long (max {_AGENT_ID_MAX_LEN} chars)")
        if not _AGENT_ID_RE.match(v):
            raise ValueError(
                "agent_id must be 'chain_id:token_id', 'chain_name:token_id', "
                "a bare token_id integer, or an EVM wallet address (0x...)"
            )
        return v


class CompareRequest(BaseModel):
    agents: List[str] = Field(
        ..., min_length=2, max_length=5,
        example=["8453:1870", "42220:1200"],
        description="List of agent_ids to compare (2-5).",
    )

    @field_validator("agents")
    @classmethod
    def validate_agents(cls, v: List[str]) -> List[str]:
        validated = []
        for raw in v:
            raw = raw.strip()
            if not _AGENT_ID_RE.match(raw):
                raise ValueError(f"Invalid agent_id format: {raw!r}")
            validated.append(raw)
        return validated


# ── Routes ────────────────────────────────────────────────────────────────

@app.get("/trust/{agent_id}", summary="Get Trust Score for an agent (GET shortcut)")
@limiter.limit("10/minute")
async def get_trust_by_path(request: Request, agent_id: str, force_refresh: bool = False):
    """
    GET shortcut for the trust score endpoint.
    Used by ACP resource URL: /trust/{{clientAddress}}
    """
    agent_id = agent_id.strip()
    if not _AGENT_ID_RE.match(agent_id):
        raise HTTPException(400, "Invalid agent_id format.")
    composite_id = _normalise_id(agent_id)

    if not force_refresh:
        cached = get_latest_trust_score(composite_id)
        if cached:
            return _format_trust_response(cached, source="cache")

    raw = fetch_agent(composite_id)
    if raw is None:
        raise HTTPException(
            404,
            detail={
                "error": f"Agent '{agent_id}' not found on 8004scan.",
                "hint": "Use format 'chain_id:token_id' e.g. '8453:1870' for Base chain.",
            },
        )
    add_watched_agent(composite_id)
    result = compute_trust_score(composite_id, raw_data=raw)
    return _format_trust_response(result, source="live")


@app.post("/trust", summary="Get Trust Score for an agent")
@limiter.limit("10/minute")
async def get_trust(request: Request, body: TrustRequest):
    """
    Returns the Trust Score, Level, Trend, Recommendation, and Red Flags
    for a given ACP/ERC-8004 agent.
    """
    agent_id = body.agent_id  # already validated and stripped
    composite_id = _normalise_id(agent_id)

    # Check cache first (unless force_refresh)
    if not body.force_refresh:
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
@limiter.limit("30/minute")
async def leaderboard(request: Request, limit: int = Query(20, ge=1, le=100)):
    """
    Returns the top N agents sorted by TrustLayer score (highest first).
    """
    rows = get_leaderboard(limit=limit)
    return {
        "count":  len(rows),
        "agents": rows,
    }


@app.get("/compare", summary="Compare multiple agents side-by-side")
@limiter.limit("5/minute")
async def compare_agents(
    request: Request,
    agents: List[str] = Query(
        ...,
        description="agent_id values to compare (repeat param for each, max 5).",
        example=["8453:1870", "42220:1200"],
    )
):
    """
    Compares 2-5 agents side-by-side. Fetches fresh data if not cached.
    """
    if len(agents) < 2:
        raise HTTPException(400, "Provide at least 2 agent IDs.")
    if len(agents) > 5:
        raise HTTPException(400, "Maximum 5 agents per comparison.")

    # Validate each agent_id before doing any upstream calls
    for raw_id in agents:
        if not _AGENT_ID_RE.match(raw_id.strip()):
            raise HTTPException(400, f"Invalid agent_id format: {raw_id!r}")

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
@limiter.limit("20/minute")
async def get_agent_alerts(
    request: Request,
    agent_id: str,
    limit: int = Query(10, ge=1, le=50),
):
    """
    Returns alerts when an agent's trust score changed by ≥ 10 points.
    """
    agent_id = agent_id.strip()
    if not _AGENT_ID_RE.match(agent_id):
        raise HTTPException(400, "Invalid agent_id format.")
    composite_id = _normalise_id(agent_id)
    alerts = get_alerts(composite_id, limit=limit)
    return {
        "agent_id": composite_id,
        "alerts":   alerts,
        "count":    len(alerts),
    }


@app.get("/stats", summary="Market-wide TrustLayer statistics")
@limiter.limit("30/minute")
async def market_stats(request: Request):
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
        "uptime_seconds": uptime,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


# ── Helpers ─────────────────────────────────────────────────────────────────

def _normalise_id(raw: str) -> str:
    """
    Ensure agent_id is in 'chain_id:token_id' format.
    Falls back to '8453:{\}raw}' if bare integer given.
    Input has already been validated by _AGENT_ID_RE before this is called.
    """
    raw = raw.strip()
    if ":" in raw:
        return raw
    try:
        int(raw)
        return f"8453:{raw}"    # assume Base
    except ValueError:
        return raw              # wallet address


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


# ── Run ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("API_PORT", 8000))
    host = os.getenv("API_HOST", "0.0.0.0")
    uvicorn.run("api.server:app", host=host, port=port, reload=False)
