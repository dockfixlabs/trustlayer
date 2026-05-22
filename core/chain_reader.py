"""
TrustLayer — chain_reader.py
Reads ERC-8004 agent data from 8004scan API and persists to SQLite.
Updates every UPDATE_INTERVAL_MINUTES automatically.
"""

import os
import time
import logging
import threading
import requests
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

from dotenv import load_dotenv
from core.database import upsert_agent, upsert_stats, init_db

load_dotenv()
logger = logging.getLogger("TrustLayer.ChainReader")

SCAN_API     = os.getenv("SCAN_API_BASE", "https://8004scan.io/api/v1")
UPDATE_EVERY = int(os.getenv("UPDATE_INTERVAL_MINUTES", "15")) * 60  # seconds

# Known chain name → chain_id mappings observed on 8004scan
CHAIN_NAME_TO_ID: Dict[str, int] = {
    "Base":           8453,
    "Celo":           42220,
    "BNB Smart Chain":56,
    "Ethereum":       1,
    "Abstract":       2741,
    "Billions":       0,      # Unknown – fallback
}

SESSION = requests.Session()
SESSION.headers.update({
    "Accept": "application/json",
    "User-Agent": "TrustLayer/1.0",
})


# ── Public API ───────────────────────────────────────────────────────────────

def parse_agent_id(raw: str) -> Tuple[int, int]:
    """
    Accept formats:
      "42220:1870"         → (42220, 1870)   explicit
      "celo:1870"          → (42220, 1870)   chain name
      "1870"               → (8453,  1870)   Base default
      "0x558e7b..."        → search by wallet
    Raises ValueError on unknown format.
    """
    raw = raw.strip()
    if ":" in raw:
        parts = raw.split(":", 1)
        left, right = parts[0], parts[1]
        try:
            chain_id = int(left)
        except ValueError:
            # try name lookup
            name_map = {k.lower(): v for k, v in CHAIN_NAME_TO_ID.items()}
            chain_id = name_map.get(left.lower())
            if chain_id is None:
                raise ValueError(f"Unknown chain '{left}'")
        return (chain_id, int(right))
    # Bare integer → assume Base
    try:
        return (8453, int(raw))
    except ValueError:
        raise ValueError(f"Cannot parse agent_id: {raw!r}")


def fetch_agent(agent_id_str: str) -> Optional[Dict[str, Any]]:
    """
    Main entry point. Fetches agent metadata + stats from 8004scan,
    persists to DB, and returns a unified dict for the scorer.
    """
    try:
        chain_id, token_id = parse_agent_id(agent_id_str)
    except ValueError as e:
        logger.error("parse_agent_id: %s", e)
        return None

    composite_id = f"{chain_id}:{token_id}"

    meta  = _fetch_metadata(chain_id, token_id)
    stats = _fetch_stats(chain_id, token_id)

    if meta is None and stats is None:
        logger.warning("No data found for %s", composite_id)
        return None

    now = datetime.utcnow().isoformat()

    # ── Persist metadata ──────────────────────────────────────────────────
    agent_row = _build_agent_row(composite_id, chain_id, token_id, meta or {}, now)
    upsert_agent(agent_row)

    # ── Persist stats ─────────────────────────────────────────────────────
    stats_row = _build_stats_row(composite_id, stats or {}, now)
    upsert_stats(stats_row)

    # ── Return unified snapshot ───────────────────────────────────────────
    return {**agent_row, **stats_row, "composite_id": composite_id}


def fetch_agents_page(page: int = 1, per_page: int = 50) -> List[Dict[str, Any]]:
    """
    Bulk fetch a page of agents from 8004scan for background refresh.
    Returns list of composite agent dicts.
    """
    url = f"{SCAN_API.replace('/v1', '')}/agents"
    params = {
        "page":    page,
        "perPage": per_page,
        "sortBy":  "score",
        "order":   "desc",
    }
    try:
        resp = SESSION.get(url, params=params, timeout=15)
        resp.raise_for_status()
        items = resp.json() if isinstance(resp.json(), list) else resp.json().get("agents", [])
        results = []
        for item in items:
            chain_id  = item.get("chainId") or CHAIN_NAME_TO_ID.get(item.get("chain", "Base"), 8453)
            token_id  = item.get("tokenId") or item.get("id")
            if token_id is None:
                continue
            composite = f"{chain_id}:{token_id}"
            result = fetch_agent(composite)
            if result:
                results.append(result)
        return results
    except Exception as e:
        logger.warning("fetch_agents_page failed: %s", e)
        return []


# ── Background refresh thread ─────────────────────────────────────────────

_refresh_running = False
_refresh_thread: Optional[threading.Thread] = None
_watched_agents: List[str] = []   # composite IDs to refresh


def add_watched_agent(composite_id: str) -> None:
    global _watched_agents
    if composite_id not in _watched_agents:
        _watched_agents.append(composite_id)
        logger.info("Watching agent %s for refresh", composite_id)


def start_background_refresh() -> None:
    global _refresh_running, _refresh_thread

    if _refresh_running:
        return

    _refresh_running = True
    _refresh_thread = threading.Thread(target=_refresh_loop, daemon=True)
    _refresh_thread.start()
    logger.info("Background refresh started (every %ds)", UPDATE_EVERY)


def stop_background_refresh() -> None:
    global _refresh_running
    _refresh_running = False


def _refresh_loop() -> None:
    while _refresh_running:
        _do_refresh()
        time.sleep(UPDATE_EVERY)


def _do_refresh() -> None:
    logger.info("Refreshing %d watched agents…", len(_watched_agents))
    for cid in list(_watched_agents):
        try:
            fetch_agent(cid)
        except Exception as e:
            logger.warning("Refresh failed for %s: %s", cid, e)
        time.sleep(0.3)   # be polite to the API


# ── Internal fetch helpers ────────────────────────────────────────────────

def _fetch_metadata(chain_id: int, token_id: int) -> Optional[Dict[str, Any]]:
    """Try to fetch agent metadata from 8004scan browse endpoint."""
    # Map chain_id to chain slug
    chain_slug_map = {
        8453:  "base",
        42220: "celo",
        56:    "bsc",
        1:     "ethereum",
        2741:  "abstract",
    }
    slug = chain_slug_map.get(chain_id)
    if slug:
        url = f"https://8004scan.io/agents/{slug}/{token_id}"
        # Use the RSC (React Server Component) endpoint for JSON
        try:
            resp = SESSION.get(
                f"https://8004scan.io/agents/{slug}/{token_id}",
                params={"_rsc": "1"},
                timeout=10,
            )
            # This returns HTML. Instead query the agents list filtered.
        except Exception:
            pass

    # Fallback: search agents list by token id
    url = f"https://8004scan.io/agents"
    try:
        resp = SESSION.get(url, params={
            "page": 1,
            "perPage": 1,
            "search": str(token_id),
        }, timeout=10)
        data = resp.json() if resp.ok else {}
        agents = data.get("agents", []) if isinstance(data, dict) else []
        for a in agents:
            if str(a.get("tokenId")) == str(token_id) and (
                a.get("chainId") == chain_id or
                CHAIN_NAME_TO_ID.get(a.get("chain", "")) == chain_id
            ):
                return a
    except Exception as e:
        logger.debug("metadata fallback failed: %s", e)

    return None


def _fetch_stats(chain_id: int, token_id: int) -> Optional[Dict[str, Any]]:
    """
    Fetch agent statistics from 8004scan REST API.
    Discovered endpoint: GET /api/v1/stats/agents/{chain_id}/{token_id}
    """
    url = f"{SCAN_API}/stats/agents/{chain_id}/{token_id}"
    try:
        resp = SESSION.get(url, timeout=10)
        if resp.status_code == 404:
            logger.debug("Agent %d:%d not found in stats API", chain_id, token_id)
            return None
        resp.raise_for_status()
        data = resp.json()
        # API may return directly or nested under "data"
        return data.get("data", data) if isinstance(data, dict) else None
    except Exception as e:
        logger.warning("_fetch_stats(%d, %d): %s", chain_id, token_id, e)
        return None


def _fetch_feedbacks(chain_id: int, token_id: int, limit: int = 50) -> List[Dict]:
    """
    Fetch recent feedback items for an agent.
    Discovered endpoint: GET /api/v1/feedbacks?chain_id=...&agent_token_id=...
    """
    url = f"{SCAN_API}/feedbacks"
    params = {
        "chain_id":       chain_id,
        "agent_token_id": token_id,
        "limit":          limit,
        "offset":         0,
        "sort_by":        "submitted_at",
        "sort_order":     "desc",
        "is_testnet":     "false",
    }
    try:
        resp = SESSION.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return data.get("data", data.get("feedbacks", []))
    except Exception as e:
        logger.debug("_fetch_feedbacks: %s", e)
        return []


# ── Row builders ──────────────────────────────────────────────────────────

def _build_agent_row(
    composite_id: str,
    chain_id: int,
    token_id: int,
    meta: Dict,
    now: str,
) -> Dict[str, Any]:
    # Try various key names that 8004scan may return
    return {
        "id":               composite_id,
        "chain_id":         chain_id,
        "token_id":         token_id,
        "chain_name":       meta.get("chain") or meta.get("chainName") or _chain_name(chain_id),
        "owner_address":    meta.get("owner") or meta.get("ownerAddress") or meta.get("walletAddress"),
        "creator_address":  meta.get("creator") or meta.get("creatorAddress"),
        "name":             meta.get("name") or meta.get("agentName"),
        "description":      meta.get("description"),
        "category":         meta.get("category"),
        "version":          meta.get("version"),
        "registry":         meta.get("registry") or meta.get("registryAddress"),
        "agent_wallet":     meta.get("agentWallet") or meta.get("wallet"),
        "last_updated":     meta.get("lastUpdated") or meta.get("updatedAt"),
        "fetched_at":       now,
    }


def _build_stats_row(composite_id: str, stats: Dict, now: str) -> Dict[str, Any]:
    """
    Map 8004scan stats response to our schema.
    Key names observed on the page:
      overall_score, avg_feedback_score, total_feedback, total_validations,
      total_stars, total_messages, engagement_score (30%), service_score (25%),
      publisher_score (20%), compliance_score (15%), momentum_score (10%)
    """
    def _get(*keys, default=None):
        for k in keys:
            v = stats.get(k)
            if v is not None:
                return v
        return default

    overall   = _get("overallScore", "overall_score", "score", default=0.0)
    avg_fb    = _get("avgFeedbackScore", "avg_feedback_score",
                     "averageFeedbackScore", default=0.0)
    # Normalise feedback score: if it looks like 0-5 scale → × 20
    if avg_fb and avg_fb <= 5.0:
        avg_fb = avg_fb * 20.0

    return {
        "id":                   composite_id,
        "overall_score":        float(overall or 0),
        "avg_feedback_score":   float(avg_fb or 0),
        "total_feedback":       int(_get("totalFeedback", "total_feedback",
                                        "feedbackCount", default=0)),
        "total_validations":    int(_get("totalValidations", "total_validations", default=0)),
        "total_stars":          int(_get("totalStars", "total_stars", default=0)),
        "total_messages":       int(_get("totalMessages", "total_messages", default=0)),
        "engagement_score":     float(_get("engagementScore", "engagement_score", default=0)),
        "service_score":        float(_get("serviceScore", "service_score", default=0)),
        "publisher_score":      float(_get("publisherScore", "publisher_score", default=0)),
        "compliance_score":     float(_get("complianceScore", "compliance_score", default=0)),
        "momentum_score":       float(_get("momentumScore", "momentum_score", default=0)),
        "last_active_raw":      _get("lastActive", "last_active", "lastActiveAt"),
        "fetched_at":           now,
    }


def _chain_name(chain_id: int) -> str:
    rev = {v: k for k, v in CHAIN_NAME_TO_ID.items()}
    return rev.get(chain_id, f"chain-{chain_id}")
