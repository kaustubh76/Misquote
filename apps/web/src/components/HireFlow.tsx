"use client";

/**
 * The Hire button, and the round trip it performs on chain.
 *
 * This replaces a card headed *"There is no Hire button on this site"*. That
 * refusal was correct about the facts and wrong about the conclusion: the
 * keystore really does enforce only the expiry, and the right response is to
 * grant a key that is bounded by the one cap the chain honours and to **say
 * which caps are missing at the moment of signing** — not to withhold the
 * product. A button that over-renders authority is the misquote. A button that
 * states its own limits is the thing this repository is arguing for.
 *
 * ## What actually happens
 *
 *   1. A fresh secp256k1 keypair is generated **in this browser**. The private
 *      half never leaves it and is never transmitted; only the public half is
 *      an argument to the transaction.
 *   2. `registerKey(keyId, validator, metadata, publicKey, expiry)` on the
 *      keyStoreController, paying `getRegistrationFeeInWei()` read live.
 *   3. `isValidKey(owner, keyId)` is read back until it answers `true`. That
 *      read is the proof — not the receipt, which only says the call did not
 *      revert.
 *   4. `revokeKey(owner, keyId)` on the keyStore — a *different contract*, per
 *      the ABI note in `lib/sessionKeys.ts` — and `isValidKey` returns to
 *      `false`.
 *
 * Every step shows its hash. The recorded chapel proofs elsewhere on this page
 * show the same four facts; the difference is that these ones happened to the
 * reader.
 */
import { useEffect, useMemo, useState } from "react";
import { formatEther, type Address, type Hex } from "viem";
import { generatePrivateKey, privateKeyToAccount } from "viem/accounts";
import {
  useAccount,
  useReadContract,
  useSwitchChain,
  useWaitForTransactionReceipt,
  useWriteContract,
} from "wagmi";
import { bsc } from "wagmi/chains";
import { Button } from "@/components/Button";
import { Card, CardHeader } from "@/components/Card";
import { Pill } from "@/components/Pill";
import {
  CONTROLLER_ABI,
  KEYSTORE_ABI,
  NO_VALIDATOR,
  capsEnforced,
  deploymentFor,
  keyId as deriveKeyId,
  shortHex,
} from "@/lib/sessionKeys";

/** One hour. Short on purpose: the expiry is the only cap the chain enforces. */
const GRANT_SECONDS = 60n * 60n;

function TxLink({ hash, explorer }: { hash: Hex; explorer: string }) {
  return (
    <a
      href={`${explorer}/tx/${hash}`}
      target="_blank"
      rel="noreferrer"
      className="font-mono text-xs break-all"
    >
      {shortHex(hash, 10, 8)} ↗
    </a>
  );
}

/**
 * Which agent the reader picked, from `?agent=`.
 *
 * Read in an effect rather than at render, for the reason `lib/scenario.ts`
 * gives about `?scenario=`: the export is static and prerendered, so reading
 * `location` during render produces HTML that disagrees with the client.
 */
function useChosenAgent(): string | null {
  const [slug, setSlug] = useState<string | null>(null);
  useEffect(() => {
    const value = new URLSearchParams(window.location.search).get("agent");
    setSlug(value && /^[a-z0-9-]{1,32}$/.test(value) ? value : null);
  }, []);
  return slug;
}

export function HireFlow() {
  const agent = useChosenAgent();
  const { address, chainId, isConnected } = useAccount();
  const { switchChain } = useSwitchChain();
  const deployment = deploymentFor(chainId);

  // Generated once per mount, not per render: a new keypair on every render
  // would change `keyId` between the write and the read-back, and the read
  // would then report `false` for a key that was granted perfectly well.
  const [session, setSession] = useState<{ publicKey: Hex; keyId: Hex } | null>(null);
  useEffect(() => {
    const account = privateKeyToAccount(generatePrivateKey());
    setSession({ publicKey: account.publicKey, keyId: deriveKeyId(account.publicKey) });
  }, []);

  const fee = useReadContract({
    abi: CONTROLLER_ABI,
    address: deployment?.keyStoreController,
    functionName: "getRegistrationFeeInWei",
    query: { enabled: Boolean(deployment) },
  });

  const valid = useReadContract({
    abi: KEYSTORE_ABI,
    address: deployment?.keyStore,
    functionName: "isValidKey",
    args: address && session ? [address, session.keyId] : undefined,
    query: {
      enabled: Boolean(deployment && address && session),
      // The grant is mined before the node serving this read necessarily has
      // it. Polling is what turns "the receipt says success" into "the chain
      // agrees the key is valid", which are different claims.
      refetchInterval: 4_000,
    },
  });

  const grant = useWriteContract();
  const revoke = useWriteContract();
  const grantReceipt = useWaitForTransactionReceipt({ hash: grant.data });
  const revokeReceipt = useWaitForTransactionReceipt({ hash: revoke.data });

  const expiry = useMemo(() => BigInt(Math.floor(Date.now() / 1000)) + GRANT_SECONDS, []);
  const isValid = valid.data === true;
  const enforced = capsEnforced(NO_VALIDATOR);

  if (!isConnected || !address) {
    return (
      <Card>
        <CardHeader title="Hire an agent" eyebrow="one transaction, on chain" />
        <p className="mt-2 mb-4 max-w-[58ch] text-sm text-dim">
          Connect a wallet to grant a session key. The key is generated in your
          browser, bounded by an expiry the contract enforces, and revocable by
          you at any time.
        </p>
        <p className="mb-0 text-xs text-faint">
          Use the Connect button in the header.
        </p>
      </Card>
    );
  }

  if (!deployment) {
    return (
      <Card>
        <CardHeader title="Hire an agent" aside={<Pill tone="fail">Wrong network</Pill>} />
        <p className="mt-2 mb-4 max-w-[58ch] text-sm text-dim">
          This keystore is deployed on BNB Smart Chain and its testnet. There is
          no deployment on the chain your wallet is connected to, so nothing here
          can be read or signed.
        </p>
        <Button onClick={() => switchChain({ chainId: bsc.id })}>
          Switch to BNB Smart Chain
        </Button>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader
        title={agent ? `Hire ${agent.charAt(0).toUpperCase()}${agent.slice(1)}` : "Hire an agent"}
        eyebrow={`${deployment.name} · one transaction`}
        aside={isValid ? <Pill tone="pass">Key live</Pill> : <Pill tone="none">No key</Pill>}
      />

      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
        <dt className="text-faint">Registration fee</dt>
        <dd className="tabular m-0">
          {fee.data !== undefined ? `${formatEther(fee.data)} BNB` : "reading…"}
        </dd>
        <dt className="text-faint">Expires</dt>
        <dd className="tabular m-0">
          {new Date(Number(expiry) * 1000).toLocaleTimeString()} — one hour
        </dd>
        <dt className="text-faint">Key id</dt>
        <dd className="m-0 font-mono">{session ? shortHex(session.keyId, 10, 8) : "…"}</dd>
      </dl>

      {/* The refusal this page used to be, reduced to the one sentence that was
          load-bearing and placed where it changes a decision: beside the button,
          before the signature, rather than instead of the product. */}
      {/* Naming the agent in the heading without saying this would be the
          misquote: the reader picked Grid and the transaction does not know it.
          `registerKey` takes a validator and metadata, and this grant carries
          neither, so nothing on chain ties the key to an agent or a pool. The
          choice is real and it lives in this page, not in the calldata. */}
      {agent && (
        <p className="mt-3 mb-0 text-xs text-faint">
          You chose {agent}. The key below is not bound to it — the keystore
          records an owner and an expiry, not an agent.
        </p>
      )}

      {!enforced && (
        <p className="mt-4 mb-0 border-l-2 border-warn-line bg-warn-bg py-2 pl-3 text-xs text-dim">
          <strong className="text-ink">The chain enforces the expiry and the
          revoke, and nothing else.</strong>{" "}
          The allowlist and the spend cap live in a validator module that is not
          deployed here — this grant carries <span className="font-mono">validator
          0x0</span>, so treat it as a key that expires, not as a key that is
          confined.
        </p>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <Button
          onClick={() =>
            session &&
            fee.data !== undefined &&
            grant.writeContract({
              abi: CONTROLLER_ABI,
              address: deployment.keyStoreController,
              functionName: "registerKey",
              args: [
                session.keyId,
                NO_VALIDATOR as Address,
                "0x",
                session.publicKey,
                Number(expiry),
              ],
              value: fee.data,
            })
          }
        >
          {grant.isPending
            ? "Check your wallet…"
            : grantReceipt.isLoading
              ? "Granting…"
              : "Grant a session key"}
        </Button>

        <Button
          tone="secondary"
          onClick={() =>
            session &&
            revoke.writeContract({
              abi: KEYSTORE_ABI,
              address: deployment.keyStore,
              functionName: "revokeKey",
              args: [address, session.keyId],
            })
          }
        >
          {revoke.isPending
            ? "Check your wallet…"
            : revokeReceipt.isLoading
              ? "Revoking…"
              : "Revoke it"}
        </Button>
      </div>

      {(grant.data || revoke.data || grant.error || revoke.error) && (
        <dl className="mt-5 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 border-t border-line pt-4 text-xs">
          {grant.data && (
            <>
              <dt className="text-faint">Grant</dt>
              <dd className="m-0">
                <TxLink hash={grant.data} explorer={deployment.explorer} />
                {grantReceipt.isSuccess && " · mined"}
              </dd>
            </>
          )}
          {revoke.data && (
            <>
              <dt className="text-faint">Revoke</dt>
              <dd className="m-0">
                <TxLink hash={revoke.data} explorer={deployment.explorer} />
                {revokeReceipt.isSuccess && " · mined"}
              </dd>
            </>
          )}
          <dt className="text-faint">isValidKey</dt>
          <dd className="m-0 font-mono">
            {valid.isLoading ? "reading…" : String(valid.data ?? false)}
          </dd>
          {/* A rejected signature is a decision, not a fault, and it is by far
              the most common outcome here. It gets one line, not a stack. */}
          {(grant.error || revoke.error) && (
            <>
              <dt className="text-faint">Last error</dt>
              <dd className="m-0 text-bad">
                {(grant.error ?? revoke.error)?.message.split("\n")[0]}
              </dd>
            </>
          )}
        </dl>
      )}
    </Card>
  );
}
