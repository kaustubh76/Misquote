import type { Metadata } from "next";
import { RegistryView } from "./view";

// A server component, so the title reaches the prerendered HTML. Every route
// was a client component, none could export metadata, and all seven pages
// therefore shipped the same <title> — which also made `title.template` in the
// layout dead code and left RouteAnnouncer announcing the wrong page name.
export const metadata: Metadata = {
  title: "Standards, and what they actually cost",
  description: "What is behind a Hire button when the hire is an on-chain job under ERC-8183, and what the ERC-8004 registry contains.",
};

export default function Page() {
  return <RegistryView />;
}
