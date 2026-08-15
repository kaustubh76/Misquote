import type { Metadata } from "next";
import { StatusView } from "./view";

// A server component, so the title reaches the prerendered HTML. Every route
// was a client component, none could export metadata, and all seven pages
// therefore shipped the same <title> — which also made `title.template` in the
// layout dead code and left RouteAnnouncer announcing the wrong page name.
export const metadata: Metadata = {
  title: "Readiness",
  description: "A checklist that executes. Anything it cannot verify is reported as unverified rather than assumed.",
};

export default function Page() {
  return <StatusView />;
}
