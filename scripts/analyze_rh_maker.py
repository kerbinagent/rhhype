#!/usr/bin/env python3
"""Replay a stopped RH maker capture under a previously frozen paper method.

Public books and flow create counterfactual executions, not private fills.
No network access, live orders, or model selection from holdout outcomes.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.maker_capture import BoundedGzip, SizeCapReached
from scripts.rh_maker_config import ASSETS, SIZES, POLICIES, ASSUMPTIONS, policy_metadata
from scripts.rh_maker_engine import Config, MakerBranch
from scripts.rh_maker_events import iter_events
from scripts.rh_maker_model import RhMakerModel

NS = 1_000_000_000
AUDIT_CAP = 96_000_000
SUMMARY_CAP = 32_000_000


class LifecycleMetrics:
    """Bounded counters and quote-time intervals for four holdout blocks."""
    def __init__(self, cutoff_ns, end_ns):
        self.cutoff, self.end = cutoff_ns, end_ns
        self.blocks = [Counter() for _ in range(4)]
        self.requested_due = None
        self.active_from = None
        self.observed_from = None
        self.cancel_due = None

    def interval(self, start, stop, key):
        if start is None:
            return
        for i, block in enumerate(self.blocks):
            lo = max(start, self.cutoff + i * 300 * NS)
            hi = min(stop, self.cutoff + (i + 1) * 300 * NS, self.end)
            if hi > lo:
                block[key] += (hi - lo) / NS

    def consume(self, row):
        at, event = int(row['ns']), row['event']
        if at < self.cutoff or at > self.end:
            return
        block = self.blocks[min(3, (at - self.cutoff) // (300 * NS))]
        block[event] += 1
        if row.get('reason'):
            block[f'{event}:{row["reason"]}'] += 1
        if event in ('abstain', 'quote_requested'):
            block['decision_opportunities'] += 1
        if event == 'quote_requested':
            self.requested_due = row['due_ns']
            self.cancel_due = None
            block[f'quote_{row["competitiveness"]}'] += 1
        elif event == 'activated':
            self.active_from = self.requested_due
            self.observed_from = at
        elif event == 'cancel_requested':
            self.cancel_due = row['due_ns']
        elif event in ('cancel_effective', 'unknown', 'episode_flat'):
            self.interval(self.active_from, min(at, self.cancel_due) if self.cancel_due else at,
                          'modeled_quote_seconds')
            self.interval(self.observed_from, at, 'observed_queue_seconds')
            self.active_from = self.observed_from = None
        if event == 'maker_increment' and self.cancel_due is not None:
            block['maker_increment_while_cancel_pending_or_late'] += 1
        if event == 'hedge_result':
            filled, requested = Decimal(row['filled']), Decimal(row['requested'])
            block['hedge_zero' if filled == 0 else 'hedge_full' if filled == requested else 'hedge_partial'] += 1

    def finish(self, stop_ns):
        self.interval(self.active_from, min(stop_ns, self.cancel_due) if self.cancel_due else stop_ns,
                      'modeled_quote_seconds')
        self.interval(self.observed_from, stop_ns, 'observed_queue_seconds')
        self.active_from = self.observed_from = None
        return {str(i): dict(b) for i, b in enumerate(self.blocks)}


def iso_ns(value):
    return int(datetime.fromisoformat(value).timestamp() * NS)


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def write_json(path, value, cap=SUMMARY_CAP):
    # Each producer has bounded rows; check encoded length before writing.
    body = json.dumps(value, allow_nan=False, sort_keys=True, separators=(',', ':')).encode() + b'\n'
    if len(body) > cap:
        raise ValueError('derived summary byte cap exceeded')
    Path(path).write_bytes(body)
    return len(body)


def outcome_metrics(summary, cutoff_ns, end_ns):
    episodes = summary['episodes']
    completed = [e for e in episodes if not e.get('funding_unknown')]
    fills = [e for e in completed if Decimal(e['maker_attributed']) > 0]
    unknown = [e for e in episodes if e.get('funding_unknown')]
    def net(e):
        return Decimal(e['cash_known']) - Decimal(e['reserve_cost']) - Decimal(e['capital_cost'])
    blocks = defaultdict(lambda: {'episodes': 0, 'filled_episodes': 0, 'funding_unknown': 0,
                                  'closed_net_parity_usd': Decimal(0)})
    for e in episodes:
        block = min(3, max(0, (e['flat_ns'] - cutoff_ns) // (300 * NS)))
        b = blocks[str(block)]
        b['episodes'] += 1
        b['filled_episodes'] += Decimal(e['maker_attributed']) > 0
        if e.get('funding_unknown'):
            b['funding_unknown'] += 1
        else:
            b['closed_net_parity_usd'] += net(e)
    for b in blocks.values():
        b['closed_net_parity_usd'] = str(b['closed_net_parity_usd'])
    known_net = sum((net(e) for e in completed), Decimal(0))
    # A rate over the nominal horizon can hide early branch censoring. Supply
    # the denominator and report closed contribution separately from total.
    horizon_s = max(0, end_ns - cutoff_ns) / NS
    return {'closed_episodes': len(episodes), 'known_closed_filled_episodes': len(fills),
            'no_flow_episodes': sum(bool(e['no_flow']) for e in episodes),
            'funding_unknown_episodes': len(unknown),
            'positive_closed_episodes': sum(net(e) > 0 for e in fills),
            'target_closed_episodes': sum(net(e) >= Decimal('.10') for e in fills),
            'closed_net_parity_usd': str(known_net),
            'cumulative_closed_contribution_bp_of_fixed_branch_budget': str(known_net / Decimal(summary['budget_usd']) * 10000),
            'holdout_seconds_observed': horizon_s,
            'closed_contribution_per_hour_parity_usd': None if horizon_s == 0 else float(known_net) * 3600 / horizon_s,
            'total_result_known': summary['complete_net'] is not None,
            'five_minute_blocks': dict(blocks)}


def markdown(result):
    lines = ['# RH maker quote experiment', '',
             f"Replay status: **{result['status']}**. Capture: `{result['capture']}`.", '',
             'Public-flow counterfactuals; no private orders or fills. All combined dollar',
             'results assume USDG/USDC parity and omit conversion and transfer costs.',
             'Closed contribution excludes unresolved inventory and funding. It is not',
             'a complete strategy return where the total-result column is unknown.', '',
             '| Tier | Asset | Budget | Quote policy | Closed with flow | Wins >0 / ≥$0.10 | Closed contribution | Total result |',
             '|---|---|---:|---|---:|---:|---:|---|']
    rows = sorted(result['branches'], key=lambda r: (r['tier'] != 'standard', int(r['budget_usd']) != 1000,
                                                   r['asset'], int(r['budget_usd']), r['policy']))
    for r in rows:
        m = r['metrics']
        value = r['complete_net']
        total = 'unknown' if value is None else f"{float(value):+.4f}"
        closed = 'N/A' if not m['known_closed_filled_episodes'] else f"{float(m['closed_net_parity_usd']):+.4f}"
        lines.append(f"| {r['tier']} | {r['asset']} | {r['budget_usd']} | {r['policy']} | "
                     f"{m['known_closed_filled_episodes']} | {m['positive_closed_episodes']} / {m['target_closed_episodes']} | "
                     f"{closed} | {total} |")
    lines += ['', 'Sizes, quote policies, and fee tiers reuse the same public events.',
              '**Do not sum these independent counterfactual portfolios.** $1,000 is the',
              'primary benchmark; smaller sizes are predeclared sensitivities.', '',
              'See `analysis.json` for calibration readiness, censor reasons, currency cash',
              'flows, inventory, costs, time blocks, and exact input/code hashes. Full',
              'bounded lifecycle decisions are in `audit.jsonl.gz`. Open-position notional',
              'cash entries are synthetic accounting flows, not actual perp wallet balances.',
              'Twenty minutes provides a feasibility sample, not evidence of durable income.', '']
    return '\n'.join(lines)


def replay(capture, out, tiers=('standard', 'premium'), *, events=None):
    if not tiers or len(set(tiers)) != len(tiers) or any(t not in ('standard', 'premium') for t in tiers):
        raise ValueError('tiers must be unique frozen Standard/Premium scenarios')
    capture, out = Path(capture), Path(out)
    if out.exists():
        raise ValueError('output must be a new directory')
    manifest_path = capture / 'manifest.json'
    if manifest_path.stat().st_size > 1_000_000:
        raise ValueError('oversized capture manifest')
    manifest = json.loads(manifest_path.read_bytes())
    if manifest.get('schema') != 'rh-maker-public-capture-v1' or not manifest.get('read_only'):
        raise ValueError('requires stopped RH maker capture')
    if manifest['configured_seconds'] != 3000 or manifest['calibration_seconds'] != 1800 or manifest['holdout_seconds'] != 1200:
        raise ValueError('timeline differs from frozen 30/20 minute method')
    if digest(capture / 'metadata/normalized.json') != manifest['metadata_normalized_sha256']:
        raise ValueError('captured normalized metadata digest changed')
    if not 0 < manifest['configured_total_bytes'] <= 384_000_000:
        raise ValueError('capture budget exceeds frozen 384 MB method')
    start = iso_ns(manifest['started_utc'])
    cutoff, intended_end = start + 1800 * NS, start + 3000 * NS
    stop = min(iso_ns(manifest['ended_utc']), intended_end)
    out.mkdir(parents=True)
    audit = BoundedGzip(out / 'audit.jsonl.gz', AUDIT_CAP, reserve=1024)
    models, branches, by_asset = {}, [], defaultdict(list)
    lifecycle = {}
    errors, counts, terminal = [], Counter(), None
    status = 'complete'
    metadata = {}
    started_replay = time.monotonic()
    try:
        for tier in tiers:
            meta = policy_metadata(capture / 'metadata', tier)
            metadata[tier] = meta
            models[tier] = RhMakerModel(meta, start)
            for asset in ASSETS:
                for budget in SIZES:
                    for policy in POLICIES:
                        config = Config(asset, Decimal(budget), policy, tier=tier)
                        identity = {'asset': asset, 'budget_usd': budget, 'policy': policy, 'tier': tier}
                        tracker = LifecycleMetrics(cutoff, stop)
                        lifecycle[(tier, asset, budget, policy)] = tracker
                        def sink(row, ident=identity, stats=tracker):
                            audit.write(dict(row, **ident))
                            stats.consume(row)
                        branch = MakerBranch(config, meta[asset], audit_sink=sink)
                        branches.append(branch)
                        by_asset[asset].append(branch)
        stream = iter_events(capture, max_raw_bytes=384_000_000) if events is None else events
        last_ns = start
        for event in stream:
            kind = event.get('type', event.get('kind'))
            now = int(event.get('received_ns', event.get('receipt_ns', stop)))
            if kind == 'end':
                terminal = event
                break
            if now > intended_end:
                continue
            last_ns = now
            counts[kind] += 1
            for model in models.values():
                model.consume(event)
            targets = by_asset[event['asset']] if event.get('asset') in by_asset else branches
            for branch in targets:
                diagnostic = None
                if now >= cutoff and kind == 'book' and event.get('valid', True):
                    diagnostic = models[branch.cfg.tier].quote(branch.cfg.asset, int(branch.cfg.budget_usd),
                                                               branch.cfg.policy, now_ns=now)
                branch.process(event, quote_diag=diagnostic)
        if terminal is None:
            status = 'missing_terminal_event'
        elif terminal.get('truncated') or manifest.get('end_reason') != 'duration_limit':
            status = 'capture_incomplete'
        for branch in branches:
            branch.tick(stop)
            branch.process({'type': 'end', 'received_ns': stop, 'truncated': status != 'complete'})
    except (ValueError, KeyError, TypeError, ArithmeticError, OSError, SizeCapReached) as exc:
        status = 'audit_size_cap' if isinstance(exc, SizeCapReached) else 'replay_error'
        errors.append(f'{type(exc).__name__}: {str(exc)[:500]}')
        # Keep observed inventory and cash. No imaginary end-of-file fills.
        for branch in branches:
            branch.truncated = True
            if branch.unknown_reason is None:
                branch.unknown_reason = status
    finally:
        audit.close()
    summaries = []
    for branch in branches:
        row = branch.summary()
        row['metrics'] = outcome_metrics(row, cutoff, stop)
        key = (branch.cfg.tier, branch.cfg.asset, int(branch.cfg.budget_usd), branch.cfg.policy)
        row['lifecycle_by_five_minute_block'] = lifecycle[key].finish(stop)
        # Every audit row is retained in the bounded external stream; avoid
        # duplicating its per-branch sample in the main JSON document.
        row.pop('audit', None)
        summaries.append(row)
    files = ['scripts/analyze_rh_maker.py', 'scripts/rh_maker_config.py', 'scripts/rh_maker_engine.py',
             'scripts/rh_maker_model.py', 'scripts/rh_maker_events.py', 'scripts/maker_book_archive.py',
             'scripts/paper_streams.py', 'scripts/maker_capture.py']
    files += ['scripts/rh_maker_capture.py', 'reports/rh-small-maker-v1/method.md',
              'reports/rh-small-maker-v1/capture-freeze.json', 'reports/rh-small-maker-v1/launch.json']
    result = {'schema': 'rh-maker-replay-v1', 'status': status, 'errors': errors,
              'event_source': 'verified_capture' if events is None else 'injected_test_events',
              'capture': str(capture), 'capture_manifest_sha256': digest(manifest_path),
              'raw_sha256': manifest['frames_sha256'], 'started_ns': start, 'cutoff_ns': cutoff,
              'ended_ns': stop, 'intended_end_ns': intended_end,
              'counts': dict(counts), 'terminal_event': terminal,
              'models': {t: m.snapshot() for t, m in models.items()},
              'branches': summaries, 'assumptions': ASSUMPTIONS,
              'metadata': metadata, 'source_sha256': {f: digest(ROOT / f) for f in files},
              'audit_bytes': audit.bytes_written, 'audit_records': audit.records,
              'audit_sha256': digest(out / 'audit.jsonl.gz'),
              'replay_wall_seconds': time.monotonic() - started_replay}
    report = markdown(result).encode()
    if len(report) > 1_000_000:
        raise ValueError('report exceeds bounded reserve')
    write_json(out / 'analysis.json', result, SUMMARY_CAP - len(report))
    (out / 'REPORT.md').write_bytes(report)
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--tiers', nargs='+', choices=('standard', 'premium'), default=['standard', 'premium'])
    args = p.parse_args(argv)
    if len(set(args.tiers)) != len(args.tiers):
        p.error('tiers must be unique')
    result = replay(args.capture, args.out, tuple(args.tiers))
    print(json.dumps({'out': str(args.out), 'status': result['status'], 'branches': len(result['branches']),
                      'events': result['counts'], 'errors': result['errors']}))
    return 0 if result['status'] == 'complete' else 2


if __name__ == '__main__':
    raise SystemExit(main())
