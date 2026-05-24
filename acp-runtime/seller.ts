import { AcpAgent, PrivyAlchemyEvmProviderAdapter, AssetToken } from "@virtuals-protocol/acp-node-v2";
import type { JobSession, JobRoomEntry } from "@virtuals-protocol/acp-node-v2";
import { base } from "@account-kit/infra";

const TRUSTLAYER_API = process.env.TRUSTLAYER_API_URL ?? "https://trustlayer-d3rf.onrender.com";
const SELLER_WALLET_ADDRESS = process.env.AGENT_WALLET_ADDRESS as `0x${string}`;
const WALLET_ID = process.env.AGENT_WALLET_ID!;
const SIGNER_PRIVATE_KEY = process.env.AGENT_PRIVATE_KEY!;
const OFFERING_PRICE = parseFloat(process.env.TRUSTLAYER_SERVICE_PRICE_USDC ?? "0.01");

interface TrustScoreRequirement {
  agentId?: string;
  agent_id?: string;
}

const jobRequirements = new Map<string, TrustScoreRequirement>();

async function callTrustLayer(agentId: string): Promise<string> {
  const response = await fetch(`${TRUSTLAYER_API}/trust`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agent_id: agentId }),
  });
  if (!response.ok) {
    const text = await response.text();
    return JSON.stringify({ error: `TrustLayer API error ${response.status}`, details: text });
  }
  const result = await response.json();
  return JSON.stringify(result, null, 2);
}

async function main() {
  console.log("TrustLayer ACP v2.0 Seller starting...");
  console.log(`Wallet: ${SELLER_WALLET_ADDRESS}`);
  console.log(`Price: ${OFFERING_PRICE} USDC`);

  const agent = await AcpAgent.create({
    provider: await PrivyAlchemyEvmProviderAdapter.create({
      walletAddress: SELLER_WALLET_ADDRESS,
      walletId: WALLET_ID,
      chains: [base],
      signerPrivateKey: SIGNER_PRIVATE_KEY,
    }),
  });

  agent.on("entry", async (session: JobSession, entry: JobRoomEntry) => {
    try {
      // Capture the requirement message from the buyer
      if (
        entry.kind === "message" &&
        entry.contentType === "requirement" &&
        session.status === "open"
      ) {
        const req: TrustScoreRequirement = JSON.parse(entry.content);
        jobRequirements.set(session.jobId, req);
        console.log(`[${session.jobId}] Requirement received:`, req);
        // Propose our fixed price
        await session.setBudget(AssetToken.usdc(OFFERING_PRICE, session.chainId));
        console.log(`[${session.jobId}] Budget set: ${OFFERING_PRICE} USDC`);
        return;
      }

      if (entry.kind === "system") {
        const eventType = (entry.event as any).type as string;
        console.log(`[${session.jobId}] Event: ${eventType}`);

        if (eventType === "job.created") {
          console.log(`[${session.jobId}] New job created — waiting for requirement message`);
        }

        if (eventType === "job.funded") {
          const req = jobRequirements.get(session.jobId) ?? {};
          const agentId = req.agentId ?? req.agent_id;
          let deliverable: string;

          if (!agentId) {
            deliverable = JSON.stringify({ error: "Missing agentId in requirements" });
            console.log(`[${session.jobId}] Error: missing agentId`);
          } else {
            console.log(`[${session.jobId}] Querying TrustLayer for agent ${agentId}...`);
            try {
              deliverable = await callTrustLayer(agentId);
            } catch (err: any) {
              deliverable = JSON.stringify({ error: "TrustLayer unreachable", details: err?.message });
            }
          }

          console.log(`[${session.jobId}] Submitting deliverable...`);
          await session.submit(deliverable);
          jobRequirements.delete(session.jobId);
        }

        if (eventType === "job.completed") {
          console.log(`[${session.jobId}] ✅ Job completed successfully`);
        }

        if (eventType === "job.rejected") {
          console.log(`[${session.jobId}] ❌ Job rejected`);
          jobRequirements.delete(session.jobId);
        }
      }
    } catch (err: any) {
      console.error(`[${session.jobId}] Handler error:`, err?.message);
    }
  });

  await agent.start(() => {
    console.log("✅ TrustLayer ACP v2.0 Seller is listening for jobs...");
  });
}

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
