#!/usr/bin/env python3
"""Freeze and summarize retained take-profit exits without changing the monitor."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from statistics import median

from paper_loss_audit import read_sample


def freeze(run, destination):
    sample = read_sample(run)
    closed = [p for p in sample['trades']
              if p['status'] in ('CLOSED', 'CLOSED_ESTIMATED')]
    selected = [p for p in closed if p.get('exit_reason') == 'take_profit']
    body = {'checkpoint_at': sample['checkpoint_at'],
            'first_retained_created_at': min((p['created_at'] for p in closed), default=None),
            'retained_closed_count': len(closed),
            'config': sample['engine']['config'], 'trades': selected}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(body, indent=2, sort_keys=True)+'\n')


def analyze(body):
    groups = defaultdict(list)
    for p in body['trades']:
        assert p['exit_reason'] == 'take_profit'
        assert p['status'] in ('CLOSED', 'CLOSED_ESTIMATED')
        assert p['exit_trigger_pnl_usd'] is not None
        assert p['closed_at'] >= p['exit_requested_at']
        groups[p['strategy']].append(p)
    result = {}
    for strategy, rows in sorted(groups.items()):
        delays = [p['closed_at']-p['exit_requested_at'] for p in rows]
        changes = [p['net_pnl_usd']-p['exit_trigger_pnl_usd'] for p in rows]
        result[strategy] = {
            'retained_take_profit_exits': len(rows),
            'positive_final_net': sum(p['net_pnl_usd'] > 0 for p in rows),
            'negative_final_net': sum(p['net_pnl_usd'] < 0 for p in rows),
            'zero_final_net': sum(p['net_pnl_usd'] == 0 for p in rows),
            'estimated_final_count': sum(p['status'] == 'CLOSED_ESTIMATED' for p in rows),
            'median_request_to_flat_seconds': median(delays),
            'max_request_to_flat_seconds': max(delays),
            'median_trigger_net_usd': median(p['exit_trigger_pnl_usd'] for p in rows),
            'median_final_net_usd': median(p['net_pnl_usd'] for p in rows),
            'median_final_minus_trigger_usd': median(changes),
            'final_net_usd_sum_within_strategy': sum(p['net_pnl_usd'] for p in rows),
        }
    return {'checkpoint_at': body['checkpoint_at'],
            'first_retained_created_at': body['first_retained_created_at'],
            'retained_closed_count': body['retained_closed_count'],
            'selection': 'Settled retained trades with exit_reason=take_profit; no missing outcomes imputed.',
            'by_strategy': result,
            'limitations': [
                'Triggered liquidation estimates are quotes; completed outcomes are paper fills.',
                'Strategy portfolios share signals and prices; never add their returns.',
                'Retained settled sample omits pending exits and evicted older records.',
                'Request-to-flat time is not continuous opportunity duration or a latency threshold.',
                'Final minus trigger includes all model changes, not solely price slippage.',
            ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, default=Path('data/paper-monitor'))
    parser.add_argument('--evidence', type=Path,
                        help='Reuse a frozen evidence JSON instead of the live database')
    parser.add_argument('--out', type=Path, default=Path('reports/exit-trigger-survival'))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    source = args.evidence or args.out/'evidence.json'
    if args.evidence is None:
        freeze(args.run, source)
    raw = source.read_bytes()
    result = analyze(json.loads(raw))
    result['evidence_sha256'] = hashlib.sha256(raw).hexdigest()
    (args.out/'summary.json').write_text(json.dumps(result, indent=2, sort_keys=True)+'\n')
    stamp = datetime.fromtimestamp(result['checkpoint_at'], timezone.utc).isoformat()
    lines = ['# Take-profit estimate versus completed paper exit', '',
             f'Frozen checkpoint: {stamp}. Retained settled trades: {result["retained_closed_count"]}.', '',
             '| Independent portfolio | Triggered exits | Positive final net | Median request → flat | Median trigger / final net USD |',
             '|---|---:|---:|---:|---:|']
    for name, row in result['by_strategy'].items():
        lines.append(f'| {name} | {row["retained_take_profit_exits"]} | '
                     f'{row["positive_final_net"]} | {row["median_request_to_flat_seconds"]:.3f}s | '
                     f'{row["median_trigger_net_usd"]:.3f} / {row["median_final_net_usd"]:.3f} |')
    lines += ['', *['- '+s for s in result['limitations']], '',
              'The $0.10 exit target requests an unwind when the current estimate qualifies. '
              'It does not lock in ten cents: each delayed leg uses a later eligible book. '
              'These records do not reveal exactly when the estimate changed sign between '
              'request and completion, so they cannot establish a millisecond speed requirement.', '',
              'Reproduce: `.venv/bin/python scripts/analyze_profit_exits.py '
              '--evidence reports/exit-trigger-survival/evidence.json`.', '']
    (args.out/'README.md').write_text('\n'.join(lines))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
