"""`lib/routes.ts` and `check-pages.mjs` must list the same routes.

Two hand-maintained copies of the site's route list exist, and they exist for
good reasons that do not go away. `lib/routes.ts` is TypeScript imported by the
nav and the 404; `check-pages.mjs` is a plain Node script driving Playwright
against a built export, with no TypeScript loader and no build step. Neither can
import the other.

So they drift, and `check-pages.mjs` already records what that costs. Beside its
`agent-router` entry:

    It was rendering only under tsc and jsdom until this line existed, and
    "every route clean" meant every route in this list, which is exactly the
    shape of claim this file exists to stop being made.

That is the failure mode precisely. The check prints "every route clean in both
themes and at 390px" and means "every route somebody remembered to add" — a
sentence that gets weaker every time the site grows, silently, in the direction
of being useless. A newly added route is exactly the one most likely to have a
layout defect and exactly the one most likely to be missing here.

It happened again immediately: `/tape` was added to `lib/routes.ts`, to the nav
test's own second copy, and to the no-JS floor table, and was still absent from
the screenshot sweep — caught by reading the output rather than by anything
failing.

## Why the no-JS table is checked separately, and loosely

`NO_JS` is a *subset* by design: it holds one of the four category pages and two
of the four agent pages, on the stated grounds that a fifth screenshot of the
same component tree over the same artifact buys nothing. So this asserts the
screenshot list covers every nav route, and asserts only that the no-JS table is
non-empty for each nav route's *prefix group* — never that the two match.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROUTES_TS = REPO / "apps" / "web" / "src" / "lib" / "routes.ts"
CHECK_MJS = REPO / "apps" / "web" / "scripts" / "check-pages.mjs"


def nav_routes() -> set[str]:
    """Every `href` in `ROUTES`, normalised to a trailing slash."""
    body = ROUTES_TS.read_text()
    hrefs = re.findall(r'href:\s*"([^"]+)"', body)
    assert hrefs, "no routes parsed out of lib/routes.ts — has the shape changed?"
    return {href if href.endswith("/") else f"{href}/" for href in hrefs}


def _paths_in(block: str) -> set[str]:
    return {p if p.endswith("/") else f"{p}/" for p in re.findall(r'"(/[^"]*)"', block)}


def screenshot_routes() -> set[str]:
    body = CHECK_MJS.read_text()
    block = re.search(r"^const ROUTES = \[(.*?)^\];", body, re.S | re.M)
    assert block, "no ROUTES array found in check-pages.mjs"
    return _paths_in(block.group(1))


def no_js_routes() -> set[str]:
    body = CHECK_MJS.read_text()
    block = re.search(r"^const NO_JS = \[(.*?)^\];", body, re.S | re.M)
    assert block, "no NO_JS array found in check-pages.mjs"
    return _paths_in(block.group(1))


def test_every_nav_route_is_screenshotted() -> None:
    missing = sorted(nav_routes() - screenshot_routes())
    assert not missing, (
        f"{missing} appear in the nav but not in check-pages.mjs's ROUTES, so "
        '"every route clean" does not include them'
    )


def test_every_nav_route_has_a_no_js_floor() -> None:
    """A route with no floor can collapse to its heading and nothing says so."""
    missing = sorted(nav_routes() - no_js_routes())
    assert not missing, f"{missing} have no entry in check-pages.mjs's NO_JS table"


def test_the_screenshot_list_names_no_route_that_does_not_exist() -> None:
    """The other direction: a renamed route leaves a sweep pointing at a 404.

    Detail routes are excluded rather than resolved — `/agent/warden/` and
    `/category/rebalancing/` are generated from artifacts and have no entry in
    `lib/routes.ts` by design.
    """
    nav = nav_routes()
    stale = sorted(
        path
        for path in screenshot_routes()
        if path not in nav and not any(path.startswith(known) and path != known for known in nav)
    )
    assert not stale, f"{stale} are screenshotted but are not routes the nav knows about"
