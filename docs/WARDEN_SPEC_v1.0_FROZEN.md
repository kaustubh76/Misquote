   # THE WARDEN — Specification & Replay Methodology (FROZEN v1.0)

**Project:** Studio Terminal v3 · BNB Smart Money Era hackathon
**Component:** Rebalancing category flagship agent + Personal Quote Engine replay core
**Status:** FROZEN. Changes after this point require a line-item answer to the requirements matrix.
**Hard dates:** Warden live on BSC mainnet **Aug 15** (zero slack — LP tearsheet window closes Aug 22). Freeze Sep 5. Submit Sep 9.
**Deployment:** own infra (latency-sensitive loop). ERC-8004 identity + ERC-8183 interface registered on-chain manually.

**Sources (hygiene per review):**
- Cartea, Jaimungal & Penalva, *Algorithmic and High-Frequency Trading* — reservation price p. 188; market making pp. 246–261 (adverse selection 261, at-the-touch 254, optimising volume 257); microprice p. 46; MLE p. 298.
- Avellaneda & Stoikov (2008), *High-frequency trading in a limit order book*.
- Milionis, Moallemi, Roughgarden & Zhang (2022), *Automated Market Making and Loss-Versus-Rebalancing* (LVR).
- BNB Agent Studio: https://www.bnbchain.org/en/bnb-agent-studio · docs.bnbchain.org · studio.bnbchain.org/install
- PancakeSwap v3 = Uniswap v3 core math (tick spacing per fee tier; NonfungiblePositionManager).

---

## 1. The isomorphism (the thesis)

A concentrated-liquidity position on [P_l, P_u] **is** a pair of limit orders:
as price rises through the range the position continuously sells the risk asset
(an ask ladder); as price falls it continuously buys (a bid ladder). Therefore the
Avellaneda–Stoikov market-making solution maps term-by-term onto v3 LP management:

| Avellaneda–Stoikov (book) | Warden (Pancake v3) |
|---|---|
| Reservation price r(s,q,t) | Range **center** (in tick space), inventory-skewed |
| Optimal half-spread δ* | Range **half-width** (in ticks) |
| Inventory penalty −qγσ²(T−t) | **Recenter trigger** when composition drifts |
| Fill intensity λ(δ)=A·e^(−κδ) | Fee-capture intensity vs. range width (κ fit from swap data) |
| Adverse selection (p. 261) | **LVR** — arbitrage flow is the informed flow |
| Quote pull on toxic flow | **Range withdrawal** on toxicity signal |

Everything below makes each row precise.

---

## 2. Notation & state

- P_t — pool price (token1 per token0); y_t = ln P_t (log-price); tick i = log_{1.0001}(P).
- q_t — inventory imbalance: q = (value of token0 held − target 50/50 value) / total position value, q ∈ [−1, 1].
- σ — volatility of y_t per √hour (estimation §5.1).
- γ — risk-aversion (user profile parameter, published; defaults §8).
- κ — fill-decay parameter of fee-capture intensity (estimation §5.2).
- T − t — remaining contract window (rolling; window length W per §7).
- L_h — Warden's (or replayed hypothetical) liquidity; L_pool — active pool liquidity at current tick.

## 3. The policy

### 3.1 Range center (reservation price)

In log-price space:

    r_t = y_t − q_t · γ · σ² · (T − t)                                   (1)

Center tick: c_t = round_to_spacing( r_t / ln(1.0001) ).
Intuition: holding excess token0 (q>0) shifts the range **down**, making the
position a keener seller of the excess — the A-S skew, verbatim.

### 3.2 Range half-width (optimal spread)

    δ*_t = ½ · [ γσ²(T−t) + (2/γ)·ln(1 + γ/κ) ]                          (2)

Half-width in ticks: w_t = max( w_min, round_to_spacing( δ*_t / ln(1.0001) ) ).
Term one is inventory-risk compensation (volatility ↑ → widen). Term two is the
fill-rate trade-off (rich fee flow near mid, κ large → tighten). w_min = 4 × tick
spacing of the pool's fee tier (floor against gas-churn on dust ranges).

Position each cycle: [c_t − w_t, c_t + w_t].

### 3.3 Recenter rule (inventory penalty, with hysteresis)

Recenter (burn → swap to target composition → mint) iff **all** of:

    R1  |c_target − c_current| ≥ θ · w_t                (drift beyond θ of half-width)
    R2  E[fee gain over remaining window] − (gas + slippage + MEV haircut) > 0
    R3  cooldown elapsed: t − t_last_rebalance ≥ τ_cool
    R4  toxicity signal OFF (§3.4)

E[fee gain] in R2 uses the trailing fee-rate-per-unit-liquidity of the target
range (trailing window only — no forward estimate). This is the practical,
threshold form of the optimal-stopping structure (book pp. 122–130); the free
boundary is approximated by (θ, τ_cool) hysteresis. Stated as such — no
pretending it's the exact QVI solution.

### 3.4 Toxicity pull rule (adverse selection / microprice)

Signal, sampled every Δs seconds:

    g_t   = (P_cex − P_pool)/P_pool           — CEX–DEX gap (lead of informed flow)
    imb_t = z-score of signed swap-volume imbalance over trailing M swaps

    TOXIC iff  |g_t| > fee_tier + arb_cost_bps  for m consecutive samples,
           or  imb_t > z_pull

Action: withdraw range (burn to wallet), hold, re-enter when signal clears for
m_clear samples. Rationale: when the CEX leads by more than the round-trip arb
cost, the next pool flow is arbitrage — the literal informed trader of p. 261 —
and expected LVR rate exceeds expected fee rate. On-chain-only fallback (if CEX
feed down): pull on realized-LVR-rate spike (trailing LVR/hr > trailing fees/hr
for m samples).

---

## 4. LVR accounting (realized, model-free — settlement-grade)

We do **not** use the model formula ℓ = σ²P²|V''(P)|/2 for settlement (it's
model-dependent). We compute **realized LVR** from chain events only:

For each pool swap k while the position is in range, the position's holdings
change by (Δx_k, Δy_k) along the bonding curve. The rebalancing benchmark
executes the same Δx_k at the post-swap price P_k. Realized LVR increment:

    LVR_k = −( Δy_k + P_k · Δx_k )  ≥ 0                                   (3)

(The LP trades along the curve at prices stale relative to P_k; (3) is exactly
the arbitrageur's edge on that swap, position-pro-rated by L_h share.)

    LVR[0,T] = Σ_k LVR_k

### 4.1 The card / tearsheet metric

    NetFeeAPR = ( F − LVR[0,T] − Gas − RebalSlippage − MEVHaircut )
                / Capital / (T/8760h)                                     (4)

reported **vs. passive benchmark**: same initial width, never recentered, same
window (primary comparator), and vs. HODL 50/50 (secondary, labeled).
F = fee growth inside range × L_h share, straight from chain state.

### 4.2 The simple marketplace floor (bonded instrument)

    Floor: InRange% ≥ N over window W, AND F − Gas ≥ 0.

Binary, chain-checkable, no counterfactual. NetFeeAPR (4) is the honest
performance display; the floor is what settles.

---

## 5. Estimation (trailing-only; fits published in tearsheet appendix)

**5.1 σ:** EWMA of 1-minute log-returns of pool price, half-life 6h, scaled to
per-√hour. Trailing data only, computed at each decision timestamp.

**5.2 κ:** from trailing 7d of swap events, bucket swap-crossing depth δ (ticks
beyond mid) vs. frequency; fit ln(rate) = ln A − κδ by least squares (MLE-lite,
p. 298 spirit). Refit daily. If R² < 0.5, fall back to κ_default and label it.

**5.3 Gas & MEV haircut:** gas = trailing median (mint+burn+collect+swap) ×
current gas price. MEV haircut h = 10 bps of rebalanced notional (assumption A4,
conservative, fixed for the hackathon).

---

## 6. Replay engine (the Quote Engine core — WEEK-2 HARD DEPENDENCY)

Event-driven, no-look-ahead. Powers Showcase Mode AND connected-wallet quotes —
same code path, different input wallet.

**Inputs:** pool Swap/Mint/Burn event log with block timestamps; wallet's
historical position (or showcase position); parameter set Θ.

**Loop:**
```
state ← position at window start; estimators ← trailing data at t0 only
for each decision time t on grid G (every block, min 3s):
    update estimators with events ≤ t                    # no-look-ahead
    compute r_t (1), w_t (2); evaluate R1–R4 (§3.3–3.4)
    if rebalance: charge gas(t) + slippage + h; move range
    accrue: fees pro-rata by L_h/(L_pool+L_h); LVR per (3); in-range time
output: NetFeeAPR (4), InRange%, rebalance count, vs. passive run (same engine,
        policy = never recenter)
```

**Assumptions (published, one click from every quote):**
- A1: L_h ≤ ε·L_pool with ε = 1% → historical swap prices treated as unperturbed.
- A2: fees pro-rated by liquidity share; no JIT-liquidity competition modeled.
- A3: decisions use trailing data only (enforced; see T3 below).
- A4: MEV haircut 10 bps per rebalance; gas at historical block prices.
- A5: quotes are **P25–P75 ranges** over K ≥ 20 rolling sub-windows and a ±25%
  perturbation of (γ, κ) — never point estimates. Display: "would have captured
  $150–$210 net."

**Look-ahead guards (tests):**
- T1: shuffle-future test — replacing all events > t with synthetic noise must
  not change any decision at t (bitwise).
- T2: fee conservation — Σ credited fees ≤ pool fee growth × max share.
- T3: estimator timestamps — every estimator input event timestamp ≤ decision t
  (assert in code, not in review).
- T4: passive run through the same engine must reproduce direct chain-state
  computation of the passive position within 1 bp (engine self-consistency).

**Showcase wallets:** my own historical BSC positions (Mission Control lineage —
auditable, on brand) + one clearly LABELED synthetic borrower for the health
story. No strangers' wallets.

---

## 7. Live operation (mainnet Aug 15)

- Window W = 24h rolling for policy horizon; tearsheet LP week = Aug 15–22.
- Capital: small real capital (my own — "audit me"), size cap §8.
- Burn-in: ≥ 24h on testnet (Aug 13–14) with full loop + kill switch before
  mainnet funds.
- Kill switches: (a) Altana session revoke (one tx — caps subset per v3),
  (b) local hard-stop that burns position to wallet, (c) toxicity pull (§3.4).
- Monitoring: heartbeat + position/PnL alert (Mission Control alerting reused).

## 8. Parameters (defaults; every value appears in the published assumption sheet)

| Param | Default | Note |
|---|---|---|
| γ | 0.8 (conservative profile) | user-selectable {0.4, 0.8, 1.5}, published |
| ε (replay liq. cap) | 1% | A1 |
| θ (recenter drift) | 0.5 | fraction of half-width |
| τ_cool | 2h | anti-churn |
| w_min | 4 × tick spacing | anti-dust |
| h (MEV haircut) | 10 bps | A4 |
| z_pull / m / m_clear | 2.5 / 3 / 10 | toxicity rule |
| Δs (signal sample) | 5s | |
| K (replay windows) | ≥ 20 | A5 |
| Position cap (live) | small fixed cap, my capital | risk control |
| Max rebalances/day | 8 | gas discipline |

## 9. Reuse manifest (so D2 is a port, not greenfield)

| Source | Component | Warden use |
|---|---|---|
| PolyLambda | A-S quoting core (reservation price, spread calc, inventory tracking) | §3.1–3.2 verbatim, re-parameterized to ticks |
| PolyLambda | σ EWMA + intensity-fit utilities | §5.1–5.2 |
| PolyLambda | sim harness event loop | replay engine skeleton (§6) |
| Mission Control | BSC RPC layer, wallet/signing, nonce mgmt, tx retry | live execution |
| Mission Control | event indexer scaffolding, monitoring/alerting | indexer + §7 monitoring |
| Mission Control | test harness patterns | T1–T4 |
| Vault Analyzer | metric/report generation | tearsheet + assumption sheet output |
| **New code** | v3 position manager (NPM mint/burn/collect), tick-math adapter, LVR accountant (3), recenter policy (R1–R4), toxicity signal | the actual D2–D3 work |

## 10. Acceptance (Warden is "done" for Gate 1 when)

1. Testnet: full loop (quote → mint → monitor → recenter → collect → burn) runs
   24h unattended, kill switches verified.
2. Mainnet Aug 15: position live, capital capped, heartbeat green.
3. Replay engine passes T1–T4 on one real pool's 30-day history.
4. One showcase quote renders end-to-end as a P25–P75 range with the assumption
   sheet linked.
5. Every number on the card traces to a chain query or a published assumption.

---
*Anything not in this document is out of scope for the Warden. The itch goes to
Sunday review.*