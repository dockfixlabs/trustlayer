"""
TrustLayer — test_core.py
اختبار فوري للـ core logic بدون server.
يعمل بمجرد: python test_core.py
"""
# -*- coding: utf-8 -*-
import sys, os, time, json
# Set DB path BEFORE any module imports so database.py picks it up
import tempfile as _tmp
_DB_FILE = os.path.join(_tmp.gettempdir(), "trustlayer_test.db")
os.environ["TRUSTLAYER_DB_PATH"] = _DB_FILE
# Clean up stale test DB
if os.path.exists(_DB_FILE):
    try: os.remove(_DB_FILE)
    except: pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

P = "✅"; F = "❌"; W = "⚠️ "

def sep(t=""):
    w = 55
    if t:
        pad = (w-len(t)-2)//2
        print(f"\n{'═'*pad} {t} {'═'*pad}")
    else:
        print("═"*w)

passed = failed = 0

def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  {P} {name}" + (f" — {detail}" if detail else ""))
    else:
        failed += 1
        print(f"  {F} {name}" + (f" — {detail}" if detail else ""))

# ── TEST 1: DB ─────────────────────────────────────────
sep("TEST 1 — Database")
try:
    from core.database import init_db, upsert_agent, upsert_stats, \
        get_latest_trust_score, get_leaderboard, get_market_stats, get_alerts
    init_db()
    check("init_db()", True)

    now = "2026-05-21T20:00:00"
    upsert_agent({
        "id":"42220:1870","chain_id":42220,"token_id":1870,
        "chain_name":"Celo","owner_address":"0x558e","creator_address":None,
        "name":"Toppa","description":"Finance AI","category":"finance",
        "version":"2.0.0","registry":None,"agent_wallet":None,
        "last_updated":now,"fetched_at":now
    })
    check("upsert_agent(Toppa)", True)

    upsert_stats({
        "id":"42220:1870","overall_score":93.96,"avg_feedback_score":98.0,
        "total_feedback":581,"total_validations":0,"total_stars":10,
        "total_messages":0,"engagement_score":69.0,"service_score":100.0,
        "publisher_score":41.0,"compliance_score":96.0,"momentum_score":10.0,
        "last_active_raw":"2h ago","fetched_at":now
    })
    check("upsert_stats(Toppa)", True)

    stats = get_market_stats()
    check("get_market_stats()", stats["total_agents_tracked"] >= 1,
          f"tracked={stats['total_agents_tracked']}")
except Exception as e:
    check("Database", False, str(e))
    import traceback; traceback.print_exc()

# ── TEST 2: Scorer ─────────────────────────────────────
sep("TEST 2 — Trust Score Algorithm")
try:
    from core.scorer import compute_trust_score, _extract_scores, _compute_components, _weighted_sum

    toppa_data = {
        "avg_feedback_score":98.0,"service_score":100.0,
        "engagement_score":69.0,"publisher_score":41.0,
        "compliance_score":96.0,"momentum_score":10.0,
        "total_feedback":581
    }
    scores = _extract_scores(toppa_data)
    comps  = _compute_components(scores)
    final  = _weighted_sum(comps)

    check("Score is 0-100", 0 <= final <= 100, f"{final:.1f}")
    check("Toppa scores > 70 (TRUSTED)", final > 70, f"{final:.1f}/100")

    result = compute_trust_score("42220:1870", raw_data=toppa_data)
    check("Level in valid set", result["level"] in
          ("DANGEROUS","RISKY","NEUTRAL","TRUSTED","ELITE"), result["level"])
    check("Recommendation valid", result["recommendation"] in
          ("HIRE","VERIFY","AVOID"), result["recommendation"])
    check("Toppa → HIRE", result["recommendation"] == "HIRE",
          f"got={result['recommendation']}")
    check("Breakdown has 5 keys", len(result["breakdown"]) == 5,
          str(list(result["breakdown"].keys())))

    # New agent (no data)
    r2 = compute_trust_score("8453:0", raw_data={
        "avg_feedback_score":0,"service_score":0,"engagement_score":0,
        "publisher_score":0,"compliance_score":0,"momentum_score":0,"total_feedback":0
    })
    check("New empty agent → AVOID", r2["recommendation"] == "AVOID",
          f"score={r2['score']}")

    print(f"\n  Toppa Full Result:")
    print(f"    Score:  {result['score']}/100  {result['emoji']} {result['level']}")
    print(f"    Trend:  {result['trend']}")
    print(f"    Rec:    {result['recommendation']}")
    for k,v in result["breakdown"].items():
        print(f"    {k:<30} raw={v['raw']:>6}  contrib={v['contribution']}")

except Exception as e:
    check("Scorer", False, str(e))
    import traceback; traceback.print_exc()

# ── TEST 3: Chain Reader (parse only) ─────────────────
sep("TEST 3 — Chain Reader (parse)")
try:
    from core.chain_reader import parse_agent_id, _chain_name

    cases = [
        ("42220:1870", (42220, 1870)),
        ("1870",       (8453,  1870)),
        ("celo:1870",  (42220, 1870)),
        ("base:42",    (8453,  42  )),
    ]
    for inp, expected in cases:
        try:
            got = parse_agent_id(inp)
            check(f'parse("{inp}")', got == expected,
                  f"got={got} expected={expected}")
        except Exception as e:
            check(f'parse("{inp}")', False, str(e))

    check('_chain_name(8453)',  _chain_name(8453)  == "Base",  _chain_name(8453))
    check('_chain_name(42220)', _chain_name(42220) == "Celo",  _chain_name(42220))

except Exception as e:
    check("Chain Reader", False, str(e))

# ── TEST 4: Leaderboard ────────────────────────────────
sep("TEST 4 — Leaderboard & Alerts")
try:
    lb = get_leaderboard(10)
    check("Leaderboard returns list", isinstance(lb, list))
    check("Toppa in leaderboard", any(a.get("id")=="42220:1870" for a in lb))
    if lb:
        top = lb[0]
        check("Top agent has score", "trust_score" in top, str(top.get("trust_score")))

    al = get_alerts("42220:1870", limit=5)
    check("get_alerts returns list", isinstance(al, list))

except Exception as e:
    check("Leaderboard/Alerts", False, str(e))

# ── SUMMARY ────────────────────────────────────────────
sep("SUMMARY")
total = passed + failed
print(f"\n  Passed: {passed}/{total}")
if failed == 0:
    print(f"\n  {P} ALL TESTS PASSED")
    print(f"  TrustLayer core is production-ready!")
else:
    print(f"\n  {F} {failed} test(s) failed — check output above")
sep()
