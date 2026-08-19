import type { Metadata } from "next";
import { VettingView, type VettingArtifact, type AddressArtifact } from "./view";
import type { IndexArtifact } from "@/lib/artifacts";
import { readArtifact } from "@/lib/build-artifact";

export const metadata: Metadata = {
  title: "Due diligence, read from chain",
  description:
    "Every pool an agent touches and every address the signer is aimed at, read from chain — with a read it could not make reported as unknown, never as a pass.",
};

export default function Page() {
  return <VettingView initialVetting={readArtifact<VettingArtifact>("vetting.json")} initialIndex={readArtifact<IndexArtifact>("index.json")} initialAddresses={readArtifact<AddressArtifact>("addresses.json")} />;
}
