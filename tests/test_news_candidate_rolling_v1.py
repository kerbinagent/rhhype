"""Small synthetic tests. No real store, nomination, capture or economics reads."""
import sys
sys.dont_write_bytecode = True
import contextlib
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from scripts import news_candidate_rolling_v1 as w


def digest(data):
    return hashlib.sha256(data).hexdigest()


def index(entries, expired=()):
    return {'schema': 'rolling-research-index-v1', 'chunks': {
        f'chunk-{n:06d}': dict(number=n, role=w.rolling.role(n), launched_ns=t, state=s, pins=[])
        for n, t, s in entries}, 'expired': list(expired)}


def rows():
    result = w.unknown_denominators('fixture', 'a' * 64)['rows']
    for r in result:
        r.update(attempts=0, closed=0, closed_cash_after_capital='0', closed_stressed_cash='0',
                 complete=True, unknown=None, position_open=False, pending_order=False)
    for r in result:
        if (r['family'], r['asset'], r['venue']) == ('depth', 'NEAR', 'lighter'):
            r.update(attempts=1, closed=1, closed_stressed_cash='0.5' if r['rule'] == 'depth_follow' else '-0.1')
    return result


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='news_candidate_rolling_test_')
        self.root = Path(self.temp.name)
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(patch.object(w, 'ROOT', self.root))
        self.stack.enter_context(patch.object(w, 'OUT', self.root / 'controls'))
        self.stack.enter_context(patch.object(w, 'PLAN', self.root / 'plan.json'))
        self.stack.enter_context(patch.object(w.fix, 'RESEARCH', self.root / 'ledgers'))

    def tearDown(self):
        # Combined synthetic disk footprint stays below the allocated temporary bound.
        self.assertLessEqual(sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file()), 32768)
        self.stack.close()
        self.temp.cleanup()

    def frozen(self, **changes):
        p = dict(schema=w.SCHEMA, status='frozen', frozen_utc_ns=w.CUTOFF_NS - 10,
                 store_identity_sha256='b' * 64, source_pins=[], **w.required_fields())
        for name in (w.SOURCE, w.TEST):
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'synthetic pinned source only\n')
            p['source_pins'].append(dict(path=name, bytes=path.stat().st_size, sha256=w.fix.sha(path)))
        p.update(changes)
        w.PLAN.write_text(json.dumps(p))
        return p, w.fix.sha(w.PLAN)

    def test_dry_no_store_or_pin_and_freeze_pins(self):
        with patch.object(w, 'read', side_effect=AssertionError('unexpected read')), \
                patch.object(w.rolling, 'Store', side_effect=AssertionError('unexpected store')), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            w.main([])
        self.assertEqual(json.loads(output.getvalue())['store_reads'], 0)
        p, sha = self.frozen()
        with patch.object(w, 'source_contracts', return_value={'execution_parameters': w.strategy.PARAMS}):
            self.assertEqual(w.verify(sha, before_cutoff=True, now_ns=w.CUTOFF_NS - 1), p)
            with self.assertRaisesRegex(ValueError, 'launch_missed_cutoff'):
                w.verify(sha, before_cutoff=True, now_ns=w.CUTOFF_NS)
            with self.assertRaisesRegex(ValueError, 'plan_sha256'):
                w.verify('c' * 64)
            (self.root / w.SOURCE).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'pin_bytes'):
                w.verify(sha)
        p, sha = self.frozen(source_pins=[])
        with patch.object(w, 'source_contracts', return_value={'execution_parameters': w.strategy.PARAMS}):
            with self.assertRaisesRegex(ValueError, 'own_source_pins'):
                w.verify(sha)
        _, sha = self.frozen(status='draft')
        with self.assertRaisesRegex(ValueError, 'plan_not_frozen'):
            w.verify(sha)

    def test_first_reserved_attempt_not_first_success(self):
        c = w.CUTOFF_NS
        obj = index([(63, c + 1, 'sealed_complete'), (64, c - 1, 'sealed_complete'),
                     (65, c + 2, 'sealed_failed'), (66, c + 3, 'sealed_complete')])
        self.assertEqual(w.select_attempt(obj)['number'], 65)
        obj['chunks']['chunk-000065']['state'] = 'collecting'
        self.assertEqual(w.select_attempt(obj)['number'], 65)
        del obj['chunks']['chunk-000065']
        obj['expired'] = [dict(chunk_id='chunk-000065', role='reserved_validation', started_ns=c + 2)]
        self.assertEqual(w.select_attempt(obj)['number'], 65)
        obj['chunks']['chunk-000066']['role'] = 'exploratory'
        with self.assertRaisesRegex(ValueError, 'reservation_identity'):
            w.select_attempt(obj)

    def test_nomination_precedes_any_selected_input_and_failure_no_replacement(self):
        c = w.CUTOFF_NS
        choice = w.select_attempt(index([(65, c + 1, 'sealed_failed'), (66, c + 2, 'sealed_complete')]))
        logs = []
        store = Mock(); store.index.return_value = index([(65, c + 1, 'sealed_failed'), (66, c + 2, 'sealed_complete')])
        with patch.object(w, 'verify'), patch.object(w, 'store_identity', return_value=store), patch.object(w, 'failed_attempt'), \
                patch.object(w, 'control', side_effect=lambda name, value, **k: logs.append((name, value))):
            self.assertEqual(w.nominate({}, 'a' * 64, wall=lambda: c + 4, sleep=lambda _: None), choice)
            self.assertEqual(logs[0][0], 'nomination.json')
            with self.assertRaisesRegex(ValueError, 'selected_attempt_failed'):
                w.wait_selected({}, 'a' * 64, choice, wall=lambda: c + 4)
        store.pin.assert_not_called()
        logs = []; commands = Mock(side_effect=AssertionError('must not evaluate'))
        w.OUT.mkdir()
        with patch.object(w, 'verify', return_value={}), \
                patch.object(w, 'read', return_value={'plan_sha256': 'a' * 64, 'launched_ns': c - 1}), \
                patch.object(w, 'nominate', return_value=choice), \
                patch.object(w, 'wait_selected', side_effect=ValueError('selected_attempt_failed')), \
                patch.object(w.fix, 'command', commands), \
                patch.object(w, 'control', side_effect=lambda name, value, **k: logs.append((name, value))):
            with self.assertRaises(SystemExit):
                w.supervise('a' * 64)
        unavailable = next(v for name, v in logs if name == 'unavailable.json.gz')
        self.assertEqual((len(unavailable['rows']), len(unavailable['audits'])), (100, 20))
        self.assertTrue(all(r['closed_stressed_cash'] is None for r in unavailable['rows']))
        self.assertTrue(all(r['status'] == 'unavailable' for r in unavailable['audits']))
        self.assertFalse(logs[-1][1]['economic_evaluation']); commands.assert_not_called()

    def test_scoped_binding_restoration_on_error(self):
        tracked = [(w.fix, 'PLAN'), (w.fix, 'verify'), (w.fix, 'configure'), (w.fix, 'input_snapshot'),
                   (w.fix, 'publish'), (w.fix.news, 'PLAN'), (w.fix.news.study, 'Study'), (w.fix.news.study, 'iter_events'),
                   (w.fix.news.study.capture, 'SELECTED'), (w.fix.ordinary, 'HARD_BYTES'),
                   (w.cash, 'verify_signal'), (w.cash, 'inputs'), (w.strategy, 'snapshot'), (w.runner, 'inputs')]
        old = [getattr(module, key) for module, key in tracked]
        with patch.object(w, 'configure') as configured:
            with self.assertRaisesRegex(RuntimeError, 'fixture error'):
                with w.bindings({}):
                    w.cash.verify_signal = 'changed by depth auditor'
                    w.strategy.snapshot = 'changed by compact logger'
                    w.fix.news.study.capture.SELECTED = {'changed': True}
                    raise RuntimeError('fixture error')
            configured.assert_called_once()
        self.assertTrue(all(getattr(module, key) is before for (module, key), before in zip(tracked, old)))

    def test_pipeline_24_commands_barrier_and_existing_refusal(self):
        w.OUT.mkdir(); logs = []; ran = []
        @contextlib.contextmanager
        def scoped(*args): yield
        p = w.required_fields()
        with patch.object(w, 'verify', return_value=p), \
                patch.object(w, 'read', return_value={'plan_sha256': 'a' * 64, 'launched_ns': w.CUTOFF_NS - 1}), \
                patch.object(w, 'nominate', return_value={'chunk': 'fixture'}), patch.object(w, 'wait_selected'), \
                patch.object(w, 'bindings', scoped), \
                patch.object(w, 'input_snapshot', return_value={'manifest_sha256': 'b' * 64, 'source': 'fixture'}), \
                patch.object(w.fix, 'require_pins'), patch.object(w.fix, 'sha', return_value='a' * 64), \
                patch.object(w.fix, 'command', side_effect=lambda args, deadline: ran.append(args)), \
                patch.object(w, 'control', side_effect=lambda name, value, **k: logs.append((name, value))), \
                patch.object(w, 'finish_result', side_effect=lambda *args: self.assertEqual(len(ran), 24)):
            w.supervise('a' * 64)
        self.assertEqual(len(ran), 24)
        self.assertEqual([a[1] for a in ran].count('replay'), 2)
        self.assertEqual([a[1] for a in ran].count('audit'), 20)
        self.assertEqual([a[1] for a in ran].count('readout'), 2)
        self.assertEqual(logs[-1][1]['completed_commands'], 24)
        with patch.object(w, 'verify', return_value=p), patch.object(w.subprocess, 'Popen') as popen:
            with self.assertRaisesRegex(ValueError, 'existing_control_root'):
                w.launch('a' * 64)
        popen.assert_not_called()

    def test_gate_primary_control_unknown_zero_and_full_denominator(self):
        rr = rows(); result = w.gate_result(rr)
        self.assertEqual(result['status'], 'advances_coverage_only')
        self.assertEqual(result['primary_minus_fade_stressed_cash'], '0.6')
        self.assertFalse(result['objective_achieved'])
        primary = next(r for r in rr if (r['family'], r['asset'], r['venue'], r['rule']) == ('depth', 'NEAR', 'lighter', 'depth_follow'))
        for change in ({'closed': 0}, {'closed_stressed_cash': '0'}, {'unknown': 'missing exit'}, {'pending_order': True}):
            copy_rows = copy.deepcopy(rr); row = copy_rows[rr.index(primary)]; row.update(change)
            self.assertEqual(w.gate_result(copy_rows)['status'], 'does_not_advance_coverage')
        control_row = next(r for r in rr if (r['family'], r['asset'], r['venue'], r['rule']) == ('depth', 'NEAR', 'lighter', 'depth_fade'))
        control_row['closed_stressed_cash'] = '0.6'
        self.assertEqual(w.gate_result(rr)['status'], 'does_not_advance_coverage')
        with self.assertRaisesRegex(ValueError, 'all_100_rows'):
            w.gate_result(rr[:-1])

    def test_control_peak_bounds_nooverwrite_and_gzip_unknowns(self):
        w.OUT.mkdir()
        w.control('first.json', {'value': 1})
        first = (w.OUT / 'first.json').read_bytes()
        with self.assertRaises(FileExistsError):
            w.control('first.json', {'value': 2})
        self.assertEqual((w.OUT / 'first.json').read_bytes(), first)
        (w.OUT / 'first.json.pending').unlink()
        with self.assertRaisesRegex(ValueError, 'control_file_cap'):
            w.control('huge.json', {'x': 'x' * 8192})
        with patch.dict(w.CAPS, {'controls': 20}):
            with self.assertRaisesRegex(ValueError, 'control_total_peak_cap'):
                w.control('cap.json', {'x': '12345'})
        w.control('unavailable.json.gz', w.unknown_denominators('failed fixture', 'a' * 64), packed=True)
        o = json.loads(gzip.decompress((w.OUT / 'unavailable.json.gz').read_bytes()))
        self.assertEqual((len(o['rows']), len(o['audits'])), (100, 20))
        self.assertTrue(all(r['attempts'] is None for r in o['rows']))

    def test_synthetic_seal_status_inventory_and_pin_before_raw(self):
        # Four tiny synthetic metadata bodies and an opaque synthetic raw file; no frame decode.
        store_root = self.root / 'store'; directory = store_root / 'chunk-000065'; cap = directory / 'capture'
        cap.mkdir(parents=True)
        for name in w.rolling.CAPTURE_NAMES:
            path = directory / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'{}')
        raw = cap / 'frames.jsonl.gz'; raw.write_bytes(b'opaque synthetic raw, never decoded')
        chunk_plan = cap / 'metadata/market_plan.json'; chunk_plan.write_bytes(b'{"fixture":true}')
        cp = dict(w.CHUNK_PLAN, sha256=w.fix.sha(chunk_plan))
        start = w.CUTOFF_NS + 2 * w.NS; end = start + 600 * w.NS
        iso = lambda n: w.datetime.datetime.fromtimestamp(n / w.NS, w.datetime.timezone.utc).isoformat()
        manifest = dict(schema='single-venue-depth-public-capture-v1', read_only=True, economic_evaluation=False,
            selected_markets=w.rolling.SELECTED, market_plan_sha256=cp['sha256'], configured_seconds=600,
            configured_total_bytes=w.BOUNDS['raw_bytes'], end_reason='duration_limit', truncated=False,
            dropped_complete_frame_on_cap=0, frames_sha256=w.fix.sha(raw), started_utc=iso(start), ended_utc=iso(end),
            compressed_payload_bytes=raw.stat().st_size, payload_records=0)
        (cap / 'manifest.json').write_text(json.dumps(manifest))
        mh = w.fix.sha(cap / 'manifest.json')
        terminal = dict(status='capture_completed', end_reason='duration_limit', plan_sha256=cp['sha256'], manifest_sha256=mh)
        (cap / 'terminal.json').write_text(json.dumps(terminal))
        status = dict(economic_evaluation=False, errors=[], compressed_bytes=0, records=0, elapsed_seconds=590)
        (cap / 'status.json').write_text(json.dumps(status))
        files = {name: dict(bytes=(directory / name).stat().st_size, sha256=w.fix.sha(directory / name))
                 for name in w.rolling.CAPTURE_NAMES}
        seal = dict(schema='rolling-research-seal-v1', chunk_id='chunk-000065', role='reserved_validation',
            state='sealed_complete', economic_evaluation=False, validation_claim=False, files=files,
            frames_sha256=manifest['frames_sha256'], manifest_sha256=mh, capture_started_ns=start,
            capture_ended_ns=end, result=dict(returncode=0, end_reason='child_finished'))
        seal_path = directory / 'seal.json'; seal_path.write_text(json.dumps(seal))
        inventory = lambda: {str(p.relative_to(directory)): p.stat().st_size for p in directory.rglob('*') if p.is_file()}
        entry = dict(number=65, role='reserved_validation', launched_ns=w.CUTOFF_NS + w.NS,
                     state='sealed_complete', pins=[w.OWNER], seal_sha256=w.fix.sha(seal_path))
        store = Mock(root=store_root); store.index.side_effect = lambda: {'chunks': {'chunk-000065': entry}}
        store.files.side_effect = lambda d: inventory()
        w.PLAN.write_bytes(b'fixture analysis plan')
        n = dict(chunk='chunk-000065', number=65, role='reserved_validation', launched_ns=entry['launched_ns'])
        p = dict(store_identity_sha256='b' * 64)
        with patch.object(w, 'nomination', return_value=n), patch.object(w, 'store_identity', return_value=store), \
                patch.object(w, 'CHUNK_PLAN', cp), \
                patch.object(w.fix.ordinary, '_metadata', return_value=({'market_plan_sha256': cp['sha256']}, {})) as metadata:
            snap = w.input_snapshot(p)
            self.assertEqual((snap['manifest_sha256'], snap['raw_sha256']), (mh, manifest['frames_sha256']))
            self.assertIn(str((cap / 'status.json').relative_to(self.root)), snap['files'])
            entry['pins'] = []
            with self.assertRaisesRegex(ValueError, 'selected_must_be_pinned_complete'):
                w.input_snapshot(p)
            self.assertEqual(metadata.call_count, 1)
            entry['pins'] = [w.OWNER]
            raw.write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'sealed_file_changed'):
                w.input_snapshot(p)
            raw.write_bytes(b'opaque synthetic raw, never decoded')
            (cap / 'extra.json').write_bytes(b'{}')
            with self.assertRaisesRegex(ValueError, 'sealed_inventory'):
                w.input_snapshot(p)

    def test_publication_labels_preserve_rows_and_cash(self):
        value = dict(rows=rows(), limits='One exploratory scheduled regime')
        body = gzip.compress(w.fix.encode(value), mtime=0)
        with patch.object(w.fix, 'sha', return_value='a' * 64):
            changed = w.output_labels(w.STEM + '-depth-comparison.json.gz', body)
        result = json.loads(gzip.decompress(changed))
        self.assertEqual(result['rows'], value['rows'])
        self.assertEqual(result['wrapper_source_sha256'], 'a' * 64)
        self.assertIn('ordinary rolling', result['limits'])
        text = w.output_labels(w.STEM + '-readout.txt', b'CORRECTED NEWS WINDOW: AUTOMATED PAPER READOUT\n')
        self.assertTrue(text.startswith(b'ORDINARY ROLLING CANDIDATE'))


if __name__ == '__main__':
    unittest.main()
