import type { Metadata } from "next";
import { VettingView } from "./view";

export const metadata: Metadata = {
  title: "Due diligence, read from chain",
  description:
    "Every pool a listed agent touches, read from chain and checked against the defects this project actually hit — with a read it could not make reported as unknown rather than as a pass.",
};

export default function Page() {
  return <VettingView />;
}
