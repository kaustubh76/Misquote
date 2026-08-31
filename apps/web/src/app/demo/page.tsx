import type { Metadata } from "next";
import { DemoView } from "./view";
import { readScenarios } from "@/lib/build-artifact";

export const metadata: Metadata = {
  title: "See it work, without a wallet",
  description:
    "The states of this site that need a running API, a worker, or a BSC position you do not hold — recorded and replayed, labelled simulated, and never mistakable for live.",
};

/**
 * A server component, so the list is read off disk and prerenders.
 *
 * The page itself is never simulated: it is the table of contents, and it has to
 * stay readable when the API is asleep — which is precisely when somebody is most
 * likely to be looking for it.
 */
export default function Page() {
  return <DemoView scenarios={readScenarios()} />;
}
