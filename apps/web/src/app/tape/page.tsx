import type { Metadata } from "next";
import { TapeView, type BadgeSurvey } from "./view";
import { readArtifact } from "@/lib/build-artifact";

export const metadata: Metadata = {
  title: "What the index actually holds",
  description:
    "A quiet range of blocks and a range nobody fetched both contain zero swaps. This is the record of which ones were actually read.",
};

export default function TapePage() {
  // The pool list, and only the pool list. `vetting.json` records which pools
  // this repository has verified — a fact that does not depend on a service
  // being up, so it prerenders. Everything about what the tape *holds* is read
  // live by the view, because a snapshot of that would be the substitution the
  // page exists to argue against.
  return <TapeView vetted={readArtifact<BadgeSurvey>("vetting.json")} />;
}
