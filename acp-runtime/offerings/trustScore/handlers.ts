/**
 * TrustLayer — handlers.ts  (acp-runtime edition)
 * ACP job handler for the "trustScore" offering.
 * Delegates computation to the hosted TrustLayer API on Render.
 *
 * Architecture:
 *   ACP buyer → openclaw-acp runtime (this file)
 *            → https://trustlayer-d3rf.onrender.com/trust
 *            → ERC-8004 on-chain data
 *            → Trust Score result
 */

const TRUSTLAYER_API = process.env.TRUSTLAYER_API_URL ?? "https://trustlayer-d3rf.onrender.com";

interface TrustScoreRequest {
  agentId: string;
}

/** Must match openclaw-acp ExecuteJobResult: { deliverable, payableDetail? } */
export interface ExecuteJobResult {
  deliverable: string;
  payableDetail?: { amount: number; tokenAddress: string };
}

export async function executeJob(requirements: TrustScoreRequest): Promise<ExecuteJobResult> {
  const agentId = requirements?.agentId ?? (requirements as any)?.agent_id;

  if (!agentId) {
    return {
      deliverable: JSON.stringify({
        error: "Missing agentId in requirements",
        hint: "Send { agentId: 'chain_id:token_id' } e.g. { agentId: '8453:1870' }",
      }),
    };
  }

  try {
    const response = await fetch(`${TRUSTLAYER_API}/trust`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent_id: agentId }),
    });

    if (!response.ok) {
      const text = await response.text();
      return {
        deliverable: JSON.stringify({
          error: `TrustLayer API returned ${response.status}`,
          details: text,
        }),
      };
    }

    const result = await response.json();
    return { deliverable: JSON.stringify(result, null, 2) };

  } catch (err: any) {
    return {
      deliverable: JSON.stringify({
        error: "TrustLayer backend unreachable",
        details: err?.message ?? String(err),
        fix: "Check https://trustlayer-d3rf.onrender.com/health — free tier ~30s cold start.",
      }),
    };
  }
}
