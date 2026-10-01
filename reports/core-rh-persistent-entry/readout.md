# Persistent versus immediate short-term basis entries

Frozen `10b40be`, 1 October 2026, 13:11:28–13:25:16 UTC. Ten predefined crypto
assets, independent $100-per-leg portfolios with $600 prefunding each.
The two-second arm additionally required three recent synchronized basis
observations spanning two seconds, each showing at least a 5 bp excursion.
Order delays stayed 400 ms; entry limits 10 bp; exits requested at a 1 bp
profit mark or 60 seconds. No actual trades.

| Policy | Paired closes | Cash wins | Cash after trading fees | After capital + 5 bp stress |
|---|---:|---:|---:|---:|
| Immediate control | 6 | 4 | −$0.037566 | −$0.336584779 |
| Two-second confirmation | 1 | 1 | +$0.045840 | −$0.004105144 |

All seven closes had both legs filled; zero rescues, unresolved positions,
partial fills or below-minimum exits. The confirmed trade was RH-long /
Core-short VVV, held about 0.8 seconds after entry. Its cash gain survives
the $0.0000002613 modeled capital charge, but not the separate stress allowance.
The control's VVV and NEAR gains also survived the stress by $0.001890929 and
$0.014537634. These individual positive paper outcomes coexist with the
control portfolio's overall loss.

Both branches saw 34 positive forecasts. Confirmation rejected 29; five
passed, of which one entered, three were blocked by cooldown and one by
the common storage admission stop. The control entered six, rejected 18
by cooldown and ten after admissions closed. This single shared VVV event
is not an independent replication: the confirmed arm entered about three
seconds later and captured $0.006 less than the control. The total comparison
does not establish stable expected profit or a causal benefit from waiting.

## Endpoint and independent checks

The predefined ingress limit stopped collection after 828.058 seconds,
not the planned 900: 128,001,096 received bytes / 224,256 messages. Both feeds
used one continuous connection. Twenty terminal invalidations were retained;
all positions were already flat. The 500,000-byte soft storage threshold
had already stopped admissions. No runtime, limit or rule was extended.

A separate auditor adapted only the original 900-second endpoint assertion
to verify this mandatory cap stop. It passed all **28 fills**: retained depth,
first eligible book, source advance, 400 ms delay, lot sizes, price limits,
past-only median, confirmed sample provenance, cash and venue wallets.
An additional independent computation reproduced capital from each leg's
entry value and actual holding interval and verified no hourly funding
boundary. Sources, raw data and metadata are hashed; 720,373 compressed raw
bytes remain. The full wire stream and idle full-depth books were not retained.

Zero Standard fees and USDG/USDC parity are conditional assumptions. Public
quote replay does not verify private execution or settlement-asset conversion.
The positive confirmed cash result is a lead for replication, not a proven
profitable strategy; one trade is insufficient to estimate a win rate.
