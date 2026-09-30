"""Offline supervisor guards, deadlines, and replay output draining."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import signal
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import watch_passive_replay as watcher
from scripts.analyze_rh_passive_exit import build_protocol


class Clock:
    def __init__(self):
        self.now = 0
        self.on_sleep = lambda: None

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        self.on_sleep()


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.root_patch = patch.object(watcher, 'ROOT', self.root)
        self.root_patch.start()
        capture = self.root / 'data/raw/capture'
        (capture / 'metadata').mkdir(parents=True)
        (capture / 'metadata/normalized.json').write_text('{}')
        (capture / 'frames.jsonl.gz').write_bytes(b'fake compressed archive')
        protocol = self.root / 'reports/study/protocol.json'
        protocol.parent.mkdir(parents=True)
        protocol.write_text(json.dumps(build_protocol('2026-09-30T00:00:00+00:00',
                                                      capture / 'metadata')))
        self.settings = watcher.Settings(capture, protocol, self.root / 'data/derived/replay',
                                         self.root / 'reports/study/supervisor',
                                         wait_seconds=5, replay_seconds=5)
        self.manifest = {'schema': 'rh-maker-public-capture-v1', 'read_only': True,
                         'configured_seconds': 3000, 'calibration_seconds': 1800,
                         'holdout_seconds': 1200, 'configured_total_bytes': 384_000_000,
                         'started_utc': '2026-09-30T00:00:01+00:00',
                         'ended_utc': '2026-09-30T00:50:01+00:00',
                         'metadata_normalized_sha256': hashlib.sha256(b'{}').hexdigest(),
                         'frames_sha256': hashlib.sha256(b'fake compressed archive').hexdigest(),
                         'end_reason': 'duration_limit', 'truncated': False}

    def tearDown(self):
        self.root_patch.stop()
        self.temp.cleanup()

    def finalize(self):
        (self.settings.capture / 'manifest.json').write_text(json.dumps(self.manifest))

    def status(self):
        return json.loads((self.settings.state_dir / 'status.json').read_text())

    def test_default_dry_plan_creates_nothing_and_launches_nothing(self):
        with patch.object(watcher, 'supervise') as supervise, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(watcher.main(['--capture', str(self.settings.capture),
                                           '--protocol', str(self.settings.protocol),
                                           '--out', str(self.settings.out),
                                           '--state-dir', str(self.settings.state_dir)]), 0)
        self.assertEqual(json.loads(out.getvalue())['mode'], 'dry_plan')
        supervise.assert_not_called()
        self.assertFalse(self.settings.state_dir.exists())
        self.assertFalse(self.settings.out.exists())

    def test_new_output_and_state_guards_do_not_overwrite(self):
        self.settings.out.mkdir(parents=True)
        sentinel = self.settings.out / 'keep.txt'
        sentinel.write_text('preserve')
        with self.assertRaisesRegex(ValueError, 'must both be new'):
            watcher.preflight(self.settings)
        self.assertEqual(sentinel.read_text(), 'preserve')
        sentinel.unlink()
        self.settings.out.rmdir()
        self.settings.state_dir.mkdir()
        with self.assertRaisesRegex(ValueError, 'must both be new'):
            watcher.preflight(self.settings)

    def test_paths_and_finite_time_bounds(self):
        for change in ({'out': Path('/tmp/unapproved-replay')}, {'wait_seconds': 3601},
                       {'replay_seconds': float('nan')}, {'poll_seconds': 0},
                       {'wait_seconds': float('inf')}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                watcher.preflight(watcher.Settings(**{**vars(self.settings), **change}))
        self.settings.out.parent.mkdir(parents=True)
        self.settings.out.symlink_to(self.root / 'unused', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'path must be inside|symlink'):
            watcher.preflight(self.settings)

    def test_wait_is_bounded_without_replay(self):
        clock, runner = Clock(), Mock()
        self.assertEqual(watcher.supervise(self.settings, monotonic=clock.monotonic,
                                          sleep=clock.sleep, runner=runner), 3)
        self.assertEqual(clock.now, 5)
        self.assertEqual(self.status()['state'], 'wait_timeout')
        runner.assert_not_called()

    def test_stop_during_wait(self):
        clock, runner = Clock(), Mock()
        self.assertEqual(watcher.supervise(self.settings, lambda: clock.now >= 1,
                                          monotonic=clock.monotonic, sleep=clock.sleep,
                                          runner=runner), 130)
        self.assertEqual(self.status()['state'], 'stopped')
        runner.assert_not_called()

    def test_manifest_arrives_once_and_unknown_replay_is_preserved(self):
        clock = Clock()
        clock.on_sleep = self.finalize
        runner = Mock(return_value=('replay_incomplete', {'replay_attempts': 1,
                                                         'replay_exit_code': 2}))
        self.assertEqual(watcher.supervise(self.settings, monotonic=clock.monotonic,
                                          sleep=clock.sleep, runner=runner), 2)
        runner.assert_called_once()
        status = self.status()
        self.assertEqual(status['state'], 'replay_incomplete')
        self.assertEqual(status['replay_attempts'], 1)
        self.assertEqual(status['frames_sha256'], self.manifest['frames_sha256'])
        self.assertLess((self.settings.state_dir / 'status.json').stat().st_size, watcher.MAX_STATUS_BYTES)
        self.assertFalse((self.settings.state_dir / 'status.json.tmp').exists())

    def test_output_created_while_waiting_rejected(self):
        clock, runner = Clock(), Mock()
        def competing_output():
            self.finalize()
            self.settings.out.mkdir(parents=True)
            clock.on_sleep = lambda: None
        clock.on_sleep = competing_output
        self.assertEqual(watcher.supervise(self.settings, monotonic=clock.monotonic,
                                          sleep=clock.sleep, runner=runner), 1)
        self.assertIn('new directory', self.status()['error'])
        runner.assert_not_called()

    def test_invalid_manifest_and_source_hashes_never_launch(self):
        cases = [([], None), ({**self.manifest, 'configured_seconds': 100}, None),
                 ({**self.manifest, 'read_only': False}, None),
                 ({**self.manifest, 'end_reason': 'signal_sigterm'}, None),
                 ({**self.manifest, 'frames_sha256': '0' * 64}, None),
                 ({**self.manifest, 'ended_utc': '2026-09-30T00:49:00+00:00'}, None),
                 (self.manifest, 'bad-source')]
        original = self.settings.protocol.read_text()
        for index, (manifest, corruption) in enumerate(cases):
            with self.subTest(index=index):
                settings = watcher.Settings(**{**vars(self.settings),
                                               'state_dir': self.settings.state_dir.with_name(f'case{index}')})
                self.settings.protocol.write_text(original)
                if corruption:
                    protocol = json.loads(original)
                    protocol['source_sha256']['scripts/analyze_rh_passive_exit.py'] = '0' * 64
                    self.settings.protocol.write_text(json.dumps(protocol))
                (settings.capture / 'manifest.json').write_text(json.dumps(manifest))
                runner = Mock()
                self.assertEqual(watcher.supervise(settings, runner=runner), 1)
                runner.assert_not_called()

    def test_protocol_changed_while_waiting_rejected(self):
        clock, runner = Clock(), Mock()
        def changed():
            self.finalize()
            self.settings.protocol.write_text(self.settings.protocol.read_text() + '\n')
        clock.on_sleep = changed
        self.assertEqual(watcher.supervise(self.settings, monotonic=clock.monotonic,
                                          sleep=clock.sleep, runner=runner), 1)
        self.assertIn('protocol changed', self.status()['error'])
        runner.assert_not_called()

    def test_transient_partial_manifest_waits_for_complete_stable_bytes(self):
        path = self.settings.capture / 'manifest.json'
        path.write_text('{"schema":')
        clock = Clock()
        def complete():
            self.finalize()
            clock.on_sleep = lambda: None
        clock.on_sleep = complete
        runner = Mock(return_value=('replay_finished', {'replay_attempts': 1,
                                                       'replay_exit_code': 0}))
        self.assertEqual(watcher.supervise(self.settings, monotonic=clock.monotonic,
                                          sleep=clock.sleep, runner=runner), 0)
        self.assertEqual(clock.now, 2)
        runner.assert_called_once()

    def test_stable_invalid_manifest_is_rejected_after_one_poll(self):
        (self.settings.capture / 'manifest.json').write_text('{"schema":')
        clock, runner = Clock(), Mock()
        self.assertEqual(watcher.supervise(self.settings, monotonic=clock.monotonic,
                                          sleep=clock.sleep, runner=runner), 1)
        self.assertEqual(clock.now, 1)
        self.assertEqual(self.status()['error_type'], 'JSONDecodeError')
        runner.assert_not_called()

    def test_changing_manifest_remains_within_wait_deadline(self):
        path = self.settings.capture / 'manifest.json'
        path.write_text('{')
        clock, runner = Clock(), Mock()
        clock.on_sleep = lambda: path.write_text(path.read_text() + ' ')
        self.assertEqual(watcher.supervise(self.settings, monotonic=clock.monotonic,
                                          sleep=clock.sleep, runner=runner), 3)
        self.assertEqual(clock.now, 5)
        self.assertEqual(self.status()['state'], 'wait_timeout')
        runner.assert_not_called()


class FakeProcess:
    pid = 87654321

    def __init__(self, chunks, returncode=0):
        self.chunks = chunks
        self.returncode = returncode
        self.stdout = Mock()
        self.stdout.fileno.return_value = 123

    def poll(self):
        return self.returncode if not self.chunks else None

    def wait(self, timeout):
        return self.returncode


class FakeSelector:
    def __init__(self, process, clock):
        self.process, self.clock = process, clock

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def register(self, *args):
        pass

    def unregister(self, *args):
        pass

    def select(self, timeout):
        self.clock.sleep(timeout)
        return [(SimpleNamespace(fileobj=self.process.stdout), 1)]


class ReplayProcessTests(unittest.TestCase):
    def run_fake(self, chunks, timeout=5, stopped=lambda: False):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        state = Path(temp.name)
        settings = watcher.Settings(state_dir=state, replay_seconds=timeout)
        process, clock, killpg = FakeProcess(chunks), Clock(), Mock()
        popen = Mock(return_value=process)
        def read(fd, maximum):
            return chunks.pop(0) if chunks else b''
        with patch.object(watcher.os, 'set_blocking'), patch.object(watcher.os, 'read', side_effect=read):
            result = watcher.run_replay(settings, stopped, popen=popen,
                                        monotonic=clock.monotonic,
                                        selector_factory=lambda: FakeSelector(process, clock),
                                        killpg=killpg)
        self.assertTrue(popen.call_args.kwargs['start_new_session'])
        process.stdout.close.assert_called_once()
        return result, state, killpg

    def test_log_cap_continues_draining_until_child_exits(self):
        chunks = [b'x' * 65_536 for _ in range(20)]
        (reason, details), state, killpg = self.run_fake(chunks)
        self.assertEqual(reason, 'replay_finished')
        self.assertEqual(chunks, [])
        self.assertEqual((state / 'replay.log').stat().st_size, watcher.MAX_LOG_BYTES)
        self.assertEqual(details['discarded_log_bytes'], 20 * 65_536 - watcher.MAX_LOG_BYTES)
        killpg.assert_not_called()

    def test_timeout_terminates_only_child_group(self):
        (reason, details), _, killpg = self.run_fake([b'busy'] * 100, timeout=0.5)
        self.assertEqual(reason, 'replay_timeout')
        self.assertEqual(killpg.call_args_list[0].args, (FakeProcess.pid, signal.SIGTERM))
        self.assertEqual(killpg.call_args_list[1].args, (FakeProcess.pid, signal.SIGKILL))

    def test_stop_terminates_child_group(self):
        (reason, _), _, killpg = self.run_fake([b'busy'], stopped=lambda: True)
        self.assertEqual(reason, 'stopped')
        self.assertEqual(killpg.call_count, 2)


if __name__ == '__main__':
    unittest.main()
