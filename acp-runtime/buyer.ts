import { AcpAgent, PrivyAlchemyEvmProviderAdapter, AssetToken } from "@virtuals-protocol/acp-node-v2";
import type { JobSession, JobRoomEntry } from "@virtuals-protocol/acp-node-v2";
import { base } from "@account-kit/infra";

const BUYER_WALLET_ADDRESS = process.env.BUYER_WALLET_ADDRESS as `0x${string}`;
const BUYER_WALLET_ID      = process.env.BUYER_WALLET_ID!;
const BUYER_PRIVATE_KEY    = process.env.BUYER_PRIVATE_KEY!;

const SELLER_WALLET = "0x76c46e61ddc94454446e87b40c7e52386b29d1c9" as `0x${string}`;
const OFFERING_NAME = "trustScore";
const REQUIREMENT   = { agentId: "019e5814-90ca-78b9-b6e8-7d453103fdcd" };
const PRICE_USDC    = 0.01;
const TOTAL_JOBS    = parseInt(process.env.TOTAL_JOBS ?? "10");

let completedJobs = 0;
let activeJobs    = new Set<string>();

async function main() {
  console.log(`[TLBuyer] Starting — target: ${TOTAL_JOBS} completed transactions`);

  const buyer = await AcpAgent.create({
    provider: await PrivyAlchemyEvmProviderAdapter.create({
      walletAddress: BUYER_WALLET_ADDRESS,
      walletId:      BUYER_WALLET_ID,
      signerPrivateKey: BUYER_PRIVATE_KEY,
      chains: [base],
    }),
  });

  const buyerAddress = await buyer.getAddress();
  console.log(`[TLBuyer] Wallet ready: ${buyerAddress}`);

  buyer.on("entry", async (session: JobSession, entry: JobRoomEntry) => {
    if (entry.kind !== "system") return;
    const eventType = (entry.event as any).type as string;

    switch (eventType) {
      case "budget.set":
        console.log(`[${session.jobId}] Budget set — funding ${PRICE_USDC} USDC`);
        await session.fund(AssetToken.usdc(PRICE_USDC, session.chainId));
        break;
      case "job.submitted":
        console.log(`[${session.jobId}] Delivery received — completing`);
        await session.complete("Looks good — trust score delivered");
        break;
      case "job.completed":
        completedJobs++;
        activeJobs.delete(session.jobId);
        console.log(`[${session.jobId}] Completed (${completedJobs}/${TOTAL_JOBS})`);
        if (completedJobs >= TOTAL_JOBS) {
          console.log(`\n All ${TOTAL_JOBS} transactions complete! TrustLayer is ready to graduate.`);
          process.exit(0);
        }
        setTimeout(() => spawnJob(buyer, buyerAddress), 3000);
        break;
      case "job.rejected":
        console.error(`[${session.jobId}] Job rejected`);
        activeJobs.delete(session.jobId);
        setTimeout(() => spawnJob(buyer, buyerAddress), 5000);
        break;
    }
  });

  await buyer.start(() => console.log("[TLBuyer] Listener active"));
  await spawnJob(buyer, buyerAddress);
}

async function spawnJob(buyer: AcpAgent, buyerAddress: `0x${string}`) {
  if (completedJobs >= TOTAL_JOBS) return;
  try {
    console.log(`[TLBuyer] Creating job #${completedJobs + activeJobs.size + 1}...`);
    const jobId = await buyer.createJobByOfferingName(
      base.id, OFFERING_NAME, SELLER_WALLET, REQUIREMENT,
      { evaluatorAddress: buyerAddress }
    );
    activeJobs.add(jobId);
    console.log(`[TLBuyer] Job created: ${jobId}`);
  } catch (err) {
    console.error("[TLBuyer] Failed to create job:", (err as Error).message);
    setTimeout(() => spawnJob(buyer, buyerAddress), 10000);
  }
}

main().catch(err => { console.error("[TLBuyer] Fatal:", err); process.exit(1); });
