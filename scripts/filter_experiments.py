#!/usr/bin/env python3
"""Frozen, retrospective entry-filter study over retained paper trade outcomes.

No counterfactual fills or exits are simulated. A filter only keeps or abstains
from observed attempts. The live monitor and its checkpoint are never changed.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / 'data/evidence/research-filter-sample.json.gz'
OUT = ROOT / 'reports/filter-experiments'
SETTLED = {'CLOSED', 'CLOSED_ESTIMATED', 'ABORTED'}
CLOSED = {'CLOSED', 'CLOSED_ESTIMATED'}
SHADOWS = ('shadow_baseline', 'cooldown', 'convergence', 'conservative', 'confirmed')
TOP_FIELDS = ('id', 'asset', 'pair_id', 'strategy', 'status', 'created_at',
              'opened_at', 'closed_at', 'settled_at', 'exit_reason', 'net_pnl_usd', 'price_pnl',
              'fees_usd', 'other_costs_usd', 'capital_costs_usd', 'funding_usd')
SIGNAL_FIELDS = ('route', 'buy', 'sell', 'quantity', 'net_edge_usd', 'opening_edge_usd',
                 'buy_value', 'sell_value', 'buy_fee_bps', 'sell_fee_bps',
                 'skew_ms', 'source_skew_ms', 'entry_policy')
LEG_FIELDS = ('venue', 'key', 'side', 'entry_result', 'quantity', 'entry_value',
              'exit_value', 'entry_time', 'exit_time', 'fees_usd', 'price_pnl',
              'entry_rejection_reason', 'entry_observation')


def utc(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def money(value, places=2):
    return f"-\u0024{abs(value):.{places}f}" if value < 0 else f"\u0024{value:.{places}f}"


def trim_trade(trade):
    result = {k: trade[k] for k in TOP_FIELDS if k in trade}
    result['signal'] = {k: trade['signal'][k] for k in SIGNAL_FIELDS if k in trade.get('signal', {})}
    result['legs'] = [{k: leg[k] for k in LEG_FIELDS if k in leg} for leg in trade['legs']]
    return result


def freeze(db_path, markets_path, destination):
    """Take one short read-only SQLite transaction and save bounded evidence."""
    db_path, markets_path, destination = map(Path, (db_path, markets_path, destination))
    db = sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        row = db.execute('SELECT payload,updated FROM engine_state WHERE id=1').fetchone()
        if row is None:
            raise ValueError('No engine checkpoint')
        state = json.loads(row[0])['engine']
        trades = [trim_trade(json.loads(row[0])) for row in
                  db.execute('SELECT payload FROM trades ORDER BY ts,id')]
        checkpoint = row[1]
    finally:
        db.close()
    markets = json.loads(markets_path.read_text())
    categories = {}
    for pair in markets['pairs']:
        hl, other = pair['hl'], pair['other']
        pair_id = f"{pair['asset']}|{hl['venue']}:{hl['market']}|{other['venue']}:{other['market']}"
        categories[pair_id] = pair.get('category')
    payload = {'schema_version': 1, 'source': str(db_path), 'checkpoint_at': checkpoint,
               'shadow_started_at': state.get('shadow_started_at'),
               'markets_updated_at': markets.get('updated_at'),
               'category_by_pair': categories,
               'ledgers': {k: state['ledgers'][k] for k in SHADOWS if k in state['ledgers']},
               'trades': trades}
    destination.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    with destination.open('wb') as stream:
        with gzip.GzipFile(fileobj=stream, mode='wb', mtime=0) as compressed:
            compressed.write(raw)
    if destination.stat().st_size > 2_000_000:
        raise ValueError('Frozen evidence exceeds the 2 MB budget')
    return {'path': str(destination), 'bytes': destination.stat().st_size,
            'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
            'checkpoint_at': checkpoint, 'retained_rows': len(trades)}


def load(path):
    with gzip.open(path, 'rt') as stream:
        return json.load(stream)


def class_of(trade, categories):
    category = categories.get(trade.get('pair_id'))
    if category == 'crypto':
        return 'crypto'
    if category == 'RWA/xyz':
        return 'rwa_xyz'
    # A missing current-market mapping is not evidence of a crypto listing.
    return 'unmapped'


def venue_of(trade):
    others = [leg['venue'] for leg in trade['legs'] if leg['venue'] != 'hyperliquid']
    return others[0] if len(others) == 1 else 'unknown'


def gross_cost_ratio(trade):
    s = trade['signal']
    gross = s['sell_value'] - s['buy_value']
    # The signal already subtracts its modeled roundtrip fees, extra cost, and
    # capital charge. Recover that complete opening cost without assuming a
    # particular monitor configuration in this offline script.
    modeled_cost = gross - s['net_edge_usd']
    return gross / modeled_cost if modeled_cost > 0 else math.inf


def settled(trades, strategy):
    return sorted((p for p in trades if p['strategy'] == strategy and p['status'] in SETTLED),
                  key=lambda p: (p['created_at'], p['id']))


def dedupe_attempts(rows, seconds=5.0):
    """Keep the first route attempt in each short signal burst."""
    last = {}
    kept = []
    for row in rows:
        route = row['signal']['route']
        stamp = row['created_at']
        if stamp - last.get(route, -math.inf) < seconds:
            continue
        kept.append(row)
        last[route] = stamp
    return kept


def outcome(rows):
    closed = [p for p in rows if p['status'] in CLOSED]
    paired = [p for p in closed if p.get('exit_reason') != 'entry_failure' and
              len(p['legs']) == 2 and all(l.get('entry_result') == 'filled' for l in p['legs'])]
    failures = [p for p in closed if p.get('exit_reason') == 'entry_failure']
    def total(field):
        return sum(p.get(field, 0) or 0 for p in closed)
    net = total('net_pnl_usd')
    return {'attempts': len(rows), 'closed': len(closed), 'aborted': len(rows) - len(closed),
            'paired_closes': len(paired), 'failed_hedges': len(failures),
            'wins': sum(p['net_pnl_usd'] > 0 for p in closed),
            'net_pnl_usd': net, 'net_per_attempt_usd': net / len(rows) if rows else None,
            'net_per_close_usd': net / len(closed) if closed else None,
            'price_pnl_usd': total('price_pnl'), 'fees_usd': total('fees_usd'),
            'other_costs_usd': total('other_costs_usd'),
            'capital_costs_usd': total('capital_costs_usd'), 'funding_usd': total('funding_usd'),
            'paired_net_pnl_usd': sum(p['net_pnl_usd'] for p in paired),
            'failed_hedge_net_pnl_usd': sum(p['net_pnl_usd'] for p in failures)}


def split_chronological(rows, share=.7):
    if not 0 < share < 1 or len(rows) < 2:
        raise ValueError('Need at least two attempts and a valid train fraction')
    cut = max(1, min(len(rows) - 1, int(len(rows) * share)))
    boundary = rows[cut]['created_at']
    # Final P&L is available only on settlement, which may follow close.
    # ABORTED attempts have no funding settlement and become known at close.
    def outcome_known_before(p):
        known_at = p.get('closed_at') if p['status'] == 'ABORTED' else p.get('settled_at')
        return known_at is not None and known_at < boundary
    train = [p for p in rows[:cut] if outcome_known_before(p)]
    return train, rows[cut:], boundary, cut - len(train)


def candidates():
    return {
        'net_edge_min_usd': [(str(x), lambda p, x=x: p['signal']['net_edge_usd'] >= x)
                             for x in (.1, .25, .5, .75)],
        'gross_to_cost_min': [(str(x), lambda p, x=x: gross_cost_ratio(p) >= x)
                              for x in (1.1, 1.25, 1.5, 2.0)],
        'receipt_skew_max_ms': [(str(x), lambda p, x=x: p['signal']['skew_ms'] <= x)
                                for x in (100, 250, 500)],
        'source_skew_max_ms': [(str(x), lambda p, x=x: p['signal']['source_skew_ms'] <= x)
                               for x in (250, 500, 750)],
        'asset_class': [('crypto', lambda p: p['_class'] == 'crypto'),
                        ('rwa_xyz', lambda p: p['_class'] == 'rwa_xyz')],
    }


def select_on_train(train, family, choices):
    minimum = max(30, math.ceil(.10 * len(train)))
    evaluated = []
    for label, predicate in choices:
        selected = [p for p in train if predicate(p)]
        result = outcome(selected)
        evaluated.append({'threshold': label, 'eligible': len(selected) >= minimum,
                          'train_coverage': len(selected) / len(train), 'train': result})
    eligible = [item for item in evaluated if item['eligible']]
    winner = max(eligible, key=lambda item: (item['train']['net_per_attempt_usd'],
                                             item['train']['attempts'])) if eligible else None
    return winner, evaluated, minimum


def groups(rows, key, minimum=10):
    buckets = defaultdict(list)
    for row in rows:
        buckets[key(row)].append(row)
    return {name: outcome(bucket) for name, bucket in sorted(buckets.items(),
            key=lambda item: (-len(item[1]), item[0])) if len(bucket) >= minimum}


def forecaster_diagnostics(sample, baseline):
    result = {}
    for policy in ('convergence', 'conservative', 'confirmed'):
        rows = settled(sample['trades'], policy)
        forecasts = [(p['signal']['entry_policy']['forecast_net_usd'], p)
                     for p in rows if p['status'] in CLOSED and
                     isinstance(p.get('signal', {}).get('entry_policy', {}).get('forecast_net_usd'), (int, float))]
        summary = {'outcome': outcome(rows), 'forecasted_closes': len(forecasts),
                   'forecast_mean_usd': sum(f for f, _ in forecasts) / len(forecasts) if forecasts else None,
                   'realized_mean_on_forecasted_usd': sum(p['net_pnl_usd'] for _, p in forecasts) / len(forecasts) if forecasts else None,
                   'positive_forecast_closes': sum(f > 0 for f, _ in forecasts),
                   'positive_forecast_losses': sum(f > 0 and p['net_pnl_usd'] < 0 for f, p in forecasts)}
        summary['forecast_cohorts'] = {
            '0_to_0.5': outcome([p for f, p in forecasts if 0 <= f < .5]),
            '0.5_to_1': outcome([p for f, p in forecasts if .5 <= f < 1]),
            '1_or_more': outcome([p for f, p in forecasts if f >= 1])}
        if rows:
            start, end = rows[0]['created_at'], rows[-1]['created_at']
            summary['calendar_window'] = {'start': utc(start), 'end': utc(end)}
            summary['baseline_same_calendar_window'] = outcome(
                [p for p in baseline if start <= p['created_at'] <= end])
        result[policy] = summary
    return result


def analyze(sample):
    categories = sample['category_by_pair']
    rows = settled(sample['trades'], 'shadow_baseline')
    for row in rows:
        row['_class'] = class_of(row, categories)
    primary = dedupe_attempts(rows)
    train, holdout, cut, purged = split_chronological(primary)
    experiments = {}
    for family, choices in candidates().items():
        winner, evaluated, minimum = select_on_train(train, family, choices)
        selected = next((predicate for label, predicate in choices
                         if winner and label == winner['threshold']), None)
        kept = [p for p in holdout if selected(p)] if selected else []
        experiments[family] = {'selection_criterion': 'highest train net per attempt, with >=10% train coverage and >=30 attempts',
                               'min_train_attempts': minimum, 'train_candidates': evaluated,
                               'chosen_threshold': winner['threshold'] if winner else None,
                               'holdout_coverage': len(kept) / len(holdout) if holdout else None,
                               'holdout': outcome(kept) if winner else None}
    closed = [p for p in primary if p['status'] in CLOSED]
    accounting_error = max((abs(p['net_pnl_usd'] - (p['price_pnl'] - p['fees_usd'] -
                       p['other_costs_usd'] - p['capital_costs_usd'] + p.get('funding_usd', 0)))
                       for p in closed), default=0)
    return {'schema_version': 1, 'checkpoint_at': sample['checkpoint_at'],
            'checkpoint_utc': utc(sample['checkpoint_at']),
            'sample_retained_rows': len(sample['trades']),
            'primary_strategy': 'shadow_baseline', 'fee_tier': 'Standard',
            'deduplication': {'rule': 'first settled shadow_baseline route attempt within 5 seconds',
                              'before': len(rows), 'after': len(primary), 'removed': len(rows)-len(primary)},
            'primary_all': outcome(primary),
            'paired_close_component': outcome([p for p in primary if p['status'] in CLOSED and
                p.get('exit_reason') != 'entry_failure' and len(p['legs']) == 2 and
                all(l.get('entry_result') == 'filled' for l in p['legs'])]),
            'failed_hedge_component': outcome([p for p in primary if p['status'] in CLOSED and
                p.get('exit_reason') == 'entry_failure']),
            'train_test': {'rule': 'first 70% of deduplicated attempts by created_at train; last 30% holdout',
                           'cut_at': cut, 'cut_utc': utc(cut),
                           'train_crossing_outcomes_purged': purged,
                           'train': outcome(train), 'holdout': outcome(holdout)},
            'experiments': experiments,
            'components_by_class': groups(primary, lambda p: p['_class']),
            'components_by_countervenue': groups(primary, venue_of),
            'components_by_route_min_20': groups(primary, lambda p: p['signal']['route'], 20),
            'forecasters_diagnostic_only': forecaster_diagnostics(sample, primary),
            'max_accounting_identity_error_usd': accounting_error,
            'limitations': [
                'Filters only retain or abstain from recorded fills and exits; a changed entry policy could receive different fills.',
                'The holdout is retrospective and all candidate families are exploratory; it is not prospective profit evidence.',
                'Using only shadow_baseline removes duplicate fee-variant rows, but routes and assets can remain correlated in time.',
                'Historical forecasts are present only for selected forecaster entries and cannot be imputed onto baseline attempts.',
                'Current market metadata supplies asset categories; unmapped historical pairs remain unmapped.',
                'The SQLite trade ring omits earlier history; ledger lifetime totals are not substituted for this retained sample.']}


def markdown(result, sample_hash):
    split = result['train_test']
    hold = split['holdout']
    overall = result['primary_all']
    paired = result['paired_close_component']
    failed = result['failed_hedge_component']
    lines = [
        '# Retrospective entry-filter experiments', '',
        f"Frozen checkpoint: {result['checkpoint_utc']}. Evidence SHA-256: `{sample_hash}`.", '',
        'The primary sample is the Standard-fee `shadow_baseline` portfolio. Each filter keeps or abstains from an observed attempt; fills and exits are unchanged.', '',
        f"After 5-second route deduplication: {result['deduplication']['after']} settled attempts "
        f"({result['deduplication']['removed']} removed). Chronological 70/30 split at {split['cut_utc']}; "
        f"{split['train_crossing_outcomes_purged']} training outcomes unavailable by the boundary were purged "
        '(settlement for closes, close time for aborts).', '',
        f"Unfiltered holdout: {hold['attempts']} attempts, {hold['closed']} closes, "
        f"{hold['paired_closes']} paired closes, {hold['failed_hedges']} failed hedges, "
        f"{hold['wins']} wins, net {money(hold['net_pnl_usd'])} "
        f"({money(hold['net_per_attempt_usd'], 3)} per attempt).", '',
        f"Across the full retained baseline, net {money(overall['net_pnl_usd'])} = "
        f"price P&L {money(overall['price_pnl_usd'])} less fees {money(overall['fees_usd'])}, "
        f"modeled other costs {money(overall['other_costs_usd'])}, and small capital costs, "
        'plus funding. ' f"Paired closes: {paired['closed']} and {money(paired['net_pnl_usd'])}; "
        f"failed hedges: {failed['closed']} and {money(failed['net_pnl_usd'])}.", '',
        '## Train-selected filters on untouched holdout', '',
        '| Family | Train choice | Holdout attempts | Coverage | Holdout net | Net/attempt | Wins | Failed hedges |',
        '|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for family, item in result['experiments'].items():
        test = item['holdout']
        if test is None:
            lines.append(f'| {family} | none met coverage | — | — | — | — | — | — |')
        else:
            value = money(test['net_per_attempt_usd'], 3) if test['net_per_attempt_usd'] is not None else '—'
            lines.append(f"| {family} | {item['chosen_threshold']} | {test['attempts']} | "
                         f"{item['holdout_coverage']:.1%} | {money(test['net_pnl_usd'])} | "
                         f"{value} | {test['wins']} | {test['failed_hedges']} |")
    lines += ['', 'Selection maximizes training net P&L per observed attempt among the listed fixed thresholds, subject to at least 10% training coverage and 30 attempts. Only outcomes known before the holdout began train the selection. No threshold was chosen from holdout outcomes. All filter outcomes are observed subsets, not simulated trades.', '',
              '## Loss components and venue mix', '',
              '| Group | Attempts | Paired | Failed hedge | Price P&L | Fees | Other costs | Net P&L |',
              '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name, item in list(result['components_by_class'].items()) + list(result['components_by_countervenue'].items()):
        lines.append(f"| {name} | {item['attempts']} | {item['paired_closes']} | {item['failed_hedges']} | "
                     f"{money(item['price_pnl_usd'])} | {money(item['fees_usd'])} | "
                     f"{money(item['other_costs_usd'])} | {money(item['net_pnl_usd'])} |")
    lines += ['', 'Largest route cohorts (at least 20 attempts):', '',
              '| Route | Attempts | Failed hedge | Price P&L | Fees | Other costs | Net P&L |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for name, item in list(result['components_by_route_min_20'].items())[:10]:
        lines.append(f"| {name} | {item['attempts']} | {item['failed_hedges']} | "
                     f"{money(item['price_pnl_usd'])} | {money(item['fees_usd'])} | "
                     f"{money(item['other_costs_usd'])} | {money(item['net_pnl_usd'])} |")
    lines += ['', '## Forecast-policy diagnostic', '',
              'Forecasts exist only on policies that entered. Their outcomes are shown separately from the primary baseline; calendar-window baseline rows are not matched counterpart trades.', '',
              '| Policy | Settled attempts | Paired | Failed hedge | Forecasted closes | Mean forecast | Mean realized on forecasted | Net P&L | Calendar baseline |',
              '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for name, item in result['forecasters_diagnostic_only'].items():
        o = item['outcome']
        f = item['forecast_mean_usd']
        a = item['realized_mean_on_forecasted_usd']
        calendar = item.get('baseline_same_calendar_window')
        baseline_cell = f"{calendar['attempts']} / {money(calendar['net_pnl_usd'])}" if calendar else '—'
        lines.append(f"| {name} | {o['attempts']} | {o['paired_closes']} | {o['failed_hedges']} | "
                     f"{item['forecasted_closes']} | {money(f, 3) if f is not None else '—'} | "
                     f"{money(a, 3) if a is not None else '—'} | {money(o['net_pnl_usd'])} | {baseline_cell} |")
    lines += ['', 'Forecast cohorts among selected closes (retrospective, no baseline forecast imputation):', '',
              '| Policy | Forecast USD | Closes | Wins | Failed hedges | Realized net |',
              '|---|---|---:|---:|---:|---:|']
    for name, item in result['forecasters_diagnostic_only'].items():
        for label, cohort in item['forecast_cohorts'].items():
            if cohort['closed']:
                lines.append(f"| {name} | {label} | {cohort['closed']} | {cohort['wins']} | "
                             f"{cohort['failed_hedges']} | {money(cohort['net_pnl_usd'])} |")
    lines += ['', '## Interpretation', '',
              'This study can identify filters that avoided losses in this sample. It cannot establish that abstention improves future executions or that any selected filter is profitable. The recorded single-leg failures remain a separate risk from spread convergence.', '',
              '## Limits', '']
    lines += [f'- {item}' for item in result['limitations']]
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    freeze_cmd = sub.add_parser('freeze')
    freeze_cmd.add_argument('--db', type=Path, default=ROOT / 'data/paper-monitor/paper.sqlite3')
    freeze_cmd.add_argument('--markets', type=Path, default=ROOT / 'data/paper-monitor/markets.json')
    freeze_cmd.add_argument('--out', type=Path, default=SAMPLE)
    report_cmd = sub.add_parser('report')
    report_cmd.add_argument('--sample', type=Path, default=SAMPLE)
    report_cmd.add_argument('--out-dir', type=Path, default=OUT)
    args = parser.parse_args()
    if args.command == 'freeze':
        print(json.dumps(freeze(args.db, args.markets, args.out), indent=2))
    else:
        result = analyze(load(args.sample))
        args.out_dir.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(result, sort_keys=True, indent=2, allow_nan=False)
        (args.out_dir / 'summary.json').write_text(encoded + '\n')
        sha = hashlib.sha256(args.sample.read_bytes()).hexdigest()
        (args.out_dir / 'REPORT.md').write_text(markdown(result, sha))
        print(json.dumps({'summary': str(args.out_dir / 'summary.json'),
                          'report': str(args.out_dir / 'REPORT.md'), 'sample_sha256': sha}, indent=2))


if __name__ == '__main__':
    main()
