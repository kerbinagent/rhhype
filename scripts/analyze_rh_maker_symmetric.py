#!/usr/bin/env python3
"""Offline, protocol-gated symmetric RH maker replay of a *future* capture.

All 192 ledgers are independent public-flow counterfactuals. This module never
connects to a venue or creates a capture. A protocol must be frozen separately
before the input capture starts.
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
from scripts.analyze_rh_maker import LifecycleMetrics, outcome_metrics
from scripts.maker_capture import BoundedGzip, SizeCapReached
from scripts.rh_maker_config import ASSETS, SIZES, POLICIES, ASSUMPTIONS, policy_metadata
from scripts.rh_maker_engine import Config
from scripts.rh_maker_late_flow_guard import GuardedMakerBuyBranch, GuardedMakerSellBranch
from scripts.rh_maker_events import iter_events, _epoch_ns
from scripts.rh_maker_model import RhMakerModel
from scripts.rh_maker_sell_model import RhMakerSellModel

NS = 1_000_000_000
SCHEMA = 'rh-maker-symmetric-protocol-v1'
AUDIT_CAP = 192_000_000
SUMMARY_CAP = 64_000_000
RAW_CAP = 384_000_000
DIRECTIONS = {'buy': (RhMakerModel, GuardedMakerBuyBranch),
              'sell': (RhMakerSellModel, GuardedMakerSellBranch)}
# The import closure used by replay and public-frame decoding. A future method
# document is an additional, protocol-selected required hash.
REQUIRED_SOURCES = (
    'scripts/analyze_rh_maker_symmetric.py', 'scripts/analyze_rh_maker.py',
    'scripts/rh_maker_config.py', 'scripts/rh_maker_engine.py',
    'scripts/rh_maker_model.py', 'scripts/rh_maker_sell_engine.py',
    'scripts/rh_maker_sell_model.py', 'scripts/rh_maker_late_flow_guard.py',
    'scripts/rh_maker_events.py',
    'scripts/maker_book_archive.py', 'scripts/maker_capture.py',
    'scripts/paper_streams.py', 'scripts/rh_maker_capture.py',
    'scripts/analyze_maker_equity.py', 'scripts/analyze_maker_capture.py',
    'scripts/analyze_maker_roundtrip.py',
)


def digest(path: Path) -> str:
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _utc_ns(value: str) -> int:
    if not isinstance(value, str):
        raise ValueError('timestamp must be ISO8601 text')
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() != timezone.utc.utcoffset(stamp):
        raise ValueError('timestamp must have a UTC offset')
    return _epoch_ns(value)


def _source_path(relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError('protocol source paths must be repository relative')
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise ValueError(f'protocol source path outside repository or missing: {relative}')
    return path


def build_protocol(frozen_at: str, method_path: str, metadata_dir: Path) -> dict:
    """Build a reviewable protocol object; caller must explicitly freeze it.

    This helper does not choose a capture, write a protocol, or set a freeze
    timestamp. The method file and all imported replay source are hashed now.
    """
    _utc_ns(frozen_at)
    if method_path in REQUIRED_SOURCES:
        raise ValueError('method must be a separate document')
    paths = (*REQUIRED_SOURCES, method_path)
    return {'schema': SCHEMA, 'frozen_at': frozen_at,
            'method_path': method_path,
            'source_sha256': {name: digest(_source_path(name)) for name in paths},
            'metadata_normalized_sha256': digest(Path(metadata_dir) / 'normalized.json')}


def verify_protocol(protocol_path: Path, capture: Path) -> tuple[dict, dict, int, int, int]:
    protocol_path, capture = Path(protocol_path), Path(capture)
    if protocol_path.stat().st_size > 1_000_000:
        raise ValueError('protocol exceeds 1 MB')
    protocol = json.loads(protocol_path.read_bytes())
    if protocol.get('schema') != SCHEMA:
        raise ValueError('symmetric protocol schema required')
    frozen_ns = _utc_ns(protocol.get('frozen_at'))
    method_path = protocol.get('method_path')
    if not isinstance(method_path, str) or method_path in REQUIRED_SOURCES:
        raise ValueError('separate method_path required')
    expected = protocol.get('source_sha256')
    if not isinstance(expected, dict) or set(expected) != set(REQUIRED_SOURCES) | {method_path}:
        raise ValueError('protocol source hash inventory incomplete or unexpected')
    for name, claimed in expected.items():
        if not isinstance(claimed, str) or len(claimed) != 64 or digest(_source_path(name)) != claimed:
            raise ValueError(f'protocol source hash mismatch: {name}')
    manifest_path = capture / 'manifest.json'
    if manifest_path.stat().st_size > 1_000_000:
        raise ValueError('capture manifest exceeds 1 MB')
    manifest = json.loads(manifest_path.read_bytes())
    if manifest.get('schema') != 'rh-maker-public-capture-v1' or manifest.get('read_only') is not True:
        raise ValueError('stopped read-only RH maker capture required')
    if (manifest.get('configured_seconds'), manifest.get('calibration_seconds'),
            manifest.get('holdout_seconds')) != (3000, 1800, 1200):
        raise ValueError('capture must use strict 30/20 minute split')
    budget = manifest.get('configured_total_bytes')
    if type(budget) is not int or not 0 < budget <= RAW_CAP:
        raise ValueError('capture raw budget exceeds 384 MB')
    start, end = _utc_ns(manifest.get('started_utc')), _utc_ns(manifest.get('ended_utc'))
    if start < frozen_ns:
        raise ValueError('capture started before symmetric protocol was frozen')
    if end < start or end > start + 3001 * NS:
        raise ValueError('capture duration invalid')
    meta_hash = digest(capture / 'metadata/normalized.json')
    if (meta_hash != manifest.get('metadata_normalized_sha256')
            or meta_hash != protocol.get('metadata_normalized_sha256')):
        raise ValueError('captured/frozen normalized metadata mismatch')
    return protocol, manifest, start, start + 1800 * NS, min(end, start + 3000 * NS)


def _write_json(path: Path, body: dict, cap: int) -> None:
    encoded = (json.dumps(body, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    if len(encoded) > cap:
        raise ValueError('symmetric summary exceeds 64 MB bound')
    path.write_bytes(encoded)


def symmetric_outcome_metrics(summary: dict, cutoff_ns: int, end_ns: int) -> dict:
    """Known closed economics exclude funding and late-flow uncertainty."""
    all_episodes = summary['episodes']
    eligible = [row for row in all_episodes if not row.get('execution_unknown')]
    metrics = outcome_metrics(dict(summary, episodes=eligible), cutoff_ns, end_ns)
    metrics['closed_episodes'] = len(all_episodes)
    metrics['no_flow_episodes'] = sum(bool(row['no_flow']) for row in all_episodes)
    metrics['funding_unknown_episodes'] = sum(bool(row.get('funding_unknown')) for row in all_episodes)
    metrics['execution_unknown_episodes'] = sum(bool(row.get('execution_unknown')) for row in all_episodes)
    for row in all_episodes:
        if row.get('execution_unknown'):
            block = str(min(3, max(0, (row['flat_ns'] - cutoff_ns) // (300 * NS))))
            bucket = metrics['five_minute_blocks'].setdefault(block, {
                'episodes': 0, 'filled_episodes': 0, 'funding_unknown': 0,
                'closed_net_parity_usd': '0'})
            bucket['episodes'] += 1
            bucket['filled_episodes'] += Decimal(row['maker_attributed']) > 0
            bucket['funding_unknown'] += bool(row.get('funding_unknown'))
            bucket['execution_unknown'] = bucket.get('execution_unknown', 0) + 1
    return metrics


def _report(result: dict) -> str:
    lines = [
        '# Symmetric RH maker public-flow replay', '',
        f"Status: **{result['status']}**. Branches: {len(result['branches'])}.", '',
        'Buy and sell directions, fee tiers, sizes, and policies are independent',
        'counterfactual ledgers driven by the same public events. Do not sum them.',
        'No private orders or fills were observed. Combined USD values assume',
        'USDG/USDC parity and omit conversion. Open obligations have unknown total',
        'results; closed contribution is not a complete portfolio return.', '',
        '| Direction | Tier | Asset | Size | Policy | Known closed with flow | Execution unknown | Closed contribution | Total |',
        '|---|---|---|---:|---|---:|---:|---:|---|',
    ]
    for row in sorted(result['branches'], key=lambda r: (r['direction'], r['tier'], r['asset'],
                                                         int(r['budget_usd']), r['policy'])):
        m = row['metrics']
        total = 'unknown' if row['complete_net'] is None else row['complete_net']
        lines.append(f"| {row['direction']} | {row['tier']} | {row['asset']} | {row['budget_usd']} | "
                     f"{row['policy']} | {m['known_closed_filled_episodes']} | "
                     f"{m['execution_unknown_episodes']} | "
                     f"{m['closed_net_parity_usd']} | {total} |")
    lines += ['', 'Five-minute lifecycle counters, calibration fits, source hashes,',
              'and per-branch costs are in `analysis.json`; the bounded event audit',
              'is in `audit.jsonl.gz`. The 20-minute holdout is descriptive only.', '']
    return '\n'.join(lines)


def replay(capture: Path, out: Path, protocol_path: Path, *, events=None) -> dict:
    """Replay one verified future capture; `events` is explicit test injection."""
    capture, out = Path(capture), Path(out)
    protocol, manifest, start, cutoff, stop = verify_protocol(protocol_path, capture)
    if out.exists():
        raise ValueError('output must be a new directory')
    metadata = {tier: policy_metadata(capture / 'metadata', tier)
                for tier in ('standard', 'premium')}
    intended_end = start + 3000 * NS
    out.mkdir(parents=True)
    audit = BoundedGzip(out / 'audit.jsonl.gz', AUDIT_CAP, reserve=1024)
    models, branches, by_asset, lifecycle = {}, [], defaultdict(list), {}
    counts, errors, terminal = Counter(), [], None
    status, started_wall = 'complete', time.monotonic()
    try:
        for direction, (model_type, branch_type) in DIRECTIONS.items():
            for tier in ('standard', 'premium'):
                meta = metadata[tier]
                models[(direction, tier)] = model_type(meta, start)
                for asset in ASSETS:
                    for budget in SIZES:
                        for policy in POLICIES:
                            config = Config(asset, Decimal(budget), policy, tier=tier)
                            ident = {'direction': direction, 'tier': tier,
                                     'asset': asset, 'budget_usd': budget, 'policy': policy}
                            tracker = LifecycleMetrics(cutoff, stop)
                            lifecycle[(direction, tier, asset, budget, policy)] = tracker
                            def sink(row, identity=ident, metrics=tracker):
                                audit.write(dict(row, **identity))
                                metrics.consume(row)
                            branch = branch_type(config, meta[asset], audit_sink=sink)
                            branches.append((direction, branch))
                            by_asset[asset].append((direction, branch))
        stream = iter_events(capture, max_raw_bytes=RAW_CAP) if events is None else events
        for event in stream:
            kind = event.get('type', event.get('kind'))
            now = int(event.get('received_ns', event.get('receipt_ns', stop)))
            if kind == 'end':
                terminal = event
                break
            if now > intended_end:
                continue
            counts[kind] += 1
            for model in models.values():
                model.consume(event)
            targets = by_asset[event['asset']] if event.get('asset') in by_asset else branches
            for direction, branch in targets:
                diag = None
                if now >= cutoff and kind == 'book' and event.get('valid', True):
                    diag = models[(direction, branch.cfg.tier)].quote(
                        branch.cfg.asset, int(branch.cfg.budget_usd), branch.cfg.policy, now_ns=now)
                branch.process(event, quote_diag=diag)
        if terminal is None:
            status = 'missing_terminal_event'
        elif terminal.get('truncated') or manifest.get('end_reason') != 'duration_limit' or stop < intended_end:
            status = 'capture_incomplete'
        for _, branch in branches:
            branch.tick(stop)
            branch.process({'type': 'end', 'received_ns': stop, 'truncated': status != 'complete'})
    except (ValueError, KeyError, TypeError, ArithmeticError, OSError, SizeCapReached) as exc:
        status = 'audit_size_cap' if isinstance(exc, SizeCapReached) else 'replay_error'
        errors.append(f'{type(exc).__name__}: {str(exc)[:500]}')
        for _, branch in branches:
            branch.truncated = True
            if branch.unknown_reason is None:
                branch.unknown_reason = status
    finally:
        audit.close()
    summaries = []
    for direction, branch in branches:
        row = branch.summary()
        row['direction'] = direction
        row['orientation'] = ('rh_maker_buy_hl_taker_sell' if direction == 'buy'
                              else 'rh_maker_sell_hl_taker_buy')
        row['metrics'] = symmetric_outcome_metrics(row, cutoff, stop)
        key = (direction, branch.cfg.tier, branch.cfg.asset,
               int(branch.cfg.budget_usd), branch.cfg.policy)
        row['lifecycle_by_five_minute_block'] = lifecycle[key].finish(stop)
        row.pop('audit', None)
        summaries.append(row)
    result = {
        'schema': 'rh-maker-symmetric-replay-v1', 'status': status, 'errors': errors,
        'event_source': 'verified_capture' if events is None else 'injected_test_events',
        'capture': str(capture), 'capture_manifest_sha256': digest(capture / 'manifest.json'),
        'raw_sha256': manifest['frames_sha256'], 'protocol_sha256': digest(Path(protocol_path)),
        'protocol_schema': SCHEMA, 'protocol_frozen_at': protocol['frozen_at'],
        'method_path': protocol['method_path'],
        'source_sha256': protocol['source_sha256'],
        'metadata_normalized_sha256': protocol['metadata_normalized_sha256'],
        'started_ns': start, 'cutoff_ns': cutoff, 'ended_ns': stop,
        'intended_end_ns': intended_end, 'counts': dict(counts), 'terminal_event': terminal,
        'models': {d: {t: model.snapshot() for (direction, t), model in models.items()
                       if direction == d} for d in DIRECTIONS},
        'branches': summaries, 'assumptions': ASSUMPTIONS, 'metadata': metadata,
        'audit_bytes': audit.bytes_written, 'audit_records': audit.records,
        'audit_sha256': digest(out / 'audit.jsonl.gz'),
        'replay_wall_seconds': time.monotonic() - started_wall,
    }
    report = _report(result).encode()
    if len(report) > 1_000_000:
        raise ValueError('report exceeds bounded reserve')
    _write_json(out / 'analysis.json', result, SUMMARY_CAP - len(report))
    (out / 'REPORT.md').write_bytes(report)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, required=True)
    args = parser.parse_args(argv)
    result = replay(args.capture, args.out, args.protocol)
    print(json.dumps({'out': str(args.out), 'status': result['status'],
                      'branches': len(result['branches']), 'errors': result['errors']}))
    return 0 if result['status'] == 'complete' else 2


if __name__ == '__main__':
    raise SystemExit(main())
