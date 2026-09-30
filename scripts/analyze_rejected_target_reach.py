"""Bounded post-capture public-price reach diagnostic; no strategy replay.

Every logged fixed-cost target rejection is retained. No queue, fill, hedge,
cash, or profit is inferred. No wider ceiling is selected or implemented.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
import gzip
import hashlib
import json
from pathlib import Path

from scripts.analyze_rh_passive_exit import verify_protocol, RESULT_SCHEMA
from scripts.rh_maker_engine import Config, NS
from scripts.rh_maker_events import iter_events, _trade

ROOT = Path(__file__).resolve().parents[1]
CAP = 2_000_000


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def identity(row):
    return (row['tier'], row['asset'], int(row['budget_usd']), row['exit_policy'])


def event_hash(event):
    return hashlib.sha256(json.dumps(event, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def reconstruct(row, first_hedge, metadata):
    """Use the logged frozen cost requirement, never recalibrate its costs."""
    out = dict(row)
    out['request_ns'] = int(row['ns'])
    out['reconstruction_status'] = 'unreconstructable'
    if row.get('reason') != 'target_above_5bp_ask_cap' or first_hedge is None:
        return out
    try:
        required, cap = Decimal(row['required_price']), Decimal(row['capped_price'])
        tick = Decimal(metadata[row['tier']][row['asset']]['rh']['price_tick'])
        if not all(x.is_finite() and x > 0 for x in (required, cap, tick)):
            return out
        # This value is cross-checked against the actual preceding raw book,
        # not accepted as a substitute for missing as-of quote provenance.
        logged_ask = cap / Decimal('1.0005')
        target = (max(required, logged_ask) / tick).to_integral_value(rounding=ROUND_CEILING) * tick
        hold_ns = (60 if row['exit_policy'] == 'passive_target60s' else 10) * NS
        cfg = Config(row['asset'], Decimal(str(row['budget_usd'])), 'fixed_best',
                     tier=row['tier'], hold_ns=hold_ns)
        hold_due = int(first_hedge['ns']) + hold_ns
        if hold_due != int(first_hedge['hold_due_ns']) or row['ns'] >= hold_due:
            return out
        out.update(logged_asof_ask=str(logged_ask), required_price=str(required),
                   target_price=str(target), original_rh_tick=str(tick),
                   hypothetical_activation_ns=row['ns'] + cfg.maker_latency_ns,
                   assumed_maker_latency_ns=cfg.maker_latency_ns,
                   first_full_hedge_ns=int(first_hedge['ns']), hold_deadline_ns=hold_due,
                   first_full_hedge_audit_sha256=event_hash(first_hedge),
                   reconstruction_status='pending_asof_book')
    except (KeyError, ValueError, ArithmeticError):
        pass
    return out


def read_attempts(audit, result):
    attempts, first_hedges = [], {}
    records = 0
    decoded = 0
    with gzip.open(audit, 'rb') as f:
        for line in f:
            decoded += len(line)
            if decoded > 64_000_000 or len(line) > 1_000_000:
                raise ValueError('audit decoded bound exceeded')
            row = json.loads(line)
            records += 1
            key = identity(row)
            if row['event'] == 'quote_requested':
                first_hedges.pop(key, None)
            elif row['event'] == 'first_full_hedge':
                first_hedges[key] = row
            elif row['event'] == 'passive_target_abstain':
                if len(attempts) >= 4096:
                    raise ValueError('attempt bound exceeded')
                attempt = reconstruct(row, first_hedges.get(key), result['metadata'])
                attempt.update(attempt_number=len(attempts) + 1, audit_line=records,
                               audit_row_sha256=event_hash(row))
                attempts.append(attempt)
    if records != result['audit_records']:
        raise ValueError('audit record count mismatch')
    return attempts


def scan_events(events, attempts):
    """No engine invocation: retain books for as-of checks and trades as evidence."""
    by_request = defaultdict(list)
    for attempt in attempts:
        by_request[attempt['request_ns']].append(attempt)
    latest, issues, trades, invalid_open = {}, [], [], {}
    previous_receipt = None
    receipt_events = []
    terminal = None
    seen_ids = {}
    duplicate_count = 0

    def finish_receipt(receipt, group):
        if receipt not in by_request:
            return
        # A unique book callback determines which incoming book was visible
        # to the request. Shared receipt timestamps lack audit sequence.
        book_callbacks = [x for x in group if x.get('type') == 'book']
        for attempt in by_request[receipt]:
            if attempt['reconstruction_status'] != 'pending_asof_book':
                continue
            same_asset = [x for x in book_callbacks if x.get('asset') == attempt['asset']]
            rh = latest.get(('rh_lighter', attempt['asset']))
            if len(same_asset) != 1 or rh is None or not rh.get('asks'):
                attempt['reconstruction_status'] = 'unreconstructable_asof_callback'
                continue
            if Decimal(str(rh['asks'][0][0])) != Decimal(attempt['logged_asof_ask']):
                attempt['reconstruction_status'] = 'unreconstructable_asof_ask_mismatch'
                continue
            if not (rh['source_ns'] <= rh['received_ns'] <= receipt
                    and receipt - rh['source_ns'] <= 2 * NS
                    and receipt - rh['received_ns'] <= 2 * NS):
                attempt['reconstruction_status'] = 'unreconstructable_asof_clock'
                continue
            attempt.update(reconstruction_status='reconstructed',
                asof_rh_book={'source_ns': rh['source_ns'], 'received_ns': rh['received_ns'],
                             'generation': rh['generation'], 'sequence': rh.get('sequence'),
                             'canonical_event_index': rh['_event_index'],
                             'sha256': event_hash({k: v for k, v in rh.items() if k != '_event_index'}),
                             'best_ask': str(rh['asks'][0][0])},
                target_request_callback={'venue': same_asset[0]['venue'],
                    'source_ns': same_asset[0]['source_ns'],
                    'canonical_event_index': same_asset[0]['_event_index'],
                    'sha256': event_hash({k: v for k, v in same_asset[0].items() if k != '_event_index'})})

    for index, original in enumerate(events, 1):
        event = {**original, '_event_index': index}
        receipt = event['received_ns']
        if previous_receipt is not None and receipt < previous_receipt:
            raise ValueError('backward canonical receipt')
        if previous_receipt is not None and receipt != previous_receipt:
            finish_receipt(previous_receipt, receipt_events)
            receipt_events = []
        previous_receipt = receipt
        receipt_events.append(event)
        if len(receipt_events) > 10_000:
            raise ValueError('same receipt event bound exceeded')
        key = (event.get('venue'), event.get('asset'))
        if event['type'] in ('book', 'invalidate') and key[1] is not None:
            old = latest.get(key)
            if old is not None:
                expiry = min(old['source_ns'], old['received_ns']) + 2 * NS + 1
                if expiry < receipt:
                    issues.append({'venue': key[0], 'asset': key[1], 'start_ns': expiry,
                                   'end_ns': receipt, 'reason': 'book_freshness_proxy_gap'})
            if event['type'] == 'invalidate':
                invalid_key = (*key, event.get('scope', 'book'))
                invalid_open.setdefault(invalid_key, {'venue': key[0], 'asset': key[1],
                    'start_ns': receipt, 'reason': event.get('reason'),
                    'scope': invalid_key[2], 'event_sha256': event_hash(original)})
                if event.get('scope') != 'trade':
                    latest.pop(key, None)
            else:
                invalid = invalid_open.pop((*key, 'book'), None)
                if invalid is not None:
                    issues.append(dict(invalid, end_ns=receipt))
                latest[key] = event
        if event['type'] == 'trade' and event.get('venue') == 'rh_lighter':
            invalid = invalid_open.pop((*key, 'trade'), None)
            if invalid is not None:
                issues.append(dict(invalid, end_ns=receipt))
            ident = (event['asset'], str(event['trade_id']))
            signature = (event['source_ns'], event['side'], str(Decimal(str(event['price'])).normalize()),
                         str(Decimal(str(event['qty'])).normalize()))
            if ident in seen_ids:
                duplicate_count += 1
                if seen_ids[ident] != signature:
                    issues.append({'venue': 'rh_lighter', 'asset': event['asset'],
                                   'start_ns': receipt, 'end_ns': receipt,
                                   'reason': 'canonical_native_id_conflict', 'trade_id': ident[1]})
                continue
            if len(seen_ids) >= 65_536:
                raise ValueError('native ID diagnostic bound exceeded')
            seen_ids[ident] = signature
            if event['side'] == 'buy':
                trades.append(original)
        if event['type'] == 'end':
            terminal = original
    if previous_receipt is not None:
        finish_receipt(previous_receipt, receipt_events)
    if terminal is None or terminal.get('truncated'):
        raise ValueError('complete canonical terminal required')
    issues.extend(dict(invalid, end_ns=terminal['received_ns']) for invalid in invalid_open.values())
    for key, old in latest.items():
        expiry = min(old['source_ns'], old['received_ns']) + 2 * NS + 1
        if expiry < terminal['received_ns']:
            issues.append({'venue': key[0], 'asset': key[1], 'start_ns': expiry,
                           'end_ns': terminal['received_ns'], 'reason': 'book_freshness_proxy_gap'})
    if len(issues) > 65_536:
        raise ValueError('coverage issue bound exceeded')
    return trades, issues, {'canonical_events': index, 'buy_prints': len(trades),
                           'additional_cross_generation_duplicates': duplicate_count,
                           'terminal': terminal}


def raw_id_review(capture):
    """Frozen adapter suppresses repeated IDs; detect changed raw content too."""
    manifest = json.loads((capture / 'manifest.json').read_text())
    assets = {str(m): a for a, m in manifest['selected_markets']['rh_lighter'].items()}
    seen, conflicts, counts = {}, [], Counter()
    with gzip.open(capture / 'frames.jsonl.gz', 'rb') as f:
        for line_no, line in enumerate(f, 1):
            if len(line) > 8 * 1024 * 1024:
                raise ValueError('raw line bound exceeded')
            row = json.loads(line)
            if row.get('venue') != 'rh_lighter' or row.get('channel') != 'trade':
                continue
            payload = row.get('payload') or {}
            if payload.get('type') != 'update/trade':
                continue
            market = str(row.get('market'))
            for raw in payload.get('trades') or []:
                try:
                    parsed = _trade(row, raw, market)
                    signature = (parsed['source_ns'], parsed['side'],
                                 str(Decimal(str(raw['price'])).normalize()),
                                 str(Decimal(str(raw['size'])).normalize()))
                    key = (assets[market], str(parsed['trade_id']))
                except (KeyError, ValueError, TypeError, ArithmeticError):
                    counts['malformed_ordinary_trade_rows'] += 1
                    continue
                evidence = {'asset': key[0], 'trade_id': key[1], 'received_ns': row['receipt_utc_ns'],
                            'source_ns': parsed['source_ns'], 'generation': row['generation'],
                            'raw_line': line_no, 'raw_line_sha256': hashlib.sha256(line).hexdigest()}
                if key in seen:
                    if seen[key][0] != signature:
                        counts['conflicting_native_id_rows'] += 1
                        conflicts.append({'first': seen[key][1], 'conflict': evidence})
                    else:
                        counts['exact_native_id_retransmissions'] += 1
                else:
                    if len(seen) >= 65_536:
                        raise ValueError('raw native ID bound exceeded')
                    seen[key] = (signature, evidence)
    return conflicts, dict(counts)


def evaluate(attempt, trades, issues, conflicts):
    if attempt['reconstruction_status'] != 'reconstructed':
        return {'reach_status': 'unreconstructable'}
    start, deadline = attempt['hypothetical_activation_ns'], attempt['hold_deadline_ns']
    target = Decimal(attempt['target_price'])
    def valid_buy(x):
        try:
            return (x.get('venue') == 'rh_lighter' and x.get('side') == 'buy'
                    and x.get('clock_valid', True) and x['source_ns'] > 0
                    and Decimal(str(x['price'])).is_finite() and Decimal(str(x['price'])) > 0
                    and Decimal(str(x['qty'])).is_finite() and Decimal(str(x['qty'])) > 0)
        except (KeyError, TypeError, ValueError, ArithmeticError):
            return False
    relevant = [x for x in trades if valid_buy(x) and x['asset'] == attempt['asset']
                and start <= x['source_ns'] <= deadline
                and x['received_ns'] >= start and x['source_ns'] <= x['received_ns']]
    reaching = [x for x in relevant if Decimal(str(x['price'])) >= target]
    timely = [x for x in reaching if x['received_ns'] <= deadline]
    late = [x for x in reaching if x['received_ns'] > deadline]
    overlap = [x for x in issues if x['asset'] == attempt['asset']
               and x['start_ns'] <= deadline and x['end_ns'] >= attempt['request_ns']]
    conflict_rows = [x for x in conflicts if x['first']['asset'] == attempt['asset']]
    # A conflicting ID can revise an old print; all such asset evidence is
    # explicit uncertainty, rather than retaining an arbitrary first version.
    return {'reach_status': 'observed_timely_reach' if timely else
                            'observed_late_receipt_reach_only' if late else 'observed_nonreach',
            'eligible_new_buy_prints': len(relevant), 'timely_reaching_prints': len(timely),
            'late_receipt_reaching_prints': len(late),
            'max_eligible_buy_price': (str(max(Decimal(str(x['price'])) for x in relevant))
                                       if relevant else None),
            'first_timely_reach': (dict(timely[0], canonical_event_sha256=event_hash(timely[0])) if timely else None),
            'first_late_receipt_reach': (dict(late[0], canonical_event_sha256=event_hash(late[0])) if late else None),
            'coverage_issues': overlap, 'asset_native_id_conflicts': conflict_rows,
            'coverage_or_identity_uncertain': bool(overlap or conflict_rows),
            'capture_covers_deadline': True}


def verify_result(result, capture, hashes, protocol, manifest):
    terminal = result.get('terminal_event') or {}
    if (result.get('schema') != RESULT_SCHEMA or result.get('event_source') != 'verified_capture'
            or result.get('capture') != str(capture.resolve())
            or result.get('status') != 'complete' or result.get('errors') != []
            or result.get('source_sha256') != protocol['source_sha256']
            or result.get('capture_manifest_sha256') != hashes['manifest']
            or result.get('raw_sha256') != hashes['raw'] or manifest['frames_sha256'] != hashes['raw']
            or result.get('audit_sha256') != hashes['audit']
            or result.get('protocol_sha256') != hashes['protocol']
            or result.get('metadata_normalized_sha256') != hashes['metadata']
            or terminal.get('type') != 'end' or terminal.get('truncated') is not False
            or terminal.get('raw_sha_verified') is not True
            or terminal.get('raw_gzip_sha256') != hashes['raw']
            or terminal.get('manifest_sha256') != hashes['manifest']):
        raise ValueError('strict result/input provenance mismatch')


def analyze(capture, replay, protocol_path, correction_freeze):
    diagnostic_hash = digest(__file__)
    protocol, manifest, _, _, stop = verify_protocol(protocol_path, capture)
    freeze = json.loads(correction_freeze.read_text())
    frozen = {**freeze['source_sha256'], **freeze['source_sha256_extra']}
    for name, expected in frozen.items():
        if digest(ROOT / name) != expected:
            raise ValueError('frozen20 mismatch: ' + name)
    paths = {'analysis': replay / 'analysis.json', 'audit': replay / 'audit.jsonl.gz',
             'manifest': capture / 'manifest.json', 'raw': capture / 'frames.jsonl.gz',
             'metadata': capture / 'metadata/normalized.json', 'protocol': protocol_path,
             'correction_freeze': correction_freeze}
    hashes = {name: digest(path) for name, path in paths.items()}
    if (freeze['source_sha256'] != protocol['source_sha256'] or len(frozen) != 20
            or freeze['protocol_sha256'] != hashes['protocol']):
        raise ValueError('correction source inventory/protocol mismatch')
    result = json.loads(paths['analysis'].read_text())
    verify_result(result, capture, hashes, protocol, manifest)
    attempts = read_attempts(paths['audit'], result)
    trades, issues, scan = scan_events(iter_events(capture, expected_raw_sha256=hashes['raw']), attempts)
    if scan['terminal'] != result['terminal_event']:
        raise ValueError('canonical terminal differs from strict result')
    conflicts, id_counts = raw_id_review(capture)
    groups = defaultdict(Counter)
    for attempt in attempts:
        outcome = evaluate(attempt, trades, issues, conflicts)
        if attempt.get('hold_deadline_ns', stop) > stop:
            outcome['capture_covers_deadline'] = False
            outcome['coverage_or_identity_uncertain'] = True
        attempt.update(outcome)
        state = groups[identity(attempt)]
        state['attempts'] += 1
        state[attempt['reach_status']] += 1
        state['coverage_or_identity_uncertain'] += bool(attempt.get('coverage_or_identity_uncertain'))
    after = {name: digest(path) for name, path in paths.items()}
    if (hashes != after or digest(__file__) != diagnostic_hash
            or any(digest(ROOT / name) != claimed for name, claimed in frozen.items())):
        raise ValueError('input/source changed during diagnostic')
    return {'schema': 'rh-rejected-fixed-target-public-reach-diagnostic-v1',
            'created_at': datetime.now(timezone.utc).isoformat(), 'post_capture_diagnostic': True,
            'strategy_replay_run': False, 'fills_inferred': False, 'profits_inferred': False,
            'queue_modeled': False, 'input_paths': {k: str(v.resolve()) for k, v in paths.items()},
            'input_sha256': hashes, 'frozen_source_sha256': frozen,
            'diagnostic_source_sha256': {str(Path(__file__).relative_to(ROOT)): diagnostic_hash},
            'assumptions': ['Native IDs unique/stable per RH asset across generations; conflicts are uncertainty.',
                'Hypothetical activation is request plus original configured maker latency, not a private ACK.',
                'Activation source equality is included; hold-deadline source equality is included.',
                'Both source and receipt must be causal after hypothetical activation; later receipts shown separately.',
                '2s book freshness is a coverage proxy; quiet trades alone are not missing-feed proof.',
                'Public trade completeness and calibrated source clocks are unavailable; nonreach is not an absolute no-fill bound.',
                'A reaching print proves neither queue priority nor maker fill; no hypothetical quantity is attributed.',
                'Required cost targets are logged fixed requirements, not recomputed under later books or fees.'],
            'attempts': attempts, 'scan': scan, 'raw_id_review': id_counts,
            'groups': [dict(tier=k[0], asset=k[1], budget_usd=k[2], policy=k[3], **v)
                       for k, v in sorted(groups.items())]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'reports/rejected-target-public-reach/analysis.json')
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError('diagnostic output must be new')
    result = analyze(ROOT / 'data/raw/rh-passive-exit-v1/20260930T0252Z',
                     ROOT / 'data/derived/rh-passive-exit-v1-restart',
                     ROOT / 'reports/rh-passive-exit-v1-restart/protocol.json',
                     ROOT / 'reports/rh-passive-exit-v1-restart/retirement-correction-freeze.json')
    body = (json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    if len(body) > CAP:
        raise ValueError('2 MB diagnostic output cap exceeded')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(body)
    print(json.dumps({'output': str(args.out), 'bytes': len(body), 'attempts': len(result['attempts']),
                      'status': dict(Counter(x['reach_status'] for x in result['attempts']))}))


if __name__ == '__main__':
    main()
