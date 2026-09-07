import type { Metadata } from "next";
import { ActivateView, type EscrowHalf, type SessionKeySurvey, type SessionProof } from "./view";
import type { HireableAgent } from "@/components/HireEscrow";
import { readArtifact } from "@/lib/build-artifact";

export const metadata: Metadata = {
  title: "Activation, bounded and reversible",
  description:
    "Hire an agent with a session key your wallet grants and can revoke. The contract enforces the expiry and the revoke; the allowlist and the spend cap are not enforced, and the button says so before you sign.",
};

/**
 * The round trip is read at build time, not fetched.
 *
 * It is three transaction hashes and two booleans — small, and it never changes
 * once mined. Fetching it would make the one piece of third-party-checkable
 * evidence on this page the one piece that needs JavaScript to appear.
 */
export default function Page() {
  const addresses = readArtifact<{
    session_key_proof?: SessionProof;
    session_keys?: Record<string, SessionKeySurvey>;
  }>("addresses.json");
  // Chapel, because chapel is where the round trip was run. Publishing the
  // mainnet survey beside a testnet proof would invite reading one as evidence
  // for the other.
  // The escrow half, read at build time from the same artifact `/registry`
  // renders. The addresses are not duplicated here for the reason `lib/escrow.ts`
  // opens with: a second copy would be a second thing to be wrong, and the
  // wrong one would be the one people send money to.
  const registry = readArtifact<{
    hire_flow?: EscrowHalf;
    ours?: { owner?: string };
  }>("registry.json");
  const index = readArtifact<{ agents?: HireableAgent[] }>("index.json");

  return (
    <ActivateView
      proof={addresses?.session_key_proof}
      survey={addresses?.session_keys?.["97"]}
      escrow={registry?.hire_flow}
      agents={index?.agents}
      owner={registry?.ours?.owner}
    />
  );
}
