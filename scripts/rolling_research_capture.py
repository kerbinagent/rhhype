#!/usr/bin/env python3
"""Bounded public capture store. Independent chunks; no orders or economics.

Readers must pin sealed chunks before opening them and unpin after closing them.
The store lock serializes pinning, publication and expiry. Existing evidence is
outside this store and is never considered for deletion.
Sealed complete means a verified whole capture with annotated gaps and errors;
downstream adapters must still reject invalid events and subscription history.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import ctypes
from datetime import datetime
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time
import zlib

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / 'data/rolling/market-research-v1'
PLAN = ROOT / 'reports/experiment-storage/rolling-research-capture-v1.json'
RAW_BYTES = 64 * 1024 * 1024
CAPTURE_BYTES = RAW_BYTES + 262144
CHUNK_BYTES = CAPTURE_BYTES + 65536
CONTROL_BYTES = 4 * 1024 * 1024
STORE_BYTES = 2_000_000_000
SECONDS = 600
CHILD_SECONDS = 720
RUNTIME_SECONDS = 48 * 3600
RETENTION_NS = 2 * 3600 * 10**9
INDEX_BYTES = 1024 * 1024
MAX_CHUNKS = 288
ASSETS = ('BTC', 'ETH', 'SOL', 'HYPE', 'XRP', 'SUI', 'NEAR', 'ZEC', 'VVV', 'LIT')
SELECTED = {
    'rh_lighter': dict(zip(ASSETS, ('1', '0', '3', '2', '6', '9', '7', '4', '8', '5'))),
    'lighter': dict(zip(ASSETS, ('1', '0', '2', '24', '7', '16', '10', '90', '69', '120'))),
}
CHUNK_NAME = re.compile(r'chunk-[0-9]{6}\Z')
OWNER = re.compile(r'[A-Za-z0-9_.-]{1,64}\Z')
CONTROL_NAMES = {'identity.json', 'index.json', 'status.json', 'process.json',
                 'stop.flag', '.lock', '.controller.lock', '.index.json.tmp',
                 '.status.json.tmp', '.process.json.tmp'}
CAPTURE_NAMES = {'capture/frames.jsonl.gz', 'capture/status.json',
                 'capture/manifest.json', 'capture/terminal.json'}
for prefix in ('rh_markets', 'core_markets', 'rh_assets', 'core_assets'):
    CAPTURE_NAMES.update({f'capture/metadata/{prefix}.json.gz',
                          f'capture/metadata/{prefix}.request.json'})
CAPTURE_NAMES.update({'capture/metadata/market_plan.json', 'capture/metadata/normalized.json'})


class StoreError(RuntimeError):
    pass


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def regular(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise StoreError(f'unsafe file: {path}')
    return info.st_size


def read_json(path, cap=INDEX_BYTES):
    if regular(path) > cap:
        raise StoreError(f'JSON exceeds bound: {path}')
    return json.loads(path.read_bytes())


def encoded(value, cap):
    body = (json.dumps(value, separators=(',', ':'), allow_nan=False) + '\n').encode()
    if len(body) > cap:
        raise StoreError('control record exceeds bound')
    return body


def safe_parents(path):
    for parent in (path, *path.parents):
        if parent.exists() or parent.is_symlink():
            if parent.is_symlink() or not parent.is_dir():
                raise StoreError(f'unsafe directory: {parent}')


def role(number):
    return 'exploratory' if (number - 1) % 6 < 3 else 'reserved_validation'


def utc_ns(text):
    value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        raise StoreError('timestamp has no UTC offset')
    origin = datetime.fromisoformat('1970-01-01T00:00:00+00:00')
    delta = value - origin
    return (delta.days * 86400 + delta.seconds) * 10**9 + delta.microseconds * 1000


def verify_config(plan_path=PLAN):
    plan = read_json(plan_path, 65536)
    if (plan.get('schema') != 'rolling-research-capture-v1'
            or plan.get('store_budget_bytes') != STORE_BYTES
            or plan.get('max_runtime_seconds') != RUNTIME_SECONDS):
        raise StoreError('parent plan limits differ')
    relative = Path(plan['capture_plan'])
    if relative.is_absolute() or '..' in relative.parts:
        raise StoreError('capture plan must be a workspace relative path')
    chunk_path = ROOT / relative
    if digest(chunk_path) != plan['capture_plan_sha256']:
        raise StoreError('capture plan hash differs')
    chunk = read_json(chunk_path, 65536)
    if (chunk.get('schema') != 'rolling-research-chunk-v1'
            or chunk.get('selected') != SELECTED or chunk.get('assets') != list(ASSETS)
            or chunk.get('categories_bytes', {}).get('raw') != RAW_BYTES):
        raise StoreError('chunk plan configuration differs')
    for config in (plan, chunk):
        pins = config.get('source_pins', [])
        if not pins:
            raise StoreError('source pins required')
        for pin in pins:
            relative = Path(pin['path'])
            if relative.is_absolute() or '..' in relative.parts:
                raise StoreError('source pin must be workspace relative')
            path = ROOT / relative
            regular(path)
            if digest(path) != pin['sha256']:
                raise StoreError(f'source pin differs: {relative}')
    return plan, chunk_path, chunk


class Store:
    def __init__(self, root=STORE, budget=STORE_BYTES):
        self.root = Path(root)
        self.budget = budget

    def initialize(self, plan_sha256, now_ns=None):
        now_ns = time.time_ns() if now_ns is None else now_ns
        safe_parents(self.root)
        if self.root.exists():
            identity = read_json(self.root / 'identity.json', 16384)
            if (identity.get('schema') != 'rolling-research-store-v1'
                    or identity.get('plan_sha256') != plan_sha256
                    or identity.get('budget_bytes') != self.budget):
                raise StoreError('existing store identity differs')
            return
        self.root.mkdir(parents=True, exist_ok=False)
        identity = dict(schema='rolling-research-store-v1', plan_sha256=plan_sha256,
                        budget_bytes=self.budget, created_ns=now_ns,
                        deadline_ns=now_ns + RUNTIME_SECONDS * 10**9)
        (self.root / 'identity.json').write_bytes(encoded(identity, 16384))
        (self.root / 'index.json').write_bytes(encoded(dict(
            schema='rolling-research-index-v1', next_number=1, chunks={}, expired=[]), INDEX_BYTES))

    @contextmanager
    def locked(self):
        safe_parents(self.root)
        lock = self.root / '.lock'
        descriptor = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            regular(lock)
            yield
        finally:
            os.close(descriptor)

    def index(self):
        value = read_json(self.root / 'index.json')
        if value.get('schema') != 'rolling-research-index-v1':
            raise StoreError('unknown index schema')
        return value

    def write(self, name, value, cap=65536):
        if name not in ('index.json', 'status.json', 'process.json'):
            raise StoreError('unknown control destination')
        body = encoded(value, cap)
        temporary = self.root / f'.{name}.tmp'
        if temporary.exists() or temporary.is_symlink():
            regular(temporary)
        # Fixed CONTROL_BYTES reserves both old and new control versions.
        with temporary.open('wb') as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.root / name)

    def files(self, directory):
        allowed = CAPTURE_NAMES | {'seal.json'}
        records = {}
        for path in directory.rglob('*'):
            relative = path.relative_to(directory).as_posix()
            if path.is_symlink():
                raise StoreError('symlink in chunk')
            if path.is_dir():
                if relative not in ('capture', 'capture/metadata'):
                    raise StoreError('unknown chunk directory')
                continue
            if relative not in allowed:
                raise StoreError(f'unknown chunk content: {relative}')
            records[relative] = regular(path)
        if len(records) > 32 or sum(records.values()) > CHUNK_BYTES:
            raise StoreError('chunk exceeds bound')
        return records

    def usage(self, index):
        chunk_total = control = 0
        for path in self.root.iterdir():
            if path.is_symlink():
                raise StoreError('symlink in store')
            if path.is_dir():
                if path.name not in index['chunks'] or not CHUNK_NAME.fullmatch(path.name):
                    raise StoreError('unrecognized store directory')
                chunk_total += sum(self.files(path).values())
            elif path.name in CONTROL_NAMES:
                control += regular(path)
            else:
                raise StoreError(f'unknown store file: {path.name}')
        if control > CONTROL_BYTES or chunk_total + control > self.budget:
            raise StoreError('store exceeds disk bound')
        return chunk_total, control

    def expire(self, index, now_ns, required_bytes=CHUNK_BYTES):
        # Validate the entire store first: no deletion on an unsafe inventory.
        chunk_total, _ = self.usage(index)
        expired = []
        oldest_first = sorted(index['chunks'].items(),
                              key=lambda row: (row[1].get('sealed_ns', now_ns), row[1]['number']))
        for name, entry in oldest_first:
            if chunk_total + CONTROL_BYTES + required_bytes <= self.budget:
                break
            if (entry['state'] not in ('sealed_complete', 'sealed_failed')
                    or entry.get('pins') or now_ns - entry['sealed_ns'] < RETENTION_NS):
                continue
            directory = self.root / name
            records = self.files(directory)
            seal_path = directory / 'seal.json'
            seal = read_json(seal_path, 65536)
            if (digest(seal_path) != entry['seal_sha256']
                    or seal.get('schema') != 'rolling-research-seal-v1'
                    or seal.get('chunk_id') != name):
                raise StoreError('expiry seal differs')
            expected = seal['files']
            if set(records) - {'seal.json'} != set(expected):
                raise StoreError('expiry inventory differs')
            for relative, record in expected.items():
                path = directory / relative
                if records[relative] != record['bytes'] or digest(path) != record['sha256']:
                    raise StoreError('expiry artifact differs')
            # Chunk tree and ownership have been checked while holding .lock.
            for relative in sorted(records, reverse=True):
                (directory / relative).unlink()
            for subdirectory in ('capture/metadata', 'capture'):
                path = directory / subdirectory
                if path.exists():
                    path.rmdir()
            directory.rmdir()
            index['expired'].append(dict(chunk_id=name, role=entry['role'],
                state=entry['state'], started_ns=entry['launched_ns'],
                sealed_ns=entry['sealed_ns'], seal_sha256=entry['seal_sha256'],
                frames_sha256=seal.get('frames_sha256'),
                payload_records=seal.get('payload_records'),
                decoded_bytes=seal.get('decoded_bytes'), expired_ns=now_ns))
            del index['chunks'][name]
            expired.append(name)
            chunk_total -= sum(records.values())
        # Bounded hash catalog; no market payload or economic result survives here.
        index['expired'] = index['expired'][-256:]
        if len(encoded(index['expired'], 262144)) > 262144:
            raise StoreError('expired catalog exceeds bound')
        return expired

    def reserve(self, now_ns=None):
        now_ns = time.time_ns() if now_ns is None else now_ns
        with self.locked():
            index = self.index()
            number = index['next_number']
            if number > MAX_CHUNKS:
                self.write('index.json', index, INDEX_BYTES)
                return None, 'campaign_chunk_limit'
            if any(x['state'] == 'collecting' for x in index['chunks'].values()):
                raise StoreError('another chunk is collecting')
            self.expire(index, now_ns)
            chunks, _ = self.usage(index)
            if chunks + CONTROL_BYTES + CHUNK_BYTES > self.budget:
                self.write('index.json', index, INDEX_BYTES)
                return None, 'storage_blocked'
            name = f'chunk-{number:06d}'
            (self.root / name).mkdir(exist_ok=False)
            index['chunks'][name] = dict(state='collecting', role=role(number),
                number=number, launched_ns=now_ns, pins=[], economic_evaluation=False,
                validation_claim=False, freeze_before_capture_required=role(number) == 'reserved_validation')
            index['next_number'] += 1
            self.write('index.json', index, INDEX_BYTES)
            return name, 'collecting'

    def seal(self, name, result, capture_plan_sha256, now_ns=None):
        now_ns = time.time_ns() if now_ns is None else now_ns
        with self.locked():
            index = self.index()
            entry = index['chunks'][name]
            if entry['state'] != 'collecting':
                raise StoreError('chunk already sealed')
            directory = self.root / name
            records = self.files(directory)
            outcome = dict(schema='rolling-research-seal-v1', chunk_id=name,
                role=entry['role'], sealed_ns=now_ns, result=result,
                validation_claim=False, economic_evaluation=False, files={})
            complete = False
            # Retain operational coverage from partial manifests as well. It never
            # makes a capped, disconnected or interrupted chunk analysis eligible.
            manifest_path = directory / 'capture/manifest.json'
            if manifest_path.exists():
                try:
                    manifest = read_json(manifest_path, 65536)
                    for key in ('started_utc', 'ended_utc', 'end_reason', 'truncated',
                                'payload_records', 'compressed_payload_bytes', 'frames_sha256'):
                        if key in manifest:
                            outcome[key] = manifest[key]
                    for label in ('started', 'ended'):
                        if manifest.get(label + '_utc'):
                            outcome['capture_' + label + '_ns'] = utc_ns(manifest[label + '_utc'])
                except (ValueError, TypeError, OSError, StoreError) as error:
                    outcome['partial_manifest_error'] = f'{type(error).__name__}: {str(error)[:160]}'
            try:
                outcome.update(inspect_capture(directory / 'capture', capture_plan_sha256, result))
                complete = True
            except (AssertionError, ValueError, KeyError, TypeError, OSError,
                    StoreError, EOFError, zlib.error) as error:
                outcome['failure'] = f'{type(error).__name__}: {str(error)[:240]}'
            outcome['state'] = 'sealed_complete' if complete else 'sealed_failed'
            for relative, size in records.items():
                if relative == 'seal.json':
                    raise StoreError('unpublished seal exists; manual recovery required')
                outcome['files'][relative] = dict(bytes=size, sha256=digest(directory / relative))
            (directory / 'seal.json').write_bytes(encoded(outcome, 65536))
            previous_ends = [x.get('capture_ended_ns') for x in index['chunks'].values()
                             if x['number'] < entry['number'] and x.get('capture_ended_ns')]
            entry.update(state=outcome['state'], sealed_ns=now_ns,
                seal_sha256=digest(directory / 'seal.json'), bytes=sum(self.files(directory).values()),
                capture_started_ns=outcome.get('capture_started_ns'),
                capture_ended_ns=outcome.get('capture_ended_ns'), coverage=outcome.get('coverage'),
                payload_records=outcome.get('payload_records'), decoded_bytes=outcome.get('decoded_bytes'),
                handoff_gap_ns=(outcome['capture_started_ns'] - max(previous_ends)
                    if outcome.get('capture_started_ns') and previous_ends else None))
            self.write('index.json', index, INDEX_BYTES)
            self.usage(index)
            return outcome

    def pin(self, names, owner, remove=False):
        if not OWNER.fullmatch(owner):
            raise StoreError('owner must be 1..64 letters, digits, dot, dash or underscore')
        with self.locked():
            index = self.index()
            self.usage(index)
            for name in names:
                entry = index['chunks'].get(name)
                if not entry or (not remove and entry['state'] != 'sealed_complete'):
                    raise StoreError(f'only sealed complete chunks can be pinned: {name}')
                if not remove:
                    seal = self.root / name / 'seal.json'
                    if digest(seal) != entry['seal_sha256']:
                        raise StoreError('pin seal differs')
            for name in names:
                entry = index['chunks'][name]
                owners = set(entry['pins'])
                owners.discard(owner) if remove else owners.add(owner)
                if len(owners) > 32:
                    raise StoreError('too many pins on chunk')
                entry['pins'] = sorted(owners)
            self.write('index.json', index, INDEX_BYTES)
            return {name: dict(index['chunks'][name], path=str(self.root / name / 'capture')) for name in names}

    def health(self, state, **details):
        with self.locked():
            index = self.index()
            chunks, control = self.usage(index)
            self.write('status.json', dict(schema='rolling-research-health-v1', state=state,
                updated_ns=time.time_ns(), chunk_bytes=chunks, control_bytes=control,
                store_budget_bytes=self.budget, capture_running=state == 'collecting',
                economic_evaluation=False, **details))


def observe_frame(coverage, row):
    """Count wire events and times without inspecting prices or account fields."""
    if row.get('kind') != 'frame' or row.get('market') is None:
        return
    key = f"{row['venue']}|{row['market']}|{row['channel']}"
    item = coverage.setdefault(key, dict(records=0, receipt_min_ns=None,
        receipt_max_ns=None, source_min_ns=None, source_max_ns=None, invalid_frames=0,
        subscribed_frames=0, update_frames=0, history_trade_prints=0,
        history_liquidation_prints=0, live_trade_prints=0, live_liquidation_prints=0,
        live_receipt_min_ns=None, live_receipt_max_ns=None,
        live_source_min_ns=None, live_source_max_ns=None))
    item['records'] += 1
    if row.get('annotation', {}).get('quality') != 'wire_ok':
        item['invalid_frames'] += 1
    payload = row.get('payload', {})
    kind = payload.get('type', '') if isinstance(payload, dict) else ''
    subscribed = isinstance(kind, str) and kind.startswith('subscribed/')
    live = isinstance(kind, str) and kind.startswith('update/')
    item['subscribed_frames'] += int(subscribed)
    item['update_frames'] += int(live)
    if row['channel'] == 'trade' and kind in ('subscribed/trade', 'update/trade'):
        prefix = 'history' if subscribed else 'live'
        for field, suffix in (('trades', 'trade_prints'), ('liquidation_trades', 'liquidation_prints')):
            batch = payload.get(field, [])
            if isinstance(batch, list):
                item[prefix + '_' + suffix] += len(batch)
    for label, values in (('receipt', [row['receipt_utc_ns']]),
            ('source', [row.get('annotation', {}).get('source_min_ns'),
                        row.get('annotation', {}).get('source_max_ns')])):
        values = [x for x in values if isinstance(x, int)]
        if values:
            low, high = min(values), max(values)
            for prefix in ('', 'live_') if live else ('',):
                low_key, high_key = prefix + label + '_min_ns', prefix + label + '_max_ns'
                item[low_key] = min(item[low_key] or low, low)
                item[high_key] = max(item[high_key] or high, high)


def inspect_capture(directory, plan_sha256, result):
    if result.get('returncode') != 0 or result.get('end_reason') != 'child_finished':
        raise StoreError('child failed, stopped or exceeded timeout')
    terminal = read_json(directory / 'terminal.json', 65536)
    manifest_path = directory / 'manifest.json'
    manifest = read_json(manifest_path, 65536)
    if (terminal.get('status') != 'capture_completed'
            or terminal.get('end_reason') != 'duration_limit'
            or terminal.get('manifest_sha256') != digest(manifest_path)
            or terminal.get('plan_sha256') != plan_sha256
            or manifest.get('end_reason') != 'duration_limit'
            or manifest.get('truncated') is not False
            or manifest.get('dropped_complete_frame_on_cap') != 0
            or manifest.get('configured_seconds') != SECONDS
            or manifest.get('configured_total_bytes') != CAPTURE_BYTES
            or manifest.get('selected_markets') != SELECTED
            or manifest.get('market_plan_sha256') != plan_sha256
            or manifest.get('read_only') is not True
            or manifest.get('economic_evaluation') is not False):
        raise StoreError('capture terminal or limits invalid')
    raw = directory / 'frames.jsonl.gz'
    if regular(raw) > RAW_BYTES or digest(raw) != manifest['frames_sha256']:
        raise StoreError('raw size/hash differs')
    if sum(regular(p) for p in directory.rglob('*') if p.is_file()) > CAPTURE_BYTES:
        raise StoreError('complete capture directory exceeds bound')
    import single_venue_depth_capture as capture
    if manifest.get('source_sha256') != digest(Path(capture.__file__)):
        raise StoreError('capture source differs')
    configure_capture(capture, directory, directory / 'metadata/market_plan.json')
    capture.verify_metadata(directory / 'metadata', SELECTED, plan_sha256)
    started, ended = utc_ns(manifest['started_utc']), utc_ns(manifest['ended_utc'])
    if ended < started or ended - started < SECONDS * 10**9 or ended - started > CHILD_SECONDS * 10**9:
        raise StoreError('capture duration invalid')
    metadata_bytes = sum(regular(p) for p in (directory / 'metadata').iterdir())
    if metadata_bytes != manifest['metadata_bytes'] or metadata_bytes > 131072:
        raise StoreError('metadata byte count differs')
    for request in capture.verify_metadata(directory / 'metadata', SELECTED, plan_sha256)['raw_requests'].values():
        began, completed = request['request_started_utc_ns'], request['response_completed_utc_ns']
        if (not 0 < began <= completed <= started
                or started - completed > capture.MAX_METADATA_AGE_NS):
            raise StoreError('capture metadata not fresh at start')
    coverage = {}; records = decoded = 0
    with gzip.open(raw, 'rb') as stream:
        while True:
            line = stream.readline(8 * 1024 * 1024 + 1)
            if not line:
                break
            records += 1; decoded += len(line)
            if len(line) > 8 * 1024 * 1024 or decoded > 1024**3 or records > 1_000_000:
                raise StoreError('raw decoded stream exceeds bound')
            row = json.loads(line)
            observe_frame(coverage, row)
    if records != manifest['payload_records'] or regular(raw) != manifest['compressed_payload_bytes']:
        raise StoreError('capture record count differs')
    for venue, markets in SELECTED.items():
        for market in markets.values():
            if f'{venue}|{market}|order_book' not in coverage:
                raise StoreError('selected market has no captured book coverage')
    return dict(capture_started_ns=started, capture_ended_ns=ended,
        frames_sha256=manifest['frames_sha256'], manifest_sha256=digest(manifest_path),
        payload_records=records, decoded_bytes=decoded,
        coverage=coverage, generation_count=len(manifest['generations']),
        reconnect_or_feed_errors=manifest['errors'], source_clock_calibrated=False)


def configure_capture(capture, directory, chunk_plan):
    capture.PLAN = Path(chunk_plan)
    capture.OUT = Path(directory)
    capture.SELECTED = SELECTED
    capture.HARD_SECONDS = SECONDS
    capture.HARD_BYTES = CAPTURE_BYTES
    capture.METADATA_MAX_BYTES = 131072


def child(name, parent_pid):
    if not CHUNK_NAME.fullmatch(name):
        raise StoreError('invalid chunk identifier')
    # Prevent an orphan capture if the controller exits unexpectedly (Linux/WSL).
    if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
        raise StoreError('cannot install parent death signal')
    if os.getppid() != parent_pid:
        raise StoreError('controller already exited')
    _, chunk_plan, _ = verify_config()
    store = Store()
    with store.locked():
        entry = store.index()['chunks'].get(name)
        if not entry or entry['state'] != 'collecting':
            raise StoreError('chunk not reserved')
    import single_venue_depth_capture as capture
    configure_capture(capture, STORE / name / 'capture', chunk_plan)
    asyncio.run(capture.main())


def supervise_child(command, store, timeout=CHILD_SECONDS, heartbeat=None):
    if not 0 < timeout <= CHILD_SECONDS:
        raise StoreError('child timeout exceeds limit')
    process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    started = time.monotonic(); last_heartbeat = started
    reason = 'child_finished'
    try:
        while process.poll() is None:
            if (store.root / 'stop.flag').exists():
                reason = 'user_stop'; break
            if time.monotonic() - started >= timeout:
                reason = 'child_timeout'; break
            if time.monotonic() - last_heartbeat >= 30:
                if heartbeat:
                    heartbeat()
                last_heartbeat = time.monotonic()
            time.sleep(0.5)
    finally:
        if process.poll() is None:
            process.kill()
        returncode = process.wait(timeout=10)
    return dict(returncode=returncode, end_reason=reason,
                elapsed_seconds=time.monotonic() - started)


def supervise():
    _, chunk_plan, _ = verify_config()
    store = Store(); store.initialize(digest(PLAN))
    descriptor = os.open(STORE / '.controller.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor); raise StoreError('controller already running')
    identity = read_json(STORE / 'identity.json')
    wall_start = time.time_ns(); mono_start = time.monotonic()
    try:
        # A previous supervisor may have ended during a child; preserve its partial data.
        with store.locked():
            recovery = [n for n, x in store.index()['chunks'].items() if x['state'] == 'collecting']
        for name in recovery:
            store.seal(name, dict(returncode=None, end_reason='controller_interrupted'), digest(chunk_plan))
        while True:
            now = time.time_ns()
            if abs((now - wall_start) / 1e9 - (time.monotonic() - mono_start)) > 0.25:
                store.health('stopped', end_reason='clock_shift'); break
            if (STORE / 'stop.flag').exists():
                store.health('stopped', end_reason='user_stop'); break
            if now + CHILD_SECONDS * 10**9 > identity['deadline_ns']:
                store.health('finished', end_reason='runtime_limit'); break
            name, state = store.reserve(now)
            if name is None:
                store.health(state)
                if state == 'campaign_chunk_limit':
                    break
                time.sleep(30); continue
            slot_started = time.monotonic()
            store.health('collecting', current_chunk=name)
            command = [sys.executable, str(Path(__file__).resolve()), 'child', name, str(os.getpid())]
            result = supervise_child(command, store,
                heartbeat=lambda: store.health('collecting', current_chunk=name))
            seal = store.seal(name, result, digest(chunk_plan))
            store.health('handoff', previous_chunk=name, previous_state=seal['state'],
                         previous_result=result)
            # Failure advances to the next scheduled slot, never an immediate replacement retry.
            while time.monotonic() - slot_started < SECONDS and not (STORE / 'stop.flag').exists():
                time.sleep(min(30, SECONDS - (time.monotonic() - slot_started)))
                store.health('handoff', previous_chunk=name, previous_state=seal['state'])
    except Exception as error:
        try:
            store.health('failed', error=f'{type(error).__name__}: {str(error)[:300]}')
        except Exception:
            pass
        raise
    finally:
        os.close(descriptor)


def launch_controller(store, plan_sha256):
    # One launch per store. A completed/failed prior launch stays reviewable;
    # launching again requires a separate explicit recovery design.
    with store.locked():
        store.usage(store.index())
        existing = store.root / 'process.json'
        if existing.exists() or existing.is_symlink():
            raise StoreError('store already has a process record; launch refused')
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'supervise'],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
        try:
            record = dict(schema='rolling-research-process-v1', pid=process.pid,
                          launched_ns=time.time_ns(), plan_sha256=plan_sha256)
            store.write('process.json', record)
        except Exception:
            process.kill(); process.wait(timeout=10)
            raise
        return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('validate', 'launch', 'supervise', 'child',
                                          'pin', 'unpin', 'stop', 'status'))
    parser.add_argument('chunks', nargs='*')
    parser.add_argument('--owner')
    args = parser.parse_args()
    if args.action == 'child':
        if len(args.chunks) != 2:
            parser.error('child requires chunk identifier and controller PID')
        child(args.chunks[0], int(args.chunks[1])); return
    if args.action == 'supervise':
        supervise(); return
    if args.action in ('validate', 'launch'):
        verify_config()
        if args.action == 'validate':
            print(json.dumps(dict(valid=True, store=str(STORE), store_budget_bytes=STORE_BYTES,
                child_seconds=SECONDS, child_timeout_seconds=CHILD_SECONDS,
                chunk_reservation_bytes=CHUNK_BYTES, max_runtime_seconds=RUNTIME_SECONDS)))
            return
        store = Store(); store.initialize(digest(PLAN))
        record = launch_controller(store, digest(PLAN))
        print(json.dumps(record)); return
    store = Store()
    if args.action in ('pin', 'unpin'):
        if not args.owner or not args.chunks:
            parser.error('pin/unpin require --owner and one or more chunk IDs')
        print(json.dumps(store.pin(args.chunks, args.owner, remove=args.action == 'unpin')))
    elif args.action == 'stop':
        with store.locked():
            path = STORE / 'stop.flag'
            if path.exists():
                regular(path)
            else:
                path.write_bytes(b'user_stop\n')
        print(json.dumps(dict(stop_requested=True)))
    else:
        with store.locked():
            print(json.dumps(dict(status=read_json(STORE / 'status.json'), index=store.index())))


if __name__ == '__main__':
    main()
