# $100 short-term Core/RH paper experiment

Completed 2026-10-01 04:44:34–05:04:34 UTC. The primary $100-per-leg, ten-second branch closed **11 paired trades, zero wins, and −$0.183554 total modeled cash P&L**. The accounting and fill-evidence audit passed. No actual orders were sent.

## Fixed size and holding-period comparison

| Maximum per-leg notional | Maximum hold | Paired closes | Cash wins | Cash P&L | After capital and 5 bp stress |
|---:|---:|---:|---:|---:|---:|
| $100 | 10 s | 11 | 0 | $-0.183554 | $-0.731145 |
| $100 | 60 s | 10 | 0 | $-0.156949 | $-0.655045 |
| $100 | 300 s | 4 | 0 | $-0.048210 | $-0.247640 |
| $1000 | 10 s | 1 | 0 | $-0.066402 | $-0.565991 |
| $1000 | 60 s | 1 | 0 | $-0.066402 | $-0.565991 |
| $1000 | 300 s | 1 | 0 | $-0.066402 | $-0.565991 |

Each row is a separate counterfactual portfolio using the same feed; their observations overlap and must not be pooled as independent trades. In particular, each $1,000 branch took the same single early ETH trade and exited on the same take-profit signal. All positions finished flat; there were zero rescue closes, aborted attempts, unresolved positions, or exits below the published minimums.

Cash P&L includes price gains/losses, explicit Standard trading fees (zero), and settled funding (zero because every inventory interval stayed within one funding hour). The 5 bp allowance is an additional stress scenario, not an exchange fee. Primary capital opportunity cost totaled $0.00003146. All six rows are already negative without either extra deduction. USDG/USDC parity and public Standard account behavior remain conditional.

The notional label is a maximum for each leg, not the whole wallet. Each branch starts with six times that amount in collateral, split evenly between Core and RH, allows at most three concurrent pairs, and carries losses forward. The primary branch therefore used a $600 starting model portfolio.

## What the execution records show

For the primary branch, the opening spread worsened between signal and delayed fill in 10 of 11 trades; the median deterioration was $0.026716. The two primary take-profit requests showed roughly 1.1 cents of estimated profit at the decision, but their subsequent delayed fills ended at losses of $0.003312 and $0.011040. These observed changes support a timing problem in the quoted opportunity; they do not prove a venue-specific causal explanation or justify assuming faster fills.

The prospective rule used a trailing 120-second median Core/RH basis with a two-second embargo, at least 90 valid observations, and a 1 bp forecast hurdle. BTC, ETH and SOL were fixed in advance. Entry and exit orders used a 300 ms Standard processing assumption plus 100 ms network allowance, then waited for a new eligible source book. The 20-minute run had a 122-second warmup, a fixed admissions cutoff, a shared guard against crossing the next funding hour, and a 12-attempt cap per branch. Controls changed size and maximum hold only.

## Verification and limits

The [independent audit](audit.json) reconstructed all 112 recorded fills from their available depth, checked the lot grid, entry minimums and notional ceilings, verified the delayed source clocks, rebuilt every terminal leg and branch cash result, and reconciled each venue wallet. It also checked all source/plan/raw/metadata hashes and each past-only median reference. All 3,802 archived records were covered; the raw compressed archive is 359,641 bytes.

The full inbound feed was not retained, so first-eligible-book selection cannot be independently replayed from this archive. Public displayed liquidity is not a private execution acknowledgement, and no account-level funding or conversion statement exists. The results are a paper model, with actual P&L unknown. The six final invalidations occurred during connection shutdown after the run, not feed reconnections; both feeds stayed on their first connection with no transport errors.

Source and policy were frozen at ec3cb89 before capture; the audit code was committed at 2858afe before the endpoint. The later [execution diagnostic](execution-diagnostic.json) is descriptive and did not change the collector or rules. [Machine summary](summary.json) contains all branch gates and wallets.

**Decision:** reject this version as evidence of profitable short-term trading. Increasing the holding limit did not produce a positive cash branch in this sample. Retain its losses and continue investigating structurally different trade cycles; no claims of profitability follow from displayed take-profit marks.
