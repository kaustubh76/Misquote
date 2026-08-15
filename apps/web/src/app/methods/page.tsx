import type { Metadata } from "next";
import { MethodsView } from "./view";

// A server component, so the title reaches the prerendered HTML. Every route
// was a client component, none could export metadata, and all seven pages
// therefore shipped the same <title> — which also made `title.template` in the
// layout dead code and left RouteAnnouncer announcing the wrong page name.
export const metadata: Metadata = {
  title: "How a quote is made",
  description: "The arithmetic between a replay and the range on a card, and the four floors that stop a number being printed at all.",
};

export default function Page() {
  return <MethodsView />;
}
