"""Offline safety checks. No test opens market sockets or existing study data."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import rolling_research_capture as capture


class RollingStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / 'rolling'
        self.store = capture.Store(self.root)
        self.now = 10**18
        self.store.initialize('a' * 64, self.now)

    def tearDown(self):
        self.temporary.cleanup()

    def sealed(self, complete=True):
        name, _ = self.store.reserve(self.now)
        (self.root / name / 'capture').mkdir()
        (self.root / name / 'capture/terminal.json').write_text('{}')
        response = dict(capture_started_ns=self.now, capture_ended_ns=self.now + 600 * 10**9,
                        coverage={}, frames_sha256='b' * 64, payload_records=100, decoded_bytes=200)
        effect = None if complete else capture.StoreError('compressed_size_cap')
        with patch.object(capture, 'inspect_capture', return_value=response, side_effect=effect):
            self.store.seal(name, dict(returncode=0, end_reason='child_finished'),
                            'c' * 64, self.now + 601 * 10**9)
        return name

    def expire(self, now):
        with self.store.locked():
            index = self.store.index()
            # Force pressure in tests of deletion eligibility. Production asks
            # only for the next full chunk and otherwise retains older data.
            result = self.store.expire(index, now,
                required_bytes=self.store.budget - capture.CONTROL_BYTES)
            self.store.write('index.json', index, capture.INDEX_BYTES)
            return result

    def test_ample_budget_keeps_chunks_older_than_two_hours(self):
        name = self.sealed()
        next_name, state = self.store.reserve(self.now + 601 * 10**9 + capture.RETENTION_NS)
        self.assertEqual(state, 'collecting')
        self.assertEqual(next_name, 'chunk-000002')
        self.assertTrue((self.root / name / 'seal.json').exists())
        with self.store.locked():
            self.assertEqual(self.store.index()['expired'], [])

    def test_pressure_expires_only_the_oldest_needed_chunk(self):
        oldest = self.sealed(); newer = self.sealed()
        with self.store.locked():
            total, _ = self.store.usage(self.store.index())
        self.store.budget = total + capture.CONTROL_BYTES + capture.CHUNK_BYTES - 1
        next_name, state = self.store.reserve(self.now + 601 * 10**9 + capture.RETENTION_NS)
        self.assertEqual(state, 'collecting')
        self.assertEqual(next_name, 'chunk-000003')
        self.assertFalse((self.root / oldest).exists())
        self.assertTrue((self.root / newer / 'seal.json').exists())

    def test_minimum_age_and_pins_prevent_expiry(self):
        name = self.sealed()
        sealed_ns = self.now + 601 * 10**9
        self.assertEqual(self.expire(sealed_ns + capture.RETENTION_NS - 1), [])
        self.store.pin([name], 'reader')
        self.assertEqual(self.expire(sealed_ns + capture.RETENTION_NS + 1), [])
        self.store.pin([name], 'reader', remove=True)
        self.assertEqual(self.expire(sealed_ns + capture.RETENTION_NS + 1), [name])
        self.assertFalse((self.root / name).exists())
        with self.store.locked():
            row = self.store.index()['expired'][0]
        self.assertEqual(row['frames_sha256'], 'b' * 64)
        self.assertEqual(row['payload_records'], 100)

    def test_expiry_waits_for_reader_lock_and_observes_its_pin(self):
        name = self.sealed()
        started = threading.Event(); completed = threading.Event(); result = []
        def expiry():
            started.set()
            result.extend(self.expire(self.now + 601 * 10**9 + capture.RETENTION_NS))
            completed.set()
        with self.store.locked():
            worker = threading.Thread(target=expiry)
            worker.start(); self.assertTrue(started.wait(1))
            self.assertFalse(completed.wait(0.05))
            index = self.store.index()
            index['chunks'][name]['pins'] = ['reader']
            self.store.write('index.json', index, capture.INDEX_BYTES)
        worker.join(timeout=2)
        self.assertTrue(completed.is_set())
        self.assertEqual(result, [])
        self.assertTrue((self.root / name / 'seal.json').exists())

    def test_incomplete_chunks_cannot_be_pinned_for_analysis(self):
        name = self.sealed(complete=False)
        with self.assertRaises(capture.StoreError):
            self.store.pin([name], 'reader')
        self.assertEqual(self.expire(self.now + 601 * 10**9 + capture.RETENTION_NS), [name])

    def test_unknown_directory_blocks_expiry_without_deleting_known_data(self):
        name = self.sealed()
        unknown = self.root / 'existing-experiment'
        unknown.mkdir(); (unknown / 'keep').write_text('evidence')
        with self.assertRaises(capture.StoreError):
            self.expire(self.now + 601 * 10**9 + capture.RETENTION_NS)
        self.assertTrue((self.root / name / 'seal.json').exists())
        self.assertEqual((unknown / 'keep').read_text(), 'evidence')

    def test_unknown_chunk_content_and_symlinks_block_expiry(self):
        name = self.sealed()
        extra = self.root / name / 'unknown'
        extra.write_text('keep')
        with self.assertRaises(capture.StoreError):
            self.expire(self.now + 601 * 10**9 + capture.RETENTION_NS)
        extra.unlink()
        outside = Path(self.temporary.name) / 'outside'
        outside.write_text('keep')
        (self.root / name / 'capture/status.json').symlink_to(outside)
        with self.assertRaises(capture.StoreError):
            self.expire(self.now + 601 * 10**9 + capture.RETENTION_NS)
        self.assertEqual(outside.read_text(), 'keep')

    def test_budget_reserves_a_full_next_chunk_and_controls(self):
        small = capture.Store(Path(self.temporary.name) / 'small',
                              capture.CONTROL_BYTES + capture.CHUNK_BYTES - 1)
        small.initialize('a' * 64, self.now)
        self.assertEqual(small.reserve(self.now), (None, 'storage_blocked'))
        with small.locked():
            self.assertEqual(small.index()['next_number'], 1)

    def test_all_pinned_full_store_waits_and_does_not_delete(self):
        name = self.sealed()
        self.store.pin([name], 'reader')
        with self.store.locked():
            chunks, _ = self.store.usage(self.store.index())
        self.store.budget = chunks + capture.CONTROL_BYTES + capture.CHUNK_BYTES - 1
        self.assertEqual(self.store.reserve(self.now + capture.RETENTION_NS * 2),
                         (None, 'storage_blocked'))
        self.assertTrue((self.root / name).exists())

    def test_partial_capture_never_seals_complete(self):
        name, _ = self.store.reserve(self.now)
        directory = self.root / name / 'capture'; directory.mkdir()
        outcome = self.store.seal(name, dict(returncode=-9, end_reason='child_timeout'),
                                  'c' * 64, self.now)
        self.assertEqual(outcome['state'], 'sealed_failed')
        self.assertIn('timeout', outcome['failure'])

    def test_interrupted_manifest_is_preserved_as_failed(self):
        name, _ = self.store.reserve(self.now)
        directory = self.root / name / 'capture'; directory.mkdir()
        (directory / 'manifest.json').write_text('{"unfinished":')
        outcome = self.store.seal(name, dict(returncode=-9, end_reason='child_timeout'),
                                  'c' * 64, self.now)
        self.assertEqual(outcome['state'], 'sealed_failed')
        self.assertIn('partial_manifest_error', outcome)
        self.assertIn('capture/manifest.json', outcome['files'])

    def test_raw_cap_cannot_publish_a_complete_chunk(self):
        name, _ = self.store.reserve(self.now)
        directory = self.root / name / 'capture'; directory.mkdir()
        manifest = dict(end_reason='duration_limit', truncated=False,
            dropped_complete_frame_on_cap=0, configured_seconds=600,
            configured_total_bytes=capture.CAPTURE_BYTES, selected_markets=capture.SELECTED,
            market_plan_sha256='c' * 64, read_only=True, economic_evaluation=False)
        (directory / 'manifest.json').write_text(json.dumps(manifest))
        terminal = dict(status='capture_completed', end_reason='duration_limit',
            plan_sha256='c' * 64, manifest_sha256=capture.digest(directory / 'manifest.json'))
        (directory / 'terminal.json').write_text(json.dumps(terminal))
        with (directory / 'frames.jsonl.gz').open('wb') as stream:
            stream.truncate(capture.RAW_BYTES + 1)
        outcome = self.store.seal(name, dict(returncode=0, end_reason='child_finished'),
                                  'c' * 64, self.now)
        self.assertEqual(outcome['state'], 'sealed_failed')
        self.assertIn('raw size/hash differs', outcome['failure'])

    def test_tampered_seal_or_file_blocks_expiry(self):
        name = self.sealed()
        (self.root / name / 'capture/terminal.json').write_text('{"changed":true}')
        with self.assertRaises(capture.StoreError):
            self.expire(self.now + 601 * 10**9 + capture.RETENTION_NS)
        self.assertTrue((self.root / name / 'seal.json').exists())

    def test_role_schedule_is_fixed_and_no_validation_claim(self):
        self.assertEqual([capture.role(i) for i in range(1, 13)],
                         ['exploratory'] * 3 + ['reserved_validation'] * 3
                         + ['exploratory'] * 3 + ['reserved_validation'] * 3)
        name, _ = self.store.reserve(self.now)
        with self.store.locked():
            entry = self.store.index()['chunks'][name]
        self.assertFalse(entry['validation_claim'])

    def test_controller_timeout_stops_child(self):
        result = capture.supervise_child(
            [sys.executable, '-c', 'import time; time.sleep(30)'], self.store, timeout=0.1)
        self.assertEqual(result['end_reason'], 'child_timeout')
        self.assertNotEqual(result['returncode'], 0)
        with self.assertRaises(capture.StoreError):
            capture.supervise_child([], self.store, timeout=721)

    def test_user_stop_stops_child(self):
        (self.root / 'stop.flag').write_text('stop')
        result = capture.supervise_child(
            [sys.executable, '-c', 'import time; time.sleep(30)'], self.store)
        self.assertEqual(result['end_reason'], 'user_stop')

    def test_child_configuration_uses_frozen_collector_and_native_ids(self):
        class Module:
            pass
        module = Module()
        capture.configure_capture(module, self.root / 'chunk/capture', Path('chunk-plan.json'))
        self.assertEqual(module.SELECTED, capture.SELECTED)
        self.assertEqual(module.HARD_SECONDS, 600)
        self.assertEqual(module.HARD_BYTES, 67108864 + 262144)
        self.assertEqual(module.METADATA_MAX_BYTES, 131072)
        self.assertEqual(module.PLAN, Path('chunk-plan.json'))

    def test_duplicate_launch_preserves_original_process_record(self):
        with patch.object(capture.subprocess, 'Popen') as popen:
            popen.return_value.pid = 12345
            first = capture.launch_controller(self.store, 'a' * 64)
            before = (self.root / 'process.json').read_bytes()
            with self.assertRaisesRegex(capture.StoreError, 'launch refused'):
                capture.launch_controller(self.store, 'a' * 64)
            self.assertEqual(popen.call_count, 1)
        self.assertEqual(first['pid'], 12345)
        self.assertEqual((self.root / 'process.json').read_bytes(), before)

    def test_subscription_history_does_not_count_as_live_trade_or_liquidation(self):
        coverage = {}
        history = dict(kind='frame', venue='lighter', market='0', channel='trade',
            receipt_utc_ns=500, annotation=dict(quality='wire_ok', source_min_ns=10, source_max_ns=20),
            payload=dict(type='subscribed/trade', trades=[{}] * 7, liquidation_trades=[{}] * 2))
        capture.observe_frame(coverage, history)
        item = coverage['lighter|0|trade']
        self.assertEqual(item['subscribed_frames'], 1)
        self.assertEqual(item['live_trade_prints'], 0)
        self.assertEqual(item['live_liquidation_prints'], 0)
        self.assertIsNone(item['live_source_min_ns'])
        live = dict(history, receipt_utc_ns=600,
            annotation=dict(quality='wire_ok', source_min_ns=400, source_max_ns=410),
            payload=dict(type='update/trade', trades=[{}] * 3, liquidation_trades=[{}]))
        capture.observe_frame(coverage, live)
        self.assertEqual(item['update_frames'], 1)
        self.assertEqual(item['history_trade_prints'], 7)
        self.assertEqual(item['history_liquidation_prints'], 2)
        self.assertEqual(item['live_trade_prints'], 3)
        self.assertEqual(item['live_liquidation_prints'], 1)
        self.assertEqual(item['source_min_ns'], 10)
        self.assertEqual(item['live_source_min_ns'], 400)
        self.assertEqual(item['live_receipt_min_ns'], 600)


if __name__ == '__main__':
    unittest.main()
