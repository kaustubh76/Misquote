import type { Metadata } from "next";
import { VettingView } from "./view";

export const metadata: Metadata = {
  title: "Due diligence, read from chain",
  description:
    "Every pool an agent touches and every address the signer is aimed at, read from chain — with a read it could not make reported as unknown, never as a pass.",
};

export default function Page() {
  return <VettingView />;
}
