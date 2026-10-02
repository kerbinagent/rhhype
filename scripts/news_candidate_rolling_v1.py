#!/usr/bin/env python3
"""One future rolling attempt; unchanged news rules, descriptive ledgers only.

Default dry does not inspect the rolling store or nominate/pin/decode anything.
Root must freeze and review the final plan before the fixed cutoff. No collector,
network request, order, replacement attempt or automatic unpin is implemented.
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True
import argparse
from contextlib import contextmanager
import datetime
from decimal import Decimal as D
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import single_venue_news_ordinary_fix as fix
from scripts import rolling_research_capture as rolling
from scripts import single_venue_strategy as strategy
from scripts import run_single_venue_study as runner
from scripts import audit_single_venue_study as cash

SOURCE = 'scripts/news_candidate_rolling_v1.py'
TEST = 'tests/test_news_candidate_rolling_v1.py'
PLAN = ROOT / 'reports/experiment-storage/news-candidate-rolling-v1.json'
ALLOCATION = {'path': 'reports/experiment-storage/news-candidate-rolling-v1-allocation.json',
              'sha256': 'f179818fbac5f6f062c19631665806cde8b9e40bce10f0cce83183fb0c5418d8'}
PARENT = {'path': 'reports/experiment-storage/single-venue-news-inventory-fix-v2.json',
          'sha256': 'e4e5d4b56e2a2a461123fe23067e749b44ae043c4e97f6f9b37291b6d1d42793'}
ROLLING_PARENT = {'path': 'reports/experiment-storage/rolling-research-capture-v1.json',
                  'sha256': 'e19c6ed52ace7310e8a717bf39b2cf707976b2fe92c6ff8eb6ed34f738936ac4'}
CHUNK_PLAN = {'path': 'reports/experiment-storage/rolling-research-chunk-v1.json',
              'sha256': 'ab5e7e39a48ecde0e7e5f6205b325984659606867773c9ad984bc633267414cb'}
RECOVERY = {'path': 'reports/experiment-storage/rolling-research-capture-recovery-v1.json',
            'sha256': 'c4fb5e6519c10dbc2e4c2f353fbece5f4754a3f2a4cfe7ca251fb84fddae470f'}
OUT = ROOT / 'reports/news-candidate-rolling-v1/run-v1'
STEM = 'news-candidate-rolling-v1'
OWNER = 'news_candidate_rolling_v1'
SCHEMA = 'news-candidate-rolling-v1'
CUTOFF_NS = 1790953200000000000  # 2026-10-02 15:00:00 UTC
DEADLINE_NS = 1790964000000000000  # 2026-10-02 18:00:00 UTC
BOUNDS = {**fix.BOUNDS, 'raw_bytes': 67108864 + 262144}
CAPS = {**fix.CAPS, 'controls': 49152}
LIMITS = dict(source=98304, tests_and_temporary_fixtures=65536,
              protocol_and_preparation=32768, ledger_outputs=2621440,
              comparison_outputs=98304, control_provenance=49152,
              readout=16384, margin=163840)
FAMILIES = ('relative', 'depth')
ASSETS = tuple(rolling.ASSETS)
RULES = {'relative': ('gap_fade', 'leader_follow', 'local_shock_fade'),
         'depth': ('depth_fade', 'depth_follow')}
NS = 10**9


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path, cap=16384):
    path = Path(path)
    require(not path.is_symlink() and path.is_file() and path.stat().st_size <= cap, 'bounded_regular_json')
    return json.loads(path.read_bytes())


def pin_file(pin):
    path = ROOT / pin['path']
    require(path.resolve() == ROOT.resolve() / pin['path'] and not path.is_symlink(), 'pin_path')
    require(path.is_file() and path.stat().st_size <= 1048576, 'pin_missing_or_unbounded')
    if 'bytes' in pin:
        require(type(pin['bytes']) is int and path.stat().st_size == pin['bytes'], 'pin_bytes')
    require(fix.sha(path) == pin['sha256'], 'pin_sha256')
    return path


def source_contracts():
    """Validate referenced original chains without configuring old run routes."""
    documents = [read(pin_file(p), 65536) for p in (ALLOCATION, PARENT, ROLLING_PARENT, CHUNK_PLAN, RECOVERY)]
    allocation, parent, rp, cp, recovery = documents
    require(allocation['categories_bytes'] == LIMITS and allocation['reserved_bytes'] == 3145728, 'allocation_scope')
    require(parent['execution_parameters'] == strategy.PARAMS and parent['assets'] == list(ASSETS), 'original_science')
    require(parent['selected'] == rolling.SELECTED and parent['families'] == list(FAMILIES), 'original_cohort')
    require(rp['capture_plan_sha256'] == CHUNK_PLAN['sha256'] and cp['selected'] == rolling.SELECTED, 'rolling_plan_binding')
    # The original news plan carries the strategy/replay/auditor transitive pins.
    news_plan = read(pin_file({'path': parent['capture_plan'], 'sha256': parent['original_capture_plan_sha256']}), 65536)
    require(news_plan['execution_parameters'] == strategy.PARAMS, 'original_execution')
    for doc in (parent, news_plan, rp, cp, recovery):
        pins = doc.get('source_pins')
        require(isinstance(pins, list) and bool(pins), 'referenced_source_pins')
        for pin in pins:
            pin_file(pin)
    return parent


def required_fields():
    return dict(allocation=ALLOCATION, original_analysis=PARENT, rolling_parent=ROLLING_PARENT,
                 rolling_chunk_plan=CHUNK_PLAN, rolling_recovery=RECOVERY,
                 control_root=str(OUT.relative_to(ROOT)), output_stem=STEM,
                 store_root='data/rolling/market-research-v1', pin_owner=OWNER,
                 cutoff_ns=CUTOFF_NS, selection_deadline_ns=DEADLINE_NS,
                 assets=list(ASSETS), selected=rolling.SELECTED, families=list(FAMILIES),
                 execution_parameters=strategy.PARAMS, adapter_bounds=BOUNDS, output_caps=CAPS,
                 duration_seconds=600, analysis_seconds=3600, child_seconds=600,
                 primary={'family': 'depth', 'asset': 'NEAR', 'venue': 'lighter', 'rule': 'depth_follow'},
                 comparator={'family': 'depth', 'asset': 'NEAR', 'venue': 'lighter', 'rule': 'depth_fade'})


def verify(expected, *, before_cutoff=False, now_ns=None):
    require(isinstance(expected, str) and re.fullmatch('[0-9a-f]{64}', expected), 'exact_plan_sha_required')
    require(fix.sha(PLAN) == expected, 'plan_sha256')
    p = read(PLAN, 16384)
    require(p.get('schema') == SCHEMA and p.get('status') == 'frozen', 'plan_not_frozen')
    parent = source_contracts()
    require(all(p.get(k) == v for k, v in required_fields().items()), 'plan_scope')
    frozen = p.get('frozen_utc_ns')
    require(type(frozen) is int and 0 < frozen < CUTOFF_NS, 'freeze_missed_cutoff')
    require(p.get('store_identity_sha256') and re.fullmatch('[0-9a-f]{64}', p['store_identity_sha256']), 'store_identity_pin')
    pins = p.get('source_pins')
    require(isinstance(pins, list) and len(pins) == 2 and {x.get('path') for x in pins} == {SOURCE, TEST}, 'own_source_pins')
    for pin in pins:
        path = pin_file(pin)
        require(path.stat().st_size <= (LIMITS['source'] if pin['path'] == SOURCE else LIMITS['tests_and_temporary_fixtures']), 'own_source_cap')
    # The inherited source chain is independently verified, not duplicated in this plan.
    require(parent['execution_parameters'] == p['execution_parameters'], 'science_changed')
    if before_cutoff:
        now = time.time_ns() if now_ns is None else now_ns
        require(frozen <= now < CUTOFF_NS, 'launch_missed_cutoff')
    return p


def control(name, value, *, packed=False):
    """Atomic no-overwrite controls; pending copies count against the total cap."""
    body = fix.encode(value)
    require(len(body) <= 131072, 'decoded_control_cap')
    if packed:
        body = gzip.compress(body, mtime=0)
    require(len(body) <= 8192, 'control_file_cap')
    path = OUT / name
    used = fix.tree_bytes(OUT)
    require(used + 2 * len(body) <= CAPS['controls'], 'control_total_peak_cap')
    pending = path.with_name(path.name + '.pending')
    with pending.open('xb') as stream:
        stream.write(body); stream.flush(); os.fsync(stream.fileno())
    os.link(pending, path)  # Fails without replacing existing output.
    pending.unlink()
    return path


def select_attempt(index, cutoff=CUTOFF_NS):
    """Pure reservation identity selection. State/coverage/prices cannot rank attempts."""
    require(index.get('schema') == 'rolling-research-index-v1', 'index_schema')
    choices = []
    for name, entry in index.get('chunks', {}).items():
        n, launched = entry.get('number'), entry.get('launched_ns')
        require(type(n) is int and name == f'chunk-{n:06d}' and 1 <= n <= rolling.MAX_CHUNKS, 'reservation_number')
        require(type(launched) is int and launched > 0 and entry.get('role') == rolling.role(n), 'reservation_identity')
        if entry['role'] == 'reserved_validation' and launched >= cutoff:
            choices.append(dict(chunk=name, number=n, role=entry['role'], launched_ns=launched))
    # Expiry cannot silently remove the first attempt from the denominator.
    for entry in index.get('expired', []):
        if entry.get('role') == 'reserved_validation' and entry.get('started_ns', 0) >= cutoff:
            name = entry['chunk_id']
            n = int(name.removeprefix('chunk-'))
            choices.append(dict(chunk=name, number=n, role=entry['role'], launched_ns=entry['started_ns']))
    if not choices:
        return None
    choices.sort(key=lambda x: x['number'])
    require(len({x['number'] for x in choices}) == len(choices), 'duplicate_reservation')
    require(all(a['launched_ns'] <= b['launched_ns'] for a, b in zip(choices, choices[1:])), 'reservation_clock_regression')
    return choices[0]


def store_identity(p):
    store = rolling.Store()
    path = store.root / 'identity.json'
    identity = read(path, 16384)
    require(fix.sha(path) == p['store_identity_sha256'], 'store_identity_changed')
    require(identity.get('schema') == 'rolling-research-store-v1' and identity.get('plan_sha256') == ROLLING_PARENT['sha256']
            and identity.get('budget_bytes') == 2000000000, 'store_contract')
    return store


def nominate(p, expected, *, wall=time.time_ns, sleep=time.sleep):
    store = store_identity(p)
    limit = time.monotonic() + max(0, (DEADLINE_NS - wall()) / NS)
    while wall() <= DEADLINE_NS and time.monotonic() <= limit:
        verify(expected)
        choice = select_attempt(store.index())
        if choice:
            require(choice['launched_ns'] <= DEADLINE_NS, 'first_attempt_after_deadline')
            control('nomination.json', dict(schema=SCHEMA + '-nomination', plan_sha256=expected,
                nominated_utc=fix.utc(), selection_fields=['role', 'number', 'launched_ns'], **choice))
            return choice
        sleep(min(15, max(0, (DEADLINE_NS - wall()) / NS)))
    raise TimeoutError('no_reserved_attempt_before_selection_deadline')


def wait_selected(p, expected, choice, *, wall=time.time_ns, sleep=time.sleep):
    store = store_identity(p)
    # Nomination is final; an attempt launching by 18:00 gets its original 720s child bound.
    last = min(choice['launched_ns'] + 780 * NS, DEADLINE_NS + 780 * NS)
    limit = time.monotonic() + max(0, (last - wall()) / NS)
    while wall() <= last and time.monotonic() <= limit:
        verify(expected)
        entry = store.index()['chunks'].get(choice['chunk'])
        require(entry is not None, 'selected_attempt_expired_or_missing')
        require(all(entry.get(k) == choice[k] for k in ('number', 'role', 'launched_ns')), 'selected_identity_changed')
        if entry['state'] == 'sealed_failed':
            failed_attempt(store, expected, choice, entry)
            raise ValueError('selected_attempt_failed')
        if entry['state'] == 'sealed_complete':
            store.pin([choice['chunk']], OWNER)
            control('pin.json', dict(chunk=choice['chunk'], owner=OWNER, seal_sha256=entry['seal_sha256'],
                                    plan_sha256=expected, retained_until_root_release=True))
            return
        require(entry['state'] == 'collecting', 'selected_state_unknown')
        sleep(min(15, max(0, (last - wall()) / NS)))
    raise TimeoutError('selected_attempt_never_completed')


def failed_attempt(store, expected, choice, entry):
    """Retain failed producer identities without opening its unpinned raw payload."""
    result = dict(schema=SCHEMA + '-failed-attempt', plan_sha256=expected, **choice,
                  state='sealed_failed', seal_sha256=entry.get('seal_sha256'),
                  raw_opened=False, declared_files=None, identity_error=None)
    try:
        path = store.root / choice['chunk'] / 'seal.json'
        seal = read(path, 65536)
        require(fix.sha(path) == entry.get('seal_sha256') and seal.get('chunk_id') == choice['chunk']
                and seal.get('role') == choice['role'] and seal.get('state') == 'sealed_failed', 'failed_seal_identity')
        # These are seal-authenticated producer declarations, not verification of raw files.
        require(isinstance(seal.get('files'), dict) and set(seal['files']) <= rolling.CAPTURE_NAMES, 'failed_inventory')
        declared = {}
        for name, item in seal['files'].items():
            require(isinstance(item, dict) and type(item.get('bytes')) is int and item['bytes'] >= 0
                    and isinstance(item.get('sha256'), str) and re.fullmatch('[0-9a-f]{64}', item['sha256']), 'failed_file_identity')
            declared[name] = dict(bytes=item['bytes'], sha256=item['sha256'])
        result['declared_files'] = declared
        result['failure'] = seal.get('failure', 'producer_failed')[:700]
    except Exception as exc:
        result['identity_error'] = type(exc).__name__ + ': ' + str(exc)[:300]
    control('failed-attempt.json', result)


def nomination(expected):
    n = read(OUT / 'nomination.json', 8192)
    require(n['schema'] == SCHEMA + '-nomination' and n['plan_sha256'] == expected, 'nomination_binding')
    require(type(n['number']) is int and n['chunk'] == f"chunk-{n['number']:06d}" and rolling.role(n['number']) == n['role'] == 'reserved_validation', 'nomination_role')
    require(CUTOFF_NS <= n['launched_ns'] <= DEADLINE_NS, 'nomination_clock')
    return n


def input_snapshot(p):
    """Pinned exact selected inventory. Hash raw opaquely; never replay to validate a seal."""
    expected = fix.sha(PLAN)
    n = nomination(expected)
    store = store_identity(p)
    entry = store.index()['chunks'].get(n['chunk'])
    require(entry and entry['state'] == 'sealed_complete' and OWNER in entry['pins'], 'selected_must_be_pinned_complete')
    require(all(entry.get(k) == n[k] for k in ('number', 'role', 'launched_ns')), 'selected_entry_identity')
    directory = store.root / n['chunk']
    inventory = store.files(directory)
    seal_path = directory / 'seal.json'
    seal = read(seal_path, 65536)
    require(fix.sha(seal_path) == entry['seal_sha256'] and seal.get('schema') == 'rolling-research-seal-v1'
            and seal.get('chunk_id') == n['chunk'] and seal.get('role') == 'reserved_validation'
            and seal.get('state') == 'sealed_complete' and seal.get('economic_evaluation') is False
            and seal.get('validation_claim') is False, 'seal_identity')
    require(set(inventory) == rolling.CAPTURE_NAMES | {'seal.json'} and set(seal['files']) == rolling.CAPTURE_NAMES, 'sealed_inventory')
    require(sum(inventory.values()) <= rolling.CHUNK_BYTES, 'sealed_size')
    for name, item in seal['files'].items():
        require(inventory[name] == item['bytes'] and fix.sha(directory / name) == item['sha256'], 'sealed_file_changed')
    cap = directory / 'capture'
    manifest, terminal, status = read(cap / 'manifest.json', 65536), read(cap / 'terminal.json', 8192), read(cap / 'status.json', 8192)
    require(manifest.get('schema') == 'single-venue-depth-public-capture-v1' and manifest.get('read_only') is True
            and manifest.get('economic_evaluation') is False and manifest.get('selected_markets') == rolling.SELECTED
            and manifest.get('market_plan_sha256') == CHUNK_PLAN['sha256'] and manifest.get('configured_seconds') == 600
            and manifest.get('configured_total_bytes') == BOUNDS['raw_bytes'] and manifest.get('end_reason') == 'duration_limit'
            and manifest.get('truncated') is False and manifest.get('dropped_complete_frame_on_cap') == 0, 'manifest_contract')
    digest, raw = fix.sha(cap / 'manifest.json'), fix.sha(cap / 'frames.jsonl.gz')
    require(raw == manifest['frames_sha256'] == seal['frames_sha256'] and digest == seal['manifest_sha256'], 'manifest_raw_seal')
    require(terminal.get('status') == 'capture_completed' and terminal.get('end_reason') == 'duration_limit'
            and terminal.get('plan_sha256') == CHUNK_PLAN['sha256'] and terminal.get('manifest_sha256') == digest, 'capture_terminal')
    require(seal.get('result', {}).get('returncode') == 0 and seal['result'].get('end_reason') == 'child_finished', 'seal_child_result')
    start, end = rolling.utc_ns(manifest['started_utc']), rolling.utc_ns(manifest['ended_utc'])
    require(n['launched_ns'] <= start <= end and 600 * NS <= end - start <= 601 * NS
            and start == seal['capture_started_ns'] and end == seal['capture_ended_ns'], 'capture_span')
    require(status.get('economic_evaluation') is False and status.get('errors') == [], 'capture_status')
    for old, final in (('compressed_bytes', 'compressed_payload_bytes'), ('records', 'payload_records')):
        require(type(status.get(old)) is int and type(manifest.get(final)) is int and 0 <= status[old] <= manifest[final], 'status_prior_heartbeat')
    require(type(status.get('elapsed_seconds')) in (int, float) and 0 <= status['elapsed_seconds'] <= (end - start) / NS + 1, 'status_elapsed')
    require(fix.sha(cap / 'metadata/market_plan.json') == CHUNK_PLAN['sha256'], 'embedded_chunk_plan')
    require(fix.tree_bytes(cap) <= BOUNDS['raw_bytes'], 'capture_archive_bound')
    metadata = fix.ordinary._metadata(cap, manifest, start)[0]
    require(metadata['market_plan_sha256'] == CHUNK_PLAN['sha256'], 'metadata_plan')
    files = {str((directory / name).relative_to(ROOT)): dict(bytes=size, sha256=fix.sha(directory / name))
             for name, size in inventory.items()}
    files[str(PLAN.relative_to(ROOT))] = dict(bytes=PLAN.stat().st_size, sha256=expected)
    return dict(manifest_sha256=digest, raw_sha256=raw, analysis_plan_sha256=expected,
                capture_plan_sha256=CHUNK_PLAN['sha256'], chunk=n['chunk'], launched_ns=n['launched_ns'],
                source=str(cap.relative_to(ROOT)), store_identity_sha256=p['store_identity_sha256'],
                seal_sha256=entry['seal_sha256'], capture_started_ns=start, capture_ended_ns=end, files=files)


def output_labels(path, body):
    """Metadata-only labels for the inherited reporter; never change a row or cash."""
    name = Path(path).name
    if name in {STEM + '-' + f + '-comparison.json.gz' for f in FAMILIES}:
        require(len(body) <= CAPS['comparison_gzip_per_family'], 'comparison_input_cap')
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
            plain = stream.read(2097153)
        require(len(plain) <= 2097152, 'comparison_decoded_cap')
        value = json.loads(plain)
        value['limits'] = ('One ordinary rolling regime, conditional public-book IOC only; no private fills, '
            'news replication or durable profit. Independent ledgers are not additive. USDG/USDC separate. '
            'Unknown outcomes remain unavailable. Primary gate advances coverage only.')
        value['wrapper_source_sha256'] = fix.sha(ROOT / SOURCE)
        return gzip.compress(fix.encode(value), mtime=0)
    if name == STEM + '-readout.txt':
        return body.replace(b'CORRECTED NEWS WINDOW: AUTOMATED PAPER READOUT',
            b'ORDINARY ROLLING CANDIDATE: CONDITIONAL MODEL READOUT').replace(
            b'One exploratory regime is not durable profitability.',
            b'One ordinary regime is not news replication or durable profitability; primary gate advances coverage only.')
    return body


@contextmanager
def bindings(p, family='relative'):
    """Restore all process-local routes, including compact logger and depth audit aliases."""
    study, capture, ordinary, compact = fix.news.study, fix.news.study.capture, fix.ordinary, fix.compact
    from scripts import single_venue_depth_events as old_events
    from scripts import audit_single_venue_depth  # loads the shared cash alias before saving it
    changes = []
    def setv(module, key, value):
        changes.append((module, key, getattr(module, key)))
        setattr(module, key, value)
    try:
        for module, names in ((strategy, ['snapshot']), (runner, ['inputs']),
                              (cash, ['PLAN', 'inputs', 'match_book', 'verify_signal'])):
            for key in names:
                setv(module, key, getattr(module, key))  # save mutations made by inherited functions
        setv(fix, 'PLAN', PLAN); setv(fix, 'BOUNDS', BOUNDS); setv(fix, 'CAPS', CAPS)
        setv(fix, 'CAPTURE_PLAN_SHA', CHUNK_PLAN['sha256'])
        setv(fix, 'verify', lambda f='relative': configured_verify(f))
        setv(fix, 'input_snapshot', input_snapshot)
        setv(fix, 'configure', configure)
        original_publish = fix.publish
        setv(fix, 'publish', lambda path, body, cap, **kw: original_publish(path, output_labels(path, body), cap, **kw))
        setv(fix.news, 'PLAN', ROOT / CHUNK_PLAN['path'])
        for module in (study, capture, ordinary, old_events):
            keys = (['PLAN', 'NAMES', 'ASSETS', 'Study', 'PARAMS', 'iter_events'] if module is study else
                    ['PLAN', 'OUT', 'SELECTED', 'HARD_BYTES', 'HARD_SECONDS', 'METADATA_MAX_BYTES'] if module is capture else
                    ['HARD_BYTES', 'HARD_SECONDS', 'METADATA_MAX_BYTES', 'MAX_DECODED_BYTES', 'MAX_RECORDS', 'MAX_TRADE_IDS'])
            for key in keys:
                if hasattr(module, key):
                    setv(module, key, getattr(module, key))
        configure(p, family)
        yield
    finally:
        for module, key, old in reversed(changes):
            setattr(module, key, old)


def configure(p, family):
    require(family in FAMILIES, 'family')
    n = nomination(fix.sha(PLAN))
    study, capture, ordinary = fix.news.study, fix.news.study.capture, fix.ordinary
    study.Study = fix.news.Study if family == 'relative' else fix.news.DepthStudy
    study.PARAMS = strategy.PARAMS; study.PLAN = PLAN; study.ASSETS = ASSETS
    study.NAMES = {a: STEM + '-' + family + '-' + a.lower() for a in ASSETS}
    capture.PLAN = ROOT / CHUNK_PLAN['path']; capture.OUT = rolling.STORE / n['chunk'] / 'capture'
    capture.SELECTED = rolling.SELECTED; capture.HARD_BYTES = BOUNDS['raw_bytes']; capture.HARD_SECONDS = 600
    capture.METADATA_MAX_BYTES = BOUNDS['metadata_bytes']
    ordinary.HARD_BYTES = BOUNDS['raw_bytes']; ordinary.HARD_SECONDS = 600
    ordinary.METADATA_MAX_BYTES = BOUNDS['metadata_bytes']; ordinary.MAX_DECODED_BYTES = BOUNDS['decoded_bytes']
    ordinary.MAX_RECORDS = BOUNDS['records']; ordinary.MAX_TRADE_IDS = BOUNDS['trade_ids']
    study.iter_events = fix.events
    return study


def configured_verify(family):
    p = verify(fix.sha(PLAN))
    configure(p, family)
    p = dict(p, capture_root=str(fix.news.study.capture.OUT.relative_to(ROOT)))
    return p


def commands(digest, expected):
    for family in FAMILIES:
        common = ['--family', family, '--plan-sha256', expected]
        yield [SOURCE, 'replay', *common, '--manifest-sha256', digest]
        for asset in ASSETS:
            yield [SOURCE, 'audit', *common, '--asset', asset, '--manifest-sha256', digest]
        yield [SOURCE, 'readout', *common]


def unknown_denominators(reason, expected):
    rows = [dict(family=f, asset=a, rule=r, venue=v, collateral='USDC' if v == 'lighter' else 'USDG',
                 attempts=None, closed=None, closed_cash_after_capital=None, closed_stressed_cash=None,
                 complete=False, unknown=reason)
            for f in FAMILIES for a in ASSETS for r in RULES[f] for v in ('lighter', 'rh_lighter')]
    audits = [dict(family=f, asset=a, sample=STEM + '-' + f + '-' + a.lower(), status='unavailable', reason=reason)
              for f in FAMILIES for a in ASSETS]
    return dict(schema=SCHEMA + '-unavailable', plan_sha256=expected, reason=reason,
                denominator=100, audit_denominator=20, rows=rows, audits=audits,
                claim='No complete economic result; unavailable cash is not zero. No replacement attempt.')


def gate_result(rows):
    require(len(rows) == 100 and len({(r['family'], r['asset'], r['venue'], r['rule']) for r in rows}) == 100, 'all_100_rows')
    wanted = {(f, a, v, rule) for f in FAMILIES for a in ASSETS for v in ('lighter', 'rh_lighter') for rule in RULES[f]}
    require({(r['family'], r['asset'], r['venue'], r['rule']) for r in rows} == wanted, 'row_cohort')
    def get(rule):
        return next(r for r in rows if (r['family'], r['asset'], r['venue'], r['rule']) == ('depth', 'NEAR', 'lighter', rule))
    primary, control_row = get('depth_follow'), get('depth_fade')
    flat = all(r['complete'] is True and not r['unknown'] and not r.get('position_open') and not r.get('pending_order')
               for r in (primary, control_row))
    complete = all(r['complete'] is True and not r['unknown'] for r in rows)
    net = D(primary['closed_stressed_cash']) if flat else None
    delta = net - D(control_row['closed_stressed_cash']) if flat else None
    if flat:
        require(net.is_finite() and delta.is_finite(), 'gate_nonfinite_cash')
    passed = flat and primary['closed'] >= 1 and net > 0 and delta > 0
    return dict(status='advances_coverage_only' if passed else 'does_not_advance_coverage', all_100_complete=complete,
                primary_and_control_flat_known=flat, primary_closed=primary['closed'],
                primary_stressed_cash=str(net) if net is not None else None,
                primary_minus_fade_stressed_cash=str(delta) if delta is not None else None,
                independent_ledgers_not_additive=True, objective_achieved=False,
                claim='One ordinary-regime conditional public-book observation; no actual fills, durable profit or news replication.')


def finish_result(p, expected):
    from scripts import single_venue_news_ordinary_fix_readout as reporter
    fix.make_readout(p)  # Checks all100 identities, all20 audit/trace/summary bindings.
    rows = []
    for family in FAMILIES:
        report = reporter.packed_json(fix.RESEARCH / (STEM + '-' + family + '-comparison.json.gz'), CAPS['comparison_gzip_per_family'])
        rows.extend(dict(family=family, **r) for r in report['rows'])
    result = gate_result(rows)
    verify(expected); fix.require_pins(p)
    control('result.json', dict(plan_sha256=expected, **result))
    return result


def supervise(expected):
    p = verify(expected)
    ok, economics, reason, completed = False, False, None, 0
    try:
        claim = read(OUT / 'launch-claim.json', 8192)
        require(claim['plan_sha256'] == expected and claim['launched_ns'] < CUTOFF_NS, 'precutoff_claim')
        choice = nominate(p, expected)
        wait_selected(p, expected, choice)
        with bindings(p):
            snap = input_snapshot(p)
            control('input-pins.json', snap)
            digest = snap['manifest_sha256']; deadline = time.monotonic() + 3600
            for args in commands(digest, expected):
                verify(expected); fix.require_pins(p, digest)
                control(f'command-{completed + 1:02d}.json', dict(index=completed + 1, command=args,
                    entrypoint_sha256=fix.sha(ROOT / SOURCE), analysis_plan_sha256=expected, manifest_sha256=digest))
                economics = True
                fix.command(args, deadline)
                completed += 1
            require(completed == 24 and time.monotonic() < deadline, 'pipeline_deadline')
            routed = dict(p, capture_root=snap['source'])
            finish_result(routed, expected)
            verify(expected); fix.require_pins(p, digest)
            require(time.monotonic() < deadline, 'analysis_deadline_after_publication')
        ok = True
    except BaseException as exc:
        reason = type(exc).__name__ + ': ' + str(exc)[:700]
        control('unavailable.json.gz', unknown_denominators(reason, expected), packed=True)
    finally:
        control('terminal.json', dict(schema=SCHEMA + '-terminal', plan_sha256=expected,
            status='completed' if ok else 'unavailable', success=ok, economic_evaluation=economics,
            completed_commands=completed, reason=reason, ended_utc=fix.utc(), no_retry=True,
            objective_achieved=False, retained_pin_owner=OWNER if (OUT / 'pin.json').exists() else None))
    if not ok:
        raise SystemExit(1)


def launch(expected):
    verify(expected, before_cutoff=True)
    require(not OUT.exists(), 'existing_control_root')
    for f in FAMILIES:
        require(not any((fix.RESEARCH / (STEM + '-' + f + '-' + a.lower())).exists() for a in ASSETS), 'existing_ledger_output')
        require(not any((fix.RESEARCH / (STEM + '-' + f + '-comparison' + suffix)).exists() for suffix in ('.json.gz', '.csv')), 'existing_comparison_output')
    require(not (fix.RESEARCH / (STEM + '-readout.txt')).exists(), 'existing_readout')
    OUT.mkdir(parents=True, exist_ok=False)
    control('launch-claim.json', dict(schema=SCHEMA + '-launch', plan_sha256=expected,
        launched_ns=time.time_ns(), source_sha256=fix.sha(ROOT / SOURCE), cutoff_ns=CUTOFF_NS,
        selection_deadline_ns=DEADLINE_NS, new_http_requests=0, no_replacement=True))
    args = [sys.executable, '-B', str(ROOT / SOURCE), 'supervise', '--plan-sha256', expected]
    child = None
    try:
        child = subprocess.Popen(args, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        control('process.json', dict(pid=child.pid, command=args, entrypoint_sha256=fix.sha(ROOT / SOURCE),
            plan_sha256=expected, analysis_seconds=3600, child_seconds=600))
    except BaseException as exc:
        if child is not None:
            try: os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            child.wait()
        reason = type(exc).__name__ + ': ' + str(exc)[:700]
        control('unavailable.json.gz', unknown_denominators(reason, expected), packed=True)
        control('launch-terminal.json', dict(status='launch_failed', plan_sha256=expected,
            economic_evaluation=None if child else False, reason=reason))
        raise
    return dict(status='launched', pid=child.pid, plan_sha256=expected, no_new_network=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', default='dry', choices=('dry', 'run', 'supervise', 'replay', 'audit', 'readout'))
    parser.add_argument('--plan-sha256'); parser.add_argument('--family', choices=FAMILIES)
    parser.add_argument('--asset', choices=ASSETS); parser.add_argument('--manifest-sha256')
    args = parser.parse_args(argv)
    if args.action == 'dry':
        value = dict(status='dry', network_requests=0, store_reads=0, nominations=0, pins=0, economic_evaluation=False,
                     final_plan=str(PLAN.relative_to(ROOT)), cutoff_ns=CUTOFF_NS, selection_deadline_ns=DEADLINE_NS,
                     rows=100, audits=20, commands=24)
    elif args.action == 'run':
        value = launch(args.plan_sha256)
    elif args.action == 'supervise':
        supervise(args.plan_sha256); return
    else:
        p = verify(args.plan_sha256)
        require(args.family in FAMILIES, 'family_required')
        with bindings(p, args.family):
            require((OUT / 'input-pins.json').exists(), 'input_snapshot_required')
            if args.action == 'replay':
                require(args.manifest_sha256 is not None, 'manifest_required')
                fix.replay(args.family, args.manifest_sha256)
            elif args.action == 'audit':
                require(args.asset in ASSETS and args.manifest_sha256 is not None, 'audit_args')
                fix.audit(args.family, args.asset, args.manifest_sha256)
            else:
                from scripts import single_venue_news_ordinary_fix_readout as reporter
                reporter.main(args.family)
        return
    print(json.dumps(value, separators=(',', ':')))


if __name__ == '__main__':
    main()
