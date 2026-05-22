# -*- coding: utf-8 -*-
"""
TrustLayer -- register_acp.py
سكريبت التسجيل في ACP Registry (Sandbox أو Mainnet)

الخطوات:
  1. يطبع الـ job offering الجاهز للنسخ في ACP Dashboard
  2. يتحقق من صحة credentials البيئة
  3. يختبر اتصال ACP SDK
  4. يُشغّل معاملة اختبار كاملة (self-evaluation)

تشغيل:
  python register_acp.py --network testnet   # للـ Sandbox
  python register_acp.py --network mainnet   # للإنتاج
"""

import sys, os, json, argparse, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

# ─────────────────────────────────────────────────────
CYAN  = "\033[96m"
GREEN = "\033[92m"
RED   = "\033[91m"
YELLOW= "\033[93m"
RESET = "\033[0m"
BOLD  = "\033[1m"

def c(text, color): return f"{color}{text}{RESET}"
def ok(m):   print(f"  {c('OK','')}{c(m, GREEN)}")
def fail(m): print(f"  {c('FAIL','')}{c(m, RED)}")
def info(m): print(f"  {c('--', '')} {m}")
def head(m): print(f"\n{BOLD}{c(m, CYAN)}{RESET}")
# ─────────────────────────────────────────────────────

JOB_OFFERING = {
    "name":        "trust-score",
    "description": (
        "Before hiring any agent, know their trust score. "
        "TrustLayer reads ERC-8004 on-chain data and gives you an instant "
        "HIRE/AVOID recommendation. The trust layer every agent needs."
    ),
    "price":       0.01,
    "slaMinutes":  3,
    "requirement": {
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "ERC-8004 agent to evaluate. Format: chain_id:token_id (e.g. 8453:1870)"
            }
        },
        "required": ["agent_id"]
    },
    "deliverable": (
        "JSON with: score (0-100), level (DANGEROUS/RISKY/NEUTRAL/TRUSTED/ELITE), "
        "trend, recommendation (HIRE/VERIFY/AVOID), red_flags, breakdown."
    )
}

AGENT_METADATA = {
    "name":        "TrustLayer",
    "description": (
        "Trust Intelligence for ACP Agents. "
        "Reads ERC-8004 on-chain reputation data and delivers instant "
        "HIRE/AVOID decisions. The trust layer every agent needs before paying."
    ),
    "category":    "intelligence,trust,reputation,security",
    "tags":        ["trust", "reputation", "erc-8004", "agent-intelligence", "hire-avoid"],
    "version":     "1.0.0",
}


def print_registration_guide(network: str):
    """Print the manual ACP Dashboard registration guide."""
    head("=" * 60)
    head("  TrustLayer — ACP Registration Guide")
    head("=" * 60)

    print(f"""
{BOLD}STEP 1:{RESET} Go to ACP Dashboard
  {c('https://app.virtuals.io/acp', YELLOW)}
  (or Sandbox: https://acpx.virtuals.gg)

{BOLD}STEP 2:{RESET} Create New Agent
  Name:        {c('TrustLayer', GREEN)}
  Description: {c(AGENT_METADATA['description'][:80] + '...', GREEN)}
  Category:    {c('intelligence,trust,reputation', GREEN)}
  Tags:        {c('trust, reputation, erc-8004, agent-intelligence', GREEN)}

{BOLD}STEP 3:{RESET} Add Job Offering
  Name:        {c('trust-score', GREEN)}
  Price:       {c('0.01 USDC', GREEN)}
  SLA:         {c('3 minutes', GREEN)}
  Description: {c(JOB_OFFERING['description'][:70]+'...', GREEN)}

{BOLD}STEP 4:{RESET} Set Agent URL
  Point to your running TrustLayer API:
  {c('http://YOUR_IP:8000', YELLOW)}

{BOLD}STEP 5:{RESET} Copy credentials to .env:
  AGENT_WALLET_ADDRESS = (from dashboard)
  AGENT_ENTITY_ID      = (entity ID from dashboard)
  WHITELISTED_WALLET_PRIVATE_KEY = (your dev wallet private key)
""")

    print(f"{BOLD}Job Offering JSON (copy to dashboard):{RESET}")
    print(json.dumps(JOB_OFFERING, indent=2))


def check_credentials() -> bool:
    """Verify .env credentials are set."""
    head("Checking Credentials")
    pk     = os.getenv("WHITELISTED_WALLET_PRIVATE_KEY", "")
    wallet = os.getenv("AGENT_WALLET_ADDRESS", "")
    entity = os.getenv("AGENT_ENTITY_ID", "")

    has_pk     = bool(pk and pk != "your_private_key_here_without_0x")
    has_wallet = bool(wallet and wallet.startswith("0x"))
    has_entity = bool(entity)

    if has_pk:     ok("WHITELISTED_WALLET_PRIVATE_KEY — set")
    else:          fail("WHITELISTED_WALLET_PRIVATE_KEY — missing in .env")

    if has_wallet: ok(f"AGENT_WALLET_ADDRESS — {wallet[:10]}...{wallet[-6:]}")
    else:          fail("AGENT_WALLET_ADDRESS — missing in .env")

    if has_entity: ok(f"AGENT_ENTITY_ID — {entity}")
    else:          fail("AGENT_ENTITY_ID — missing in .env")

    return has_pk and has_wallet and has_entity


def test_acp_connection(network: str) -> bool:
    """Test connection to ACP SDK."""
    head(f"Testing ACP SDK Connection ({network})")
    try:
        from virtuals_acp.client import VirtualsACP
        from virtuals_acp.contract_clients.v2_contract_client import ACPContractClientV2
        from virtuals_acp.configs.configs import (
            BASE_MAINNET_ACP_X402_CONFIG_V2,
            BASE_SEPOLIA_ACP_X402_CONFIG_V2,
        )
        ok("virtuals-acp SDK imported")

        config = BASE_MAINNET_ACP_X402_CONFIG_V2 if network == "mainnet" \
                 else BASE_SEPOLIA_ACP_X402_CONFIG_V2

        info(f"ACP API URL: {config.acp_api_url}")
        info(f"Contract:    {config.contract_address}")
        info(f"Chain ID:    {config.chain_id}")

        pk     = os.getenv("WHITELISTED_WALLET_PRIVATE_KEY")
        wallet = os.getenv("AGENT_WALLET_ADDRESS")
        entity = os.getenv("AGENT_ENTITY_ID")

        contract_client = ACPContractClientV2(
            wallet_private_key=pk,
            agent_wallet_address=wallet,
            entity_id=int(entity),
            config=config,
        )
        ok("ACPContractClientV2 created")

        acp = VirtualsACP(
            acp_contract_clients=contract_client,
            on_new_task=lambda job, memo: None,
            skip_socket_connection=True,
        )
        ok("VirtualsACP initialized (socket skipped for test)")

        # Try browsing agents
        info("Searching for agents on ACP...")
        agents = acp.browse_agents(
            keyword="trust",
            top_k=3,
        )
        ok(f"browse_agents() returned {len(agents)} agents")
        for a in agents[:2]:
            info(f"  {a.name or a.wallet_address} — {len(a.job_offerings)} offerings")

        return True

    except ImportError:
        fail("virtuals-acp not installed. Run: pip install virtuals-acp")
        return False
    except Exception as e:
        fail(f"ACP connection error: {e}")
        info("Make sure your credentials in .env are correct")
        return False


def run_self_eval_transaction(network: str):
    """
    Run a complete self-evaluation test transaction.
    TrustLayer acts as both buyer AND seller to test the full lifecycle.
    """
    head("Self-Evaluation Transaction Test")
    info("This will initiate a real job on the ACP contract")
    info("Cost: 0.01 USDC from your test wallet")
    confirm = input(f"  {c('Proceed? (yes/no): ', YELLOW)}")
    if confirm.lower() != "yes":
        info("Skipped by user.")
        return

    try:
        from virtuals_acp.client import VirtualsACP
        from virtuals_acp.contract_clients.v2_contract_client import ACPContractClientV2
        from virtuals_acp.configs.configs import (
            BASE_MAINNET_ACP_X402_CONFIG_V2,
            BASE_SEPOLIA_ACP_X402_CONFIG_V2,
        )
        from virtuals_acp.fare import FareAmount

        config = BASE_MAINNET_ACP_X402_CONFIG_V2 if network == "mainnet" \
                 else BASE_SEPOLIA_ACP_X402_CONFIG_V2

        contract_client = ACPContractClientV2(
            wallet_private_key=os.getenv("WHITELISTED_WALLET_PRIVATE_KEY"),
            agent_wallet_address=os.getenv("AGENT_WALLET_ADDRESS"),
            entity_id=int(os.getenv("AGENT_ENTITY_ID")),
            config=config,
        )

        delivered = {"done": False, "result": None}

        def on_new_task(job, memo_to_sign):
            info(f"Provider received job {job.id}")
            # Accept
            if memo_to_sign:
                memo_to_sign.sign(True, "TrustLayer accepting job")
            # Compute trust score for a known agent
            from core.scorer import compute_trust_score
            from core.chain_reader import fetch_agent
            result = compute_trust_score("42220:1870")
            job.deliver(json.dumps(result, indent=2))
            info(f"Delivered score: {result['score']}")
            delivered["done"] = True
            delivered["result"] = result

        acp = VirtualsACP(
            acp_contract_clients=contract_client,
            on_new_task=on_new_task,
            on_evaluate=lambda job: job.evaluate(True, "Auto-approved"),
        )
        ok("ACP agent connected")

        # Find TrustLayer agent on ACP and initiate a job to itself
        # (self-evaluation: buyer = seller = TrustLayer)
        agents = acp.browse_agents(keyword="TrustLayer", top_k=1)
        if not agents:
            fail("TrustLayer not found on ACP yet. Register first via the dashboard.")
            return

        agent = agents[0]
        ok(f"Found TrustLayer: {agent.wallet_address}")
        offering = agent.job_offerings[0] if agent.job_offerings else None
        if not offering:
            fail("No job offerings found. Add 'trust-score' offering in dashboard.")
            return

        info("Initiating self-evaluation job...")
        job_id = offering.initiate_job(
            service_requirement=json.dumps({"agent_id": "42220:1870"}),
            evaluator_address=None,  # self-evaluate
        )
        ok(f"Job initiated! ID: {job_id}")

        # Wait for delivery
        for i in range(30):
            if delivered["done"]:
                ok(f"Transaction complete!")
                print(f"\n  {BOLD}Result:{RESET}")
                print(f"    Score:  {delivered['result']['score']}/100")
                print(f"    Level:  {delivered['result']['level']}")
                print(f"    Rec:    {delivered['result']['recommendation']}")
                print(f"\n  {c('FIRST PAID TRANSACTION COMPLETE!', GREEN)}")
                return
            time.sleep(2)
            info(f"Waiting for delivery... ({(i+1)*2}s)")

        fail("Timeout waiting for job delivery")

    except Exception as e:
        fail(f"Transaction error: {e}")
        import traceback; traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(description="TrustLayer ACP Registration & Test")
    parser.add_argument("--network", default="testnet", choices=["testnet","mainnet"])
    parser.add_argument("--guide-only", action="store_true",
                        help="Just print the registration guide")
    args = parser.parse_args()

    print_registration_guide(args.network)

    if args.guide_only:
        return

    creds_ok = check_credentials()
    if not creds_ok:
        print(f"\n{c('Fill in .env first, then re-run this script.', YELLOW)}\n")
        return

    sdk_ok = test_acp_connection(args.network)
    if not sdk_ok:
        return

    run_self_eval_transaction(args.network)


if __name__ == "__main__":
    main()
