# Deploying the Studio agent

Two routes, and they do not support the same claim. **Render** runs the agent as
an ordinary Node service and gives it a public URL. **`bag deploy --provider
aws`** deploys it through the vendor's own CLI, which is the native-citizenship
proof the BNB track is about. Only the second one lets anyone say "deployed via
the Agent Studio CLI", and the ledger says which of the two has happened.

## Render — the route taken when AWS stalled

`render.yaml` declares `misquote-agent` beside the existing API. `rootDir` is
the project root rather than `app/agent`, because the runtime resolves
`.studio/` relative to the project root and pointing at the inner package would
leave the wallet directory outside the build context.

**No secret file is needed, which is not where this started.** The first
version of this section said the keystore had to be uploaded as a Render secret
file and called that the one untested step. The runtime has a better door:
`WALLET_KEYSTORE_JSON` takes the keystore as a JSON string, derives its filename
from the `address` field inside it, writes it to disk and deletes the variable
from its own environment afterwards.

Rehearsed against a clean `git archive` checkout with no `.studio/` directory in
it at all — install, build, and the agent served its A2A card on the port it was
given. So the whole deployment is four dashboard fields and no file:

| Variable | Value |
|---|---|
| `WALLET_KEYSTORE_JSON` | the contents of `.studio/wallets/0xdEaF…5bd7.json`, whole |
| `WALLET_PASSWORD` | from `.studio/.env.local` |
| `PIEVERSE_LLM_API_KEY` | from `.studio/.env.local` |
| `DELIVERABLE_S3_*` | only once the bucket exists |

The three environment variables beside it — `WALLET_PASSWORD`,
`PIEVERSE_LLM_API_KEY`, and the two `DELIVERABLE_S3_*` values — are declared
`sync: false`, so the blueprint names them and holds none of them.

---

## Deploying to AWS

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

## The two IAM identities, and why they are separate

The Studio wants a **deliverable key** that is not the deploy profile, and that
separation is worth keeping rather than collapsing. The deploy provisions
infrastructure once; the running agent writes an object per job, forever, from a
container. Giving the second one the first one's rights is how a compromised
runtime becomes a compromised account.

**1. The deploy profile** — `aws configure --profile misquote`, used once by
`bag deploy --provider aws`. Needs ECR, `bedrock-agentcore`,
`bedrock-agentcore-control`, Secrets Manager, STS, and — the widest, worth
scoping to a path — `iam:CreateRole` and `iam:PassRole`, because the starter
toolkit provisions the runtime's execution role.

**2. The deliverable key** — `DELIVERABLE_S3_ACCESS_KEY_ID` and
`DELIVERABLE_S3_SECRET_ACCESS_KEY` in `.studio/.env.local`. This one should do
nothing but write to one bucket:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:PutObject", "s3:GetObject"],
    "Resource": "arn:aws:s3:::misquote-agent-deliverables/*"
  }]
}
```

No `s3:ListBucket`, no `s3:DeleteObject`, no wildcard resource. If the container
leaks the key, what leaks is the ability to write into one bucket.

### The bucket, and the part to get right

`misquote-agent-deliverables` in `us-east-1`. A buyer fetches the deliverable by
URL, so the object has to be readable — but **do not make the bucket public**.
Prefer presigned URLs; if the agent publishes a plain `https://` object URL on
chain, scope a read policy to that one prefix rather than enabling public access
at the bucket level. A world-readable bucket is the single easiest thing to get
wrong here and the reason IPFS was the safer default.

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
