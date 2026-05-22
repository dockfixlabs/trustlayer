"""
TrustLayer — database.py
SQLite persistence layer for agent data and trust scores.
"""

import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger("TrustLayer.DB")

import os as _os
DB_PATH = Path(
    _os.getenv("TRUSTLAYER_DB_PATH",
               str(Path(__file__).parent.parent / "trustlayer.db"))
)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS agents (
                id              TEXT PRIMARY KEY,          -- "{chain_id}:{token_id}"
                chain_id        INTEGER NOT NULL,
                token_id        INTEGER NOT NULL,
                chain_name      TEXT,
                owner_address   TEXT,
                creator_address TEXT,
                name            TEXT,
                description     TEXT,
                category        TEXT,
                version         TEXT,
                registry        TEXT,
                agent_wallet    TEXT,
                last_updated    TEXT,
                fetched_at      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agent_stats (
                id                      TEXT PRIMARY KEY,  -- same as agents.id
                overall_score           REAL,
                avg_feedback_score      REAL,              -- 0-100
                total_feedback          INTEGER,
                total_validations       INTEGER,
                total_stars             INTEGER,
                total_messages          INTEGER,
                engagement_score        REAL,              -- 0-100
                service_score           REAL,              -- 0-100
                publisher_score         REAL,              -- 0-100
                compliance_score        REAL,              -- 0-100
                momentum_score          REAL,              -- 0-100
                last_active_raw         TEXT,
                fetched_at              TEXT NOT NULL,
                FOREIGN KEY(id) REFERENCES agents(id)
            );

            CREATE TABLE IF NOT EXISTS trust_scores (
                id                  TEXT NOT NULL,
                computed_at         TEXT NOT NULL,
                trust_score         REAL NOT NULL,        -- 0-100
                trust_level         TEXT NOT NULL,        -- DANGEROUS..ELITE
                trend               TEXT NOT NULL,        -- Rising/Stable/Declining
                recommendation      TEXT NOT NULL,        -- HIRE/AVOID/VERIFY
                red_flags           TEXT NOT NULL,        -- JSON list
                breakdown           TEXT NOT NULL,        -- JSON dict
                PRIMARY KEY(id, computed_at)
            );

            CREATE INDEX IF NOT EXISTS idx_trust_scores_id
                ON trust_scores(id, computed_at DESC);

            CREATE TABLE IF NOT EXISTS alerts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id    TEXT NOT NULL,
                alert_type  TEXT NOT NULL,
                message     TEXT NOT NULL,
                old_score   REAL,
                new_score   REAL,
                created_at  TEXT NOT NULL
            );
        """)
    logger.info("Database initialised at %s", DB_PATH)


# ── Agent helpers ────────────────────────────────────────────────────────────

def upsert_agent(data: Dict[str, Any]) -> None:
    sql = """
        INSERT INTO agents
            (id, chain_id, token_id, chain_name, owner_address, creator_address,
             name, description, category, version, registry, agent_wallet,
             last_updated, fetched_at)
        VALUES
            (:id, :chain_id, :token_id, :chain_name, :owner_address, :creator_address,
             :name, :description, :category, :version, :registry, :agent_wallet,
             :last_updated, :fetched_at)
        ON CONFLICT(id) DO UPDATE SET
            chain_name      = excluded.chain_name,
            owner_address   = excluded.owner_address,
            creator_address = excluded.creator_address,
            name            = excluded.name,
            description     = excluded.description,
            category        = excluded.category,
            version         = excluded.version,
            registry        = excluded.registry,
            agent_wallet    = excluded.agent_wallet,
            last_updated    = excluded.last_updated,
            fetched_at      = excluded.fetched_at
    """
    with get_connection() as conn:
        conn.execute(sql, data)


def upsert_stats(data: Dict[str, Any]) -> None:
    sql = """
        INSERT INTO agent_stats
            (id, overall_score, avg_feedback_score, total_feedback, total_validations,
             total_stars, total_messages, engagement_score, service_score,
             publisher_score, compliance_score, momentum_score,
             last_active_raw, fetched_at)
        VALUES
            (:id, :overall_score, :avg_feedback_score, :total_feedback, :total_validations,
             :total_stars, :total_messages, :engagement_score, :service_score,
             :publisher_score, :compliance_score, :momentum_score,
             :last_active_raw, :fetched_at)
        ON CONFLICT(id) DO UPDATE SET
            overall_score       = excluded.overall_score,
            avg_feedback_score  = excluded.avg_feedback_score,
            total_feedback      = excluded.total_feedback,
            total_validations   = excluded.total_validations,
            total_stars         = excluded.total_stars,
            total_messages      = excluded.total_messages,
            engagement_score    = excluded.engagement_score,
            service_score       = excluded.service_score,
            publisher_score     = excluded.publisher_score,
            compliance_score    = excluded.compliance_score,
            momentum_score      = excluded.momentum_score,
            last_active_raw     = excluded.last_active_raw,
            fetched_at          = excluded.fetched_at
    """
    with get_connection() as conn:
        conn.execute(sql, data)


def save_trust_score(agent_id: str, result: Dict[str, Any]) -> None:
    sql = """
        INSERT INTO trust_scores
            (id, computed_at, trust_score, trust_level, trend, recommendation,
             red_flags, breakdown)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    with get_connection() as conn:
        conn.execute(sql, (
            agent_id,
            datetime.utcnow().isoformat(),
            result["score"],
            result["level"],
            result["trend"],
            result["recommendation"],
            json.dumps(result["red_flags"]),
            json.dumps(result["breakdown"]),
        ))
        # Check if score changed significantly → create alert
        _maybe_create_alert(conn, agent_id, result["score"])


def _maybe_create_alert(conn: sqlite3.Connection, agent_id: str, new_score: float) -> None:
    row = conn.execute("""
        SELECT trust_score FROM trust_scores
        WHERE id = ? ORDER BY computed_at DESC LIMIT 1 OFFSET 1
    """, (agent_id,)).fetchone()

    if row is None:
        return

    old_score = row["trust_score"]
    delta = abs(new_score - old_score)
    if delta >= 10:
        direction = "dropped" if new_score < old_score else "jumped"
        conn.execute("""
            INSERT INTO alerts (agent_id, alert_type, message, old_score, new_score, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            agent_id,
            "score_change",
            f"Trust score {direction} by {delta:.1f} points",
            old_score,
            new_score,
            datetime.utcnow().isoformat(),
        ))


# ── Query helpers ────────────────────────────────────────────────────────────

def get_latest_trust_score(agent_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute("""
            SELECT ts.*, a.name, a.chain_name, a.owner_address
            FROM trust_scores ts
            LEFT JOIN agents a ON a.id = ts.id
            WHERE ts.id = ?
            ORDER BY ts.computed_at DESC
            LIMIT 1
        """, (agent_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["red_flags"] = json.loads(d["red_flags"])
    d["breakdown"] = json.loads(d["breakdown"])
    return d


def get_leaderboard(limit: int = 20) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT ts.id, ts.trust_score, ts.trust_level, ts.trend,
                   ts.recommendation, ts.computed_at,
                   a.name, a.chain_name, a.owner_address
            FROM trust_scores ts
            INNER JOIN (
                SELECT id, MAX(computed_at) AS latest FROM trust_scores GROUP BY id
            ) latest ON ts.id = latest.id AND ts.computed_at = latest.latest
            LEFT JOIN agents a ON a.id = ts.id
            ORDER BY ts.trust_score DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_alerts(agent_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM alerts WHERE agent_id = ?
            ORDER BY created_at DESC LIMIT ?
        """, (agent_id, limit)).fetchall()
    return [dict(r) for r in rows]


def get_stats_snapshot(agent_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM agent_stats WHERE id = ?", (agent_id,)
        ).fetchone()
    return dict(row) if row else None


def get_market_stats() -> Dict[str, Any]:
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
        scored = conn.execute(
            "SELECT COUNT(DISTINCT id) FROM trust_scores"
        ).fetchone()[0]
        avg = conn.execute(
            """SELECT AVG(trust_score) FROM trust_scores ts
               INNER JOIN (SELECT id, MAX(computed_at) mx FROM trust_scores GROUP BY id) l
               ON ts.id = l.id AND ts.computed_at = l.mx"""
        ).fetchone()[0]
        dist = conn.execute(
            """SELECT trust_level, COUNT(*) as cnt
               FROM trust_scores ts
               INNER JOIN (SELECT id, MAX(computed_at) mx FROM trust_scores GROUP BY id) l
               ON ts.id = l.id AND ts.computed_at = l.mx
               GROUP BY trust_level"""
        ).fetchall()
    return {
        "total_agents_tracked": total,
        "total_agents_scored": scored,
        "average_trust_score": round(avg, 2) if avg else None,
        "distribution": {r["trust_level"]: r["cnt"] for r in dist},
    }
