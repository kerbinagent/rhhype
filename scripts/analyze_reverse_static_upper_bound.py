"""Upper bound for the reverse static best-quote route at inherited quantity.

Consumes only a completed fixed-anchor report. No raw scan, engine, queue,
fill, funding cash, new sizing, capture nomination, or network operation.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / 'reports/passive-rare-spread/0252Z-fixed-1s-v1'
METHOD = ROOT / 'research/reverse-static-upper-bound-method.md'
TESTS = ROOT / 'tests/test_reverse_static_upper_bound.py'
ASSETS = ('BTC', 'ETH', 'NVDA', 'XAG')
SIZES = (100, 250, 500, 1000)
ROWS = 48_000
INPUT_CAP = 16_000_000
OUTPUT_CAP = 2_000_000
RAW_SHA = 'c92c269e3bc3bb345beeaf834ad55d0a97601339b4506e36a9397287f8407bb6'
PARENT_FILES = {'manifest.json', 'freeze.json', 'summary.json', 'metadata.json',
                'observations.csv', 'timing.csv', 'readout.md', 'source.py', 'tests.py', 'method.md'}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def rational(value):
    if isinstance(value, Fraction):
        return value
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError('nonfinite value')
    return Fraction(number)


def text(value):
    """Exact compact decimal when finite, otherwise an exact rational string."""
    den = value.denominator
    for prime in (2, 5):
        while den % prime == 0:
            den //= prime
    if den != 1:
        return str(value)
    with localcontext() as context:
        context.prec = len(str(abs(value.numerator))) + len(str(value.denominator)) + 8
        result = format(Decimal(value.numerator) / Decimal(value.denominator), 'f')
    return result.rstrip('0').rstrip('.') if '.' in result else result


def upper_bound(quantity, rh_bid, rh_ask, hl_sell, hl_buy, maker_rate):
    q, bid, ask, S, B, h = map(rational,
                               (quantity, rh_bid, rh_ask, hl_sell, hl_buy, maker_rate))
    if not (q > 0 and 0 < bid < ask and 0 < S < B and 0 <= h < 1):
        raise ValueError('invalid static bound inputs')
    return (1 - h) * B - (1 + h) * S - q * (ask - bid) - Fraction(1, 10) - Fraction(5, 10_000) * S


def index_of(k, asset, budget):
    if type(k) is not int or not 0 <= k < 3000 or asset not in ASSETS or budget not in SIZES:
        raise ValueError('parent row identity outside fixed universe')
    return k * 16 + ASSETS.index(asset) * 4 + SIZES.index(budget)


def boolean(value):
    if value not in ('True', 'False'):
        raise ValueError('invalid CSV boolean')
    return value == 'True'


def rates(metadata):
    result = {}
    for asset in ASSETS:
        rh = metadata['markets']['rh_lighter'][asset]
        hl = metadata['markets']['hyperliquid'][asset]
        maker = rational(hl['maker_fee_bps'])
        expected = rational('1.5' if asset in ('BTC', 'ETH') else '.300')
        if maker != expected or rational(rh['taker_fee_bps']) != 0:
            raise ValueError('unexpected frozen reverse fee schedule')
        if rational(rh['contract_multiplier']) != 1 or rational(rh['quote_multiplier']) != 1:
            raise ValueError('unexpected RH units')
        if asset in ('NVDA', 'XAG') and (hl['growth_mode'] != 'enabled'
                                        or rational(hl['deployer_fee_scale']) != 1):
            raise ValueError('unexpected growth fee context')
        result[asset] = maker / 10_000
    return result


def inventory(parent):
    entries = list(parent.iterdir())
    names = {p.name for p in entries}
    if (any(p.is_symlink() or not p.is_file() for p in entries)
            or names not in (PARENT_FILES, PARENT_FILES | {'verification.json'})):
        raise ValueError('parent publication file inventory differs')
    if sum(p.stat().st_size for p in entries) > INPUT_CAP:
        raise ValueError('parent input cap exceeded')
    return {p.name: sha(p) for p in entries}


def verify_publication(parent, hashes):
    manifest = json.loads((parent / 'manifest.json').read_text())
    freeze = json.loads((parent / 'freeze.json').read_text())
    summary = json.loads((parent / 'summary.json').read_text())
    metadata = json.loads((parent / 'metadata.json').read_text())
    expected_outputs = {name: value for name, value in hashes.items()
                        if name not in ('manifest.json', 'verification.json')}
    if (manifest.get('input_hashes_unchanged') is not True or manifest.get('raw_scan_count') != 1
            or manifest.get('network_calls') != 0 or manifest.get('derived_cap_bytes') != INPUT_CAP
            or manifest.get('output_hashes') != expected_outputs
            or manifest.get('input_hashes') != freeze.get('input_hashes')
            or freeze.get('anchors') != 3000 or freeze.get('expected_rows') != ROWS
            or freeze.get('bounds', {}).get('derived_bytes') != INPUT_CAP
            or summary.get('possible') != ROWS
            or summary.get('interpretation') != 'retrospective_static_quote_feasibility_not_fill_or_profit'):
        raise ValueError('parent incomplete/provenance mismatch')
    frozen_at = datetime.fromisoformat(freeze['frozen_at'])
    completed_at = datetime.fromisoformat(manifest['completed_at'])
    if frozen_at.tzinfo is None or completed_at.tzinfo is None or completed_at < frozen_at:
        raise ValueError('parent freeze/completion clock invalid')
    claims = freeze['input_hashes']
    def claimed(suffix):
        matching = [v for k, v in claims.items() if k.endswith(suffix)]
        if len(matching) != 1:
            raise ValueError('missing or ambiguous parent hash claim')
        return matching[0]
    for name, suffix in (('source.py', '/scripts/analyze_passive_rare_spread.py'),
                         ('tests.py', '/tests/test_passive_rare_spread.py'),
                         ('method.md', '/research/passive-rare-spread-fixed-anchor-method.md'),
                         ('metadata.json', '/metadata/normalized.json')):
        if hashes[name] != claimed(suffix):
            raise ValueError('parent frozen copy mismatch')
    end = summary.get('canonical_terminal') or {}
    if (end.get('type') != 'end' or end.get('truncated') is not False
            or end.get('raw_sha_verified') is not True or end.get('reason') != 'duration_limit'
            or end.get('raw_gzip_sha256') != RAW_SHA
            or claimed('/frames.jsonl.gz') != RAW_SHA
            or end.get('manifest_sha256') != claimed('/20260930T0252Z/manifest.json')
            or end.get('adapter_sha256') != claimed('/scripts/rh_maker_events.py')
            or end.get('book_decoder_sha256') != claimed('/scripts/maker_book_archive.py')
            or end.get('counts', {}).get('decoded_records') != 124019
            or end.get('stopped_ns', 0) - end.get('started_ns', 0) < 3000 * 1_000_000_000):
        raise ValueError('parent terminal not complete and verified')
    return summary, metadata, freeze


def validate_counts(counters, summary):
    expected = {}
    for route in summary['asset_budgets']:
        route_key = (route['asset'], int(route['budget']))
        if route_key in expected or route_key[0] not in ASSETS or route_key[1] not in SIZES:
            raise ValueError('parent summary route identity')
        expected[route_key] = route
        strata = {s['stratum']: s for s in route['strata']}
        if len(route['strata']) != 5 or set(strata) != set(range(5)):
            raise ValueError('parent stratum identity')
        total = Counter()
        exclusion = Counter()
        for stratum in range(5):
            state = counters[(*route_key, stratum)]
            target = strata[stratum]
            if (state['possible'] != 600 or any(state[field] != target[field]
                 for field in ('possible', 'valid', 'positive'))
                    or dict(state['exclusions']) != target['exclusions']):
                raise ValueError('parent CSV/summary stratum counters disagree')
            for field in ('possible', 'valid', 'positive'):
                total[field] += state[field]
            exclusion.update(state['exclusions'])
        if any(total[field] != route[field] for field in ('possible', 'valid', 'positive')) or dict(exclusion) != route['exclusions']:
            raise ValueError('parent route counters disagree')
    if len(expected) != 16 or any(sum(c[field] for c in counters.values()) != summary[field]
                                  for field in ('possible', 'valid', 'positive')):
        raise ValueError('parent total denominator counters disagree')


def evaluate_rows(rows, metadata, summary):
    maker_rates = rates(metadata)
    bounds = [None] * ROWS
    statuses = ['?'] * ROWS
    counters = defaultdict(lambda: {'possible': 0, 'valid': 0, 'positive': 0, 'exclusions': Counter()})
    group_values = defaultdict(list)
    count = 0
    for row in rows:
        count += 1
        if count > ROWS:
            raise ValueError('parent row count exceeded')
        k, budget = int(row['k']), int(row['budget'])
        asset = row['asset']
        index = index_of(k, asset, budget)
        if statuses[index] != '?':
            raise ValueError('duplicate parent row identity')
        state = counters[(asset, budget, k // 600)]
        state['possible'] += 1
        if not boolean(row['valid']):
            if not row.get('reason'):
                raise ValueError('parent invalid row lacks reason')
            statuses[index] = 'X'
            state['exclusions'][row['reason']] += 1
            continue
        state['valid'] += 1
        positive = boolean(row['positive'])
        if positive != (rational(row['net']) > 0):
            raise ValueError('parent forward sign flag inconsistent')
        state['positive'] += positive
        q, bid, ask = map(rational, (row['quantity'], row['rh_bid'], row['rh_ask']))
        rh = metadata['markets']['rh_lighter'][asset]
        hl = metadata['markets']['hyperliquid'][asset]
        a, b = rational(rh['size_step']), rational(hl['size_step'])
        den = math.lcm(a.denominator, b.denominator)
        common = Fraction(math.lcm(int(a * den), int(b * den)), den)
        if common <= 0 or q != (Fraction(budget) / ask / common).__floor__() * common:
            raise ValueError('quantity differs from inherited parent policy')
        value = upper_bound(q, bid, ask, row['hl_sell'], row['hl_buy'], maker_rates[asset])
        bounds[index] = text(value)
        statuses[index] = 'N' if value <= 0 else 'P'
        group_values[(asset, budget, k // 600)].append(value)
    if count != ROWS or '?' in statuses:
        raise ValueError('parent full 48000 row identities required')
    validate_counts(counters, summary)
    groups = []
    for asset in ASSETS:
        for budget in SIZES:
            for stratum in range(5):
                key = (asset, budget, stratum)
                values = group_values[key]
                state = counters[key]
                groups.append({'asset': asset, 'budget_usd': budget, 'stratum': stratum,
                    'possible': state['possible'], 'evaluated': len(values),
                    'parent_invalid_unadjudicated': state['possible'] - len(values),
                    'parent_exclusions': dict(state['exclusions']),
                    'upper_bound_nonpositive': sum(v <= 0 for v in values),
                    'upper_bound_positive_inconclusive': sum(v > 0 for v in values),
                    'minimum_upper_bound': text(min(values)) if values else None,
                    'median_upper_bound': text(statistics.median(values)) if values else None,
                    'maximum_upper_bound': text(max(values)) if values else None})
    return {'possible': ROWS, 'evaluated': statuses.count('N') + statuses.count('P'),
            'parent_invalid_unadjudicated': statuses.count('X'),
            'upper_bound_nonpositive': statuses.count('N'),
            'upper_bound_positive_inconclusive': statuses.count('P'),
            'row_order': 'index=k*16+asset_index*4+budget_index; k=0..2999',
            'assets_in_index_order': list(ASSETS), 'budgets_in_index_order': list(SIZES),
            'row_status_48000': ''.join(statuses), 'row_upper_bound_48000': bounds,
            'status_legend': {'N': 'nonpositive static upper bound at inherited q',
                             'P': 'positive upper bound; inconclusive',
                             'X': 'parent invalid; reverse unadjudicated'},
            'groups': groups,
            'maker_fee_bps': {asset: text(value * 10_000) for asset, value in maker_rates.items()}}


def validate_timing(path):
    seen = set()
    with path.open(newline='') as f:
        for row in csv.DictReader(f):
            key = (int(row['k']), row['asset'])
            if not 0 <= key[0] < 3000 or key[1] not in ASSETS or key in seen:
                raise ValueError('parent timing identity')
            seen.add(key)
    if len(seen) != 12_000:
        raise ValueError('parent full timing denominator required')


def unchanged(parent, expected, dependencies):
    if inventory(parent) != expected or any(sha(path) != value for path, value in dependencies.items()):
        raise ValueError('parent/helper changed during bound diagnostic')


def publish(out, files, cap=OUTPUT_CAP):
    if out.exists() or out.is_symlink():
        raise ValueError('output must be new')
    total = sum(len(body) for body in files.values())
    if total > cap:
        raise ValueError('2 MB aggregate output cap exceeded')
    staging = out.with_name(out.name + '.building')
    staging.mkdir(parents=True, exist_ok=False)
    for name, body in files.items():
        (staging / name).write_bytes(body)
    staging.rename(out)


def run(parent, out):
    if parent.resolve() != PARENT.resolve() or parent.name.endswith('.building'):
        raise ValueError('only completed fixed-anchor parent allowed')
    if out.resolve().parent != (ROOT / 'reports/passive-rare-spread-reverse-bound').resolve():
        raise ValueError('output must be new reverse-bound report child')
    if out.exists() or out.with_name(out.name + '.building').exists():
        raise ValueError('output must be new')
    dependencies = {Path(__file__): sha(__file__), METHOD: sha(METHOD), TESTS: sha(TESTS)}
    hashes = inventory(parent)
    summary, metadata, parent_freeze = verify_publication(parent, hashes)
    validate_timing(parent / 'timing.csv')
    started = datetime.now(timezone.utc).isoformat()
    with (parent / 'observations.csv').open(newline='') as f:
        result = evaluate_rows(csv.DictReader(f), metadata, summary)
    unchanged(parent, hashes, dependencies)
    result.update(schema='rh-reverse-static-best-quote-upper-bound-v1',
        created_at=datetime.now(timezone.utc).isoformat(), parent=str(parent.resolve()),
        post_capture_diagnostic=True, raw_scans=0, network_calls=0, fills_inferred=False,
        profit_bound_including_funding=False, reverse_entry_budget_validated=False,
        quantity_policy='inherited forward quantity; no reverse resizing or budget equivalence claim',
        positive_upper_bound_is_inconclusive=True, wider_quotes_and_dynamic_prices_excluded=True,
        supplemental_attestation_sha256=hashes.get('verification.json'),
        supplemental_attestation_authenticated_by_original_manifest=False,
        parent_completed_input_sha256=hashes, source_sha256={str(p): v for p, v in dependencies.items()})
    freeze = {'frozen_at': started, 'parent_input_sha256': hashes,
              'source_sha256': {str(p): v for p, v in dependencies.items()},
              'parent_implementation_freeze_time': parent_freeze['frozen_at'],
              'input_cap_bytes': INPUT_CAP, 'aggregate_output_cap_bytes': OUTPUT_CAP,
              'post_capture': True, 'raw_scans': 0, 'network_calls': 0}
    report = '\n'.join(['# Reverse static best-quote route: upper bound', '',
        f"All {ROWS} identities retained; evaluated {result['evaluated']}; parent-invalid reverse-unadjudicated {result['parent_invalid_unadjudicated']}.",
        f"Nonpositive upper bounds: {result['upper_bound_nonpositive']}; positive, inconclusive upper bounds: {result['upper_bound_positive_inconclusive']}.", '',
        'At inherited q only: HL best bid/ask makers and Standard RH taker hedge. Positive U supplies no candidate or fill evidence. Funding credits, changed q, wider maker quotes and dynamic prices are excluded. Forward-invalid rows may still be reverse-feasible and remain unadjudicated.', '',
        'Proof and limits: method.md. All 48,000 row statuses/bounds and 80 asset/budget/stratum groups: analysis.json. No independent-sample or summed-PnL inference.', ''])
    files = {'analysis.json': (json.dumps(result, separators=(',', ':'), allow_nan=False) + '\n').encode(),
             'freeze.json': (json.dumps(freeze, indent=2) + '\n').encode(), 'REPORT.md': report.encode(),
             'source.py': Path(__file__).read_bytes(), 'method.md': METHOD.read_bytes(), 'tests.py': TESTS.read_bytes()}
    output_hashes = {name: hashlib.sha256(body).hexdigest() for name, body in files.items()}
    files['manifest.json'] = (json.dumps({'completed_at': datetime.now(timezone.utc).isoformat(),
        'input_and_source_hashes_unchanged': True, 'parent_input_sha256': hashes,
        'source_sha256': {str(p): v for p, v in dependencies.items()}, 'output_sha256': output_hashes,
        'aggregate_output_cap_bytes': OUTPUT_CAP, 'raw_scans': 0, 'network_calls': 0}, indent=2) + '\n').encode()
    unchanged(parent, hashes, dependencies)
    publish(out, files)
    print(json.dumps({'out': str(out), 'bytes': sum(map(len, files.values())),
                      'possible': ROWS, 'evaluated': result['evaluated'],
                      'nonpositive': result['upper_bound_nonpositive'],
                      'positive_inconclusive': result['upper_bound_positive_inconclusive']}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent', type=Path, default=PARENT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    run(args.parent, args.out)


if __name__ == '__main__':
    main()
