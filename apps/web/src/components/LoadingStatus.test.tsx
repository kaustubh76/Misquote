/**
 * The invariant `Loadable` exists to hold.
 *
 * `aria-busy="true"` tells assistive technology to defer changes inside that
 * subtree. A `role="status"` region nested within it therefore says nothing
 * until the load it describes has already finished — it would announce
 * "loading" at the exact moment loading stopped.
 *
 * That is subtle enough that re-establishing it by hand on six pages is how it
 * comes to be wrong on one of them, so it lives in one component and this test
 * holds it there.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Loadable, LoadingStatus } from "./LoadingStatus";

describe("LoadingStatus", () => {
  it("announces the wait in words, because the skeletons are aria-hidden", () => {
    render(<LoadingStatus loading what="agent cards" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading agent cards.");
  });

  it("announces arrival too, so the region is not left saying 'loading' forever", () => {
    render(<LoadingStatus loading={false} what="agent cards" />);
    expect(screen.getByRole("status")).toHaveTextContent("agent cards loaded.");
  });
});

describe("Loadable", () => {
  it("puts the status region OUTSIDE the aria-busy subtree", () => {
    const { container } = render(
      <Loadable loading what="the report">
        <p>content</p>
      </Loadable>,
    );

    const status = container.querySelector('[role="status"]');
    const busy = container.querySelector("[aria-busy]");
    expect(status).not.toBeNull();
    expect(busy).not.toBeNull();

    // The whole point: a status region inside the busy container is deferred,
    // so it must not be a descendant of it.
    expect(busy!.contains(status!)).toBe(false);
    expect(status!.nextElementSibling).toBe(busy);
  });

  it("marks the container busy only while loading", () => {
    const { container, rerender } = render(
      <Loadable loading what="x">
        <p>c</p>
      </Loadable>,
    );
    expect(container.querySelector("[aria-busy='true']")).not.toBeNull();

    rerender(
      <Loadable loading={false} what="x">
        <p>c</p>
      </Loadable>,
    );
    expect(container.querySelector("[aria-busy='true']")).toBeNull();
  });

  it("renders its children", () => {
    render(
      <Loadable loading={false} what="x">
        <p>the actual content</p>
      </Loadable>,
    );
    expect(screen.getByText("the actual content")).toBeInTheDocument();
  });
});
