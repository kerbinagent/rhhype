# Prepared symmetric maker replay

**Implementation status, 29 September 2026, 22:10 UTC:** committed in
56a1776, with 37 focused sell-model, execution, guard and coordinator tests
passing. This is preparation for a future public-data experiment. No
symmetric protocol or capture has been launched, and no market P&L exists
for this implementation. The running original buy pilot remains separate.

The [new coordinator](../scripts/analyze_rh_maker_symmetric.py) runs
**192 independent branches**: buy/sell directions, Standard/Premium RH
accounts, BTC/ETH/NVDA/XAG, $100/$250/$500/$1,000, and adaptive/persistence/
fixed-best quotes. $1,000 Standard adaptive is the primary panel in each
direction; smaller sizes, tiers and alternative quote rules are separate
sensitivities, never additive returns.

The [sell-side method](rh-maker-sell-followup.md) mirrors the completed
four-leg economics and public-flow handling. The buy quote model is the
original control. Both future execution branches use the
[late-flow guard](rh-maker-late-flow-audit.md): retired activated quotes
with remaining quantity retain bounded evidence throughout the study.
Delayed qualifying source-time flow marks the old episode execution unknown,
even after reconnect or a new quote. No cash or inventory is invented;
known completed contributions exclude such episodes. The original buy
pilot's engine is unchanged and receives an independent read-only audit.

## Launch gate and bounds

A separate protocol JSON must be written before a new capture starts.
`build_protocol(frozen_at, method_path, metadata_dir)` returns a reviewable
object with required source hashes, method hash and normalized metadata
hash. Normalized metadata also authenticates its market plan and raw public
responses. The coordinator refuses a capture predating the protocol, a
changed source/metadata file, or a timeline other than thirty-minute
calibration and twenty-minute holdout. It does not collect data or send
orders. Test-injected events are explicitly labeled in output.

The raw collector cap remains 384 MB. The symmetric derived budget is
192 MB compressed audit plus 64 MB summaries, at most **640 MB raw plus
derived for one run**. This is larger than the original 512 MB study cap
because it doubles the independent directions. Output must be a new
folder. No repeating launcher or unbounded accumulation is enabled here.

After a future protocol is frozen and its separate capture has stopped:

```bash
.venv/bin/python scripts/analyze_rh_maker_symmetric.py \
  --protocol reports/FUTURE-STUDY/protocol.json \
  --capture data/raw/rh-small-maker/FUTURE-CAPTURE \
  --out data/derived/FUTURE-STUDY
```

These placeholder paths intentionally refer to no current experiment. The
original pilot is not eligible input under a newly written protocol.
Public-flow attribution remains counterfactual; USDG/USDC combined values
assume parity, and unavailable funding, residual inventory and uncertainty
stay visible. Passing synthetic tests establishes implementation checks,
not a profitable strategy or a production promotion.
