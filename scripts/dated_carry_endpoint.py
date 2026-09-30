#!/usr/bin/env python3
"""Run the frozen sampler once; publish diagnostics only after its fixed endpoint."""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
from pathlib import Path
import time

try:
    from scripts import dated_carry_collector as collector
    from scripts import dated_carry_analysis as analysis
except ModuleNotFoundError:
    import dated_carry_collector as collector
    import dated_carry_analysis as analysis


def endpoint_check(config, now_ns):
    endpoint = collector.timestamp(config['t0_utc']) + collector.DURATION_NS
    if now_ns < endpoint:
        raise ValueError('fixed_endpoint_not_reached')
    return endpoint


def metadata_age_check(config, now_utc_ns, now_monotonic_ns):
    receipts = config['metadata_receipts']
    if len(receipts) != 2 or {r['role'] for r in receipts} != {'spot', 'future'}:
        raise ValueError('metadata_receipt_roster')
    for receipt in receipts:
        if not (0 <= now_utc_ns - receipt['utc_ns'] <= 120_000_000_000
                and 0 <= now_monotonic_ns - receipt['monotonic_ns'] <= 120_000_000_000):
            raise ValueError('fresh_metadata_launch_age_exceeded')


def launch_endpoint_check(config, launch, now_utc_ns, now_monotonic_ns, identity):
    endpoint = endpoint_check(config, now_utc_ns)
    mapping = launch['mapping']
    if {key: mapping.get(key) for key in ('host', 'boot_id')} != identity:
        raise ValueError('launch_clock_identity_changed')
    if mapping['t0_utc_ns'] != collector.timestamp(config['t0_utc']):
        raise ValueError('launch_t0_mismatch')
    if mapping['t0_monotonic_ns'] != mapping['monotonic_ns'] + mapping['t0_utc_ns'] - mapping['utc_ns']:
        raise ValueError('launch_mapping_inconsistent')
    if now_monotonic_ns < mapping['t0_monotonic_ns'] + collector.DURATION_NS:
        raise ValueError('monotonic_endpoint_not_reached')
    drift = now_utc_ns - (mapping['utc_ns'] + now_monotonic_ns - mapping['monotonic_ns'])
    if abs(drift) > collector.TOLERANCE_NS:
        raise ValueError('endpoint_clock_mapping_invalid')
    return endpoint


def final_rows(config, store, index):
    if index.get('schema') != 'dated-carry-collector-index-v1' or index.get('status') == 'running':
        raise ValueError('collector_must_be_terminal')
    entries = index.get('slots')
    if not isinstance(entries, list) or len(entries) != collector.SLOTS:
        raise ValueError('full_slot_roster_required')
    if [e.get('slot') for e in entries] != list(range(collector.SLOTS)):
        raise ValueError('ordered_unique_roster_required')
    rows = []
    t0 = collector.timestamp(config['t0_utc'])
    for entry in entries:
        if entry.get('planned_utc_ns') != t0 + entry['slot'] * collector.INTERVAL_NS:
            raise ValueError('index_planned_time_mismatch')
        record = collector.load_slot(store.path, entry)
        if record is None:
            rows.extend(analysis.invalid_rows(entry['slot'], entry.get('status', 'missing')))
        else:
            if record.get('status') != entry['status']:
                raise ValueError('index_sample_status_mismatch')
            rows.extend(analysis.evaluate_record(record, config))
    return rows


def finalize(args):
    config, store = collector.verify_freeze(args.config, args.config_sha256, args.study_dir,
                                           args.freeze, args.freeze_sha256)
    launch = json.loads(collector.read(store.path / 'terminal' / 'launch.json', 131072))
    endpoint = launch_endpoint_check(config, launch, time.time_ns(), time.monotonic_ns(),
                                     collector.clock_identity())
    with store.lock(finalize_only=True):
        if not (store.path / 'terminal' / 'launch.json').exists():
            raise ValueError('launch_evidence_required')
        index_path = store.path / 'terminal' / 'index.json'
        index_data = collector.read(index_path, collector.INDEX_RESERVE)
        index = json.loads(index_data)
        if index.get('status') == 'running':
            # Keep every previously attested hash. A sample written after the last
            # index update stays physically retained but unindexed/unevaluated.
            # Never regenerate the index from possibly changed sample contents.
            index = dict(index, status='interrupted_preserved_last_index')
        if index.get('status') == 'source_changed':
            raise ValueError('source_changed_no_economic_evaluation')
        store.write('terminal', 'analysis-claim.json', collector.body({
            'schema': 'dated-carry-analysis-claim-v1', 'endpoint_utc_ns': endpoint,
            'started_utc_ns': time.time_ns(), 'index_sha256': collector.digest(index_data),
            'single_attempt': True}))
        rows = final_rows(config, store, index)
        summary = analysis.summarize(rows)
        summary.update(collector_status=index['status'], index_sha256=collector.digest(index_data),
                       config_sha256=args.config_sha256, freeze_sha256=args.freeze_sha256,
                       endpoint_utc_ns=endpoint)
        collector.verify_freeze(args.config, args.config_sha256, args.study_dir,
                                args.freeze, args.freeze_sha256)
        if collector.read(index_path, collector.INDEX_RESERVE) != index_data:
            raise ValueError('terminal_index_changed')
        encoded = b''.join(analysis.json_bytes(row) for row in rows)
        compressed = gzip.compress(encoded, mtime=0)
        summary_data = analysis.json_bytes(summary)
        store.write('derived', 'rows.jsonl.gz', compressed)
        store.write('derived', 'summary.json', summary_data)
        store.write('terminal', 'analysis-result.json', collector.body({
            'status': 'complete', 'rows': len(rows), 'finished_utc_ns': time.time_ns(),
            'input_index_sha256': collector.digest(index_data),
            'outputs': {'derived/rows.jsonl.gz': {'sha256': collector.digest(compressed), 'bytes': len(compressed)},
                        'derived/summary.json': {'sha256': collector.digest(summary_data), 'bytes': len(summary_data)}},
            'usage_before_result': store.usage(), 'all_in_headroom_usd': None, 'closed_net_usd': None}))
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--launch', action='store_true')
    mode.add_argument('--finalize', action='store_true')
    parser.add_argument('--study-dir', type=Path)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--config-sha256')
    parser.add_argument('--freeze', type=Path)
    parser.add_argument('--freeze-sha256')
    args = parser.parse_args(argv)
    if not (args.launch or args.finalize):
        print('{"mode":"dry","network_performed":false}')
        return 0
    if not all((args.study_dir, args.config, args.config_sha256, args.freeze, args.freeze_sha256)):
        parser.error('all frozen identity arguments required')
    config, store = collector.verify_freeze(args.config, args.config_sha256, args.study_dir,
                                           args.freeze, args.freeze_sha256)
    if args.launch:
        metadata_age_check(config, time.time_ns(), time.monotonic_ns())
        with store.lock():
            asyncio.run(collector.live(config, store))
        # Even an interrupted acquisition gets no premature economic readout.
        launch = json.loads(collector.read(store.path / 'terminal' / 'launch.json', 131072))
        endpoint_mono = launch['mapping']['t0_monotonic_ns'] + collector.DURATION_NS
        while time.monotonic_ns() < endpoint_mono:
            time.sleep(max(0, min(30, (endpoint_mono-time.monotonic_ns())/1e9)))
    finalize(args)
    print('{"status":"endpoint_analysis_complete","closed_net_usd":null}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
