import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Heading, HeadingLevel, Section } from "./Heading";

/**
 * The mechanism, tested directly.
 *
 * `Section` and `HeadingLevel` shipped with zero importers, so `LevelContext`
 * was never provided and `useHeadingLevel()` always returned its
 * `createContext(2)` default — every `<Heading>` rendered `<h2>`
 * unconditionally, which is exactly the hardcoded `h2` the file was written to
 * replace. The abstraction existed and did nothing.
 *
 * These assertions are on the tag name rather than on the role, because the
 * role is `heading` at every level and the level is the entire point.
 */
describe("heading level follows the tree", () => {
  it("deepens once per Section", () => {
    render(
      <Section title="Outer">
        <Section title="Inner">
          <Heading>Leaf</Heading>
        </Section>
      </Section>,
    );

    expect(screen.getByText("Outer").tagName).toBe("H2");
    expect(screen.getByText("Inner").tagName).toBe("H3");
    expect(screen.getByText("Leaf").tagName).toBe("H4");
  });

  it("defaults to h2 with no provider, so a bare page section is right", () => {
    render(<Heading>Alone</Heading>);
    expect(screen.getByText("Alone").tagName).toBe("H2");
  });

  it("lets an explicit level win", () => {
    render(
      <Section title="Outer">
        <Heading level={5}>Pinned</Heading>
      </Section>,
    );
    expect(screen.getByText("Pinned").tagName).toBe("H5");
  });

  it("clamps rather than emitting an h7", () => {
    render(
      <HeadingLevel value={9}>
        <Heading>Deep</Heading>
      </HeadingLevel>,
    );
    expect(screen.getByText("Deep").tagName).toBe("H6");
  });

  it("marks its own section, so a test can tell it from any other <section>", () => {
    // `Card` defaults to rendering a <section>, so a rule keyed on the element
    // would fire on cards. The scope attribute keeps the outline test aimed at
    // Section itself.
    const { container } = render(<Section title="Scoped">body</Section>);
    expect(container.querySelector("[data-heading-scope]")).toBeInTheDocument();
  });

  it("renders the intro only when given one", () => {
    const { rerender, container } = render(<Section title="Bare" />);
    expect(container.querySelectorAll("p")).toHaveLength(0);

    rerender(<Section title="Bare" intro="Why this section exists." />);
    expect(screen.getByText("Why this section exists.")).toBeInTheDocument();
  });
});
