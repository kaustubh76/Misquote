"use client";

/**
 * Connect, disconnect, and say which chain you are on.
 *
 * ## It must render its label before JavaScript runs
 *
 * `scripts/check-pages.mjs` loads every route with JavaScript disabled and
 * asserts a body-text floor. A connect button that renders `null` until an
 * effect settles would vanish from that pass, and — worse for a real visitor —
 * the header would reflow the moment hydration completed. So the disconnected
 * state *is* the server-rendered state: the label is in the static HTML and the
 * button is simply inert until React attaches. `CompareTray.tsx:3-18` makes the
 * same argument for the same reason.
 *
 * ## Why `mounted` still exists
 *
 * wagmi reads the wallet during hydration, so the first client render can
 * disagree with the server's HTML about whether an account exists. Rendering
 * the connected state only after mount keeps the two in step; React error #418
 * is a hydration text mismatch and the browser gate treats one as a failure.
 */
import { useEffect, useState } from "react";
import { formatUnits } from "viem";
import { useAccount, useBalance, useConnect, useDisconnect, useSwitchChain } from "wagmi";
import { bsc } from "wagmi/chains";
import { deploymentFor, shortHex } from "@/lib/sessionKeys";

export function ConnectButton() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const { address, chainId, isConnected } = useAccount();
  const { connect, connectors, isPending } = useConnect();
  const { disconnect } = useDisconnect();
  const { switchChain } = useSwitchChain();
  const { data: balance } = useBalance({ address });

  const injected = connectors[0];
  const deployment = deploymentFor(chainId);

  // The pre-hydration and disconnected states are the same markup on purpose —
  // see the note above. `disabled` rather than a different element, so the
  // button does not change size when React attaches.
  if (!mounted || !isConnected || !address) {
    return (
      <button
        type="button"
        onClick={() => injected && connect({ connector: injected })}
        disabled={!mounted || isPending}
        className="rounded-full border border-brand-line bg-brand-bg px-4 py-1.5 font-mono text-xs text-brand-ink transition-colors hover:bg-brand disabled:opacity-60"
      >
        {/* "Connect" at 390px, where the nav band is about one link wide and
            every pixel this takes is a route the reader cannot see. The full
            label is in the static HTML either way — the narrow one is hidden
            with CSS rather than swapped in by JavaScript, so the no-JS pass
            still reads the whole word. */}
        {isPending ? (
          "Check your wallet…"
        ) : (
          <>
            <span className="hidden sm:inline">Connect wallet</span>
            <span className="sm:hidden">Connect</span>
          </>
        )}
      </button>
    );
  }

  return (
    <div className="flex items-center gap-2">
      {/* An unsupported chain is named, not silently tolerated. Every read
          below would return nothing useful against a chain with no keystore,
          and "0 keys" is indistinguishable from "wrong network" unless this
          says which happened. */}
      {!deployment ? (
        <button
          type="button"
          onClick={() => switchChain({ chainId: bsc.id })}
          className="rounded-full border border-bad-line bg-bad-bg px-3 py-1.5 font-mono text-xs text-ink"
        >
          Switch to BNB Chain
        </button>
      ) : (
        <span
          className="rounded-full border border-line px-2.5 py-1 font-mono text-[0.7rem] text-dim"
          title={deployment.name}
        >
          {deployment.chainId === 56 ? "mainnet" : "testnet"}
        </span>
      )}

      <button
        type="button"
        onClick={() => disconnect()}
        className="tabular rounded-full border border-line bg-glass px-3 py-1.5 font-mono text-xs text-ink transition-colors hover:border-line-strong"
        title={`${address} — click to disconnect`}
      >
        {shortHex(address)}
        {balance && (
          <span className="ml-2 hidden text-dim sm:inline">
            {Number(formatUnits(balance.value, balance.decimals)).toFixed(3)}{" "}
            {balance.symbol}
          </span>
        )}
      </button>
    </div>
  );
}
