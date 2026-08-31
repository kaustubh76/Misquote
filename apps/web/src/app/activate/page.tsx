import type { Metadata } from "next";
import { ActivateView, type SessionKeySurvey, type SessionProof } from "./view";
import { readArtifact } from "@/lib/build-artifact";

export const metadata: Metadata = {
  title: "Activation, bounded and reversible",
  description:
    "Hiring an agent should be bounded and reversible: an allowlist, a spend cap, an expiry, and a one-transaction revoke. Two of the four are enforced by the contract and proven on chapel with transaction hashes; the other two are enforced by nothing, so there is still no Hire button.",
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
  return (
    <ActivateView
      proof={addresses?.session_key_proof}
      survey={addresses?.session_keys?.["97"]}
    />
  );
}
