import "@testing-library/jest-dom/vitest";

// Testing Library's own retry window, raised alongside `testTimeout`. `findBy*`
// defaults to 1s, which is the one that actually expires first when the machine
// is busy — the outer test timeout never gets a chance to be the reason.
import { configure } from "@testing-library/dom";
configure({ asyncUtilTimeout: 5_000 });
