#!/usr/bin/env python3
"""Independently reconcile retained paper fills and attribute losses (read only).

Input: monitor directory, SQLite database, or a frozen .json.gz audit export.
Retained-trade totals are not lifetime totals once the retention limit is reached.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import sqlite3
from statistics import median


def read_sample(path):
    path = Path(path)
    if path.name.endswith('.json.gz'):
        with gzip.open(path, 'rt') as stream:
            return json.load(stream)
    if path.is_dir():
        path /= 'paper.sqlite3'
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    try:
        db.execute('BEGIN')
        payload, updated = db.execute('SELECT payload,updated FROM engine_state WHERE id=1').fetchone()
        engine = json.loads(payload)['engine']
        trades = [json.loads(row[0]) for row in db.execute('SELECT payload FROM trades ORDER BY ts DESC LIMIT 5000')]
        return {'checkpoint_at': updated,
                'engine': {k: engine[k] for k in ('config', 'ledgers', 'positions', 'stats')},
                'trades': trades}
    finally:
        db.close()


def audit(sample):
    engine = sample['engine']
    cfg = engine['config']
    closed = [p for p in sample['trades'] if p['status'] in ('CLOSED', 'CLOSED_ESTIMATED')]
    errors = defaultdict(float)
    def check(name, computed, stored):
        errors[name] = max(errors[name], abs(computed - stored))
    for p in closed:
        gross = fees = elapsed = 0.0
        for leg in p['legs']:
            fills = leg['exit_fills']
            exited = sum(f['quantity'] for f in fills)
            value = sum(f['value'] for f in fills)
            check('closed_quantity', exited, leg['quantity'])
            check('exit_value_usd', value, leg['exit_value'])
            pnl = (value - leg['entry_value']) * (1 if leg['side'] == 'long' else -1)
            check('leg_price_pnl_usd', pnl, leg['price_pnl'])
            entry_fee = leg['entry_value'] * leg.get('entry_fee_bps', leg['fee_bps']) / 10000
            exit_fee = sum(f['value'] * f['fee_bps'] / 10000 for f in fills)
            check('entry_fee_usd', entry_fee, leg['entry_fee'])
            check('exit_fee_usd', exit_fee, leg['exit_fee'])
            check('leg_fees_usd', entry_fee + exit_fee, leg['fees_usd'])
            gross += pnl
            fees += entry_fee + exit_fee
            if leg['entry_time'] is not None:
                elapsed += (leg['exit_time'] - leg['entry_time']) * leg['entry_value'] * cfg['margin_fraction']
        reserve = max(l['entry_value'] for l in p['legs']) * cfg['extra_cost_bps'] / 10000
        capital = elapsed * cfg['capital_rate'] / (365 * 86400)
        check('price_pnl_usd', gross, p['price_pnl'])
        check('fees_usd', fees, p['fees_usd'])
        check('reserve_usd', reserve, p['other_costs_usd'])
        check('capital_usd', capital, p['capital_costs_usd'])
        check('net_pnl_usd', gross - fees - reserve - capital + p['funding_usd'], p['net_pnl_usd'])
    portfolios = {}
    for name, ledger in engine['ledgers'].items():
        rows = [p for p in closed if p['strategy'] == name]
        active = [p for p in engine['positions'].values() if p['strategy'] == name]
        active_cash = sum(sum(l['price_pnl'] - l['fees_usd'] for l in p['legs'])
                          - p.get('other_costs_usd', 0) - p.get('capital_costs_usd', 0) for p in active)
        expected = ledger['initial_capital'] + ledger['closed_pnl_exact'] + ledger['closed_pnl_estimated'] + active_cash
        wallet_error = sum(ledger['wallets'].values()) - expected
        check('wallet_usd', expected, sum(ledger['wallets'].values()))
        holds = [p['closed_at'] - p['opened_at'] for p in rows]
        routes = defaultdict(lambda: {'closed': 0, 'net_usd': 0.0})
        for p in rows:
            group = routes[p['signal']['route']]
            group['closed'] += 1
            group['net_usd'] += p['net_pnl_usd']
        portfolios[name] = {
            'closed_retained': len(rows), 'wins': sum(p['net_pnl_usd'] > 0 for p in rows),
            'gross_price_wins': sum(p['price_pnl'] > 0 for p in rows),
            'wins_after_fees_before_reserve': sum(p['price_pnl'] - p['fees_usd'] + p['funding_usd'] > 0 for p in rows),
            **{k: sum(p[k] for p in rows) for k in ('price_pnl', 'fees_usd', 'other_costs_usd', 'capital_costs_usd', 'funding_usd', 'net_pnl_usd')},
            'exit_reasons': dict(Counter(p.get('exit_reason', 'unknown') for p in rows)),
            'hold_median_seconds': median(holds) if holds else None,
            'entry_signal_below_profit_target': sum(p['signal']['net_edge_usd'] < (cfg.get('take_profit_usd') or 0) for p in rows),
            'wallet_reconciliation_error_usd': wallet_error,
            'lifetime_closed_count': ledger['closed_trades'] + ledger['estimated_trades'],
            'routes': dict(sorted(routes.items(), key=lambda x: x[1]['net_usd']))}
    return {'checkpoint_utc': datetime.fromtimestamp(sample['checkpoint_at'], timezone.utc).isoformat(),
            'first_retained_entry_utc': datetime.fromtimestamp(min(p['created_at'] for p in closed), timezone.utc).isoformat() if closed else None,
            'closed_retained': len(closed), 'independent_max_absolute_errors': dict(errors),
            'accounting_checks_pass': all(v < 1e-7 for v in errors.values()),
            'portfolios': portfolios,
            'profit_triggered_exits': [{k: p.get(k) for k in ('id', 'asset', 'strategy', 'exit_trigger_pnl_usd', 'exit_requested_at', 'closed_at', 'net_pnl_usd')} for p in closed if p.get('exit_reason') == 'take_profit'],
            'limitations': ['Portfolios are alternative fee scenarios; do not add their returns.',
                            'Checks validate stored fill arithmetic, not execution realism or external fee schedules.',
                            'Per-trade totals describe the retained window; lifetime counters can cover more trades.',
                            'Removing the reserve is an accounting sensitivity, not a strategy rerun.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', nargs='?', default='data/paper-monitor')
    parser.add_argument('--freeze', type=Path, help='Write compact reproducible evidence to this .json.gz path')
    args = parser.parse_args()
    sample = read_sample(args.path)
    if args.freeze:
        args.freeze.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(args.freeze, 'wt') as stream:
            json.dump(sample, stream, separators=(',', ':'), allow_nan=False)
    print(json.dumps(audit(sample), indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
