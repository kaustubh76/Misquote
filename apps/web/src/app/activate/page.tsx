import type { Metadata } from "next";
import { ActivateView } from "./view";

export const metadata: Metadata = {
  title: "Activation, and the address it does not have",
  description:
    "Hiring an agent should be bounded and reversible: an allowlist, a spend cap, an expiry, and a one-transaction revoke. The plan is published; the module to send it to is not verified, so there is no Hire button.",
};

export default function Page() {
  return <ActivateView />;
}
