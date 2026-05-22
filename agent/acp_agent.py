"""
TrustLayer — acp_agent.py
Registers TrustLayer as an ACP Provider on Base (mainnet or testnet).

Flow:
  1. Client sends job with {"agent_id": "8453:1870"}
  2. TrustLayer fetches data + computes score
  3. Delivers result as JSON deliverable
  4. Client auto-evaluates (self-evaluation mode) → USDC released

Price: 0.01 USDC per query
"""

import os
import sys
import json
import logging
import threading
import time
import requests

from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.database import init_db
from core.chain_reader import fetch_agent, add_watched_agent, start_background_refresh
from core.scorer import compute_trust_score

load_dotenv()
logger = logging.getLogger("TrustLayer.ACPAgent")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ── Config ────────────────────────────────────────────────────────────────
NETWORK        = os.getenv("NETWORK", "testnet")   # "mainnet" or "testnet"
PRIVATE_KEY    = os.getenv("WHITELISTED_WALLET_PRIVATE_KEY", "")
AGENT_WALLET   = os.getenv("AGENT_WALLET_ADDRESS", "")
ENTITY_ID      = os.getenv("AGENT_ENTITY_ID", "")
SERVICE_PRICE  = float(os.getenv("TRUSTLAYER_SERVICE_PRICE_USDC", "0.01"))
SLA_MINUTES    = int(os.getenv("TRUSTLAYER_SLA_MINUTES", "3"))

TRUSTLAYER_API = f"http://localhost:{os.getenv('API_PORT', 8000)}"

# ACP job offering definition
JOB_OFFERING = {
    "name":        "trust-score",
    "description": (
        "Before hiring any agent, know their trust score. "
        "TrustLayer reads ERC-8004 on-chain data and gives you an instant "
        "HIRE/AVOID recommendation. The trust layer every agent needs."
    ),
    "price":       SERVICE_PRICE,
    "slaMinutes":  SLA_MINUTES,
    "requirement": json.dumps({
        "type": "object",
        "properties": {
            "agent_id": {
                "type":        "string",
                "description": (
                    "The ERC-8004 agent to evaluate. "
                    "Format: 'chain_id:token_id' (e.g. '8453:1870') "
                    "or bare token_id for Base chain."
                ),
            }
        },
        "required": ["agent_id"],
    }),
    "deliverable": (
        "JSON object containing: score (0-100), level (DANGEROUS/RISKY/NEUTRAL/TRUSTED/ELITE), "
        "trend (Rising/Stable/Declining), recommendation (HIRE/VERIFY/AVOID), "
        "red_flags list, and detailed breakdown."
    ),
}


# ── Main agent class ──────────────────────────────────────────────────────

class TrustLayerAgent:
    def __init__(self):
        self.acp = None
        self._validate_config()

    def _validate_config(self):
        missing = []
        if not PRIVATE_KEY:
            missing.append("WHITELISTED_WALLET_PRIVATE_KEY")
        if not AGENT_WALLET:
            missing.append("AGENT_WALLET_ADDRESS")
        if not ENTITY_ID:
            missing.append("AGENT_ENTITY_ID")
        if missing:
            logger.warning(
                "Missing env vars: %s — running in dry-run mode (no ACP connection)",
                ", ".join(missing),
            )
            self._dry_run = True
        else:
            self._dry_run = False

    def start(self):
        """Initialise DB, start background refresh, then connect to ACP."""
        init_db()
        start_background_refresh()

        if self._dry_run:
            logger.info("DRY-RUN MODE — ACP connection skipped. API server will still work.")
            return

        self._connect_acp()

    def _connect_acp(self):
        try:
            from virtuals_acp.client import VirtualsACP
            from virtuals_acp.contract_clients.v2_contract_client import ACPContractClientV2
            from virtuals_acp.configs.configs import (
                BASE_MAINNET_ACP_X402_CONFIG_V2,
                BASE_SEPOLIA_ACP_X402_CONFIG_V2,
            )

            config = (
                BASE_MAINNET_ACP_X402_CONFIG_V2
                if NETWORK == "mainnet"
                else BASE_SEPOLIA_ACP_X402_CONFIG_V2
            )

            contract_client = ACPContractClientV2(
                wallet_private_key=PRIVATE_KEY,
                agent_wallet_address=AGENT_WALLET,
                entity_id=int(ENTITY_ID),
                config=config,
            )

            self.acp = VirtualsACP(
                acp_contract_clients=contract_client,
                on_new_task=self._on_new_task,
                on_evaluate=self._on_evaluate,
            )

            logger.info(
                "TrustLayer connected to ACP (%s) — wallet: %s",
                NETWORK,
                AGENT_WALLET,
            )

        except ImportError as e:
            logger.error("virtuals-acp not installed: %s", e)
            logger.error("Run: pip install virtuals-acp")
        except Exception as e:
            logger.error("ACP connection failed: %s", e)

    # ── Job handlers ──────────────────────────────────────────────────────

    def _on_new_task(self, job, memo_to_sign):
        """Called when a buyer sends a trust-score request."""
        threading.Thread(
            target=self._handle_task,
            args=(job, memo_to_sign),
            daemon=True,
        ).start()

    def _handle_task(self, job, memo_to_sign):
        job_id = getattr(job, "id", "unknown")
        logger.info("New task received — job_id=%s", job_id)

        try:
            # Step 1: Accept the job (set budget)
            if memo_to_sign:
                memo_to_sign.sign(True, f"TrustLayer accepted — price: {SERVICE_PRICE} USDC")
                logger.info("Job %s accepted", job_id)

            # Step 2: Extract agent_id from requirements
            agent_id = self._extract_agent_id(job)
            if not agent_id:
                self._deliver_error(job, "Missing or invalid 'agent_id' in request.")
                return

            logger.info("Computing trust score for agent_id=%s (job=%s)", agent_id, job_id)

            # Step 3: Fetch data + compute score
            start = time.time()
            raw = fetch_agent(agent_id)
            if raw:
                add_watched_agent(agent_id)
                result = compute_trust_score(agent_id, raw_data=raw)
            else:
                # Try cached score
                result = compute_trust_score(agent_id)

            elapsed = time.time() - start
            logger.info(
                "Trust score for %s: %s (%s) in %.2fs",
                agent_id, result["score"], result["level"], elapsed,
            )

            # Step 4: Deliver result
            self._deliver_result(job, result)

        except Exception as e:
            logger.error("Task handling error (job=%s): %s", job_id, e)
            self._deliver_error(job, f"Internal error: {str(e)}")

    def _on_evaluate(self, job):
        """Auto-evaluate and approve deliverable (self-evaluation)."""
        try:
            deliverable = getattr(job, "deliverable", None)
            if deliverable:
                job.evaluate(True, "TrustLayer delivered valid trust score.")
                logger.info("Job %s auto-approved", getattr(job, "id", "?"))
            else:
                job.evaluate(False, "No deliverable received.")
        except Exception as e:
            logger.error("Evaluate error: %s", e)

    # ── Delivery helpers ──────────────────────────────────────────────────

    def _extract_agent_id(self, job) -> str:
        """Parse agent_id from the job requirements."""
        try:
            memos = getattr(job, "memos", [])
            for memo in memos:
                content = getattr(memo, "content", None)
                if content:
                    if isinstance(content, str):
                        try:
                            content = json.loads(content)
                        except json.JSONDecodeError:
                            pass
                    if isinstance(content, dict):
                        aid = content.get("agent_id") or content.get("agentId")
                        if aid:
                            return str(aid).strip()
                    elif isinstance(content, str) and content.strip():
                        # plain string might be the agent_id directly
                        return content.strip()
        except Exception as e:
            logger.debug("_extract_agent_id: %s", e)
        return ""

    def _deliver_result(self, job, result: dict):
        try:
            payload = json.dumps(result, indent=2)
            job.deliver(payload)
            logger.info(
                "Delivered: agent=%s score=%.1f level=%s rec=%s",
                result.get("agent_id"),
                result.get("score", 0),
                result.get("level"),
                result.get("recommendation"),
            )
        except Exception as e:
            logger.error("Deliver failed: %s", e)

    def _deliver_error(self, job, message: str):
        try:
            error_payload = json.dumps({
                "error": message,
                "hint":  "Send a valid agent_id. Format: 'chain_id:token_id' e.g. '8453:1870'",
            })
            job.deliver(error_payload)
        except Exception as e:
            logger.error("Error delivery failed: %s", e)


# ── HTTP fallback for direct API queries ──────────────────────────────────

def query_trust_via_api(agent_id: str) -> dict:
    """
    Utility function: query TrustLayer's own REST API.
    Used for integration testing.
    """
    try:
        resp = requests.post(
            f"{TRUSTLAYER_API}/trust",
            json={"agent_id": agent_id},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("API query failed: %s", e)
        return {"error": str(e)}


# ── Entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    import multiprocessing

    # Start ACP agent in the current process
    agent = TrustLayerAgent()
    agent.start()

    # Also start FastAPI server in a separate thread
    def run_api():
        port = int(os.getenv("API_PORT", 8000))
        host = os.getenv("API_HOST", "0.0.0.0")
        uvicorn.run(
            "api.server:app",
            host=host,
            port=port,
            reload=False,
            log_level="info",
        )

    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()

    logger.info("TrustLayer fully started — API on port %s, ACP connected (%s)",
                os.getenv("API_PORT", 8000), NETWORK)

    # Keep alive
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        logger.info("TrustLayer shutting down...")
