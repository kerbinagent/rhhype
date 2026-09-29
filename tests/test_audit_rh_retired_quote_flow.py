"""Synthetic, outcome-free checks for the independent late-flow adjudicator."""

import gzip
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.audit_rh_retired_quote_flow import (
    CACHED_VARIANT, FREEZE, ORIGINAL_SOURCE_KEYS, ROOT, WRAPPER,
    audit_rows, bounded_json, match_trades, retired_quotes,
    report_markdown, sha256, verify_inputs,
)


def key():
    return {'tier': 'standard', 'asset': 'BTC', 'budget_usd': 1000,
            'policy': 'fixed_best'}


def mock_analysis(*, attributed='0', flat_ns=250):
    branches = []
    for tier in ('standard', 'premium'):
        for asset in ('BTC', 'ETH', 'NVDA', 'XAG'):
            for budget in (100, 250, 500, 1000):
                for policy in ('adaptive', 'persistence', 'fixed_best'):
                    branch = {'tier': tier, 'asset': asset, 'budget_usd': str(budget),
                              'policy': policy, 'unknown_reason': None, 'episodes': []}
                    if (tier, asset, budget, policy) == ('standard', 'BTC', 1000, 'fixed_best'):
                        branch['episodes'] = [{'number': 1, 'decided_ns': 10,
                                               'flat_ns': flat_ns,
                                               'maker_attributed': attributed}]
                    branches.append(branch)
    return {'branches': branches}


def row(event, ns, **extra):
    return dict(key(), event=event, ns=ns, **extra)


def trade(receipt, source, *, side='sell', price=100, qty=1, ident='x'):
    return {'type': 'trade', 'venue': 'rh_lighter', 'asset': 'BTC',
            'received_ns': receipt, 'source_ns': source, 'clock_valid': True,
            'side': side, 'price': price, 'qty': qty, 'trade_id': ident}


class RetiredQuoteAuditTests(unittest.TestCase):
    def test_late_source_interval_flags_only_potential_ambiguity(self):
        rows = [row('quote_requested', 10, price='100', qty='1', due_ns=100),
                row('activated', 110), row('cancel_requested', 150, due_ns=200),
                row('episode_flat', 250)]
        tombstones, counts = retired_quotes(mock_analysis(), rows)
        self.assertEqual(counts['retired_with_remaining'], 1)
        self.assertEqual(tombstones['BTC'][0]['remaining'], 1)
        events = [trade(250, 180, ident='before_flat_receipt'),
                  trade(251, 99, ident='before_activation'),
                  trade(252, 201, ident='after_cancel_source'),
                  trade(253, 180, side='buy', ident='wrong_side'),
                  trade(254, 180, price=100.01, ident='above_bid'),
                  trade(255, 100, ident='start_inclusive'),
                  trade(256, 200, ident='end_inclusive'),
                  {'type': 'end', 'raw_sha_verified': True, 'raw_gzip_sha256': 'x'}]
        trade_counts, terminal = match_trades(tombstones, events)
        self.assertEqual(trade_counts['unique_trade_events_with_match'], 2)
        self.assertEqual(tombstones['BTC'][0]['match_count'], 2)
        self.assertTrue(terminal['raw_sha_verified'])

    def test_partial_attribution_retains_residual_and_unknown_branch(self):
        rows = [row('quote_requested', 10, price='100', qty='1', due_ns=100),
                row('activated', 110), row('maker_increment', 120, qty='.25', remaining='.75'),
                row('cancel_requested', 150, due_ns=200), row('episode_flat', 250)]
        analysis = mock_analysis(attributed='.25')
        target = next(b for b in analysis['branches'] if b['tier'] == 'standard'
                      and b['asset'] == 'BTC' and b['budget_usd'] == '1000'
                      and b['policy'] == 'fixed_best')
        target['unknown_reason'] = 'later_new_quote_unknown'
        tombstones, _ = retired_quotes(analysis, rows)
        q = tombstones['BTC'][0]
        self.assertEqual(str(q['remaining']), '0.75')
        self.assertEqual(q['prior_unknown_reason'], 'later_new_quote_unknown')
        counts, _ = match_trades(tombstones, [trade(300, 180),
                                              {'type': 'end', 'raw_sha_verified': True}])
        self.assertEqual(counts['trade_quote_ambiguity_matches'], 1)

    def test_fully_attributed_and_unactivated_not_retired(self):
        rows = [row('quote_requested', 10, price='100', qty='1', due_ns=100),
                row('activated', 110), row('maker_increment', 120, qty='1', remaining='0'),
                row('cancel_requested', 150, due_ns=200), row('episode_flat', 250)]
        tombstones, counts = retired_quotes(mock_analysis(attributed='1'), rows)
        self.assertFalse(tombstones)
        self.assertEqual(counts.get('retired_with_remaining', 0), 0)

    def test_audit_reader_count_and_hash_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capture, derived = root / 'capture', root / 'derived'
            (capture / 'metadata').mkdir(parents=True)
            derived.mkdir()
            shutil.copyfile(ROOT / 'reports/rh-small-maker-v1/metadata/normalized.json',
                            capture / 'metadata/normalized.json')
            audit = gzip.compress((json.dumps(row('quote_requested', 10,
                                                  price='100', qty='1', due_ns=100)) + '\n').encode())
            (derived / 'audit.jsonl.gz').write_bytes(audit)
            manifest = {'schema': 'rh-maker-public-capture-v1', 'read_only': True,
                        'frames_sha256': 'a' * 64,
                        'metadata_normalized_sha256': sha256(capture / 'metadata/normalized.json')}
            (capture / 'manifest.json').write_text(json.dumps(manifest))
            freeze = bounded_json(FREEZE, 1_000_000)
            source = {name: freeze['files'][name] for name in ORIGINAL_SOURCE_KEYS}
            analysis = {'schema': 'rh-maker-replay-v1', 'event_source': 'verified_capture',
                        'status': 'complete', 'branches': mock_analysis()['branches'],
                        'capture_manifest_sha256': sha256(capture / 'manifest.json'),
                        'raw_sha256': 'a' * 64, 'audit_sha256': sha256(derived / 'audit.jsonl.gz'),
                        'audit_bytes': len(audit), 'audit_records': 1, 'source_sha256': source}
            (derived / 'analysis.json').write_text(json.dumps(analysis))
            self.assertEqual(len(list(audit_rows(derived / 'audit.jsonl.gz', 1))), 1)
            self.assertEqual(verify_inputs(capture, derived)[0]['status'], 'complete')
            self.assertEqual(verify_inputs(capture, derived)[3]['variant'], 'original_frozen')
            analysis['implementation_variant'] = CACHED_VARIANT
            analysis['optimization_cache'] = {'parse_calls': 3, 'cache_hits': 2,
                                              'cache_misses': 1, 'validation_errors': 0}
            for name in (WRAPPER, 'scripts/analyze_rh_maker.py', 'scripts/rh_maker_engine.py'):
                analysis['source_sha256'][name] = sha256(ROOT / name)
            (derived / 'analysis.json').write_text(json.dumps(analysis))
            provenance = {
                'schema': 'rh-maker-replay-optimization-v1',
                'implementation_variant': CACHED_VARIANT,
                'post_freeze_optimization': True,
                'optimization': 'one_event_identity_immutable_Book_parse_cache',
                'original_replay': 'scripts/analyze_rh_maker.py',
                'original_engine': 'scripts/rh_maker_engine.py',
                'capture_manifest_sha256': analysis['capture_manifest_sha256'],
                'raw_sha256': analysis['raw_sha256'],
                'analysis_sha256': sha256(derived / 'analysis.json'),
                'audit_sha256': analysis['audit_sha256'],
                'source_sha256': {name: analysis['source_sha256'][name] for name in
                                  (WRAPPER, 'scripts/analyze_rh_maker.py',
                                   'scripts/rh_maker_engine.py')},
                'cache': analysis['optimization_cache']}
            (derived / 'optimization_provenance.json').write_text(json.dumps(provenance))
            info = verify_inputs(capture, derived)[3]
            self.assertEqual(info['variant'], CACHED_VARIANT)
            self.assertEqual(info['original_equivalence'],
                             'not_assessed_requires_full_original_cached_comparison')
            provenance['audit_sha256'] = '0' * 64
            (derived / 'optimization_provenance.json').write_text(json.dumps(provenance))
            with self.assertRaisesRegex(ValueError, 'optimization provenance mismatch: audit_sha256'):
                verify_inputs(capture, derived)
            provenance['audit_sha256'] = analysis['audit_sha256']
            (derived / 'optimization_provenance.json').write_text(json.dumps(provenance))
            (derived / 'audit.jsonl.gz').write_bytes(audit + b'corruption')
            with self.assertRaisesRegex(ValueError, 'audit digest'):
                verify_inputs(capture, derived)

    def test_zero_flag_report_has_explicit_narrow_scope(self):
        note = report_markdown({'status': 'specific_check_passed_no_flags',
                                'affected_branch_count': 0, 'affected_episode_count': 0,
                                'replay_status': 'complete', 'capture_end_reason': 'duration_limit',
                                'capture_truncated': False, 'lifecycle_counts': {},
                                'trade_counts': {}, 'affected_branches': {},
                                'flag_details_truncated': False,
                                'implementation_variant': 'original_frozen',
                                'original_equivalence': 'original_reference'})
        self.assertIn('passes only this specific delayed-print test', note)


if __name__ == '__main__':
    unittest.main()
