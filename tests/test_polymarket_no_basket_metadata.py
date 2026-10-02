"""Focused offline synthetics. No market API or economic fixtures."""
import contextlib
import copy
import io
import json
from pathlib import Path
import signal
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts import polymarket_no_basket_metadata as m


def event(title='Fed decision in October 2026?', end='2026-10-28T18:00:00Z'):
    market = {'id': 'synthetic-market', 'question': 'Synthetic outcome?',
              'description': 'Synthetic resolution text.', 'conditionId': 'synthetic-condition',
              'outcomes': '["Yes","No"]', 'clobTokenIds': '["1","2"]',
              'active': True, 'closed': False, 'archived': False,
              'enableOrderBook': True, 'acceptingOrders': True,
              'negRisk': True, 'negRiskMarketID': 'synthetic-negative-risk-id',
              'feeSchedule': {'exponent': 1, 'rate': 0.04, 'takerOnly': True,
                              'rebateRate': 'EXCLUDED-REBATE'}}
    return {'id': 'synthetic-event', 'title': title, 'slug': 'synthetic-event',
            'endDate': end, 'active': True, 'closed': False, 'archived': False,
            'negRisk': True, 'negRiskAugmented': False,
            'negRiskMarketID': 'synthetic-negative-risk-id',
            'markets': [market, dict(market, id='synthetic-market-2')]}


class Response:
    def __init__(self, body, status=200, length=True, media='application/json', encoding='identity', fail_after=None):
        self.stream = io.BytesIO(body)
        self.status = status
        self.headers = {'Content-Type': media, 'Content-Encoding': encoding}
        if length:
            self.headers['Content-Length'] = str(len(body))
        self.fail_after = fail_after

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read1(self, count):
        if self.fail_after is not None and self.stream.tell() >= self.fail_after:
            raise OSError('EXCLUDED raw exception payload')
        if self.fail_after is not None:
            count = min(count, self.fail_after - self.stream.tell())
        return self.stream.read(count)


class Connection:
    def __init__(self, response):
        self.response = response
        self.requests = []
        self.closed = False

    def request(self, *args, **kwargs):
        self.requests.append((args, kwargs))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class MetadataTests(unittest.TestCase):
    def test_dry_default_and_unfrozen_never_connect(self):
        with patch.object(m.http.client, 'HTTPSConnection', side_effect=AssertionError('network')) as network:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(m.main([]), 0)
                self.assertEqual(m.main(['--run']), 1)
            self.assertIn('dry_no_http', output.getvalue())
            self.assertIn('expected_plan_sha_required', output.getvalue())
            network.assert_not_called()

    def frozen_fixture(self, root):
        draft = json.loads(m.PLAN.read_bytes())
        for name in (m.SOURCE, m.TEST):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'synthetic pinned source\n')
        previous = root / draft['previous']
        previous.parent.mkdir(parents=True, exist_ok=True)
        previous.write_bytes(b'synthetic predecessor')
        draft.update(status='frozen_metadata_probe', previous_sha256=m.digest(previous.read_bytes()))
        draft['source_pins'] = [
            {'path': name, 'bytes': len((root / name).read_bytes()),
             'sha256': m.digest((root / name).read_bytes())} for name in (m.SOURCE, m.TEST)]
        plan = root / 'plan.json'
        def save():
            plan.write_bytes(m.encoded(draft))
            return m.digest(plan.read_bytes())
        return draft, plan, save

    def test_exact_plan_source_test_parent_and_caps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            draft, plan, save = self.frozen_fixture(root)
            sha = save()
            with patch.object(m, 'ROOT', root), patch.object(m, 'PLAN', plan):
                self.assertEqual(m.verify(sha)['status'], 'frozen_metadata_probe')
                with self.assertRaises(m.Refusal):
                    m.verify('0' * 64)
                original = copy.deepcopy(draft)
                for mutate in (
                    lambda p: p.update(status='draft'),
                    lambda p: p.update(source_pins=p['source_pins'][:1]),
                    lambda p: p['source_pins'][1].update(path='scripts/other.py'),
                    lambda p: p['source_pins'][0].update(sha256='0' * 64),
                    lambda p: p['request_plan'].update(url='https://example.invalid'),
                    lambda p: p['request_plan'].update(count=True),
                    lambda p: p['request_plan'].update(redirects=True),
                    lambda p: p['output_limits_bytes'].update(raw_body_or_partial=999999),
                    lambda p: p.update(previous_sha256='0' * 64),
                ):
                    draft.clear()
                    draft.update(copy.deepcopy(original))
                    mutate(draft)
                    with self.assertRaises(m.Refusal):
                        m.verify(save())
                draft.clear()
                draft.update(original)
                sha = save()
                out = root / m.OUT
                out.mkdir(parents=True)
                with patch.object(m.http.client, 'HTTPSConnection') as network:
                    with self.assertRaises(FileExistsError):
                        m.run(sha)
                    network.assert_not_called()

    def test_candidate_projection_has_no_incidental_economics(self):
        chosen = event()
        chosen.update(volume='EXCLUDED-VOLUME', liquidity='EXCLUDED-LIQUIDITY')
        chosen['markets'][0].update(bestBid='EXCLUDED-BID', outcomePrices='EXCLUDED-PRICES',
                                   rewards={'id': 'EXCLUDED-REWARDS'}, feeSchedule={
                                       'rate': 0.04, 'exponent': 1, 'takerOnly': True,
                                       'bestAsk': 'EXCLUDED-NESTED', 'rebateRate': 'EXCLUDED-REBATE'})
        result = m.project({'events': [event('Other event'), chosen],
                            'profiles': [{'id': 'EXCLUDED-PROFILE'}]})
        self.assertEqual(result['candidate_indices'], [1])
        self.assertEqual(len(result['search_summaries']), 2)
        self.assertEqual(len(result['candidate']['markets']), 2)
        self.assertEqual(result['candidate']['values']['description'], None)
        self.assertIn('description', result['candidate']['missing_fields'])
        self.assertNotIn('EXCLUDED', m.encoded(result).decode())
        self.assertEqual(result['status'], 'unique_candidate_metadata_available_semantic_review_required')
        # An allowed field with an unexpected object cannot smuggle economics.
        chosen['markets'][0]['description'] = {'bestAsk': 'EXCLUDED-NESTED'}
        result = m.project({'events': [chosen]})
        self.assertEqual(result['status'], 'inconclusive')
        self.assertIn('description', result['candidate']['markets'][0]['invalid_type_fields'])
        self.assertNotIn('EXCLUDED', m.encoded(result).decode())

    def test_exact_title_date_ambiguity_and_unknown_structure(self):
        for title in ('Fed decision in October 2027?', ' Fed decision in October?',
                      'Fed decision in October? extra', 'Other event'):
            self.assertEqual(m.project({'events': [event(title)]})['candidate_indices'], [])
        self.assertEqual(m.project({'events': [event(end='2026-10-28')]})['candidate_indices'], [])
        self.assertEqual(m.project({'events': [event(end='2026-10-29T01:00:00+03:00')]})['candidate_indices'], [0])
        result = m.project({'events': [event(), event()]})
        self.assertIsNone(result['candidate'])
        self.assertIn('candidate_not_unique', result['reasons'])
        for replacement in (None, {}, [dict()], [dict()] * 9):
            chosen = event()
            chosen['markets'] = replacement
            result = m.project({'events': [chosen]})
            self.assertEqual(result['status'], 'inconclusive')
        chosen = event()
        del chosen['negRiskAugmented']
        chosen['markets'][0].pop('acceptingOrders')
        result = m.project({'events': [chosen]})
        self.assertIsNone(result['candidate']['values']['negRiskAugmented'])
        self.assertIsNone(result['candidate']['markets'][0]['values']['acceptingOrders'])
        self.assertEqual(result['status'], 'inconclusive')
        self.assertEqual(len(m.project({'events': [event()] * 11})['search_summaries']), 11)
        self.assertEqual(m.project({'events': [None, event()]})['status'], 'inconclusive')
        for body in ({}, [], {'events': None}):
            with self.assertRaises(m.Refusal):
                m.project(body)

    def test_bounded_json_unicode_duplicate_depth_and_publication(self):
        for raw in (b'{bad', b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}',
                    b'"\\ud800"', b'"\xff"', b'[' * 33 + b']' * 33,
                    b' ' * (m.BODY_CAP + 1)):
            with self.assertRaises(m.Refusal):
                m.strict_json(raw)
        self.assertEqual(m.strict_json(b'{"description":"[{}]"}'), {'description': '[{}]'})
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            m.publish(out / 'metadata.json', {'x': 1}, 100)
            with self.assertRaises(FileExistsError):
                m.publish(out / 'metadata.json', {'x': 2}, 100)
            with self.assertRaises(m.Refusal):
                m.publish(out / 'large.json', {'x': 'a' * 100}, 100)
            self.assertFalse((out / 'large.json').exists())

    def exercise_fetch(self, response):
        connection = Connection(response)
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            receipt = {'request_attempted': False, 'raw_bytes': 0, 'body_complete': False}
            with patch.object(m.http.client, 'HTTPSConnection', return_value=connection) as factory:
                try:
                    m.fetch(out / 'response.body', receipt)
                    code = None
                except Exception as exc:
                    code = str(exc) if isinstance(exc, m.Refusal) else type(exc).__name__
            raw = (out / 'response.body').read_bytes()
        self.assertEqual(len(connection.requests), 1)
        self.assertEqual(connection.requests[0][0], ('GET', m.TARGET))
        self.assertEqual(factory.call_args.args, (m.HOST,))
        self.assertNotIn('proxy', factory.call_args.kwargs)
        self.assertTrue(connection.closed)
        self.assertLessEqual(len(raw), m.BODY_CAP)
        return code, raw, receipt

    def test_transport_is_single_fixed_get_with_partial_evidence(self):
        body = m.encoded({'events': []})
        code, raw, receipt = self.exercise_fetch(Response(body))
        self.assertIsNone(code)
        self.assertEqual(raw, body)
        self.assertTrue(receipt['body_complete'])
        for response, expected in (
            (Response(body, status=302), 'http_status_not_200'),
            (Response(body, status=500), 'http_status_not_200'),
            (Response(body, encoding='gzip'), 'unsupported_content_encoding'),
            (Response(body, media='text/html'), 'unsupported_content_type'),
            (Response(b'x' * (m.BODY_CAP + 1)), 'declared_body_byte_cap_or_invalid_length'),
            (Response(b'x' * (m.BODY_CAP + 1), length=False), 'body_cap_reached_without_complete_eof'),
        ):
            code, raw, _ = self.exercise_fetch(response)
            self.assertEqual(code, expected)
        code, raw, receipt = self.exercise_fetch(Response(body, fail_after=5))
        self.assertEqual(code, 'OSError')
        self.assertEqual(raw, body[:5])
        self.assertFalse(receipt['body_complete'])
        truncated = Response(body)
        truncated.headers['Content-Length'] = str(len(body) + 10)
        self.assertEqual(self.exercise_fetch(truncated)[0], 'incomplete_body')

    def test_worker_failure_receipt_never_leaks_body_or_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            secret = b'EXCLUDED raw price body'
            def broken(path, receipt):
                path.write_bytes(secret)
                receipt['request_attempted'] = True
                raise OSError('EXCLUDED exception price')
            with patch.object(m, 'verify', return_value={}), patch.object(m, 'fetch', side_effect=broken):
                m.worker('0' * 64, out)
            terminal = (out / 'terminal.json').read_bytes()
            self.assertNotIn(b'EXCLUDED', terminal)
            result = json.loads(terminal)
            self.assertEqual(result['raw_bytes'], len(secret))
            self.assertEqual(result['raw_sha256'], m.digest(secret))
            self.assertFalse(result['projection_published'])
            self.assertEqual(result['code'], 'transport_or_internal_failure')

    def test_hard_request_timer_restores_handler_and_supervisor_kills(self):
        previous = signal.getsignal(signal.SIGALRM)
        with self.assertRaises(m.Refusal):
            with m.hard_deadline(0.01, 'synthetic_deadline'):
                time.sleep(0.1)
        self.assertEqual(signal.getsignal(signal.SIGALRM), previous)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)
        class Stuck:
            exitcode = -9
            killed = False
            def start(self): pass
            def join(self, timeout): pass
            def is_alive(self): return True
            def kill(self): self.killed = True
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            (out / 'response.body').write_bytes(b'synthetic partial')
            process = Stuck()
            result = m.supervise(process, time.monotonic() + 0.1, out, '0' * 64)
            self.assertTrue(process.killed)
            self.assertEqual(result['status'], 'process_deadline')
            self.assertFalse(result['terminal_exists'])
            self.assertLess((out / 'supervisor.json').stat().st_size, 8192)


if __name__ == '__main__':
    unittest.main()
