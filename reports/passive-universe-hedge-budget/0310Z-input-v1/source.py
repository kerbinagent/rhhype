#!/usr/bin/env python3
"""Offline optimistic hedge-cost budgets for an unchanged-book RH maker cycle."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import datetime as dt
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / 'reports/passive-universe-screen/20260930T0310Z'
METHOD = ROOT / 'research/passive-universe-hedge-budget-method.md'
BUDGETS = [100, 250, 500, 1000]
TARGET = Decimal('.10')
STRESS = Decimal('.0005')
OUTPUT_CAP = 2_000_000


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def d(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('nonfinite_input')
    return result


def derive(quote, score):
    row = {'asset': quote['asset'], 'round': quote['round'], 'budget': score['budget'],
           'valid': score['valid']}
    if not score['valid']:
        return row | {'reason': score['reason']}
    q, bid, ask = map(d, (score['quantity'], score['rh_bid'], score['rh_ask']))
    if q <= 0 or bid <= 0 or ask <= bid:
        raise ValueError('invalid_original_rh_cycle')
    opening, spread = q * bid, q * (ask - bid)
    if (opening != d(score['rh_buy_notional']) or q * ask != d(score['rh_sell_notional'])
            or spread != d(score['rh_spread_capture'])):
        raise ValueError('saved_rh_arithmetic_does_not_reconcile')
    minimum_stress = opening * STRESS
    fee, hedge_impact, original_stress = map(d, (score['modeled_fill_fees'],
                                                 score['hl_roundtrip_spread_impact'],
                                                 score['stress_allowance']))
    if fee < 0 or hedge_impact > 0 or original_stress < minimum_stress:
        raise ValueError('optimistic_condition_not_an_upper_budget')
    original = d(score['after_target_stress'])
    if original != spread + hedge_impact - fee - TARGET - original_stress:
        raise ValueError('original_stressed_margin_does_not_reconcile')
    optimistic = spread - TARGET - minimum_stress
    retained = optimistic - fee
    if retained < original or optimistic < retained:
        raise ValueError('upper_budget_ordering_failure')
    return row | {
        'quantity': str(q), 'rh_bid': str(bid), 'rh_ask': str(ask),
        'rh_opening_notional': str(opening), 'rh_spread_capture': str(spread),
        'rh_spread_bps_on_opening': str(spread / opening * 10000),
        'minimum_required_spread_bps': str((TARGET / opening + STRESS) * 10000),
        'target': str(TARGET), 'minimum_stress': str(minimum_stress),
        'zero_fees_zero_hedge_spread_budget': str(optimistic),
        'positive_optimistic_budget': optimistic > 0,
        'original_modeled_fill_fees': str(fee),
        'observed_fees_retained_zero_hedge_spread_budget': str(retained),
        'original_stressed_margin': str(original),
        'optimistic_minus_original': str(optimistic - original),
        'original_hl_roundtrip_spread_impact': str(hedge_impact),
        'original_stress_allowance': str(original_stress),
    }


def median(values):
    return str(statistics.median(values)) if values else None


def summarize(rows, universe):
    valid = [r for r in rows if r['valid']]
    by = defaultdict(list)
    for r in valid:
        by[(r['asset'], r['budget'])].append(r)
    coverage = {p['asset']: len(by[(p['asset'], 1000)]) for p in universe['selected']}
    assets, sizes = [], []
    for p in universe['selected']:
        for budget in BUDGETS:
            selected = by[(p['asset'], budget)]
            values = [d(r['zero_fees_zero_hedge_spread_budget']) for r in selected]
            fees = [d(r['observed_fees_retained_zero_hedge_spread_budget']) for r in selected]
            assets.append({'asset': p['asset'], 'budget': budget,
                           'valid_rounds': len(selected), 'missing_rounds': 5 - len(selected),
                           'valid_1000_rounds': coverage[p['asset']],
                           'eligible_from_1000_coverage': coverage[p['asset']] >= 3,
                           'min_24h_volume': p['min_24h_volume'],
                           'positive_observations': sum(v > 0 for v in values),
                           'maximum_optimistic_budget': str(max(values)) if values else None,
                           'median_optimistic_budget': median(values),
                           'median_observed_fees_retained_budget': median(fees)})
    for budget in BUDGETS:
        selected = [r for r in valid if r['budget'] == budget]
        values = [d(r['zero_fees_zero_hedge_spread_budget']) for r in selected]
        eligible = [r for r in assets if r['budget'] == budget and r['eligible_from_1000_coverage']]
        eligible.sort(key=lambda r: (-d(r['median_optimistic_budget']), -d(r['min_24h_volume']), r['asset']))
        sizes.append({'budget': budget, 'total_observations': sum(r['budget'] == budget for r in rows),
                      'valid_observations': len(selected),
                      'missing_observations': sum(r['budget'] == budget and not r['valid'] for r in rows),
                      'positive_observations': sum(v > 0 for v in values),
                      'maximum_optimistic_budget': str(max(values)) if values else None,
                      'median_observation_optimistic_budget': median(values),
                      'eligible_assets': len(eligible),
                      'positive_eligible_medians': sum(d(r['median_optimistic_budget']) > 0 for r in eligible),
                      'best_eligible_median': eligible[0] if eligible else None,
                      'eligible_asset_medians_ranked': eligible})
    return {'interpretation': 'optimistic_necessary_static_margin_condition_not_future_profit_bound',
            'total_observations': len(rows), 'valid_observations': len(valid),
            'excluded_observations': len(rows) - len(valid),
            'excluded_reasons': dict(Counter(r['reason'] for r in rows if not r['valid'])),
            'universe_route_denominator': universe['denominator'],
            'retained_assets': len(universe['selected']), 'by_size': sizes, 'asset_size_medians': assets}


def run(source, out):
    paths = [source / n for n in ('quotes.jsonl', 'universe.json', 'summary.json', 'manifest.json', 'freeze.json')]
    paths += [METHOD, Path(__file__), ROOT / 'tests/test_passive_universe_hedge_budget.py']
    hashes = {str(p.resolve()): sha(p) for p in paths}
    freeze = json.loads((source / 'freeze.json').read_bytes())
    for name, expected in freeze['hashes'].items():
        if sha(source / name) != expected:
            raise ValueError('frozen_screen_input_changed_' + name)
    quote_bytes = (source / 'quotes.jsonl').read_bytes()
    if len(quote_bytes) > 16_000_000:
        raise ValueError('input_size_cap')
    quotes = [json.loads(line) for line in quote_bytes.splitlines()]
    original = json.loads((source / 'summary.json').read_bytes())
    universe = json.loads((source / 'universe.json').read_bytes())
    manifest = json.loads((source / 'manifest.json').read_bytes())
    if manifest['status'] != 'completed' or manifest['rounds_completed'] != 5:
        raise ValueError('requires_completed_five_round_screen')
    expected = {(p['asset'], n, b) for p in universe['selected'] for n in range(5) for b in BUDGETS}
    rows = [derive(q, s) for q in quotes for s in q['scores']]
    if len(rows) != len(expected) or {(r['asset'], r['round'], r['budget']) for r in rows} != expected:
        raise ValueError('original_denominator_mismatch')
    summary = summarize(rows, universe)
    if (summary['valid_observations'] != original['valid_size_observations']
            or summary['total_observations'] != original['total_size_observations']
            or summary['excluded_reasons'] != original['missing_size_observations']):
        raise ValueError('validity_denominator_mismatch')
    original_coverage = {r['asset']:r['valid_1000_rounds'] for r in original['coverage']}
    if any(r['valid_1000_rounds'] != original_coverage[r['asset']] for r in summary['asset_size_medians']):
        raise ValueError('coverage_mismatch')
    out.mkdir(parents=True, exist_ok=False)
    outputs = {'observations.jsonl': b''.join((json.dumps(r, separators=(',', ':')) + '\n').encode() for r in rows),
               'summary.json': (json.dumps(summary, indent=2) + '\n').encode(),
               'method.md': METHOD.read_bytes(), 'source.py': Path(__file__).read_bytes(),
               'tests.py': (ROOT / 'tests/test_passive_universe_hedge_budget.py').read_bytes()}
    if sum(map(len, outputs.values())) > OUTPUT_CAP - 100_000:
        raise ValueError('derived_output_cap')
    for name, raw in outputs.items():
        (out / name).write_bytes(raw)
    if any(sha(Path(p)) != expected for p,expected in hashes.items()):
        raise ValueError('read_input_changed_during_analysis')
    saved = {'generated_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'input_hashes': hashes,
             'frozen_screen_hashes_verified': True, 'read_inputs_unchanged': True,
             'original_validity_and_coverage_preserved': True,
             'output_hashes': {name: sha(out / name) for name in outputs},
             'network_calls': 0, 'derived_file_cap_bytes': OUTPUT_CAP}
    (out / 'manifest.json').write_text(json.dumps(saved, indent=2) + '\n')
    print(json.dumps({'out':str(out), 'sizes':[{k:v for k,v in s.items() if k!='eligible_asset_medians_ranked'} for s in summary['by_size']]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=DEFAULT_INPUT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    run(args.input, args.out)


if __name__ == '__main__':
    main()
