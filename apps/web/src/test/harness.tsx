import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { custom } from "viem";
import { WagmiProvider, createConfig } from "wagmi";
import { connect } from "wagmi/actions";
import { bsc, bscTestnet } from "wagmi/chains";
import { mock } from "wagmi/connectors";
import { WalletProvider } from "@/components/WalletProvider";
import { config as productionConfig } from "@/lib/wagmi";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { vi } from "vitest";

const ARTIFACTS = join(process.cwd(), "public", "artifacts");

/**
 * One read per artifact per worker, rather than one per fetch.
 *
 * Every view fetches its data on mount, so a page test triggers a `readFileSync`
 * of the file it renders — and `assumptions.json` is 181,816 bytes. `/assumptions`
 * has eleven tests and each one re-read all of it, synchronously, on a thread
 * vitest also runs three other suites on.
 *
 * That was the flake. `vitest.config.ts` blamed re-serialisation and raised
 * `testTimeout` to 15s over it, and the raise did not hold: the `/assumptions`
 * suites still failed one to three times per full run, always under file
 * parallelism, and always passing on a rerun or with `--no-file-parallelism`.
 * The config's own note says a flake "teaches people to rerun rather than to
 * read", which is exactly what a timeout raise teaches.
 *
 * Safe to memoise because the artifacts do not change during a run: nothing in
 * the suite writes to `public/artifacts`, and a test that wants different bytes
 * passes `overrides`, which is checked before this map is ever consulted.
 */
const FILES = new Map<string, string>();

function artifactBody(name: string): string {
  const hit = FILES.get(name);
  if (hit !== undefined) return hit;
  const body = readFileSync(join(ARTIFACTS, name), "utf8");
  FILES.set(name, body);
  return body;
}

/**
 * Serve the real generated artifacts to a page under test.
 *
 * Every view fetches its data at runtime, so a page test that stubs the data
 * proves only that the component can render the shape the test author imagined.
 * These read the same files `make artifacts` writes and the browser requests,
 * which is what makes a page test capable of catching an emitter change.
 */
/**
 * What the current test declared missing or overridden.
 *
 * Read by the `@/lib/build-artifact` mock in `vitest.setup.ts`, so a page's
 * **build-time** read sees the same bytes its runtime fetch will. In production
 * those two are the same file by construction; without this they were not, and
 * that gap is a race every prerendering page under test could lose.
 *
 * Module-level rather than passed around, because the code that has to consult
 * it is a server-only module a test never touches directly.
 */
let declared: { missing: Set<string>; overrides: Record<string, unknown> } = {
  missing: new Set(),
  overrides: {},
};

/**
 * The artifact a prerender should see, or `MISSING` when the test removed it.
 *
 * Exists so `readArtifact` can be made to agree with `fetch`. A page seeded from
 * disk while the fetch serves a fixture paints the real data first, and any
 * "is it ready?" signal fires against that paint — so assertions run against
 * whichever of the two the timing happened to deliver. Where the committed
 * artifact agrees with the fixture, the test passes by luck.
 *
 * That cost two real flakes: `/vectors` waiting on `aria-busy`, which is false
 * on the first paint when `initial` is supplied, and `/registry` finding the
 * four "register" links of the committed artifact where its fixture declared
 * one. Both read as selector problems and were timing.
 */
export const MISSING = Symbol("artifact removed by this test");

export function prerenderedArtifact(
  name: string
): unknown | typeof MISSING | undefined {
  if (declared.missing.has(name)) return MISSING;
  if (name in declared.overrides) return declared.overrides[name];
  return undefined;
}

export function serveArtifacts(
  options: { missing?: string[]; overrides?: Record<string, unknown> } = {}
) {
  const missing = new Set(options.missing ?? []);
  const overrides = options.overrides ?? {};
  declared = { missing, overrides };

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);

      // Matched as a full path, deliberately. Matching on the basename made
      // every request look correct regardless of its prefix, which is how a
      // page-relative "artifacts/warden.json" — 404 on every route but "/" —
      // passed the whole suite while the built site showed an error state.
      if (!url.startsWith("/artifacts/")) {
        throw new Error(
          `fetch("${url}") is not root-absolute. Artifact requests must start ` +
            `with "/artifacts/", or they resolve against the current route and ` +
            `404 everywhere except "/".`
        );
      }
      const name = url.slice("/artifacts/".length);

      if (missing.has(name)) {
        return new Response("<!DOCTYPE html><title>404</title>", {
          status: 404,
          statusText: "Not Found",
          headers: { "content-type": "text/html" },
        });
      }

      // A mutated body, for asserting that a figure is *read* rather than
      // restated: change the artifact and the page must change with it.
      if (name in overrides) {
        return new Response(JSON.stringify(overrides[name]), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }

      try {
        const body = artifactBody(name);
        return new Response(body, {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      } catch {
        return new Response("<!DOCTYPE html><title>404</title>", {
          status: 404,
          statusText: "Not Found",
          headers: { "content-type": "text/html" },
        });
      }
    })
  );
}

export function readArtifact<T>(name: string): T {
  // Parsed fresh from a cached string, deliberately. Callers mutate what they
  // get back to build `overrides`, so handing out a shared object would let one
  // test's edit reach the next one.
  return JSON.parse(artifactBody(name)) as T;
}

/**
 * The artifact's bytes, unparsed.
 *
 * `JSON.parse` is lossy on integers past 2**53 — `105790336763253403` comes
 * back as `105790336763253408` — so a test that asks whether the page prints
 * what the file says cannot ask a parsed object, which has already lost it.
 * `RefundTrail.test.tsx` is the caller, and the general guard is
 * `test_no_artifact_integer_loses_precision_in_a_browser`.
 */
export function readArtifactText(name: string): string {
  return artifactBody(name);
}

/**
 * A matcher for text taken verbatim out of an artifact.
 *
 * Artifact strings are prose, and prose contains regex metacharacters — the
 * kappa label is `kappa = 0.0500/tick (provisional default; fit r^2 = 0.00)`,
 * where the parentheses become a capture group and the caret an anchor. Passed
 * to `new RegExp` unescaped it matches nothing, and the test fails against
 * correct output. Escape, then match as a substring.
 */
export function textFrom(value: string): RegExp {
  return new RegExp(value.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&"));
}

/**
 * An artifact string as `Prose` puts it on the page.
 *
 * Every emitter here writes markdown, and `Prose` renders it — so `**material
 * separation**` reaches the DOM as three nodes and a `getByText` on the raw
 * artifact string matches nothing. That is not the page being wrong; it is the
 * assertion comparing source to output.
 *
 * Mirrors `Blocks.tsx`'s split exactly: a link keeps its label and drops its
 * href, and bold, emphasis and code spans keep their contents. Kept beside
 * `textFrom` because they answer the same question — what does this artifact
 * string look like once a component has had it — and both exist because the
 * naive comparison fails against output that is correct.
 */
export function asRendered(value: string): string {
  return value
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1");
}


/**
 * A render wrapper supplying the wallet providers.
 *
 * `Nav` carries the connect button, and wagmi's hooks throw outside a
 * `WagmiProvider` rather than returning a disconnected state — which is the
 * right behaviour for a library whose misuse is otherwise silent. In the app
 * the provider is at the root of `layout.tsx`, so a component tree without one
 * is a test artefact, not a state a visitor can reach.
 *
 * Use as `render(<Nav />, { wrapper: WithWallet })`.
 */
export function WithWallet({ children }: { children: React.ReactNode }) {
  return <WalletProvider>{children}</WalletProvider>;
}

/**
 * A wallet that is already connected, over a chain that answers what you say.
 *
 * `WithWallet` supplies the production config, whose only connector is
 * `injected()`. jsdom has nothing to inject, so every test using it renders the
 * disconnected branch and **no test in this app has ever reached a connected
 * state** — the escrow console's countdown, its disabled reasons, its job
 * reading and its revert decoding were all unreachable.
 *
 * wagmi ships `mock` for this. `defaultConnected` skips the connect handshake,
 * and a `custom` transport answers `eth_call` from a table rather than a
 * network, so a test can state "this job expires in an hour" or "this call
 * reverts with 0x8e78f0cb" and assert what the page does about it.
 *
 * Deliberately not a prop on `WalletProvider`: the production component keeps
 * its hard config import, and this seam exists only where tests can see it.
 */
export interface ConnectedWallet {
  /** The wallet the page believes is connected. */
  address?: `0x${string}`;
  chainId?: number;
  /** `eth_call` answers by function selector, as raw return data. */
  calls?: Record<string, `0x${string}`>;
  /** Thrown from `eth_sendTransaction`, the way a revert reaches wagmi. */
  sendError?: Error;
}

/** anvil's first account, and the address the recorded runs used. */
export const RECORDED_CLIENT = "0x0c501EE1924bfb91a028DB4BcD68f4861B0Ff6eE" as const;

export function withConnectedWallet(options: ConnectedWallet = {}) {
  const {
    address = RECORDED_CLIENT,
    chainId = 56,
    calls = {},
    sendError,
  } = options;

  const transport = custom({
    async request({ method, params }: { method: string; params?: unknown }) {
      switch (method) {
        case "eth_chainId":
          return `0x${chainId.toString(16)}`;
        case "eth_accounts":
        case "eth_requestAccounts":
          return [address];
        case "eth_blockNumber":
          return "0x1";
        case "eth_call": {
          const data = String((params as [{ data?: string }])[0]?.data ?? "");
          const answer = calls[data.slice(0, 10).toLowerCase()];
          // An unstubbed read returns empty rather than throwing: the console
          // treats a short answer as "no such job", which is a state worth
          // being able to render on purpose.
          return answer ?? "0x";
        }
        case "eth_estimateGas":
          return "0x5208";
        case "eth_sendTransaction":
          if (sendError) throw sendError;
          return `0x${"11".repeat(32)}`;
        case "eth_getTransactionReceipt":
          return null;
        default:
          return null;
      }
    },
  });

  // `lib/wagmi.ts` declares `Register.config = typeof config`, which makes the
  // app's own config the only one assignable to `WagmiProvider`. That is the
  // right trade for production — every `useReadContract` gets the app's chains
  // inferred — and it means a test config has to be cast. Cast once, here,
  // rather than at each use.
  // The mock connector's provider does not use the transport below — it makes
  // real HTTP calls to the chain's own RPC URL. Left alone, clicking a write
  // button in a test reaches bsc-dataseed over the internet: slow, flaky, and
  // not something a unit suite should be able to do at all. Pointed at a dead
  // local port so a write fails immediately and locally, which is also the
  // state worth asserting — a call that never reached a chain must not be
  // reported as a revert.
  const dead = { default: { http: ["http://127.0.0.1:1"] } } as const;
  const chains = [
    { ...bsc, rpcUrls: dead },
    { ...bscTestnet, rpcUrls: dead },
  ] as unknown as typeof productionConfig["chains"];

  const raw = createConfig({
    // wagmi batches reads through Multicall3 by default, so a stubbed
    // `eth_call` never arrives — the transport sees one `aggregate3` to
    // 0xca11bde0… instead of the call the test wrote. Off here so a stub
    // answers the question it was written for.
    batch: { multicall: false },
    chains,
    connectors: [mock({ accounts: [address], features: { defaultConnected: true } })],
    transports: { [bsc.id]: transport, [bscTestnet.id]: transport },
  });

  // `defaultConnected` makes the connector willing, not the store connected —
  // wagmi only reaches a connected state when something calls `connect`, and in
  // the app that something is a click on the nav. Doing it here is what the
  // click stands in for; the promise settles before the first `findBy*`.
  const connected = connect(raw, { connector: raw.connectors[0]! });

  const config = raw as unknown as typeof productionConfig;

  return function Connected({ children }: { children: React.ReactNode }) {
    // Retries turn one stubbed refusal into several seconds of waiting.
    const [client] = useState(
      () => new QueryClient({ defaultOptions: { queries: { retry: false } } }),
    );
    void connected;
    return (
      <WagmiProvider config={config}>
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      </WagmiProvider>
    );
  };
}

/** `getJob`'s answer, with one word overridden — the clock, usually. */
export function jobWordsWith(
  words: readonly string[],
  overrides: Record<number, bigint>,
): `0x${string}` {
  const patched = [...words];
  for (const [index, value] of Object.entries(overrides)) {
    patched[Number(index)] = `0x${value.toString(16).padStart(64, "0")}`;
  }
  return `0x${patched.map((w) => w.slice(2)).join("")}` as `0x${string}`;
}

/** A uint256 as `eth_call` return data. */
export const asWord = (value: bigint): `0x${string}` =>
  `0x${value.toString(16).padStart(64, "0")}` as `0x${string}`;
