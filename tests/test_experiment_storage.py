"""Synthetic-only safety checks for the read-only study retention planner."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest

from scripts.experiment_storage import inventory


NOW = 1_790_740_000.0


class ExperimentStorageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.workspace = Path(tmp.name)

    def study(self, root, name, *, frame_bytes=100, end_offset=7200,
              manifest=True, pid=None, symlink=False):
        study = self.workspace / 'data/raw' / root / name
        study.mkdir(parents=True)
        (study / 'frames.jsonl.gz').write_bytes(b'x' * frame_bytes)
        (study / 'metadata').mkdir()
        (study / 'metadata/source.json').write_text('{"source":"frozen"}')
        (study / 'protocol.json').write_text('{"method":"frozen"}')
        if manifest:
            ended = datetime.fromtimestamp(NOW-end_offset, timezone.utc).isoformat()
            (study / 'manifest.json').write_text(json.dumps({
                'schema': 'rh-maker-public-capture-v1', 'read_only': True,
                'ended_utc': ended, 'end_reason': 'duration_limit',
                'frames_sha256': 'a' * 64}))
        if pid is not None:
            (study / 'capture.pid').write_text(f'{pid}\n')
        if symlink:
            (study / 'external').symlink_to(self.workspace / 'outside')
        return study

    def test_oldest_complete_frame_only_planned_and_metadata_preserved(self):
        old = self.study('rh-passive-exit-v1', '20260930T000000Z', frame_bytes=400,
                         end_offset=9000)
        new = self.study('rh-passive-exit-v1', '20260930T010000Z', frame_bytes=300,
                         end_offset=7200)
        result = inventory(self.workspace, max_retained_studies=1,
                           max_total_bytes=10_000, now=NOW)
        self.assertEqual(result['mode'], 'dry_run_inventory_only')
        self.assertFalse(result['deletion_supported'])
        self.assertTrue(result['budgets_met_after_plan'])
        self.assertEqual(result['current']['raw_studies'], 2)
        self.assertEqual(result['projected_after_plan']['raw_studies'], 1)
        self.assertEqual(len(result['plan']), 1)
        self.assertEqual(result['plan'][0]['raw_file'],
                         'data/raw/rh-passive-exit-v1/20260930T000000Z/frames.jsonl.gz')
        self.assertEqual(result['plan'][0]['estimated_reclaimable_bytes'], 400)
        self.assertTrue((old / 'frames.jsonl.gz').exists())
        self.assertTrue((new / 'frames.jsonl.gz').exists())
        self.assertTrue((old / 'manifest.json').exists())
        self.assertTrue((old / 'metadata/source.json').exists())
        self.assertTrue((old / 'protocol.json').exists())

    def test_active_incomplete_live_pid_and_pinned_original_are_never_candidates(self):
        old = self.study('rh-passive-exit-v1', '20260930T000000Z', frame_bytes=400)
        active = self.study('rh-passive-exit-v1', '20260930T022700Z',
                            frame_bytes=500, manifest=False)
        live = self.study('rh-passive-exit-v1', '20260930T010000Z',
                          frame_bytes=300, pid=os.getpid())
        pinned = self.study('rh-small-maker', '20260929T212132Z', frame_bytes=600)
        result = inventory(self.workspace, roots=('rh-passive-exit-v1', 'rh-small-maker'),
                           max_retained_studies=0, max_total_bytes=0, now=NOW)
        self.assertFalse(result['budgets_met_after_plan'])
        self.assertEqual([row['study'] for row in result['plan']],
                         ['rh-passive-exit-v1/20260930T000000Z'])
        by_name = {row['study']: row for row in result['studies']}
        self.assertIn('active_or_incomplete_manifest', by_name[
            'rh-passive-exit-v1/20260930T022700Z']['reasons'])
        self.assertIn('live_or_reused_pid', by_name[
            'rh-passive-exit-v1/20260930T010000Z']['reasons'])
        self.assertIn('pinned_original_capture', by_name[
            'rh-small-maker/20260929T212132Z']['reasons'])
        for study in (old, active, live, pinned):
            self.assertTrue((study / 'frames.jsonl.gz').exists())
        stale = self.study('rh-passive-exit-v1', '20260930T013000Z',
                           frame_bytes=200, pid=999_999_999)
        updated = inventory(self.workspace, roots=('rh-passive-exit-v1',),
                            max_retained_studies=0, max_total_bytes=0, now=NOW)
        record = next(row for row in updated['studies'] if row['path'] == str(stale))
        self.assertIn('pid_record_unverified', record['reasons'])

    def test_symlink_and_untrusted_root_fail_closed(self):
        study = self.study('rh-passive-exit-v1', '20260930T000000Z', symlink=True)
        result = inventory(self.workspace, max_retained_studies=0,
                           max_total_bytes=0, now=NOW)
        self.assertEqual(result['plan'], [])
        self.assertIn('symlink_or_special_file', result['studies'][0]['reasons'])
        self.assertTrue((study / 'frames.jsonl.gz').exists())
        with self.assertRaisesRegex(ValueError, 'explicit managed-study'):
            inventory(self.workspace, roots=('arbitrary-raw',), now=NOW)
        (self.workspace / 'data/raw/rh-passive-exit-v1').rename(
            self.workspace / 'data/raw/renamed')
        (self.workspace / 'data/raw/rh-passive-exit-v1').symlink_to(
            self.workspace / 'data/raw/renamed', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'unsafe managed root'):
            inventory(self.workspace, now=NOW)
        (self.workspace / 'data/raw/rh-passive-exit-v1').unlink()
        (self.workspace / 'data/raw').rename(self.workspace / 'data/raw-real')
        (self.workspace / 'data/raw').symlink_to(
            self.workspace / 'data/raw-real', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'unsafe data/raw'):
            inventory(self.workspace, now=NOW)

    def test_recent_completion_and_byte_budget_can_leave_plan_unmet(self):
        study = self.study('rh-passive-exit-v1', '20260930T020000Z',
                           frame_bytes=300, end_offset=30)
        result = inventory(self.workspace, max_retained_studies=0,
                           max_total_bytes=1, min_age_seconds=3600, now=NOW)
        self.assertFalse(result['budgets_met_after_plan'])
        self.assertEqual(result['plan'], [])
        self.assertIn('recent_completion', result['studies'][0]['reasons'])
        self.assertTrue((study / 'metadata/source.json').exists())


if __name__ == '__main__':
    unittest.main()
