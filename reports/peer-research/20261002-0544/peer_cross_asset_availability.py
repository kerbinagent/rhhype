#!/usr/bin/env python3
"""Fixed feature-availability audit on three pinned exploratory captures.

Reuses the frozen baseline decision pass only. No forward quotes or economics.
Importing this runner reads no protocol, capture, or market observations.
"""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'scripts'))
from scripts import peer_cross_asset_diagnostic as baseline

BOUNDS = {**baseline.BOUNDS, 'run_timeout_seconds': 300,
          'output_gzip_bytes': 262144, 'readout_bytes': 16384}
CHUNK_NUMBERS = [1, 2, 3]
INVENTORY_SHA256 = 'f3ce24fc4854d6c2b29cd997b6e5b8754434c00779d24b78723edb8b7cdc6537'
REQUIRED_SOURCES = {'scripts/peer_cross_asset_availability.py',
                    'scripts/peer_cross_asset_diagnostic.py'}
CAPTURE_FILES = ('frames.jsonl.gz', 'manifest.json', 'status.json', 'terminal.json',
    'metadata/market_plan.json', 'metadata/normalized.json',
    *(f'metadata/{venue}_{kind}{suffix}' for venue in ('core', 'rh')
      for kind in ('assets', 'markets') for suffix in ('.json.gz', '.request.json')))
WINDOW_PINS = (('manifest.json', 'manifest_sha256'),
               ('frames.jsonl.gz', 'raw_sha256'),
               ('metadata/normalized.json', 'metadata_sha256'))


def read_json(path, cap):
    path = Path(path)
    if path.stat().st_size > cap:
        raise ValueError('JSON byte bound exceeded')
    return json.loads(path.read_bytes())


def verify_source_pins(pins, required):
    paths = [pin['path'] for pin in pins]
    if not pins or len(paths) != len(set(paths)) or not set(required) <= set(paths):
        raise ValueError('required unique source pins absent')
    for pin in pins:
        if baseline.digest(baseline.safe_relative(pin['path'])) != pin['sha256']:
            raise ValueError('source pin differs: '+pin['path'])


def verify_baseline_protocol(path, expected_sha):
    """Verify frozen design and sources without opening baseline input windows."""
    if not isinstance(expected_sha, str) or len(expected_sha) != 64 or baseline.digest(path) != expected_sha:
        raise ValueError('baseline protocol SHA256 differs')
    original = read_json(path, 65536)
    if (original.get('schema') != 'peer-cross-asset-v1'
            or original.get('status') != 'frozen-before-outcomes'
            or original.get('params') != baseline.PARAMS
            or original.get('bounds') != baseline.BOUNDS
            or original.get('venue') != baseline.VENUE or original.get('leader') != 'BTC'
            or original.get('targets') != list(baseline.TARGETS)
            or original.get('selected') != baseline.SELECTED):
        raise ValueError('frozen baseline design differs')
    verify_source_pins(original.get('source_pins', []), baseline.DEPENDENCIES)
    return original


def inventory_members(inventory):
    """Check the fixed 45-member export and ordered nonoverlapping spans."""
    chunks = inventory.get('chunks', [])
    names = [f'chunk-{number:06d}' for number in CHUNK_NUMBERS]
    records = inventory.get('members', [])
    paths = [member['path'] for member in records]
    expected = {f'{name}/capture/{relative}' for name in names for relative in CAPTURE_FILES}
    expected.update(f'{name}/seal.json' for name in names)
    if (inventory.get('schema') != 'rolling-exploratory-peer-export-inventory-v1'
            or [chunk['chunk'] for chunk in chunks] != names
            or len(paths) != 45 or len(set(paths)) != 45 or set(paths) != expected):
        raise ValueError('fixed export inventory identity differs')
    members = {member['path']: member for member in records}
    for member in records:
        if (type(member['bytes']) is not int or member['bytes'] < 0
                or not isinstance(member['sha256'], str) or len(member['sha256']) != 64
                or any(c not in '0123456789abcdef' for c in member['sha256'])):
            raise ValueError('inventory member byte count or SHA256 invalid')
    previous_end = None
    for chunk in chunks:
        name = chunk['chunk']
        seal = members[f'{name}/seal.json']
        files = [member for path, member in members.items() if path.startswith(name+'/capture/')]
        start = baseline.ordinary._epoch_ns(chunk['started_utc'])
        end = baseline.ordinary._epoch_ns(chunk['ended_utc'])
        if (seal['sha256'] != chunk['seal_sha256'] or seal['bytes'] != chunk['seal_bytes']
                or chunk['sealed_files'] != 14
                or chunk['sealed_file_bytes'] != sum(member['bytes'] for member in files)
                or start is None or end is None or end <= start
                or (previous_end is not None and start <= previous_end)):
            raise ValueError('export seal identity or chronological spans differ')
        previous_end = end
    return members


def bind_windows(windows, inventory, members):
    if len(windows) != 3 or [window['index'] for window in windows] != CHUNK_NUMBERS:
        raise ValueError('three ordered windows required')
    roots = set()
    for window, chunk in zip(windows, inventory['chunks']):
        capture = Path(window['capture'])
        if (capture.is_absolute() or '..' in capture.parts
                or capture.parts[-2:] != (chunk['chunk'], 'capture')):
            raise ValueError('window capture is not its exported chunk')
        roots.add(capture.parent.parent)
        for relative, key in WINDOW_PINS:
            if window[key] != members[f"{chunk['chunk']}/capture/{relative}"]['sha256']:
                raise ValueError('window hash is not its inventory member: '+key)
    if len(roots) != 1:
        raise ValueError('windows must share one extracted export root')
    return roots.pop()


def verify_seal_identity(seal, chunk, members):
    name = chunk['chunk']
    expected = {path.removeprefix(name+'/'): dict(bytes=member['bytes'], sha256=member['sha256'])
                for path, member in members.items() if path.startswith(name+'/capture/')}
    if (seal.get('schema') != 'rolling-research-seal-v1'
            or seal.get('chunk_id') != name
            or seal.get('role') != 'exploratory' or seal.get('state') != 'sealed_complete'
            or seal.get('files') != expected
            or any(seal.get(key) != chunk[key] for key in ('started_utc', 'ended_utc'))
            or seal.get('capture_started_ns') != baseline.ordinary._epoch_ns(chunk['started_utc'])
            or seal.get('capture_ended_ns') != baseline.ordinary._epoch_ns(chunk['ended_utc'])
            or seal.get('end_reason') != 'duration_limit' or seal.get('truncated') is not False
            or seal.get('frames_sha256') != members[f'{name}/capture/frames.jsonl.gz']['sha256']):
        raise ValueError('local seal role, chunk number, files or span differs')


def verify_availability_plan(plan_path, expected_sha):
    """Verify protocol, baseline, sources and all imported input identities."""
    plan_path = Path(plan_path)
    if (not isinstance(expected_sha, str) or len(expected_sha) != 64
            or baseline.digest(plan_path) != expected_sha):
        raise ValueError('external availability protocol SHA256 differs')
    plan = read_json(plan_path, 65536)
    if (plan.get('schema') != 'peer-cross-asset-availability-v1'
            or plan.get('status') != 'frozen-before-features'
            or plan.get('chunk_numbers') != CHUNK_NUMBERS
            or plan.get('bounds') != BOUNDS):
        raise ValueError('frozen availability protocol identity or bounds differ')
    original = verify_baseline_protocol(
        baseline.safe_relative(plan['baseline_protocol_path']),
        plan['baseline_protocol_sha256'])
    verify_source_pins(plan.get('source_pins', []), REQUIRED_SOURCES)
    windows = plan.get('windows', [])
    export = plan.get('input_export')
    if (not isinstance(export, dict) or not export.get('manifest_path')
            or export.get('manifest_sha256') != INVENTORY_SHA256):
        raise ValueError('fixed export manifest path and SHA256 required')
    inventory_path = baseline.safe_relative(export['manifest_path'])
    if baseline.digest(inventory_path) != export['manifest_sha256']:
        raise ValueError('committed input export manifest differs')
    inventory = read_json(inventory_path, 65536)
    members = inventory_members(inventory)
    extraction_root = bind_windows(windows, inventory, members)
    for relative, member in members.items():
        path = baseline.safe_relative(str(extraction_root/relative))
        if path.stat().st_size != member['bytes'] or baseline.digest(path) != member['sha256']:
            raise ValueError('exported local member bytes or SHA256 differs: '+relative)
    for window, chunk in zip(windows, inventory['chunks']):
        seal = read_json(ROOT/extraction_root/chunk['chunk']/'seal.json', 65536)
        verify_seal_identity(seal, chunk, members)
        manifest = read_json(ROOT/window['capture']/'manifest.json', 262144)
        if (manifest.get('schema') != 'single-venue-depth-public-capture-v1'
                or manifest.get('read_only') is not True
                or manifest.get('end_reason') != 'duration_limit'
                or manifest.get('truncated') is not False
                or manifest.get('selected_markets') != original['selected']
                or manifest.get('configured_seconds') != 600
                or manifest.get('configured_total_bytes') != BOUNDS['raw_bytes_per_capture']
                or manifest.get('frames_sha256') != window['raw_sha256']
                or any(manifest.get(key) != chunk[key] for key in ('started_utc', 'ended_utc'))):
            raise ValueError('availability capture endpoint, markets or bounds differ')
    return plan, original


def support_counts(selection):
    paired = {event['episode_id'] for event in selection['events']
              if event.get('control') is not None}
    return dict(selected_btc_episodes=len(selection['episodes']),
        selected_target_events=len(selection['events']),
        chosen_prior_controls=sum(event.get('control') is not None for event in selection['events']),
        btc_episodes_with_chosen_prior_control=len(paired))


def availability_decision(chunks):
    if len(chunks) != 3:
        raise ValueError('availability decision requires all three chunks')
    if all(chunk['support']['btc_episodes_with_chosen_prior_control'] >= 3 for chunk in chunks):
        classification = 'supports_separately_frozen_outcome_protocol'
    elif all(chunk['support']['selected_btc_episodes'] == 0 for chunk in chunks):
        classification = 'nonactivation'
    else:
        classification = 'insufficient_feature_support'
    return dict(classification=classification,
        separate_outcome_protocol_supported=classification == 'supports_separately_frozen_outcome_protocol',
        economic_evaluation=False, strategy_promotion=False,
        interpretation='Operational feature support only; adjacent chunks and assets remain dependent.')


def render_readout(chunks, decision):
    lines = ['Unchanged cross-asset signal: exploratory feature availability only.',
        'No forward quotes, economic returns, cash profit or strategy promotion.',
        'Full nine-target gates, both-direction control funnels and selected causal provenance are in the result JSON.',
        json.dumps(decision, sort_keys=True)]
    for chunk in chunks:
        selection, counts = chunk['selection'], chunk['support']
        lines.append(f"Chunk {chunk['index']:06d}: "+json.dumps(counts, sort_keys=True))
        lines.append('Leader funnel: '+json.dumps(selection['leader_counts'], sort_keys=True))
        for asset in baseline.TARGETS:
            gates = selection['target_counts'][asset]
            lines.append(f"{asset}: scheduled {gates.get('scheduled', 0)}; BTC episode decisions {gates.get('at_selected_btc_episode', 0)}; eligible target events {gates.get('eligible_target_event', 0)}; chosen controls {gates.get('control:selected', 0)}; missing controls {gates.get('control:no_eligible_earlier_control', 0)}.")
    return ('\n'.join(lines)+'\n').encode()


def run(plan_path, expected_sha, output, readout):
    started = time.monotonic()
    output, readout = Path(output), Path(readout)
    if output == readout or output.exists() or readout.exists():
        raise FileExistsError('immutable output exists or paths coincide')
    plan, original = verify_availability_plan(plan_path, expected_sha)
    chunks = []
    for window in plan['windows']:
        plan, original = verify_availability_plan(plan_path, expected_sha)
        directory = ROOT/window['capture']
        manifest = read_json(directory/'manifest.json', 262144)
        metadata = read_json(directory/'metadata/normalized.json', BOUNDS['metadata_bytes_per_capture'])['markets']
        terminals = []
        with baseline.adapter_configuration(original['selected'], original['bounds']):
            selection = baseline.decision_pass(
                baseline.archive_stream(window, terminals), metadata,
                baseline.ordinary._epoch_ns(manifest['started_utc']),
                params=original['params'], targets=original['targets'])
        if (len(terminals) != 1 or selection['leader_counts'].get('scheduled') != 408
                or any(selection['target_counts'].get(asset, {}).get('scheduled') != 408
                       for asset in baseline.TARGETS)):
            raise ValueError('complete calendar or adapter terminal differs')
        terminal = terminals[0]
        provenance = {key: terminal[key] for key in ('decoded_bytes', 'archive_bytes',
            'counts', 'metadata_sha256', 'raw_gzip_sha256', 'manifest_sha256',
            'max_receipt_gap_ns', 'adapter_sha256', 'book_decoder_sha256')}
        chunks.append(dict(index=window['index'], capture=window['capture'],
            started_utc=manifest['started_utc'], ended_utc=manifest['ended_utc'],
            selection=selection, support=support_counts(selection), provenance=provenance))
        if time.monotonic()-started > BOUNDS['run_timeout_seconds']:
            raise TimeoutError('availability runtime bound exceeded')
    decision = availability_decision(chunks)
    report = dict(schema='peer-cross-asset-availability-result-v1',
        protocol_sha256=expected_sha, baseline_protocol_path=plan['baseline_protocol_path'],
        baseline_protocol_sha256=plan['baseline_protocol_sha256'], params=original['params'],
        input_export=plan['input_export'], source_pins=plan['source_pins'],
        validation_claim=False, economic_evaluation=False,
        chunk_numbers=CHUNK_NUMBERS, chunks=chunks, decision=decision)
    packed = gzip.compress(baseline.encode(report), mtime=0)
    body = render_readout(chunks, decision)
    if len(packed) > BOUNDS['output_gzip_bytes'] or len(body) > BOUNDS['readout_bytes']:
        raise ValueError('availability derived output exceeds frozen cap')
    verify_availability_plan(plan_path, expected_sha)
    if time.monotonic()-started > BOUNDS['run_timeout_seconds']:
        raise TimeoutError('availability runtime bound exceeded before publication')
    if output.exists() or readout.exists():
        raise FileExistsError('immutable availability output already exists')
    baseline.publish_exclusive(output, packed)
    baseline.publish_exclusive(readout, body)
    return dict(protocol_sha256=expected_sha, gzip_bytes=len(packed),
                readout_bytes=len(body), decision=decision)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--expected-plan-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--readout', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.plan, args.expected_plan_sha256, args.output, args.readout), sort_keys=True))


if __name__ == '__main__':
    main()
