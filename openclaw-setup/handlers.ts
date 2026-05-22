/**
 * TrustLayer — handlers.ts
 * ACP job handler for the "trustScore" offering.
 * Delegates computation to the Python FastAPI backend (port 8000).
 *
 * Architecture:
 *   ACP buyer → openclaw-acp runtime (this file) → Python FastAPI → ERC-8004 → result
 */

const TRUSTLAYER_API = process.env.TRUSTLAYER_API_URL ?? "http://localhost:8000";

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
    // Python server not running — return helpful error
    return JSON.stringify({
      error: "TrustLayer backend unreachable",
      details: err?.message ?? String(err),
      fix: "Start the Python API: python -m uvicorn api.server:app --port 8000",
    });
  }
}
