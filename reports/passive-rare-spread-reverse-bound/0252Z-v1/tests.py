"""Synthetic exact bounds and publication gates; no parent data or raw scan."""
from collections import Counter
from copy import deepcopy
from fractions import Fraction as F
import json
from pathlib import Path
import tempfile
import unittest

from scripts.analyze_reverse_static_upper_bound import (
    ASSETS, SIZES, ROWS, upper_bound, text, evaluate_rows, rates,
    validate_counts, validate_timing, inventory, unchanged, publish, sha,
    verify_publication, RAW_SHA, INPUT_CAP,
)


def metadata():
    return {'markets': {
        'rh_lighter': {a: {'taker_fee_bps': '0', 'contract_multiplier': '1',
                           'quote_multiplier': '1', 'size_step': '.01'} for a in ASSETS},
        'hyperliquid': {a: {'maker_fee_bps': '1.5' if a in ('BTC', 'ETH') else '.300',
                            'size_step': '.01', 'growth_mode': 'enabled',
                            'deployer_fee_scale': '1'} for a in ASSETS}}}


def all_missing():
    return [{'k': str(k), 'asset': a, 'budget': str(b), 'valid': 'False', 'reason': 'missing_rh'}
            for k in range(3000) for a in ASSETS for b in SIZES]


def missing_summary():
    return {'possible': ROWS, 'valid': 0, 'positive': 0, 'asset_budgets': [
        {'asset': a, 'budget': b, 'possible': 3000, 'valid': 0, 'positive': 0,
         'exclusions': {'missing_rh': 3000}, 'strata': [
             {'stratum': s, 'possible': 600, 'valid': 0, 'positive': 0,
              'exclusions': {'missing_rh': 600}} for s in range(5)]}
        for a in ASSETS for b in SIZES]}


def synthetic_parent(directory):
    """Completed report fixture only; never creates or reads raw input."""
    payloads={'source.py':b'source', 'tests.py':b'tests', 'method.md':b'method',
              'metadata.json':json.dumps(metadata()).encode(), 'readout.md':b'readout',
              'observations.csv':b'k,asset,budget,valid\n', 'timing.csv':b'k,asset\n'}
    for name,body in payloads.items():(directory/name).write_bytes(body)
    claims={
        '/synthetic/scripts/analyze_passive_rare_spread.py':sha(directory/'source.py'),
        '/synthetic/tests/test_passive_rare_spread.py':sha(directory/'tests.py'),
        '/synthetic/research/passive-rare-spread-fixed-anchor-method.md':sha(directory/'method.md'),
        '/synthetic/20260930T0252Z/metadata/normalized.json':sha(directory/'metadata.json'),
        '/synthetic/20260930T0252Z/frames.jsonl.gz':RAW_SHA,
        '/synthetic/20260930T0252Z/manifest.json':'raw-manifest',
        '/synthetic/scripts/rh_maker_events.py':'adapter',
        '/synthetic/scripts/maker_book_archive.py':'decoder'}
    freeze={'frozen_at':'2026-09-30T04:00:00+00:00','input_hashes':claims,
            'anchors':3000,'expected_rows':ROWS,'bounds':{'derived_bytes':INPUT_CAP}}
    (directory/'freeze.json').write_text(json.dumps(freeze))
    summary=missing_summary()
    summary.update(interpretation='retrospective_static_quote_feasibility_not_fill_or_profit',
                   canonical_terminal={'type':'end','truncated':False,'raw_sha_verified':True,
                       'reason':'duration_limit','raw_gzip_sha256':RAW_SHA,
                       'manifest_sha256':'raw-manifest','adapter_sha256':'adapter',
                       'book_decoder_sha256':'decoder','counts':{'decoded_records':124019},
                       'started_ns':1,'stopped_ns':3000*1_000_000_000+1})
    (directory/'summary.json').write_text(json.dumps(summary))
    manifest={'completed_at':'2026-09-30T04:01:00+00:00','input_hashes_unchanged':True,
              'raw_scan_count':1,'network_calls':0,'derived_cap_bytes':INPUT_CAP,
              'input_hashes':claims,'output_hashes':{p.name:sha(p) for p in directory.iterdir()}}
    (directory/'manifest.json').write_text(json.dumps(manifest))
    return manifest,summary


class ReverseStaticBoundTests(unittest.TestCase):
    def test_joint_bound_against_exact_actual_own_fees(self):
        q, bid, ask, S, B = F(1), F(100), F(101), F(100), F(102)
        y, x = F('100.2'), F('101.8')
        for h in (F(0), F('0.00015'), F('0.00003')):
            actual = x-y-h*(x+y)-q*(ask-bid)-F('.10')-F('.0005')*y
            bound = upper_bound(q, bid, ask, S, B, h)
            self.assertLessEqual(actual, bound)
            loose = B-S-q*(ask-bid)-2*h*S-F('.10')-F('.0005')*S
            self.assertEqual(loose-bound, h*(B-S))
        # Actual fee can be below h*(B+S); joint algebra remains valid.
        self.assertLess(F('.00015')*(F('100.1')+F('100.2')), F('.00015')*(S+B))

    def test_exact_zero_threshold_and_invalid_fees(self):
        self.assertEqual(upper_bound(1, 100, 101, 100, '101.15', 0), 0)
        self.assertGreater(upper_bound(1, 100, 101, 100, '101.1500000000000000000001', 0), 0)
        for h in (-1, 1, 'NaN'):
            with self.assertRaises(ValueError):
                upper_bound(1, 100, 101, 100, 102, h)
        self.assertEqual(text(F(100)), '100')
        self.assertEqual(text(F(-100)), '-100')
        self.assertEqual(text(F(1, 10_000)), '0.0001')

    def test_all_invalid_retained_and_unadjudicated(self):
        result = evaluate_rows(iter(all_missing()), metadata(), missing_summary())
        self.assertEqual(result['possible'], ROWS)
        self.assertEqual(result['evaluated'], 0)
        self.assertEqual(result['row_status_48000'], 'X'*ROWS)
        self.assertEqual(result['row_upper_bound_48000'], [None]*ROWS)
        self.assertEqual(len(result['groups']), 80)
        self.assertTrue(all(g['possible']==600 and g['parent_invalid_unadjudicated']==600 for g in result['groups']))

    def test_duplicate_missing_and_outside_identities_fail(self):
        row = all_missing()[0]
        for rows in ([row, row], [row], [{**row, 'k': '3000'}]):
            with self.assertRaises(ValueError):
                evaluate_rows(iter(rows), metadata(), missing_summary())

    def test_valid_zero_row_and_summary_counter_gate(self):
        rows = all_missing()
        # budget100/ask100 gives inherited q1 exactly; the zero boundary is
        # separately tested above. This row has a simple negative bound.
        rows[0]={'k':'0','asset':'BTC','budget':'100','valid':'True','positive':'False',
                 'quantity':'1','rh_bid':'99','rh_ask':'100','hl_sell':'100','hl_buy':'101','net':'-1'}
        summary=missing_summary(); summary['valid']=1
        route=summary['asset_budgets'][0];route['valid']=1;route['exclusions']['missing_rh']-=1
        route['strata'][0]['valid']=1;route['strata'][0]['exclusions']['missing_rh']-=1
        result=evaluate_rows(iter(rows),metadata(),summary)
        self.assertEqual(result['evaluated'],1)
        self.assertEqual(result['row_status_48000'][0],'N')
        bad=deepcopy(summary);bad['valid']=2
        with self.assertRaisesRegex(ValueError,'denominator counters'):
            evaluate_rows(iter(rows),metadata(),bad)
        rows[0]['quantity']='.99'
        with self.assertRaisesRegex(ValueError,'inherited parent policy'):
            evaluate_rows(iter(rows),metadata(),summary)

    def test_fee_context_rejected(self):
        meta=metadata();self.assertEqual(rates(meta)['BTC'],F('1.5')/10000)
        for venue,asset,field,value in (('rh_lighter','BTC','taker_fee_bps','1'),
                                        ('hyperliquid','XAG','maker_fee_bps','-.3')):
            bad=deepcopy(meta);bad['markets'][venue][asset][field]=value
            with self.assertRaises(ValueError):rates(bad)

    def test_timing_identity_missing_duplicate_and_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'timing.csv'
            body='k,asset\n'+''.join(f'{k},{a}\n' for k in range(3000) for a in ASSETS)
            path.write_text(body);validate_timing(path)
            path.write_text(body+'0,BTC\n')
            with self.assertRaises(ValueError):validate_timing(path)
            path.write_text('k,asset\n0,BTC\n')
            with self.assertRaises(ValueError):validate_timing(path)

    def test_unchanged_hash_cap_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'new'
            publish(out,{'a':b'123'},cap=3)
            with self.assertRaisesRegex(ValueError,'new'):publish(out,{'a':b'1'})
            over=root/'over'
            with self.assertRaisesRegex(ValueError,'cap'):publish(over,{'a':b'1234'},cap=3)
            self.assertFalse(over.exists());self.assertFalse((root/'over.building').exists())
            helper=root/'helper.py';helper.write_text('one');claimed=sha(helper)
            # unchanged refuses unexpected publication inventory as well.
            with self.assertRaises(ValueError):unchanged(out,{}, {helper:claimed})
            from unittest.mock import patch
            with patch('scripts.analyze_reverse_static_upper_bound.inventory',return_value={'a':'hash'}):
                unchanged(out,{'a':'hash'},{helper:claimed})
                helper.write_text('two')
                with self.assertRaisesRegex(ValueError,'changed'):unchanged(out,{'a':'hash'},{helper:claimed})

    def test_completed_publication_hash_terminal_and_supplemental_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent=Path(tmp)
            manifest,summary=synthetic_parent(parent)
            verify_publication(parent,inventory(parent))
            attestation=parent/'verification.json'
            attestation.write_text('{"supplemental":true}')
            hashes=inventory(parent)
            self.assertIn('verification.json',hashes)
            self.assertNotIn('verification.json',manifest['output_hashes'])
            verify_publication(parent,hashes)
            # Supplemental attestation is never retroactively manifest-covered.
            wrong=deepcopy(manifest);wrong['output_hashes']['verification.json']=sha(attestation)
            (parent/'manifest.json').write_text(json.dumps(wrong))
            with self.assertRaisesRegex(ValueError,'provenance'):verify_publication(parent,inventory(parent))
            wrong=deepcopy(manifest);wrong['output_hashes']['observations.csv']='wrong'
            (parent/'manifest.json').write_text(json.dumps(wrong))
            with self.assertRaisesRegex(ValueError,'provenance'):verify_publication(parent,inventory(parent))
            # Reauthenticate the altered summary to exercise the terminal gate,
            # rather than fail only at its outer published-file hash.
            summary['canonical_terminal']['counts']['decoded_records']=124018
            (parent/'summary.json').write_text(json.dumps(summary))
            manifest['output_hashes']['summary.json']=sha(parent/'summary.json')
            (parent/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'terminal'):verify_publication(parent,inventory(parent))
            (parent/'unknown.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'inventory'):inventory(parent)


if __name__=='__main__':
    unittest.main()
