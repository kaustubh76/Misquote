import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Prose } from "@/components/Blocks";

afterEach(cleanup);

/**
 * The renderer every emitter in this repository writes for.
 *
 * `Prose` was private to `Blocks` while `/assumptions` was the only page that
 * used it, and six other surfaces printed markdown at the reader as characters
 * — the Agent Studio ledger card read "**The funding half of this blocker has
 * closed**" with the asterisks visible.
 */
describe("prose from an artifact", () => {
  it("renders the marks instead of printing them", () => {
    render(<Prose text="**closed**: recorded in `identity/97.json`" />);

    expect(screen.getByText("closed").tagName).toBe("STRONG");
    expect(screen.getByText("identity/97.json").tagName).toBe("CODE");
    expect(document.body.textContent).not.toContain("**");
    expect(document.body.textContent).not.toContain("`");
  });

  it("still links the assumptions a sentence names", () => {
    // The citations came first and must survive the widening: these ids were
    // inert text on every card before `WithCitations`, and the sheet the whole
    // argument rests on was one the reader had to go and find.
    render(<Prose text="**A5** is the range, net of P-1" />);

    expect(screen.getByRole("link", { name: "A5" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "P-1" })).toBeInTheDocument();
  });

  it("renders no anchor at all when it is already inside one", () => {
    // An anchor inside an anchor is not a style question. The HTML parser
    // hoists the inner one out of the server markup, the client tree no longer
    // matches, and React #418 fires on every load — which is what `/assumptions`
    // did, because three of its titles name another assumption and the index
    // draws each title inside its own `<a href="#id">`.
    render(
      <Prose text="A1 is refused at the decision, see [the sheet](/assumptions)" links={false} />,
    );

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    // Dropped from the markup, not from the sentence.
    expect(document.body.textContent).toContain("A1");
    expect(document.body.textContent).toContain("the sheet");
    expect(document.body.textContent).not.toContain("/assumptions");
  });

  it("keeps emphasis when the links are off", () => {
    render(<Prose text="**closed**, and `verify` still runs" links={false} />);

    expect(screen.getByText("closed").tagName).toBe("STRONG");
    expect(screen.getByText("verify").tagName).toBe("CODE");
  });
});
