/**
 * TrustLayer — handlers.ts
 * ACP job handler for the "trustScore" offering.
 * Delegates computation to the hosted TrustLayer API on Render.
 *
 * Architecture:
 *   ACP buyer → openclaw-acp runtime (this file) → https://trustlayer-d3rf.onrender.com/trust → ERC-8004 → result
 */

const TRUSTLAYER_API = process.env.TRUSTLAYER_API_URL ?? "https://trustlayer-d3rf.onrender.com";

interface TrustScoreRequest {
  agentId: string;
}

export async function executeJob(requirements: TrustScoreRequest): Promise<string> {
  const agentId = requirements?.agentId ?? (requirements as any)?.agent_id;

  if (!agentId) {
    return JSON.stringify({
      error: "Missing agentId in requirements",
      hint: "Send { agentId: 'chain_id:token_id' } e.g. { agentId: '8453:1870' }",
    });
  }

  try {
    const response = await fetch(`${TRUSTLAYER_API}/trust`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent_id: agentId }),
    });

    if (!response.ok) {
      const text = await response.text();
      return JSON.stringify({
        error: `TrustLayer API returned ${response.status}`,
        details: text,
      });
    }

    const result = await response.json();
    return JSON.stringify(result, null, 2);

  } catch (err: any) {
    // API unreachable (cold start or network issue)
    return JSON.stringify({
      error: "TrustLayer backend unreachable",
      details: err?.message ?? String(err),
      fix: "Check https://trustlayer-d3rf.onrender.com/health — service may be waking up (free tier ~30s cold start).",
    });
  }
}
