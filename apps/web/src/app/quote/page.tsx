import type { Metadata } from "next";
import { QuoteView } from "./view";

// A server component so the title and the standing prose reach the prerendered
// HTML. The interactive half needs JavaScript — it is an input — but the
// explanation of what a quote *is*, and why one is not served from a request,
// must be readable without it.
export const metadata: Metadata = {
  title: "Quote my positions",
  description:
    "What these agents would have done with the positions you actually hold — checked against the tape before anything is queued, and refused in advance when the evidence cannot support it.",
};

export default function Page() {
  return <QuoteView />;
}
