/**
 * Wallet configuration, and the reasons it is this small.
 *
 * ## Injected only, for now
 *
 * `injected()` covers MetaMask, Rabby, Trust and every other EIP-1193 wallet a
 * desktop visitor already has, and it needs **no project id and no environment
 * variable**. WalletConnect would add mobile and would also add a `projectId`
 * that has to be provisioned, kept out of git, and baked into a static export
 * at build time — which is the exact shape of problem `lib/api.ts` exists to
 * avoid for the API base. It is a deliberate later step, not an oversight.
 *
 * ## Transports are the public endpoints, and that is a downgrade the app states
 *
 * `http()` with no URL uses the chain's default public RPC. Those are rate
 * limited and occasionally wrong about very recent blocks. Every read this app
 * performs is a keystore view — `isValidKey`, `getKeys`, the registration fee —
 * where a stale answer is visible as a stale answer rather than dangerous. The
 * writes go through the *wallet's* own provider, not through these, so a
 * throttled public endpoint cannot cost anyone a transaction.
 *
 * ## Both chains, no default beyond what the wallet says
 *
 * `bsc` first in the tuple makes it the fallback for `useChainId()` before a
 * wallet connects, which matches where the product is meant to run. But nothing
 * here switches a user's chain on its own: `deploymentFor()` returns null for
 * an unsupported chain and the UI asks, because silently switching networks
 * under someone is how a wallet loses a user's trust.
 */
import { createConfig, http } from "wagmi";
import { bsc, bscTestnet } from "wagmi/chains";
import { injected } from "wagmi/connectors";

export const config = createConfig({
  chains: [bsc, bscTestnet],
  connectors: [injected()],
  transports: {
    [bsc.id]: http(),
    [bscTestnet.id]: http(),
  },
  // The export is static and prerendered. Without this, wagmi touches
  // `localStorage` during the server render and the build fails.
  ssr: true,
});

declare module "wagmi" {
  interface Register {
    config: typeof config;
  }
}
