"""Synthetic recovery invariants. No live rolling store or raw capture is opened."""
import copy
import fcntl
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from scripts import rolling_research_capture as base
from scripts import rolling_research_capture_recovery_v1 as recovery


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base.encoded(value, 65536))
    return base.digest(path)


def orphan_fixture(root):
    store = recovery.CompactStore(root=root)
    directory = root/recovery.ORPHAN
    cap = directory/'capture'
    cap.mkdir(parents=True)
    raw = cap/'frames.jsonl.gz'
    raw.write_bytes(b'opaque compressed fixture bytes')
    start, end = '2026-10-02T11:10:34.000000+00:00', '2026-10-02T11:20:35.000000+00:00'
    original = base.read_json(base.PLAN, 65536)
    plan_sha = base.digest(base.ROOT/original['capture_plan'])
    manifest = dict(schema='single-venue-depth-public-capture-v1',
                    started_utc=start, ended_utc=end, end_reason='duration_limit',
                    truncated=False, read_only=True, economic_evaluation=False,
                    selected_markets=base.SELECTED, configured_seconds=base.SECONDS,
                    configured_total_bytes=base.CAPTURE_BYTES,
                    frames_sha256=base.digest(raw), payload_records=1,
                    compressed_payload_bytes=base.regular(raw),
                    market_plan_sha256=plan_sha,
                    source_sha256=base.digest(base.ROOT/'scripts/single_venue_depth_capture.py'))
    manifest_sha = put(cap/'manifest.json', manifest)
    terminal = dict(status='capture_completed', end_reason='duration_limit',
                    manifest_sha256=manifest_sha, plan_sha256=plan_sha)
    put(cap/'terminal.json', terminal)
    files = {name: dict(bytes=size, sha256=base.digest(directory/name))
             for name, size in store.files(directory).items()}
    coverage = {'market|order_book': {'records': 1}}
    seal = dict(schema='rolling-research-seal-v1', chunk_id=recovery.ORPHAN,
                role='reserved_validation', state='sealed_complete', sealed_ns=123,
                result=dict(returncode=0, end_reason='child_finished'),
                validation_claim=False, economic_evaluation=False,
                files=files, manifest_sha256=manifest_sha,
                frames_sha256=manifest['frames_sha256'], payload_records=1,
                capture_started_ns=base.utc_ns(start), capture_ended_ns=base.utc_ns(end),
                decoded_bytes=100, coverage=coverage)
    seal_sha = put(directory/'seal.json', seal)
    index = dict(schema='rolling-research-index-v1', next_number=53, expired=[], chunks={
        recovery.ORPHAN: dict(state='collecting', role='reserved_validation',
                              number=52, launched_ns=1, pins=[], validation_claim=False)})
    base.Store.write(store, 'index.json', index, base.INDEX_BYTES)
    plan = dict(orphan_role='reserved_validation', original_plan={'sha256': plan_sha},
                observed_preconditions={
                    'chunk-000052/seal.json': dict(sha256=seal_sha),
                    'chunk-000052/capture/manifest.json': dict(sha256=manifest_sha),
                    'chunk-000052/capture/terminal.json': dict(sha256=base.digest(cap/'terminal.json'))})
    return store, plan, index, raw


class RecoveryTests(unittest.TestCase):
    def test_compaction_reduces_real_1mib_failure_shape_and_keeps_fields(self):
        with tempfile.TemporaryDirectory() as td:
            store = recovery.CompactStore(root=Path(td))
            channels = {str(i): {'records': i, 'padding': 'x'*100} for i in range(160)}
            entries = {}
            for i in range(52):
                name = f'chunk-{i+1:06d}'
                seal = dict(schema='rolling-research-seal-v1', chunk_id=name,
                            state='sealed_complete', coverage=channels)
                sha = put(Path(td)/name/'seal.json', seal)
                entries[name] = dict(state='sealed_complete', number=i+1,
                                     role=base.role(i+1), pins=['protected'] if i == 0 else [],
                                     seal_sha256=sha, coverage=copy.deepcopy(channels),
                                     payload_records=10, sealed_ns=100+i)
            index = dict(schema='rolling-research-index-v1', next_number=53,
                         chunks=entries, expired=[])
            self.assertGreater(len(json.dumps(index)), base.INDEX_BYTES)
            store.write('index.json', index, base.INDEX_BYTES)
            compacted = store.index()
            self.assertLess(base.regular(Path(td)/'index.json'), base.INDEX_BYTES)
            self.assertEqual(compacted['chunks']['chunk-000001']['pins'], ['protected'])
            self.assertNotIn('coverage', compacted['chunks']['chunk-000001'])
            self.assertEqual(compacted['chunks']['chunk-000001']['coverage_ref']['seal_sha256'],
                             entries['chunk-000001']['seal_sha256'])
            self.assertEqual(compacted['next_number'], 53)
            tampered = copy.deepcopy(compacted)
            tampered['chunks']['chunk-000001']['coverage_ref']['seal_sha256'] = '0'*64
            with self.assertRaisesRegex(base.StoreError, 'reference differs'):
                store.write('index.json', tampered, base.INDEX_BYTES)

    def test_orphan_adoption_validates_opaque_files_without_writing(self):
        with tempfile.TemporaryDirectory() as td, patch.object(recovery, 'pinned_file'):
            store, plan, index, raw = orphan_fixture(Path(td))
            before = base.digest(Path(td)/'index.json')
            adopted = recovery.candidate(store, plan, index)
            self.assertEqual(adopted['chunks'][recovery.ORPHAN]['state'], 'sealed_complete')
            self.assertEqual(adopted['chunks'][recovery.ORPHAN]['pins'], [])
            self.assertEqual(adopted['next_number'], 53)
            self.assertEqual(base.digest(Path(td)/'index.json'), before)
            raw.write_bytes(b'changed opaque bytes')
            with self.assertRaisesRegex(base.StoreError, 'member size/hash'):
                recovery.candidate(store, plan, index)
            self.assertEqual(base.digest(Path(td)/'index.json'), before)

    def test_protected_pin_and_seal_mismatch_refuse_adoption(self):
        with tempfile.TemporaryDirectory() as td, patch.object(recovery, 'pinned_file'):
            store, plan, index, _ = orphan_fixture(Path(td))
            pinned = copy.deepcopy(index)
            pinned['chunks'][recovery.ORPHAN]['pins'] = ['other-reader']
            with self.assertRaisesRegex(base.StoreError, 'orphan index'):
                recovery.candidate(store, plan, pinned)
            wrong = copy.deepcopy(plan)
            wrong['observed_preconditions']['chunk-000052/seal.json']['sha256'] = 'f'*64
            with self.assertRaisesRegex(base.StoreError, 'coverage seal SHA'):
                recovery.candidate(store, wrong, index)

    def test_deadline_live_controller_and_duplicate_claim_fail_closed(self):
        with tempfile.TemporaryDirectory() as td, patch.object(recovery, 'pinned_file'), \
             patch.object(recovery, 'no_original_child'):
            root = Path(td)
            store, plan, index, _ = orphan_fixture(root)
            identity = dict(schema='rolling-research-store-v1', plan_sha256='a'*64,
                            budget_bytes=base.STORE_BYTES, created_ns=1,
                            deadline_ns=time.time_ns()-1)
            put(root/'identity.json', identity)
            put(root/'process.json', dict(pid=12345))
            put(root/'status.json', dict(state='failed'))
            plan.update(identity={}, identity_values=identity, expected_old_process_pid=12345)
            plan['observed_preconditions'].update({x+'.json': {} for x in ('index', 'status', 'process')})
            output = root/'outputs'
            output.mkdir()
            with patch.object(recovery, 'OUT', output), \
                 patch.object(recovery, 'CLAIM', output/'claim.json'), \
                 patch.object(recovery, 'RECEIPT', output/'receipt.json'), \
                 patch.object(recovery, 'STARTUP', output/'startup.json'), \
                 patch.object(recovery, 'process_dead', return_value=True):
                with self.assertRaisesRegex(base.StoreError, 'deadline'):
                    recovery.check_preconditions(store, plan)
                identity['deadline_ns'] = time.time_ns()+2*base.CHILD_SECONDS*10**9
                put(root/'identity.json', identity)
                with patch.object(recovery, 'process_dead', return_value=False):
                    with self.assertRaisesRegex(base.StoreError, 'controller process'):
                        recovery.check_preconditions(store, plan)
                (output/'claim.json').write_bytes(b'existing')
                with self.assertRaisesRegex(base.StoreError, 'claim/receipt already'):
                    recovery.check_preconditions(store, plan)

    def test_live_controller_lock_refuses_before_store_work(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lock = root/'.controller.lock'
            lock.write_bytes(b'')
            descriptor = os.open(lock, os.O_RDWR)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch.object(recovery, 'pinned', return_value={}), \
                     patch.object(recovery, 'CompactStore', return_value=base.Store(root=root)):
                    with self.assertRaisesRegex(base.StoreError, 'controller lock held'):
                        recovery.recover_and_launch('synthetic')
            finally:
                os.close(descriptor)

    def test_child_waits_for_lock_before_reading_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lock = root/'.controller.lock'
            lock.write_bytes(b'')
            descriptor = os.open(lock, os.O_RDWR)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            claim = root/'claim.json'; receipt = root/'receipt.json'
            process = dict(pid=os.getpid(), schema='rolling-research-process-v1')
            put(root/'process.json', process)
            plan = dict(observed_preconditions={'chunk-000052/seal.json': {'sha256': 's'}})
            claim_value = dict(plan_sha256='p', orphan_seal_sha256='s')
            put(claim, claim_value)
            errors = []
            original_store = base.Store
            try:
                with patch.object(recovery, 'pinned', return_value=plan), \
                     patch.object(recovery, 'CLAIM', claim), \
                     patch.object(recovery, 'RECEIPT', receipt), \
                     patch.object(recovery, 'STARTUP', root/'startup.json'), \
                     patch.object(recovery, 'OUT', root), \
                     patch.object(base, 'STORE', root), \
                     patch.object(base, 'supervise') as supervised:
                    def worker():
                        try:
                            recovery.continue_supervisor('p')
                        except Exception as exc:
                            errors.append(exc)
                    thread = threading.Thread(target=worker)
                    thread.start()
                    time.sleep(0.08)
                    self.assertFalse(receipt.exists())
                    supervised.assert_not_called()
                    put(receipt, dict(phase='launched', plan_sha256='p',
                        claim_sha256=base.digest(claim), new_process=process))
                    os.close(descriptor); descriptor = None
                    thread.join(timeout=2)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual(errors, [])
                    supervised.assert_called_once()
            finally:
                base.Store = original_store
                if descriptor is not None:
                    os.close(descriptor)


if __name__ == '__main__':
    unittest.main()
