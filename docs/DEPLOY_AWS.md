# Deploying the Studio agent to AWS

What is left, named by the tool that refuses to proceed without it. Nothing
here is guesswork: every line came from `bag deploy prepare` on the scaffold in
`studio/misquoterouter`, which reports **5 CRITICAL · 5 WARNING · 0 BLOCKED**.

## What the deployment actually is

Not a container. This scaffold's runtime is `"build": "CodeZip"` on `NODE_22`,
deployed to **Amazon Bedrock AgentCore** via `bedrock-agentcore-starter-toolkit`.
Docker is checked by `bag doctor` and passes, and it substitutes for nothing —
`bag deploy` accepts `bnb`, `aws` or `azure` and there is no local provider.

The wallet is injected from **your** Secrets Manager. `--provider bnb` is the
only combination that sends a key to the vendor, and it is not the one chosen.

## Blocking, and who can clear it

| # | Check | Needs |
|---|---|---|
| 1 | `aws_targets_populated` | a 12-digit AWS account id and a region, written into `agentcore/aws-targets.json`. **No AWS access required to write it.** |
| 2 | `storage_kind_not_deployable` | `bag config set storage.kind ipfs` — a deployed seller needs durable public storage, because the buyer fetches the deliverable by URL and a container's disk is ephemeral |
| 3 | `llm_provider_key_set` | `PIEVERSE_LLM_API_KEY` |
| 4 | `pieverse_key_hash` | `bag llm activate`, which needs the wallet funded |
| 5 | `runtime_secrets_injected` | the same key present in `.studio/.env.local`, from where it is handed to the deploy as the runtime secret bundle |

Warnings that become blockers in practice: the wallet holds **0 tBNB and 0 U**.
It needs ≥ 0.02 tBNB on bsc-testnet, and 1 U for one auto-topup chunk.

## The order that works

1. **Faucet** — [@bnbchain_official_bot](https://t.me/bnbchain_official_bot),
   message `I would like to get tBNB to my wallet 0xdEaF6a182ECfb667073a85f3f1C32499D5B53e29`,
   then the same for U. Free, and it also unblocks `bag erc8004 register` and
   the `bag erc8183` cross-check, neither of which needs AWS at all.
2. `bag llm activate` — clears CRITICAL 3, 4 and 5 together.
3. `bag config set storage.kind ipfs`, then set `STORAGE_API_URL` (and
   `STORAGE_API_KEY` for a hosted pinner) — clears CRITICAL 2.
4. Fill `agentcore/aws-targets.json` with the account id and region — clears
   CRITICAL 1. `us-east-1` is the region the CLI references.
5. `aws configure --profile misquote`, then `AWS_PROFILE=misquote bag deploy --provider aws`.

## AWS permissions

The starter toolkit provisions an execution role, so `iam:CreateRole` and
`iam:PassRole` are needed alongside the service calls — that is the widest
permission in the set and worth scoping to a dedicated path. Services touched:
**ECR** (image/artifact registry), **bedrock-agentcore** and
**bedrock-agentcore-control** (create and invoke the runtime),
**Secrets Manager** (the wallet bundle), **STS** (caller identity).

Check **Bedrock AgentCore is enabled on the account and available in the
region** before spending time on the rest. It is a recent service and is not on
by default everywhere.

## What is already done

`bag init --destination self`, the local keystore, the price clamp, the
dependency install, and a verified local run — the agent starts and serves its
A2A card at `/.well-known/agent-card.json`. Recorded in
`vetting/identity/studio-local-run.json`.
