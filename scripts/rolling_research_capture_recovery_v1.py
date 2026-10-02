#!/usr/bin/env python3
"""One-shot, pinned recovery of a published seal and bounded rolling index.

Default invocation is dry. The original capture child and supervisor remain
unchanged; only their parent-side Store class is replaced after recovery.
"""
from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rolling_research_capture as base

PLAN = ROOT/'reports/experiment-storage/rolling-research-capture-recovery-v1.json'
OUT = ROOT/'reports/rolling-capture-recovery-v1'
CLAIM = OUT/'claim.json'
RECEIPT = OUT/'receipt.json'
STARTUP = OUT/'startup.json'
ORPHAN = 'chunk-000052'
EXPECTED_INDEX_SHA = '5dd1637a862302ad62bc2c7ba00df4fb913da0d03197cd81e768b71848e5fefa'


def body(obj, cap):
    return base.encoded(obj, cap)


def publish_once(path, payload):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def pinned(plan_sha):
    if not isinstance(plan_sha, str) or base.digest(PLAN) != plan_sha:
        raise base.StoreError('exact recovery plan SHA differs')
    plan = base.read_json(PLAN, 8192)
    if (plan.get('schema') != 'rolling-research-capture-recovery-v1'
            or plan.get('status') != 'frozen_recovery'
            or plan.get('store_root') != str(base.STORE.relative_to(ROOT))
            or plan.get('orphan_chunk') != ORPHAN
            or plan.get('orphan_role') != 'reserved_validation'
            or plan.get('expected_next_number') != 53
            or plan.get('expected_old_process_pid') != 3064206
            or plan.get('identity_values', {}).get('deadline_ns') != 1791081390277402345
            or plan.get('observed_preconditions', {}).get('index.json', {}).get('sha256') != EXPECTED_INDEX_SHA
            or plan.get('outputs') != dict(directory=str(OUT.relative_to(ROOT)), maximum_total_bytes=8192)):
        raise base.StoreError('recovery plan is not frozen or scope differs')
    for field, path in (('original_plan', base.PLAN), ('original_source', Path(base.__file__))):
        item = plan[field]
        if item['path'] != str(path.resolve().relative_to(ROOT)) or base.regular(path) != item['bytes'] or base.digest(path) != item['sha256']:
            raise base.StoreError(field+' pin differs')
    pins = plan.get('source_pins')
    required = {str(Path(__file__).relative_to(ROOT)),
                'tests/test_rolling_research_capture_recovery_v1.py'}
    if not isinstance(pins, list) or {x['path'] for x in pins} != required:
        raise base.StoreError('recovery source/test pins differ')
    for pin in pins:
        path = ROOT/pin['path']
        if base.regular(path) != pin['bytes'] or base.digest(path) != pin['sha256']:
            raise base.StoreError('recovery source or test differs')
    original, _, _ = base.verify_config()
    if original.get('max_runtime_seconds') != base.RUNTIME_SECONDS:
        raise base.StoreError('original runtime differs')
    return plan


def pinned_file(path, item):
    if (item.get('path') != str(path.relative_to(ROOT))
            or base.regular(path) != item['bytes'] or base.digest(path) != item['sha256']):
        raise base.StoreError('precondition file differs: '+path.name)


def process_dead(pid):
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1:
        raise base.StoreError('old process PID invalid')
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def no_original_child():
    """Fail closed if an old capture child still names the frozen module."""
    target = os.fsencode(str(Path(base.__file__).resolve()))
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal() or int(proc.name) == os.getpid():
            continue
        try:
            args = (proc/'cmdline').read_bytes().split(b'\0')
        except FileNotFoundError:
            continue
        except PermissionError as exc:
            raise base.StoreError('cannot inspect process table') from exc
        if target in args and b'child' in args:
            raise base.StoreError('original capture child remains active')


class CompactStore(base.Store):
    """Represent sealed coverage in the index by its immutable seal pointer."""

    def compact(self, index):
        if index.get('schema') != 'rolling-research-index-v1':
            raise base.StoreError('index schema differs')
        for name, entry in index['chunks'].items():
            if 'coverage' not in entry:
                if 'coverage_ref' in entry:
                    expected = dict(path=name+'/seal.json#coverage', seal_sha256=entry.get('seal_sha256'))
                    seal_path = self.root/name/'seal.json'
                    if (entry['coverage_ref'] != expected or base.digest(seal_path) != entry['seal_sha256']
                            or 'coverage' not in base.read_json(seal_path, 65536)):
                        raise base.StoreError('compacted coverage reference differs')
                continue
            if entry['coverage'] is None:
                continue
            if entry.get('state') not in ('sealed_complete', 'sealed_failed'):
                raise base.StoreError('collecting coverage cannot be compacted')
            seal_path = self.root/name/'seal.json'
            if base.digest(seal_path) != entry.get('seal_sha256'):
                raise base.StoreError('coverage seal SHA differs')
            seal = base.read_json(seal_path, 65536)
            if (seal.get('schema') != 'rolling-research-seal-v1'
                    or seal.get('chunk_id') != name
                    or seal.get('state') != entry['state']
                    or seal.get('coverage') != entry['coverage']):
                raise base.StoreError('coverage differs from sealed copy')
            entry['coverage_ref'] = dict(path=name+'/seal.json#coverage',
                                         seal_sha256=entry['seal_sha256'])
            del entry['coverage']
        return index

    def write(self, name, value, cap=65536):
        if name == 'index.json':
            value = self.compact(value)
            cap = base.INDEX_BYTES
        return super().write(name, value, cap)


def validate_orphan(store, plan, index):
    _, chunk_plan, _ = base.verify_config()
    chunk_plan_sha = base.digest(chunk_plan)
    entry = index['chunks'].get(ORPHAN)
    if (not entry or entry.get('number') != 52 or entry.get('role') != plan['orphan_role']
            or entry.get('state') != 'collecting' or entry.get('pins') != []
            or index.get('next_number') != 53):
        raise base.StoreError('orphan index identity differs')
    directory = store.root/ORPHAN
    observed = plan['observed_preconditions']
    for name in ('chunk-000052/seal.json', 'chunk-000052/capture/manifest.json',
                 'chunk-000052/capture/terminal.json'):
        pinned_file(store.root/name, observed[name])
    seal = base.read_json(directory/'seal.json', 65536)
    manifest = base.read_json(directory/'capture/manifest.json', 65536)
    terminal = base.read_json(directory/'capture/terminal.json', 65536)
    if (seal.get('schema') != 'rolling-research-seal-v1' or seal.get('chunk_id') != ORPHAN
            or seal.get('role') != entry['role'] or seal.get('state') != 'sealed_complete'
            or seal.get('validation_claim') is not False or seal.get('economic_evaluation') is not False
            or seal.get('result', {}).get('returncode') != 0
            or seal.get('result', {}).get('end_reason') != 'child_finished'
            or seal.get('manifest_sha256') != observed['chunk-000052/capture/manifest.json']['sha256']
            or seal.get('frames_sha256') != manifest.get('frames_sha256')
            or seal.get('payload_records') != manifest.get('payload_records')
            or seal.get('capture_started_ns') != base.utc_ns(manifest['started_utc'])
            or seal.get('capture_ended_ns') != base.utc_ns(manifest['ended_utc'])
            or terminal.get('status') != 'capture_completed'
            or terminal.get('end_reason') != 'duration_limit'
            or terminal.get('manifest_sha256') != seal['manifest_sha256']
            or terminal.get('plan_sha256') != chunk_plan_sha
            or manifest.get('market_plan_sha256') != chunk_plan_sha
            or manifest.get('source_sha256') != base.digest(ROOT/'scripts/single_venue_depth_capture.py')
            or manifest.get('compressed_payload_bytes') != seal['files']['capture/frames.jsonl.gz']['bytes']
            or manifest.get('end_reason') != 'duration_limit'
            or manifest.get('truncated') is not False
            or manifest.get('read_only') is not True
            or manifest.get('economic_evaluation') is not False
            or manifest.get('selected_markets') != base.SELECTED
            or manifest.get('configured_seconds') != base.SECONDS
            or manifest.get('configured_total_bytes') != base.CAPTURE_BYTES):
        raise base.StoreError('orphan seal/manifest/terminal mismatch')
    files = store.files(directory)
    if set(files)-{'seal.json'} != set(seal['files']):
        raise base.StoreError('orphan inventory differs')
    for relative, info in seal['files'].items():
        file = directory/relative
        if files[relative] != info['bytes'] or base.digest(file) != info['sha256']:
            raise base.StoreError('orphan member size/hash differs')
    if files['capture/frames.jsonl.gz'] > base.RAW_BYTES or sum(files.values()) > base.CHUNK_BYTES:
        raise base.StoreError('orphan chunk size exceeds bound')
    return seal, files


def candidate(store, plan, index):
    index = copy.deepcopy(index)
    seal, files = validate_orphan(store, plan, index)
    entry = index['chunks'][ORPHAN]
    earlier = [x.get('capture_ended_ns') for x in index['chunks'].values()
               if x['number'] < 52 and x.get('capture_ended_ns')]
    entry.update(state=seal['state'], sealed_ns=seal['sealed_ns'],
                 seal_sha256=plan['observed_preconditions']['chunk-000052/seal.json']['sha256'],
                 bytes=sum(files.values()), capture_started_ns=seal.get('capture_started_ns'),
                 capture_ended_ns=seal.get('capture_ended_ns'), coverage=seal.get('coverage'),
                 payload_records=seal.get('payload_records'), decoded_bytes=seal.get('decoded_bytes'),
                 handoff_gap_ns=(seal['capture_started_ns']-max(earlier) if earlier else None))
    store.compact(index)
    body(index, base.INDEX_BYTES)
    return index


def check_preconditions(store, plan):
    identity = store.root/'identity.json'
    pinned_file(identity, plan['identity'])
    if base.read_json(identity, 16384) != plan['identity_values']:
        raise base.StoreError('store identity values differ')
    for name in ('index.json', 'status.json', 'process.json'):
        pinned_file(store.root/name, plan['observed_preconditions'][name])
    base.safe_parents(OUT)
    if OUT.exists() and any(x.name not in ('claim.json', 'receipt.json', 'startup.json')
                            or x.is_symlink() for x in OUT.iterdir()):
        raise base.StoreError('unknown recovery output exists')
    if any(x.exists() or x.is_symlink() for x in (CLAIM, RECEIPT, STARTUP)):
        raise base.StoreError('recovery claim/receipt already exists')
    if (store.root/'stop.flag').exists():
        raise base.StoreError('user stop flag exists')
    old = base.read_json(store.root/'process.json', 65536)
    if old.get('pid') != plan['expected_old_process_pid'] or not process_dead(old['pid']):
        raise base.StoreError('old controller process remains live or differs')
    no_original_child()
    if time.time_ns()+base.CHILD_SECONDS*10**9 > plan['identity_values']['deadline_ns']:
        raise base.StoreError('original deadline leaves no complete child window')
    index = store.index()
    if base.digest(store.root/'index.json') != EXPECTED_INDEX_SHA:
        raise base.StoreError('original index SHA differs')
    if [name for name, value in index['chunks'].items() if value['state'] == 'collecting'] != [ORPHAN]:
        raise base.StoreError('other active/collecting chunk exists')
    store.usage(index)
    return index, old, base.read_json(store.root/'status.json', 65536)


def recover_and_launch(plan_sha):
    plan = pinned(plan_sha)
    store = CompactStore()
    controller = os.open(store.root/'.controller.lock', os.O_RDWR | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(controller, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise base.StoreError('controller lock held') from exc
        with store.locked():
            before, prior_process, prior_status = check_preconditions(store, plan)
            adopted = candidate(store, plan, before)
            pre_index_sha = base.digest(store.root/'index.json')
            pre_process_sha = base.digest(store.root/'process.json')
            pre_status_sha = base.digest(store.root/'status.json')
            claim = dict(schema='rolling-research-recovery-claim-v1', plan_sha256=plan_sha,
                         launcher_pid=os.getpid(), created_ns=time.time_ns(),
                         old_index_sha256=pre_index_sha, orphan_seal_sha256=adopted['chunks'][ORPHAN]['seal_sha256'])
            claim_body = body(claim, 2048)
            placeholder = 'f'*64
            receipt_ceiling = dict(schema='rolling-research-recovery-receipt-v1', phase='launched',
                plan_sha256=plan_sha, claim_sha256=placeholder,
                old_process=prior_process, old_status=prior_status,
                old_hashes=dict(index=placeholder, process=placeholder, status=placeholder),
                new_hashes=dict(index=placeholder, process=placeholder, status=placeholder),
                orphan_seal_sha256=placeholder,
                new_process=dict(schema='rolling-research-process-v1', pid=9999999999,
                    launched_ns=99999999999999999999, plan_sha256=plan['original_plan']['sha256'],
                    recovery_plan_sha256=plan_sha), adopted_index_bytes=base.INDEX_BYTES)
            if len(claim_body)+len(body(receipt_ceiling, 6144))+2048 > plan['outputs']['maximum_total_bytes']:
                raise base.StoreError('recovery receipt would exceed budget')
            base.safe_parents(OUT)
            OUT.mkdir(parents=True, exist_ok=True)
            publish_once(CLAIM, claim_body)
            store.write('index.json', adopted, base.INDEX_BYTES)
            store.write('status.json', dict(schema='rolling-research-health-v1', state='recovering',
                        updated_ns=time.time_ns(), economic_evaluation=False,
                        recovery_plan_sha256=plan_sha), 65536)
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                                        'supervise', '--plan-sha256', plan_sha], cwd=ROOT,
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
            new_process = dict(schema='rolling-research-process-v1', pid=process.pid,
                               launched_ns=time.time_ns(), plan_sha256=plan['original_plan']['sha256'],
                               recovery_plan_sha256=plan_sha)
            store.write('process.json', new_process, 65536)
            receipt = dict(schema='rolling-research-recovery-receipt-v1', phase='launched',
                           plan_sha256=plan_sha, claim_sha256=hashlib.sha256(claim_body).hexdigest(),
                           old_process=prior_process, old_status=prior_status,
                           old_hashes=dict(index=pre_index_sha, process=pre_process_sha, status=pre_status_sha),
                           new_hashes=dict(index=base.digest(store.root/'index.json'),
                                           process=base.digest(store.root/'process.json'),
                                           status=base.digest(store.root/'status.json')),
                           orphan_seal_sha256=adopted['chunks'][ORPHAN]['seal_sha256'],
                           new_process=new_process, adopted_index_bytes=base.regular(store.root/'index.json'))
            receipt_body = body(receipt, 6144)
            if len(claim_body)+len(receipt_body)+2048 > plan['outputs']['maximum_total_bytes']:
                raise base.StoreError('recovery output budget exceeded')
            publish_once(RECEIPT, receipt_body)
            return receipt
    finally:
        os.close(controller)


def continue_supervisor(plan_sha):
    plan = pinned(plan_sha)
    deadline = time.monotonic()+10
    while True:
        descriptor = os.open(base.STORE/'.controller.lock', os.O_RDWR | os.O_NOFOLLOW)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise base.StoreError('controller lock handoff timed out')
        finally:
            os.close(descriptor)
        time.sleep(0.05)
    claim = base.read_json(CLAIM, 2048)
    receipt = base.read_json(RECEIPT, 6144)
    if (receipt.get('phase') != 'launched' or receipt.get('plan_sha256') != plan_sha
            or receipt.get('claim_sha256') != base.digest(CLAIM)
            or receipt.get('new_process', {}).get('pid') != os.getpid()
            or claim.get('plan_sha256') != plan_sha
            or claim.get('orphan_seal_sha256') != plan['observed_preconditions']['chunk-000052/seal.json']['sha256']):
        raise base.StoreError('claim/receipt ownership differs')
    process = base.read_json(base.STORE/'process.json', 65536)
    if process != receipt['new_process']:
        raise base.StoreError('process ownership differs')
    base.Store = CompactStore
    startup_state('accepted', plan_sha)
    base.supervise()


def startup_state(state, plan_sha, reason=None):
    """Bounded child acceptance/failure record; replaces only this operational note."""
    payload = body(dict(schema='rolling-research-recovery-startup-v1', state=state,
                        plan_sha256=plan_sha, pid=os.getpid(), updated_ns=time.time_ns(),
                        reason=reason[:240] if reason else None), 1024)
    base.safe_parents(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    temp = OUT/'.startup.json.tmp'
    if temp.exists() or temp.is_symlink():
        raise base.StoreError('startup temp exists')
    publish_once(temp, payload)
    temp.replace(STARTUP)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', choices=('supervise',), default=None)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--plan-sha256')
    args = parser.parse_args()
    if args.action == 'supervise':
        if not args.plan_sha256:
            raise base.StoreError('supervisor needs exact plan SHA')
        try:
            continue_supervisor(args.plan_sha256)
        except Exception as exc:
            startup_state('failed', args.plan_sha256, type(exc).__name__+': '+str(exc))
            raise
    elif args.run:
        if not args.plan_sha256:
            raise base.StoreError('run needs exact plan SHA')
        print(json.dumps(recover_and_launch(args.plan_sha256)))
    else:
        print(json.dumps(dict(mode='dry', plan_status=base.read_json(PLAN, 8192).get('status'),
                              store_mutated=False, raw_opened=False)))


if __name__ == '__main__':
    main()
