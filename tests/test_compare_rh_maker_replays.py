"""Synthetic whole-output comparisons; never reads a live capture/result."""
from __future__ import annotations

import copy
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts import analyze_rh_maker
from scripts.compare_rh_maker_replays import compare, compare_loaded
from scripts.optimized_rh_maker_replay import replay_optimized
from tests.test_optimized_rh_maker_replay import FROZEN_METADATA, synthetic_events


class CompareRhMakerReplaysTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.capture = self.root / 'synthetic_capture'
        self.capture.mkdir()
        shutil.copytree(FROZEN_METADATA, self.capture / 'metadata')
        frames = gzip.compress(b'{"synthetic_fixture":true}\n', mtime=0)
        (self.capture / 'frames.jsonl.gz').write_bytes(frames)
        self.frames_hash = hashlib.sha256(frames).hexdigest()
        manifest = {
            'schema': 'rh-maker-public-capture-v1', 'read_only': True,
            'configured_seconds': 3000, 'calibration_seconds': 1800,
            'holdout_seconds': 1200, 'configured_total_bytes': 384_000_000,
            'started_utc': '2026-09-29T00:00:00+00:00',
            'ended_utc': '2026-09-29T00:50:00+00:00',
            'end_reason': 'duration_limit', 'frames_sha256': self.frames_hash,
            'metadata_normalized_sha256': hashlib.sha256(
                (self.capture / 'metadata/normalized.json').read_bytes()).hexdigest(),
        }
        (self.capture / 'manifest.json').write_text(json.dumps(manifest))
        self.original = self.root / 'original'
        self.cached = self.root / 'cached'
        events = synthetic_events()
        self.left = analyze_rh_maker.replay(self.capture, self.original,
                                            events=copy.deepcopy(events))
        self.right, self.provenance = replay_optimized(
            self.capture, self.cached, events=copy.deepcopy(events))
        self.left_variant = {'variant': 'original_frozen'}
        self.right_variant = {'variant': 'postfreeze_book_parse_cache',
                              'optimization_provenance_sha256': hashlib.sha256(
                                  (self.cached / 'optimization_provenance.json').read_bytes()).hexdigest()}

    def compared(self, left=None, right=None):
        return compare_loaded(left or self.left, right or self.right,
                              self.original, self.cached,
                              self.left_variant, self.right_variant)

    def test_full_synthetic_replay_equivalent_with_only_authorized_wrapper_differences(self):
        result = self.compared()
        self.assertTrue(result['equivalent'], result['mismatches'])
        self.assertEqual(result['audit_records_original'], result['audit_records_cached'])
        self.assertGreater(result['ordered_audit_rows_matched'], 0)
        self.assertTrue(result['ordered_audit_rows_equal'])
        self.assertTrue(result['audit_byte_identical'])
        self.assertTrue(result['models_exact'])
        self.assertTrue(result['branches_exact'])
        self.assertTrue(result['counts_exact'])
        self.assertTrue(result['errors_exact'])
        self.assertEqual(result['original_source_sha256'], self.left['source_sha256'])
        self.assertEqual(result['cached_wrapper_sha256'],
                         self.right['source_sha256']['scripts/optimized_rh_maker_replay.py'])

    def test_financial_and_nested_model_changes_cannot_hide_behind_runtime_allowlist(self):
        altered = copy.deepcopy(self.right)
        altered['branches'][0]['fees_hl'] = '999'
        altered['models']['standard']['frozen'] = not altered['models']['standard']['frozen']
        altered['counts']['book'] += 1
        altered['errors'].append('synthetic divergence')
        altered['replay_wall_seconds'] = -12345  # Only this change is allowed.
        result = self.compared(right=altered)
        self.assertFalse(result['equivalent'])
        self.assertFalse(result['branches_exact'])
        self.assertFalse(result['models_exact'])
        self.assertFalse(result['counts_exact'])
        self.assertFalse(result['errors_exact'])
        self.assertTrue(any('fees_hl' in value for value in result['mismatches']))
        self.assertTrue(any('models' in value for value in result['mismatches']))

    def test_ordered_audit_change_and_input_hash_change_are_detected(self):
        with gzip.open(self.cached / 'audit.jsonl.gz', 'rb') as stream:
            rows = stream.read().splitlines(keepends=True)
        self.assertGreater(len(rows), 2)
        rows[0], rows[1] = rows[1], rows[0]
        with gzip.GzipFile(self.cached / 'audit.jsonl.gz', 'wb', mtime=0) as stream:
            stream.writelines(rows)
        altered = copy.deepcopy(self.right)
        altered['audit_sha256'] = hashlib.sha256(
            (self.cached / 'audit.jsonl.gz').read_bytes()).hexdigest()
        result = self.compared(right=altered)
        self.assertFalse(result['ordered_audit_rows_equal'])
        self.assertFalse(result['audit_byte_identical'])
        self.assertFalse(result['equivalent'])
        self.assertTrue(any('audit[0]' in value for value in result['mismatches']))
        altered['raw_sha256'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'input identity differs'):
            self.compared(right=altered)

    def test_cli_path_calls_provenance_gate_twice_and_writes_bounded_report(self):
        def gate(capture, derived):
            self.assertEqual(Path(capture), self.capture)
            if Path(derived) == self.original:
                return self.left, {}, {}, self.left_variant
            if Path(derived) == self.cached:
                return self.right, {}, {}, self.right_variant
            self.fail('unexpected derived path')

        out = self.root / 'comparison'
        with patch('scripts.compare_rh_maker_replays.verify_inputs', side_effect=gate) as called:
            result = compare(self.capture, self.original, self.cached, out)
        self.assertEqual(called.call_count, 2)
        self.assertTrue(result['equivalent'])
        self.assertEqual(json.loads((out / 'comparison.json').read_text())['schema'],
                         'rh-maker-replay-comparison-v1')
        self.assertEqual(result['capture_frames_sha256'], self.frames_hash)
        self.assertEqual(result['original_analysis_sha256'], hashlib.sha256(
            (self.original / 'analysis.json').read_bytes()).hexdigest())
        self.assertEqual(result['cached_analysis_sha256'], hashlib.sha256(
            (self.cached / 'analysis.json').read_bytes()).hexdigest())
        self.assertEqual(result['comparator_source_sha256'], hashlib.sha256(
            (Path(__file__).resolve().parents[1] / 'scripts/compare_rh_maker_replays.py').read_bytes()).hexdigest())
        self.assertLessEqual((out / 'comparison.json').stat().st_size
                             + (out / 'REPORT.md').stat().st_size, 1_000_000)
        with self.assertRaisesRegex(ValueError, 'new directory'):
            compare(self.capture, self.original, self.cached, out)

    def test_raw_archive_tamper_rejected_before_output(self):
        self.assertTrue(self.left['raw_sha256'] == self.right['raw_sha256'] == self.frames_hash)
        (self.capture / 'frames.jsonl.gz').write_bytes(gzip.compress(b'tampered\n', mtime=0))
        def gate(_capture, derived):
            return ((self.left, {}, {}, self.left_variant) if Path(derived) == self.original
                    else (self.right, {}, {}, self.right_variant))
        out = self.root / 'bad_raw_comparison'
        with patch('scripts.compare_rh_maker_replays.verify_inputs', side_effect=gate):
            with self.assertRaisesRegex(ValueError, 'raw gzip SHA-256'):
                compare(self.capture, self.original, self.cached, out)
        self.assertFalse(out.exists())
        with patch('scripts.compare_rh_maker_replays.verify_inputs', side_effect=gate), \
             patch('scripts.compare_rh_maker_replays.MAX_RAW_BYTES', 1):
            with self.assertRaisesRegex(ValueError, '384 MB bound'):
                compare(self.capture, self.original, self.cached, out)
        self.assertFalse(out.exists())

    def test_unlabeled_cached_output_rejected(self):
        unlabeled = copy.deepcopy(self.right)
        unlabeled.pop('implementation_variant')
        with self.assertRaisesRegex(ValueError, 'variant label missing'):
            self.compared(right=unlabeled)
        bad_variant = {'variant': 'original_frozen'}
        with self.assertRaisesRegex(ValueError, 'explicit optimization provenance'):
            compare_loaded(self.left, self.right, self.original, self.cached,
                           self.left_variant, bad_variant)
        with self.assertRaisesRegex(ValueError, 'provenance digest missing'):
            compare_loaded(self.left, self.right, self.original, self.cached,
                           self.left_variant, {'variant': 'postfreeze_book_parse_cache'})


if __name__ == '__main__':
    unittest.main()
