"""
TrustLayer — scorer.py
Computes Trust Score (0-100) from ERC-8004 / 8004scan data.

Weights:
  35%  Job Success Rate      ← avg_feedback_score (quality)
  25%  Response Reliability  ← service_score (availability & uptime)
  20%  Peer Attestations     ← engagement_score + total_feedback volume
  15%  Agent Longevity       ← publisher_score (age & consistency)
   5%  Dispute History (-)   ← (100 - compliance_score) as penalty
"""

import logging
import math
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from core.database import get_stats_snapshot, get_latest_trust_score, save_trust_score

logger = logging.getLogger("TrustLayer.Scorer")

# ── Weights ───────────────────────────────────────────────────────────────
W_SUCCESS     = 0.35
W_RELIABILITY = 0.25
W_ATTESTATION = 0.20
W_LONGEVITY   = 0.15
W_DISPUTE     = 0.05   # applied as PENALTY: score × (1 - dispute_penalty)

# ── Thresholds ────────────────────────────────────────────────────────────
FEEDBACK_FLOOR = 3      # Minimum feedbacks before we trust the score fully
FEEDBACK_CAP   = 500    # Beyond this, volume bonus saturates

# Trust levels
LEVELS = [
    (81, "ELITE",    "⭐"),
    (61, "TRUSTED",  "🟢"),
    (41, "NEUTRAL",  "🟡"),
    (21, "RISKY",    "🟠"),
    (0,  "DANGEROUS","🔴"),
]

RECOMMENDATIONS = {
    "ELITE":    "HIRE",
    "TRUSTED":  "HIRE",
    "NEUTRAL":  "VERIFY",
    "RISKY":    "AVOID",
    "DANGEROUS":"AVOID",
}


# ── Public entry point ────────────────────────────────────────────────────

def compute_trust_score(composite_id: str, raw_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Compute (or refresh) the Trust Score for an agent.

    raw_data: optional dict already fetched by chain_reader.
              If None, loads the latest stats snapshot from DB.
    """
    if raw_data is None:
        raw_data = get_stats_snapshot(composite_id)

    if raw_data is None:
        return _empty_result(composite_id, "No data available for this agent.")

    score_map = _extract_scores(raw_data)
    components = _compute_components(score_map)
    final      = _weighted_sum(components)
    level, emoji = _get_level(final)
    trend        = _compute_trend(composite_id, final)
    red_flags    = _detect_red_flags(raw_data, components, final)
    recommendation = RECOMMENDATIONS[level]

    result = {
        "agent_id":     composite_id,
        "score":        round(final, 1),
        "level":        level,
        "emoji":        emoji,
        "trend":        trend,
        "recommendation": recommendation,
        "red_flags":    red_flags,
        "breakdown": {
            "job_success_rate":   {
                "raw":    round(score_map["avg_feedback"], 1),
                "weight": "35%",
                "contribution": round(components["success"] * 100, 1),
            },
            "response_reliability": {
                "raw":    round(score_map["service"], 1),
                "weight": "25%",
                "contribution": round(components["reliability"] * 100, 1),
            },
            "peer_attestations": {
                "raw":    round(score_map["attestation"], 1),
                "weight": "20%",
                "contribution": round(components["attestation"] * 100, 1),
            },
            "agent_longevity": {
                "raw":    round(score_map["longevity"], 1),
                "weight": "15%",
                "contribution": round(components["longevity"] * 100, 1),
            },
            "dispute_penalty": {
                "raw":    round(score_map["dispute_penalty"], 1),
                "weight": "5%  (inverse)",
                "contribution": round(components["dispute_penalty"] * 100, 1),
            },
        },
        "last_updated": datetime.utcnow().isoformat() + "Z",
    }

    save_trust_score(composite_id, result)
    return result


# ── Score extraction ──────────────────────────────────────────────────────

def _extract_scores(data: Dict[str, Any]) -> Dict[str, float]:
    def _f(key: str, default: float = 0.0) -> float:
        v = data.get(key)
        return float(v) if v is not None else default

    avg_feedback     = _f("avg_feedback_score")
    service          = _f("service_score")
    engagement       = _f("engagement_score")
    publisher        = _f("publisher_score")
    compliance       = _f("compliance_score")
    momentum         = _f("momentum_score")
    total_feedback   = int(data.get("total_feedback") or 0)

    # Attestation composite: engagement score + log-scaled volume bonus
    volume_bonus = _volume_bonus(total_feedback)
    attestation  = min(100.0, engagement * 0.7 + volume_bonus * 30.0)

    # Longevity: publisher score reflects how consistently and long the agent
    # has been registered and maintaining its profile
    longevity = publisher

    # Dispute penalty: 0 = perfect compliance → no penalty
    #                 100 = total non-compliance → max penalty
    dispute_penalty = max(0.0, 100.0 - compliance)

    return {
        "avg_feedback":     avg_feedback,
        "service":          service,
        "attestation":      attestation,
        "longevity":        longevity,
        "dispute_penalty":  dispute_penalty,
        "momentum":         momentum,
        "total_feedback":   float(total_feedback),
    }


def _volume_bonus(total_feedback: int) -> float:
    """Returns 0.0–1.0 based on feedback count (log-scaled)."""
    if total_feedback <= 0:
        return 0.0
    if total_feedback < FEEDBACK_FLOOR:
        return 0.3
    ratio = math.log1p(total_feedback) / math.log1p(FEEDBACK_CAP)
    return min(1.0, ratio)


# ── Weighted computation ──────────────────────────────────────────────────

def _compute_components(s: Dict[str, float]) -> Dict[str, float]:
    """Return each component as a 0-1 value (before applying weight)."""
    return {
        "success":         _norm(s["avg_feedback"]),
        "reliability":     _norm(s["service"]),
        "attestation":     _norm(s["attestation"]),
        "longevity":       _norm(s["longevity"]),
        "dispute_penalty": _norm(s["dispute_penalty"]),
    }


def _weighted_sum(c: Dict[str, float]) -> float:
    raw = (
        c["success"]     * W_SUCCESS * 100 +
        c["reliability"] * W_RELIABILITY * 100 +
        c["attestation"] * W_ATTESTATION * 100 +
        c["longevity"]   * W_LONGEVITY * 100
    )
    # Apply dispute penalty
    penalty_factor = 1.0 - (c["dispute_penalty"] * W_DISPUTE)
    return max(0.0, min(100.0, raw * penalty_factor))


def _norm(v: float) -> float:
    """Normalise a 0-100 score to 0-1."""
    return max(0.0, min(1.0, v / 100.0))


# ── Trust level ───────────────────────────────────────────────────────────

def _get_level(score: float):
    for threshold, label, emoji in LEVELS:
        if score >= threshold:
            return label, emoji
    return "DANGEROUS", "🔴"


# ── Trend ─────────────────────────────────────────────────────────────────

def _compute_trend(composite_id: str, current: float) -> str:
    try:
        from core.database import get_connection
        with get_connection() as conn:
            rows = conn.execute("""
                SELECT trust_score FROM trust_scores
                WHERE id = ?
                ORDER BY computed_at DESC
                LIMIT 5
            """, (composite_id,)).fetchall()

        if len(rows) < 2:
            return "Stable"

        scores = [r["trust_score"] for r in rows]
        # Compare current vs average of past readings
        past_avg = sum(scores[1:]) / len(scores[1:])
        delta = current - past_avg

        if delta > 3:
            return "Rising"
        elif delta < -3:
            return "Declining"
        return "Stable"
    except Exception:
        return "Stable"


# ── Red flags ─────────────────────────────────────────────────────────────

def _detect_red_flags(
    data: Dict[str, Any],
    components: Dict[str, float],
    final_score: float,
) -> List[str]:
    flags = []

    avg_fb = float(data.get("avg_feedback_score") or 0)
    total_fb = int(data.get("total_feedback") or 0)
    service  = float(data.get("service_score") or 0)
    compliance = float(data.get("compliance_score") or 0)
    momentum   = float(data.get("momentum_score") or 0)

    if total_fb < FEEDBACK_FLOOR:
        flags.append(f"Insufficient feedback data ({total_fb} reviews) — insufficient history")

    if avg_fb < 40:
        flags.append(f"Low average feedback score ({avg_fb:.0f}/100) — poor service quality")

    if service < 30:
        flags.append(f"Poor service reliability score ({service:.0f}/100) — endpoints may be offline")

    if compliance < 50:
        flags.append(f"Low compliance score ({compliance:.0f}/100) — potential unresolved disputes")

    if momentum < 20:
        flags.append("Declining activity detected — agent may be inactive")

    if components["success"] < 0.3 and total_fb >= FEEDBACK_FLOOR:
        flags.append("Consistently low job quality across multiple reviews")

    if final_score < 30 and total_fb >= 10:
        flags.append("Score below 30 with significant history — high-risk agent")

    return flags


# ── Empty result ──────────────────────────────────────────────────────────

def _empty_result(composite_id: str, reason: str) -> Dict[str, Any]:
    return {
        "agent_id":       composite_id,
        "score":          0,
        "level":          "DANGEROUS",
        "emoji":          "🔴",
        "trend":          "Stable",
        "recommendation": "AVOID",
        "red_flags":      [reason],
        "breakdown":      {},
        "last_updated":   datetime.utcnow().isoformat() + "Z",
    }


# ── Batch scoring ─────────────────────────────────────────────────────────

def batch_score(composite_ids: List[str]) -> List[Dict[str, Any]]:
    results = []
    for cid in composite_ids:
        try:
            results.append(compute_trust_score(cid))
        except Exception as e:
            logger.warning("batch_score failed for %s: %s", cid, e)
    return results
