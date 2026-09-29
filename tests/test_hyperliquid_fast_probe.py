from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from hyperliquid_fast_probe import (
    COINS, Probe, RawCapture, launch_manifest, main, nominal_delay, parse_book,
    subscription,
)


def payload(coin, source, bid='100', ask='101', size='20', levels=5):
    return {'channel': 'l2Book', 'data': {'coin': coin, 'time': source * 1000,
            'levels': [[{'px': str(float(bid) - i), 'sz': size, 'n': 1}
                        for i in range(levels)],
                       [{'px': str(float(ask) + i), 'sz': size, 'n': 1}
                        for i in range(levels)]]}}


class FastProbeTests(unittest.TestCase):
    def test_subscriptions_explicitly_preserve_mode_and_coin(self):
        self.assertEqual(len(COINS), 3)
        self.assertEqual(subscription('BTC', True)['subscription']['fast'], True)
        self.assertEqual(subscription('BTC', False)['subscription']['fast'], False)
        with self.assertRaises(ValueError):
            subscription('ETH', True)

    def test_ack_must_echo_exact_bool_on_correct_connection(self):
        probe = Probe()
        probe.record('fast', {'channel': 'subscriptionResponse',
                    'data': {'method': 'subscribe', 'subscription':
                             {'type': 'l2Book', 'coin': 'BTC', 'fast': True}}}, 100)
        probe.record('slow', {'channel': 'subscriptionResponse',
                    'data': {'method': 'subscribe', 'subscription':
                             {'type': 'l2Book', 'coin': 'BTC'}}}, 100)
        probe.record('fast', {'channel': 'subscriptionResponse',
                    'data': {'method': 'subscribe', 'subscription':
                             {'type': 'l2Book', 'coin': 'xyz:NVDA', 'fast': 1}}}, 100)
        self.assertIn('BTC', probe.acks['fast'])
        self.assertNotIn('BTC', probe.acks['slow'])
        self.assertNotIn('xyz:NVDA', probe.acks['fast'])
        self.assertEqual([e['kind'] for e in probe.errors], ['ack_mismatch', 'ack_mismatch'])

    def test_depth_and_paired_freshness_keep_connection_identity(self):
        probe = Probe()
        probe.record('slow', payload('BTC', 100, levels=20), 100.2)
        probe.record('fast', payload('BTC', 100.1, levels=5), 100.3)
        probe.record('fast', payload('BTC', 103, bid='101', ask='102'), 103.2)
        slow = probe.summary(100, 104)['feeds']['slow']['BTC']
        fast = probe.summary(100, 104)['feeds']['fast']['BTC']
        paired = probe.summary(100, 104)['paired']['BTC']
        self.assertEqual(slow['levels_bid_median'], 20)
        self.assertEqual(fast['levels_bid_median'], 5)
        self.assertEqual(fast['depth_1000_both_fit'], 2)
        self.assertEqual(paired['both_source_fresh_2s_receipt_skew_1s'], 1)
        self.assertEqual(paired['fast_fresh_slow_source_old_over_2s'], 1)
        self.assertEqual(paired['fast_top_differs_from_slow'], 1)

    def test_future_source_and_unordered_or_duplicate_depth_are_raw_only(self):
        with tempfile.TemporaryDirectory() as temp:
            capture = RawCapture(Path(temp) / 'raw.jsonl')
            probe = Probe(capture)
            future = payload('BTC', 100.3)
            probe.record('fast', future, 100.2)
            unordered = payload('BTC', 100, levels=2)
            unordered['data']['levels'][0].reverse()
            probe.record('fast', unordered, 100.2)
            duplicate = payload('BTC', 100, levels=2)
            duplicate['data']['levels'][1][1]['px'] = duplicate['data']['levels'][1][0]['px']
            probe.record('fast', duplicate, 100.2)
            capture.close()
            self.assertEqual(len(probe.events), 0)
            self.assertEqual([e['kind'] for e in probe.errors], ['malformed_book'] * 3)
            self.assertEqual(len((Path(temp) / 'raw.jsonl').read_text().splitlines()), 3)

    def test_manifest_records_process_and_source_hashes(self):
        manifest = launch_manifest()
        self.assertGreater(manifest['pid'], 0)
        self.assertEqual(len(manifest['git_commit']), 40)
        self.assertEqual(len(manifest['sha256']), 3)
        self.assertTrue(all(len(value) == 64 for value in manifest['sha256'].values()))

    def test_nominal_delay_uses_later_source_and_receipt_and_censors_tail(self):
        events = [parse_book('fast', payload('BTC', src)['data'], receipt)
                  for src, receipt in [(100, 100.2), (100.25, 100.27),
                                       (100.35, 100.4), (103.7, 103.8)]]
        result = nominal_delay(events, 104)
        self.assertEqual(result['anchors'], 4)
        self.assertEqual(result['eligible_within_3s'], 1)
        self.assertEqual(result['timed_out_3s'], 2)
        self.assertEqual(result['end_censored'], 1)

    def test_capture_skips_whole_record_at_byte_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'raw.jsonl'
            capture = RawCapture(path, limit=80)
            capture.write('fast', 1, {'channel': 'x'})
            capture.write('slow', 2, {'channel': 'long' * 100})
            capture.close()
            rows = path.read_text().splitlines()
            self.assertEqual(len(rows), 1)
            self.assertEqual(json.loads(rows[0])['connection'], 'fast')
            self.assertLessEqual(path.stat().st_size, 80)
            self.assertEqual(capture.dropped, 1)

    def test_dry_run_writes_nothing_and_duration_is_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'reports'
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--duration', '60', '--output-root', str(output)]), 0)
            self.assertFalse(output.exists())
            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as rejected:
                    main(['--duration', '121', '--output-root', str(output)])
            self.assertEqual(rejected.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
