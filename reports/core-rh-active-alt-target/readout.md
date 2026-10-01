# PONS/CASHCAT: confirmed 1 bp versus 6 bp target

Frozen at `349dcb9`. Full 900.045-second public run on 1 October 2026,
14:41:11–14:56:11 UTC. Two independent $100-per-leg, $600-prefunded
portfolios; both use two-second confirmation and 60-second maximum hold.
Targets are 1 bp and 6 bp. No orders were submitted.

Both arms had zero entries, P&L or remaining obligations. Each evaluated
12,090 directions: 4,518 failed warmup, 96 failed clock/skew, and 7,240
had less than the required 5 bp basis excursion. The 1 bp arm rejected
227 forecasts and accepted nine, but all nine failed two-second confirmation.
The 6 bp arm rejected all 236 forecasts that reached that gate.

Unlike the sparse AI run, this cohort supplied enough observations for
forecast evaluation. It still produced no confirmed entries, so there is
no execution or profitability result. Transient positive forecasts are
not profits and cannot be assumed fillable after the 400 ms order delay.

The run retained 1,468 paired samples and four terminal disconnect records,
111,847 compressed bytes, 28,665 incoming messages and 14,305,270 ingress
bytes, with one continuous connection per venue. The independent audit
passed source/metadata/raw hashes, sample identities and unchanged wallets.
Admission, fill and closing checks had zero observations. Full idle wire
books were not retained, as declared before capture.

PONS/CASHCAT were selected exploratorily for higher archived trading
activity than AI. Same-symbol/unit-index compatibility, zero Standard fees,
USDG/USDC parity and modeled order latency remain conditional. No future
funding credit was assumed.
