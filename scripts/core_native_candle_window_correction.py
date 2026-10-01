"""Offline correction: remove only candles outside the frozen September window."""
import gzip
import hashlib
import json
from pathlib import Path
import core_native_candle_screen as base

ROOT = base.ROOT
PLAN = ROOT / 'reports/experiment-storage/core-native-candle-window-allocation-v1.json'
OUT = ROOT / 'reports/core-native-candle-window-correction'


def main():
    base.self_check()
    p = PLAN.read_bytes()
    plan = json.loads(p)
    for pin in plan['input_pins']:
        assert hashlib.sha256((ROOT / pin['path']).read_bytes()).hexdigest() == pin['sha256']
    original = json.loads((ROOT / plan['original_plan']).read_bytes())
    OUT.mkdir(exist_ok=True)
    assert not any(OUT.iterdir())
    outcomes, trimmed = [], []
    for market in original['universe']:
        asset = market['asset']
        row = {'asset': asset, 'status': 'unknown', 'actual_pnl': None}
        try:
            data = {}
            for kind in ('spot', 'perp'):
                path = ROOT / ('reports/core-eth-collateral-candles/' + kind + '.json.gz' if asset == 'ETH'
                               else 'reports/core-native-candle-screen/' + asset + '-' + kind + '.json.gz')
                obj = json.loads(gzip.decompress(path.read_bytes()))
                removed = [r['t'] for r in obj['c'] if not base.START * 1000 <= r['t'] < base.END * 1000]
                # Endpoint supplied one preceding day. Permit precisely that
                # observed transport shape, never future or in-window removal.
                assert removed == ([] if asset == 'ETH' else [(base.START - 86400) * 1000])
                obj['c'] = [r for r in obj['c'] if base.START * 1000 <= r['t'] < base.END * 1000]
                # Preserve original numeric lexemes by slicing raw JSON with
                # Decimal and serializing numeric fields as decimal strings.
                from decimal import Decimal
                exact = json.loads(gzip.decompress(path.read_bytes()), parse_float=Decimal)
                exact['c'] = [r for r in exact['c'] if base.START * 1000 <= r['t'] < base.END * 1000]
                data[kind] = json.dumps(exact, default=str)
                trimmed.append({'asset': asset, 'kind': kind, 'removed_timestamps': removed,
                                'input_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
            funding = gzip.decompress((ROOT / market['funding']).read_bytes())
            row.update(status='complete_candle_proxy', blocks=base.analyze(data, funding, market))
        except Exception as exc:
            row['error'] = type(exc).__name__ + ':' + str(exc)[:240]
        outcomes.append(row)
    result = {'actual_pnl': None, 'development_not_validation': True, 'funding_value_units_inferred': True,
              'current_lot_rules_not_verified_for_history': True, 'candles_not_executable': True,
              'no_margin_solvency_claim': True, 'full_month_overlaps_weekly_blocks': True,
              'outcomes': outcomes, 'trimmed': trimmed}
    b = (json.dumps(result, indent=2) + '\n').encode()
    assert len(b) <= 49152
    with (OUT / 'summary.json').open('xb') as f:
        f.write(b)
    terminal = {'status': 'completed_offline_window_correction', 'new_requests': 0,
                'unknown_assets': sum(x['status'] == 'unknown' for x in outcomes),
                'summary_sha256': hashlib.sha256(b).hexdigest(),
                'plan_sha256': hashlib.sha256(p).hexdigest(),
                'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with (OUT / 'terminal.json').open('x') as f:
        json.dump(terminal, f)
    print(json.dumps(terminal))
    for x in outcomes:
        print(x['asset'], [r.get('candle_residual_usdc') for r in x.get('blocks', [])], x.get('error'))


if __name__ == '__main__':
    main()
