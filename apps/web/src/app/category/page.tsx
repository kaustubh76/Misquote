import type { Metadata } from "next";
import { CategoryIndexView } from "./view";
import type { IndexArtifact } from "@/lib/artifacts";
import { readArtifact } from "@/lib/build-artifact";

export const metadata: Metadata = {
  title: "The four categories",
  description:
    "What each category is judged on, the do-it-yourself baseline it is judged against, and the one agent serving it — plus why no third-party agent appears here.",
};

export default function Page() {
  return <CategoryIndexView initial={readArtifact<IndexArtifact>("index.json")} />;
}
