#!/usr/bin/env python3
"""One bounded, descriptive read of retained NVDA paper attempts for review 65."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.paper_review import _category

DIRECTORY = ROOT / 'reports/live-review-catchup'
OUTPUT = DIRECTORY / 'review65-nvda-session-breakdown.json'
CLAIM = DIRECTORY / 'review65-nvda-session-claim.json'
CAP = 65536
MAX_ROWS = 256
BOUNDARY = datetime(2026, 9, 30, 13, 30, tzinfo=timezone.utc).timestamp()


def source_hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (Path(__file__).resolve(), ROOT / 'scripts/paper_review.py')}


def project(trade, raw, upper):
    created = trade['created_at']
    settled, closed = trade.get('settled_at'), trade.get('closed_at')
    complete = (trade['status'] in ('CLOSED', 'CLOSED_ESTIMATED')
                and isinstance(settled, (float, int)) and math.isfinite(settled)
                and created <= settled <= upper)
    aborted = (trade['status'] == 'ABORTED' and isinstance(closed, (float, int))
               and math.isfinite(closed) and created <= closed <= upper)
    category = _category(trade) if complete else 'aborted' if aborted else 'unsettled_at_checkpoint'
    net = trade.get('net_pnl_usd') if complete else None
    if complete and (isinstance(net, bool) or not isinstance(net, (float, int)) or not math.isfinite(net)):
        raise ValueError('nonfinite_closed_pnl')
    row = {'id': trade['id'], 'strategy': trade['strategy'], 'created_at': created,
           'phase': 'before_1330' if created < BOUNDARY else 'from_1330',
           'paper_epoch_id': trade.get('paper_epoch_id'),
           'paper_strategy_version': trade.get('paper_strategy_version'),
           'category': category, 'net_pnl_usd': net,
           'quality': ('estimated' if trade['status'] == 'CLOSED_ESTIMATED' else 'exact') if complete else None,
           'raw_payload_sha256': hashlib.sha256(raw.encode()).hexdigest()}
    if complete:
        row['settled_at'] = settled
        row['classification_evidence'] = {
            'exit_reason': trade.get('exit_reason'), 'opened_at': trade.get('opened_at'),
            'legs': [{key: leg.get(key) for key in ('entry_result', 'quantity')}
                     for leg in trade.get('legs', [])]}
        row['costs'] = {key: trade.get(key) for key in
                        ('price_pnl', 'fees_usd', 'funding_usd', 'other_costs_usd', 'capital_costs_usd')}
    return row


def run():
    before = source_hashes()
    allocation_path = ROOT / 'reports/experiment-storage/review65-nvda-annotation-allocation-v1.json'
    allocation_raw = allocation_path.read_bytes()
    if len(allocation_raw) > 5464:
        raise ValueError('allocation_provenance_cap')
    allocation = json.loads(allocation_raw)
    if allocation['source_sha256'] != before:
        raise ValueError('allocated_source_hash_mismatch')
    if allocation['bounds']['retained_attempts'] != MAX_ROWS or allocation['categories_bytes']['output'] != CAP:
        raise ValueError('allocated_limits_mismatch')
    inputs = {}
    reviews = []
    for stamp in ('20260930T132633Z', '20260930T134633Z'):
        path = DIRECTORY / f'review-{stamp}.json'
        raw = path.read_bytes()
        if len(raw) > 262144:
            raise ValueError('review_input_cap')
        inputs[path.name] = hashlib.sha256(raw).hexdigest()
        reviews.append(json.loads(raw))
    lower, upper = (r['checkpoint_at'] for r in reviews)
    if not lower < BOUNDARY < upper or not 1100 <= upper-lower <= 1300:
        raise ValueError('fixed_review_window_identity')
    if time.time() < reviews[-1]['reviewed_at']:
        raise ValueError('review_not_yet_completed')
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    with CLAIM.open('x') as handle:
        json.dump({'started_at': time.time(), 'source_hashes': before, 'review_hashes': inputs,
                   'allocation_sha256': hashlib.sha256(allocation_raw).hexdigest(),
                   'max_retained_rows': MAX_ROWS, 'output_cap': CAP}, handle, sort_keys=True)
        handle.write('\n')
    started = time.monotonic()
    path = (ROOT / 'data/paper-monitor/paper.sqlite3').resolve()
    with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=1) as db:
        db.execute('PRAGMA query_only=ON')
        db.set_progress_handler(lambda: int(time.monotonic()-started > 10), 1000)
        db.execute('BEGIN')
        checkpoint = db.execute('SELECT updated FROM engine_state WHERE id=1').fetchone()[0]
        if checkpoint < upper:
            raise ValueError('database_behind_review')
        where = ("json_extract(payload,'$.asset')='NVDA' AND "
                 "CAST(json_extract(payload,'$.created_at') AS REAL)>? AND "
                 "CAST(json_extract(payload,'$.created_at') AS REAL)<=?")
        count = db.execute('SELECT COUNT(*) FROM trades WHERE '+where, (lower, upper)).fetchone()[0]
        if count > MAX_ROWS:
            raise ValueError(f'retained_row_cap:{count}>{MAX_ROWS}')
        rows = [project(json.loads(raw), raw, upper) for (raw,) in db.execute(
            'SELECT payload FROM trades WHERE '+where+" ORDER BY CAST(json_extract(payload,'$.created_at') AS REAL),id",
            (lower, upper))]
        db.rollback()
    if source_hashes() != before:
        raise ValueError('source_changed')
    groups = defaultdict(list)
    for row in rows:
        key = (row['paper_epoch_id'], row['paper_strategy_version'], row['strategy'], row['phase'], row['category'], row['quality'])
        groups[key].append(row)
    result = {'schema': 'review65-nvda-retained-attempt-annotation-v1', 'read_at': time.time(),
              'database_checkpoint_at': checkpoint, 'attempt_created_interval': [lower, upper],
              'split_at': BOUNDARY, 'phase_seconds': {'before_1330': BOUNDARY-lower, 'from_1330': upper-BOUNDARY},
              'coverage': 'retained_attempts_only_not_rejected_signals_or_causal_effect',
              'source_hashes': before, 'review_hashes': inputs, 'count': len(rows), 'rows': rows,
              'groups': [dict(zip(('paper_epoch_id', 'paper_strategy_version', 'strategy', 'phase', 'category', 'quality'), key),
                              count=len(group), reported_closed_net_usd=math.fsum(r['net_pnl_usd'] for r in group)
                              if key[4] not in ('aborted', 'unsettled_at_checkpoint') else None,
                              reported_positive_closes=sum(r['net_pnl_usd'] is not None and r['net_pnl_usd'] > 0 for r in group))
                         for key, group in sorted(groups.items(), key=lambda item: str(item[0]))],
              'causal_session_claim': False, 'policy_changed': False, 'new_quote_capture': False}
    encoded = (json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()
    if len(encoded) > CAP:
        raise ValueError(f'output_cap:{len(encoded)}>{CAP}')
    with OUTPUT.open('xb') as handle:
        handle.write(encoded)
    print(json.dumps({'status': 'complete', 'retained_attempts': len(rows), 'bytes': len(encoded)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    if args.run:
        run()
    else:
        print('{"mode":"dry","database_read":false,"new_quote_capture":false}')
