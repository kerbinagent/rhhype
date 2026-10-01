# Equity opening-session persistence comparison

Frozen `8f4d802`; 1 October 2026, 13:25:00–13:40:00 UTC (09:25–09:40 ET).
AAPL, AMZN, NVDA and TSLA perpetuals on Core/RH; independent $100-per-leg
branches, $600 prefunding each. Fresh metadata verified active unit contracts,
positive index/mark prices, zero Standard fees and no forced reduce-only mode.
Same-symbol derivative and USDG/USDC equivalence remain conditional.

| Branch | Attempts | Paired closes | Failed-hedge rescues | Cash after fees | Capital + stress net |
|---|---:|---:|---:|---:|---:|
| Immediate | 6 | 2 | 4 | −$0.385427 | −$0.684613873 |
| Two-second confirmation | 0 | 0 | 0 | $0 | $0 |

All six immediate closes lost cash. The two TSLA paired trades reached the
60-second hold deadline and lost $0.058719 and $0.077478. Four NVDA/AAPL/AMZN
attempts filled only one leg before the other exceeded its 10 bp entry limit;
rescue closes lost $0.017320, $0.078260, $0.138600 and $0.015050. No inventory
remained. A preliminary chat update called all six paired; this table and the
independent trade addendum correct that classification.

Both branches had 14 positive forecasts. Confirmation rejected all 14.
The immediate arm entered six, had four cooldown rejections and three
admission-window rejections; the remaining forecast did not yield an entry.
There were 28,733 below-5-bp excursion gates and 105 failed forecasts per arm.
This session supports a filtering effect, but demonstrates no profitable
confirmed equity strategy and is not pooled with crypto results.

The full 900.034-second endpoint completed: one feed connection per venue,
94,780 messages, 46,902,083 ingress bytes, 3,638 retained records and 317,384
compressed raw bytes. Eight terminal invalidations; no runtime errors.
Independent audit passed all 16 actual paper fills, retained depth, delays,
first eligible source-advanced books, past-only references, lots and wallets.
The addendum separately rebuilt exact per-leg cash, capital and funding-hour
exclusions. Full idle books/wire messages are not retained. No actual orders.
