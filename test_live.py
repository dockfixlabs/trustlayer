"""
TrustLayer — test_live.py
اختبار شامل بدون محفظة:
  - chain_reader: تجلب بيانات حقيقية من 8004scan
  - scorer: تحسب Trust Score
  - API: تختبر كل endpoints
  - يطبع تقرير كامل
"""

import sys
import os
import json
import time
import subprocess
import threading
import requests

# Add project root
sys.path.insert(0, os.path.dirname(__file__))

PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "

# معرّفات وكلاء حقيقيين من 8004scan (مكتشفة في البحث)
TEST_AGENTS = [
    ("42220:1870", "Toppa — Celo (Rank #1)"),
    ("8453:2",     "Base agent #2"),
]

API_BASE = "http://localhost:8000"


def sep(title=""):
    w = 55
    if title:
        pad = (w - len(title) - 2) // 2
        print(f"\n{'═'*pad} {title} {'═'*pad}")
    else:
        print("═" * w)


def ok(msg):  print(f"  {PASS} {msg}")
def fail(msg): print(f"  {FAIL} {msg}")
def warn(msg): print(f"  {WARN} {msg}")


# ══════════════════════════════════════════════════════
# TEST 1 — Database
# ══════════════════════════════════════════════════════
def test_database():
    sep("TEST 1 — Database")
    try:
        from core.database import init_db, get_market_stats
        init_db()
        ok("init_db() — tables created")
        stats = get_market_stats()
        ok(f"get_market_stats() — {stats}")
        return True
    except Exception as e:
        fail(f"Database error: {e}")
        return False


# ══════════════════════════════════════════════════════
# TEST 2 — Chain Reader (8004scan live)
# ══════════════════════════════════════════════════════
def test_chain_reader():
    sep("TEST 2 — Chain Reader (live 8004scan)")
    from core.chain_reader import fetch_agent, parse_agent_id
    results = {}

    for agent_id, label in TEST_AGENTS:
        print(f"\n  Fetching: {label} ({agent_id})")
        t0 = time.time()
        try:
            data = fetch_agent(agent_id)
            elapsed = time.time() - t0
            if data:
                ok(f"Fetched in {elapsed:.2f}s")
                # Print key fields
                for k in ("name", "chain_name", "overall_score",
                           "avg_feedback_score", "total_feedback",
                           "service_score", "engagement_score",
                           "compliance_score", "momentum_score"):
                    v = data.get(k)
                    if v is not None:
                        print(f"      {k}: {v}")
                results[agent_id] = data
            else:
                warn(f"No data returned (agent may not exist on this chain)")
                results[agent_id] = None
        except Exception as e:
            fail(f"fetch_agent({agent_id}): {e}")
            results[agent_id] = None

    return results


# ══════════════════════════════════════════════════════
# TEST 3 — Scorer
# ══════════════════════════════════════════════════════
def test_scorer(raw_data_map: dict):
    sep("TEST 3 — Trust Score Computation")
    from core.scorer import compute_trust_score
    scores = {}

    for agent_id, label in TEST_AGENTS:
        raw = raw_data_map.get(agent_id)
        print(f"\n  Scoring: {label}")
        try:
            result = compute_trust_score(agent_id, raw_data=raw)
            score = result["score"]
            level = result["level"]
            emoji = result.get("emoji", "")
            trend = result["trend"]
            rec   = result["recommendation"]
            flags = result["red_flags"]

            ok(f"Score: {score}/100  {emoji} {level}")
            print(f"      Trend:          {trend}")
            print(f"      Recommendation: {rec}")
            if flags:
                print(f"      Red Flags:")
                for f in flags:
                    print(f"        • {f}")
            print(f"      Breakdown:")
            for k, v in result.get("breakdown", {}).items():
                contrib = v.get("contribution", "?")
                raw_v   = v.get("raw", "?")
                weight  = v.get("weight", "?")
                print(f"        {k:<28} raw={raw_v:>6}  weight={weight}  contrib={contrib}")

            scores[agent_id] = result

            # Sanity checks
            assert 0 <= score <= 100, f"Score out of range: {score}"
            assert level in ("DANGEROUS","RISKY","NEUTRAL","TRUSTED","ELITE"), f"Bad level: {level}"
            assert rec in ("HIRE","VERIFY","AVOID"), f"Bad rec: {rec}"
            ok("Sanity checks passed")

        except AssertionError as e:
            fail(f"Sanity check failed: {e}")
        except Exception as e:
            fail(f"Scorer error: {e}")
            import traceback; traceback.print_exc()

    return scores


# ══════════════════════════════════════════════════════
# TEST 4 — API (starts server in background)
# ══════════════════════════════════════════════════════
def start_api_server():
    """Launch FastAPI in a background subprocess."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.server:app",
         "--host", "127.0.0.1", "--port", "8000", "--log-level", "error"],
        cwd=os.path.dirname(__file__),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait for server to be ready
    for _ in range(20):
        time.sleep(0.5)
        try:
            requests.get(f"{API_BASE}/health", timeout=1)
            return proc
        except Exception:
            pass
    return proc


def test_api():
    sep("TEST 4 — FastAPI Endpoints")

    # ── /health ──────────────────────────────────────
    print("\n  GET /health")
    try:
        r = requests.get(f"{API_BASE}/health", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        ok(f"/health → {data['status']} (uptime: {data['uptime_seconds']}s)")
    except Exception as e:
        fail(f"/health: {e}")
        return False

    # ── POST /trust ───────────────────────────────────
    for agent_id, label in TEST_AGENTS:
        print(f"\n  POST /trust  ({label})")
        try:
            t0 = time.time()
            r = requests.post(
                f"{API_BASE}/trust",
                json={"agent_id": agent_id, "force_refresh": True},
                timeout=30,
            )
            elapsed = time.time() - t0
            if r.status_code == 200:
                d = r.json()
                ok(f"score={d['score']}  level={d['level']}  rec={d['recommendation']}  ({elapsed:.2f}s)")
            elif r.status_code == 404:
                warn(f"Agent not found (404) — {r.json().get('detail')}")
            else:
                fail(f"HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            fail(f"/trust: {e}")

    # ── GET /leaderboard ──────────────────────────────
    print("\n  GET /leaderboard?limit=5")
    try:
        r = requests.get(f"{API_BASE}/leaderboard", params={"limit": 5}, timeout=10)
        assert r.status_code == 200
        d = r.json()
        ok(f"/leaderboard → {d['count']} agents returned")
        for a in d["agents"][:3]:
            print(f"      #{d['agents'].index(a)+1}  score={a.get('trust_score', '?')}  "
                  f"level={a.get('trust_level', '?')}  id={a.get('id', '?')}")
    except Exception as e:
        fail(f"/leaderboard: {e}")

    # ── GET /stats ────────────────────────────────────
    print("\n  GET /stats")
    try:
        r = requests.get(f"{API_BASE}/stats", timeout=5)
        assert r.status_code == 200
        d = r.json()
        ok(f"/stats → tracked={d['total_agents_tracked']}  "
           f"scored={d['total_agents_scored']}  "
           f"avg={d['average_trust_score']}")
    except Exception as e:
        fail(f"/stats: {e}")

    # ── GET /compare ──────────────────────────────────
    if len(TEST_AGENTS) >= 2:
        print(f"\n  GET /compare ({TEST_AGENTS[0][0]} vs {TEST_AGENTS[1][0]})")
        try:
            r = requests.get(
                f"{API_BASE}/compare",
                params={"agents": [a[0] for a in TEST_AGENTS[:2]]},
                timeout=30,
            )
            if r.status_code == 200:
                d = r.json()
                ok(f"/compare → winner={d.get('winner')}  count={d.get('count')}")
            else:
                warn(f"HTTP {r.status_code}")
        except Exception as e:
            fail(f"/compare: {e}")

    # ── GET /alerts ───────────────────────────────────
    print(f"\n  GET /alerts/{TEST_AGENTS[0][0]}")
    try:
        r = requests.get(f"{API_BASE}/alerts/{TEST_AGENTS[0][0]}", timeout=5)
        assert r.status_code == 200
        d = r.json()
        ok(f"/alerts → {d['count']} alerts")
    except Exception as e:
        fail(f"/alerts: {e}")

    return True


# ══════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════
def main():
    sep("TrustLayer — Live Test Suite")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    print(f"  Python: {sys.version.split()[0]}")
    print()

    total = 0
    passed = 0

    # Test 1 — DB
    total += 1
    if test_database():
        passed += 1

    # Test 2 — Chain reader
    total += 1
    raw_map = test_chain_reader()
    if any(v is not None for v in raw_map.values()):
        passed += 1
    else:
        warn("Chain reader returned no data — will test scorer with empty data")

    # Test 3 — Scorer
    total += 1
    scores = test_scorer(raw_map)
    if scores:
        passed += 1

    # Test 4 — API
    sep("Starting API server...")
    proc = None
    try:
        proc = start_api_server()
        ok("API server started on port 8000")
        total += 1
        if test_api():
            passed += 1
    except Exception as e:
        fail(f"Could not start API: {e}")
    finally:
        if proc:
            proc.terminate()

    # Summary
    sep("TEST SUMMARY")
    print(f"\n  Passed: {passed}/{total}")
    if passed == total:
        print(f"\n  {PASS} ALL TESTS PASSED — TrustLayer is working!")
    else:
        print(f"\n  {WARN} {total - passed} test(s) need attention.")

    sep()


if __name__ == "__main__":
    main()
