import type { Metadata } from "next";
import { AdvantageView } from "./view";

// A server component, so the title reaches the prerendered HTML. Every route
// was a client component, none could export metadata, and all seven pages
// therefore shipped the same <title> — which also made `title.template` in the
// layout dead code and left RouteAnnouncer announcing the wrong page name.
export const metadata: Metadata = {
  title: "Does hiring an agent beat doing it yourself?",
  description: "Three tasks, each done both ways, through the same replay engine — with the aggregate verdict refused for want of observations.",
};

export default function Page() {
  return <AdvantageView />;
}
