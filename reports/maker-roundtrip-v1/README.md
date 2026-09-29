# Prospective maker round-trip diagnostic

Rules and filtered BTC/ETH market metadata were committed before the public
19:39:04–19:46:04 UTC capture. The capture, including copied rules and metadata,
occupies 23,658,122 bytes, below its 25 MB cap. Raw archive remains local under
`data/raw/maker-capture/20260929T1939Z`; derived cases and source hashes are
committed. See [the prospective report](../../research/maker-roundtrip-prospective.md).

## Decision

No maker strategy is promoted. At the primary 1s arrival setting, 32 hypothetical
full-flow cases produced 14 complete quoted hedge/unwind paths, all negative
after four fees. Nine lacked hedge depth/freshness, nine lacked exit depth/freshness.
These 18 outcomes remain unknown; complete-case results do not estimate their
returns. Public trade flow cannot establish an actual maker fill or queue place.

On the 14 unchanged complete paths, eliminating every trading fee produces two
positive gross quotes, with a maximum of $0.052712. None reaches the user's
$0.10 target, and none clears the 5bp reserve. This fixed-path sensitivity is
not a simulation of different fee-tier latency or fills, and does not model
maker rebates. Controls share observations and must not be added as income.
See `fixed-path-fee-sensitivity.json` for all predeclared arrival settings.

## Reproduce

```bash
.venv/bin/python scripts/analyze_maker_roundtrip.py \
  --capture data/raw/maker-capture/20260929T1939Z \
  --out /tmp/rhhype-maker-roundtrip --design prospective
```

The 100ms hedge quote delay omits Lighter Standard's 300ms processing delay;
exit matching and private acknowledgements are also absent. This is an
optimistic conditional quote diagnostic, not account-compatible execution.
