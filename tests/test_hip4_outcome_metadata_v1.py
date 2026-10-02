"""Focused offline synthetics. No exchange API, market data or economic fixtures."""
import contextlib
from decimal import Decimal
import gzip
import io
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from scripts import hip4_outcome_metadata_v1 as m

ONE = Decimal(1)


def outcome(oid, quote='USDC', **extra):
    spec = {'outcome': oid, 'name': f'synthetic {oid}', 'description': 'index:0',
            'sideSpecs': [{'name': 'Yes'}, {'name': 'No'}], 'quoteToken': quote}
    spec.update(extra)
    return spec


def meta(**question_changes):
    question = {'question': 7, 'name': 'Synthetic question', 'description': 'synthetic',
                'fallbackOutcome': 10, 'namedOutcomes': [11, 12], 'settledNamedOutcomes': []}
    question.update(question_changes)
    return {'outcomes': [outcome(10), outcome(11), outcome(12),
                         outcome(20, description='class:priceBinary|underlying:SYN')],
            'questions': [question]}


class Response:
    def __init__(self, body, status=200, length=True, media='application/json', encoding='identity'):
        self.stream, self.status = io.BytesIO(body), status
        self.headers = {'Content-Type': media, 'Content-Encoding': encoding, 'Date': 'synthetic'}
        if length:
            self.headers['Content-Length'] = str(len(body))

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read1(self, size):
        return self.stream.read(size)


class Connection:
    calls = []

    def __init__(self, response):
        self.response = response

    def __call__(self, host, timeout, context):
        Connection.calls.append(host)
        return self

    def request(self, method, target, body, headers):
        Connection.calls.append((method, target, body, headers['Accept-Encoding']))

    def getresponse(self):
        return self.response

    def close(self):
        pass


class Ledger:
    """Independent token ledger using the documented conversion semantics."""

    def __init__(self, members):
        self.members, self.cash, self.hold = members, Decimal(0), {}

    def add(self, token, qty):
        self.hold[token] = self.hold.get(token, 0) + qty
        assert self.hold[token] >= 0, token

    def apply(self, kind, member, book):
        tops = book.get(member, {})
        if kind == 'split':
            self.cash -= ONE
            self.add(('Y', member), 1)
            self.add(('N', member), 1)
        elif kind == 'negate':
            self.add(('N', member), -1)
            for other in self.members:
                if other != member:
                    self.add(('Y', other), 1)
        elif kind == 'sell_yes':
            self.add(('Y', member), -1)
            self.cash += Decimal(tops['yes_bid'][0])
        elif kind == 'buy_no':
            self.cash -= Decimal(tops['no_ask'][0])
            self.add(('N', member), 1)
        elif kind == 'buy_yes':
            self.cash -= Decimal(tops['yes_ask'][0])
            self.add(('Y', member), 1)
        elif kind == 'merge_question':
            for other in self.members:
                self.add(('Y', other), -1)
            self.cash += ONE
        elif kind == 'sell_no':
            self.add(('N', member), -1)
            self.cash += Decimal(tops['no_bid'][0])
        else:
            raise AssertionError(kind)

    def residual(self):
        return {k: v for k, v in self.hold.items() if v}


def merged(bid, ask, size='5'):
    """Merged-book tops in Yes terms plus their exact No mirror."""
    tops = {'yes_bid': None, 'yes_ask': None, 'no_bid': None, 'no_ask': None}
    if bid is not None:
        tops['yes_bid'] = (bid, size)
        tops['no_ask'] = (str(ONE - Decimal(bid)), size)
    if ask is not None:
        tops['yes_ask'] = (ask, size)
        tops['no_bid'] = (str(ONE - Decimal(ask)), size)
    return tops


class MetadataTests(unittest.TestCase):
    def test_dry_main_performs_no_http(self):
        out = io.StringIO()
        with patch('http.client.HTTPSConnection', side_effect=AssertionError('network')), \
                contextlib.redirect_stdout(out):
            self.assertEqual(m.main([]), 0)
        self.assertEqual(json.loads(out.getvalue())['status'], 'dry_no_http')

    def test_complete_question_is_structural_candidate_with_gaps_kept(self):
        r = m.analyze(meta())
        self.assertEqual(r['status'], 'structural_candidate')
        q = r['questions'][0]
        self.assertTrue(q['structural_candidate'])
        self.assertEqual(q['common_quote_label'], 'USDC')
        self.assertEqual([s['outcome'] for s in q['member_specs']], [10, 11, 12])
        self.assertEqual(r['standalone_outcomes'], [20])
        self.assertEqual(set(r['unverified']), {'active_state', 'quote_asset_identity', 'native_precision'})
        self.assertEqual(r['precision_status'], 'unavailable_no_documented_field')
        self.assertEqual(r['labels'], {'class:priceBinary': 1, 'other': 3})

    def test_blocking_structures_are_never_candidates(self):
        cases = {
            'settled_named_outcomes_present': meta(settledNamedOutcomes=[11]),
            'fallback_in_named': meta(namedOutcomes=[10, 11]),
            'member_not_listed:13': meta(namedOutcomes=[11, 12, 13]),
            'duplicate_named_outcomes': meta(namedOutcomes=[11, 11]),
            'fallback_missing_or_invalid': meta(fallbackOutcome=True),
            'namedOutcomes_missing_or_invalid': meta(namedOutcomes=[11, 1.0]),
            'no_named_outcomes': meta(namedOutcomes=[]),
        }
        mismatch = meta()
        mismatch['outcomes'][1] = outcome(11, quote='OTHER')
        cases['quote_label_mismatch'] = mismatch
        missing = meta()
        del missing['outcomes'][2]['quoteToken']
        cases['member_quote_missing:12'] = missing
        sides = meta()
        sides['outcomes'][0]['sideSpecs'].append({'name': 'Maybe'})
        cases['member_spec_invalid:10'] = sides
        shared = meta()
        shared['questions'].append(dict(shared['questions'][0], question=8, namedOutcomes=[12, 20]))
        cases['member_shared:12'] = shared
        listed_twice = meta()
        listed_twice['outcomes'].append(outcome(11))
        cases['member_listed_twice:11'] = listed_twice
        for issue, obj in cases.items():
            with self.subTest(issue=issue):
                r = m.analyze(obj)
                self.assertNotEqual(r['status'], 'structural_candidate')
                self.assertIn(issue, r['questions'][0]['issues'])
                self.assertFalse(r['questions'][0]['structural_candidate'])

    def test_missing_or_empty_question_lists(self):
        no_key = meta()
        del no_key['questions']
        self.assertEqual(m.analyze(no_key)['status'], 'inconclusive_membership_unavailable')
        self.assertNotIn('standalone_outcomes', m.analyze(no_key))
        empty = dict(meta(), questions=[])
        self.assertEqual(m.analyze(empty)['status'], 'park_no_question_structure')
        self.assertEqual(m.analyze({'outcomes': {}})['status'], 'inconclusive_schema')
        self.assertEqual(m.analyze(dict(meta(), questions={}))['status'], 'inconclusive_schema')
        bad = dict(meta(), questions=['not-an-object'])
        self.assertEqual(m.analyze(bad)['status'], 'inconclusive_no_structural_candidate')
        # Valid-looking but degenerate or malformed questions never park.
        for change in ({'namedOutcomes': []}, {'fallbackOutcome': None}, {'name': 3}):
            with self.subTest(change=change):
                self.assertEqual(m.analyze(meta(**change))['status'],
                                 'inconclusive_no_structural_candidate')

    def test_duplicate_question_ids_mark_every_occurrence(self):
        obj = meta()
        obj['outcomes'] += [outcome(30), outcome(31)]
        obj['questions'].append(dict(obj['questions'][0], fallbackOutcome=30, namedOutcomes=[31]))
        r = m.analyze(obj)
        self.assertEqual(r['status'], 'inconclusive_no_structural_candidate')
        for q in r['questions']:
            self.assertIn('duplicate_question_id', q['issues'])
            self.assertFalse(q['structural_candidate'])

    def test_truncated_quote_labels_never_match(self):
        obj = meta()
        for spec in obj['outcomes'][:3]:
            spec['quoteToken'] = 'Q' * 600 + str(spec['outcome'])
        r = m.analyze(obj)
        self.assertFalse(r['questions'][0]['structural_candidate'])
        self.assertIn('member_spec_invalid:10', r['questions'][0]['issues'])

    def test_unknown_fields_side_tokens_and_truncation(self):
        obj = meta()
        obj['outcomes'][0].update(newField=1, description='x' * 600)
        obj['outcomes'][1]['sideSpecs'][0]['token'] = 5
        obj['deployers'], obj['feeScale'] = ['0xabc'], 0
        r = m.analyze(obj)
        spec = r['questions'][0]['member_specs'][0]
        self.assertEqual(spec['unknownKeys'], ['newField'])
        self.assertEqual(len(spec['description']), m.TEXT_CAP)
        self.assertEqual(spec['truncated'], ['description'])
        self.assertEqual(r['precision_status'], 'unavailable_side_token_indices_unjoined')
        self.assertEqual((r['deployers_shape'], r['feeScale_shape']), ('list[1]', 0))
        self.assertEqual(r['status'], 'structural_candidate')

    def test_projection_reduction_is_deterministic_and_bounded(self):
        obj = {'outcomes': [], 'questions': []}
        for q in range(400):
            ids = [3 * q, 3 * q + 1, 3 * q + 2]
            obj['outcomes'] += [outcome(i, description='d' * 200) for i in ids]
            obj['questions'].append({'question': q, 'name': 'n', 'description': 'd',
                                     'fallbackOutcome': ids[0], 'namedOutcomes': ids[1:],
                                     'settledNamedOutcomes': []})
        fitted = m.fit(m.analyze(obj))
        self.assertLessEqual(len(m.encoded(fitted)), m.PROJECTION_CAP)
        self.assertEqual(fitted['status'], 'structural_candidate')
        self.assertIn(fitted['detail_level'], ('question_summaries', 'counts_only'))
        self.assertEqual(fitted['counts']['structural_candidates'], 400)


class CertificateTests(unittest.TestCase):
    def replay(self, book, result):
        ledger = Ledger(sorted(book))
        for kind, member in result['route']['legs']:
            ledger.apply(kind, member, book)
        return ledger

    def test_merged_book_without_cycle_is_certified(self):
        book = {1: merged('0.30', '0.32'), 2: merged('0.33', '0.35'), 3: merged('0.34', '0.36')}
        r = m.certificate(book)
        self.assertEqual(r['status'], 'certified_no_static_cycle')
        self.assertEqual(r['mirror_mismatch'], [])
        self.assertEqual((r['sum_ell'], r['sum_u']), ('0.97', '1.03'))

    def test_inverse_route_replays_to_zero_inventory(self):
        book = {1: merged('0.28', '0.30'), 2: merged('0.30', '0.31', size='2'), 3: merged('0.36', '0.37')}
        r = m.certificate(book)
        self.assertEqual(r['status'], 'candidate_inverse')
        ledger = self.replay(book, r)
        self.assertEqual(ledger.residual(), {})
        self.assertEqual(ledger.cash, Decimal('0.02'))
        self.assertEqual(r['route']['margin_per_unit'], '0.02')
        self.assertEqual(r['route']['unit_cap'], '2')

    def test_inverse_uses_split_and_no_sale_when_only_no_side_given(self):
        book = {1: merged(None, '0.30'), 2: {'no_bid': ('0.65', '3')}, 3: merged(None, '0.31')}
        r = m.certificate(book)
        self.assertEqual(r['status'], 'candidate_inverse')
        self.assertIn(['split', 2], r['route']['legs'])
        self.assertIn(['sell_no', 2], r['route']['legs'])
        self.assertEqual(r['route']['collateral_before_merge'], '1.61')
        ledger = self.replay(book, r)
        self.assertEqual((ledger.residual(), ledger.cash), ({}, Decimal('0.04')))

    def test_forward_mint_route_k0(self):
        book = {1: merged('0.40', '0.41'), 2: merged('0.42', '0.43'), 3: merged('0.35', '0.36', '2')}
        r = m.certificate(book)
        self.assertEqual(r['status'], 'candidate_forward')
        self.assertEqual(r['route']['legs'][:2], [['split', 1], ['negate', 1]])
        self.assertEqual((r['route']['collateral_before_proceeds'], r['route']['unit_cap']), ('1', '2'))
        ledger = self.replay(book, r)
        self.assertEqual((ledger.residual(), ledger.cash), ({}, Decimal('0.17')))

    def test_forward_constructive_no_routes_k1_and_k2(self):
        k1 = {1: merged('0.40', '0.41'), 2: {'no_ask': ('0.60', '1')}, 3: merged('0.35', '0.36')}
        k2 = {1: {'no_ask': ('0.55', '2')}, 2: {'no_ask': ('0.58', '3')}, 3: merged('0.30', '0.31')}
        for book, cash, outlay, merges in ((k1, '0.15', '0.60', 0), (k2, '0.17', '1.13', 1)):
            with self.subTest(outlay=outlay):
                r = m.certificate(book)
                self.assertEqual(r['status'], 'candidate_forward')
                route = r['route']
                self.assertEqual(route['collateral_before_proceeds'], outlay)
                self.assertEqual(route['legs'].count(['merge_question', None]), merges)
                self.assertNotIn('split', [kind for kind, _ in route['legs']])
                ledger = self.replay(book, r)
                self.assertEqual((ledger.residual(), ledger.cash), ({}, Decimal(cash)))
                self.assertEqual(Decimal(route['margin_per_unit']), Decimal(cash))

    def test_mirror_mismatch_is_unusable(self):
        book = {1: merged('0.40', '0.41'), 2: {'yes_bid': ('0.30', '4'), 'no_ask': ('0.60', '1')},
                3: merged('0.35', '0.36')}
        r = m.certificate(book)
        self.assertEqual((r['status'], r['route'], r['mirror_mismatch']), ('inconsistent_snapshot', None, [2]))
        sizes = {1: merged('0.40', '0.41'), 2: {'yes_bid': ('0.30', '4'), 'no_ask': ('0.70', '1')}}
        self.assertEqual(m.certificate(sizes)['status'], 'inconsistent_snapshot')

    def test_missing_disposal_is_residual_not_cash_closed(self):
        # Clipped 0 is not a trade: Y3 has no disposal path, so profit needs residual inventory.
        sol = m.certificate({1: {'yes_bid': ('0.6', '1')}, 2: {'yes_bid': ('0.6', '1')}, 3: {}})
        self.assertEqual((sol['status'], sol['sum_ell'], sol['route']['residual_yes']),
                         ('candidate_forward_residual', '1.2', [3]))
        book = {1: merged('0.55', '0.56'), 2: merged('0.50', '0.52'), 3: merged(None, '0.10')}
        r = m.certificate(book)
        self.assertEqual(r['status'], 'candidate_forward_residual')
        self.assertFalse(r['route']['cash_closed'])
        ledger = self.replay(book, r)
        self.assertEqual(ledger.residual(), {('Y', 3): 1})
        self.assertEqual(ledger.cash, Decimal('0.05'))

    def test_missing_acquisition_cannot_fail_inverse_side(self):
        book = {1: merged(None, '0.20'), 2: merged(None, None)}
        self.assertEqual(m.certificate(book)['status'], 'certified_no_static_cycle')

    def test_crossed_and_invalid_inputs(self):
        crossed = {1: {'yes_bid': ('0.50', '1'), 'yes_ask': ('0.40', '1')}, 2: merged('0.4', '0.6')}
        self.assertEqual(m.certificate(crossed)['status'], 'inconsistent_snapshot')
        self.assertIsNone(m.certificate(crossed)['route'])
        # bY+bN>1 and aY+aN<1 are local conflicts: inconsistent data, never a route.
        for local in ({'yes_bid': ('0.6', '1'), 'no_bid': ('0.5', '1')},
                      {'yes_ask': ('0.4', '1'), 'no_ask': ('0.5', '1')}):
            with self.subTest(local=local):
                r = m.certificate({1: local, 2: merged('0.4', '0.6')})
                self.assertEqual((r['status'], r['crossed'], r['route']), ('inconsistent_snapshot', [1], None))
        for bad in (('1.1', '1'), ('0.5', '0'), ('nan', '1'), ('x', '1')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                m.certificate({1: {'yes_bid': bad}, 2: {}})
        with self.assertRaises(ValueError):
            m.certificate({1: merged('0.4', '0.6')})

    def test_certified_books_admit_no_value_gaining_operation(self):
        rng = random.Random(4)
        checked = 0
        for _ in range(400):
            n = rng.randint(2, 5)
            book = {}
            for i in range(n):
                bid, ask = sorted(rng.sample(range(1, 100), 2))
                full = merged(str(Decimal(bid) / 100) if rng.random() < 0.8 else None,
                              str(Decimal(ask) / 100) if rng.random() < 0.8 else None, '1')
                show = rng.choice(('yes', 'no', 'both'))  # same orders, any representation
                book[i] = {k: v for k, v in full.items()
                           if v is not None and (show == 'both' or k.startswith(show))}
            r = m.certificate(book)
            if r['status'] != 'certified_no_static_cycle':
                continue
            checked += 1
            def px(t, side, flip=False):
                return [ONE - Decimal(t[side][0]) if flip else Decimal(t[side][0])] if side in t else []
            ell = {i: max([Decimal(0)] + px(t, 'yes_bid') + px(t, 'no_ask', True)) for i, t in book.items()}
            u = {i: min([ONE] + px(t, 'yes_ask') + px(t, 'no_bid', True)) for i, t in book.items()}
            span = sum(u.values()) - sum(ell.values())
            lam = (ONE - sum(ell.values())) / span if span else Decimal(0)
            pi = {i: ell[i] + lam * (u[i] - ell[i]) for i in book}
            self.assertEqual(sum(pi.values()).quantize(Decimal('1e-20')), ONE.quantize(Decimal('1e-20')))
            for i, t in book.items():
                self.assertTrue(ell[i] <= pi[i] <= u[i])
                # Trades at the touch never raise cash plus valued holdings.
                if 'yes_ask' in t:
                    self.assertLessEqual(pi[i] - Decimal(t['yes_ask'][0]), 0)
                if 'yes_bid' in t:
                    self.assertLessEqual(Decimal(t['yes_bid'][0]) - pi[i], 0)
                if 'no_ask' in t:
                    self.assertLessEqual((ONE - pi[i]) - Decimal(t['no_ask'][0]), 0)
                if 'no_bid' in t:
                    self.assertLessEqual(Decimal(t['no_bid'][0]) - (ONE - pi[i]), 0)
            # Conversions preserve every state payoff, hence value under any pi.
            for state in book:
                for i in book:
                    y, no = int(state == i), int(state != i)
                    self.assertEqual(y + no, 1)  # split/merge
                    self.assertEqual(no, sum(int(state == j) for j in book if j != i))  # negate
                self.assertEqual(sum(int(state == j) for j in book), 1)  # mergeQuestion
        self.assertGreater(checked, 50)


class RunTests(unittest.TestCase):
    def test_verify_accepts_only_exact_frozen_plan(self):
        draft = json.loads((m.ROOT / 'reports/hip4-outcome-v1/draft-protocol.json').read_text())
        pins = [{'path': p, 'bytes': len((m.ROOT / p).read_bytes()),
                 'sha256': m.digest((m.ROOT / p).read_bytes())} for p in (m.SOURCE, m.TEST, m.HELPER)]
        frozen = dict(draft, status='frozen_metadata_probe', source_pins=pins)
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / 'plan.json'
            def check(value, expected=None):
                data = m.encoded(value)
                plan.write_bytes(data)
                with patch.object(m, 'PLAN', plan):
                    if expected is None:
                        return m.verify(m.digest(data))
                    with self.assertRaises(m.Refusal) as caught:
                        m.verify(m.digest(data))
                    self.assertEqual(str(caught.exception), expected)
            self.assertEqual(check(frozen)['schema'], m.SCHEMA)
            check(draft, 'plan_not_frozen')
            check(dict(frozen, request_plan=dict(frozen['request_plan'], retry=True)), 'request_plan_changed')
            check(dict(frozen, output_dir='elsewhere'), 'output_plan_changed')
            check(dict(frozen, source_pins=pins[:2]), 'missing_source_pins')
            check(dict(frozen, source_pins=[dict(pins[0], sha256='0' * 64)] + pins[1:]), 'source_pin_mismatch')
            check(dict(frozen, previous_sha256='0' * 64), 'previous_plan_sha_mismatch')
            plan.write_bytes(m.encoded(frozen))
            with patch.object(m, 'PLAN', plan), self.assertRaises(m.Refusal) as caught:
                m.verify('1' * 64)
            self.assertEqual(str(caught.exception), 'plan_sha_mismatch')

    def fetch(self, response):
        sink, receipt = bytearray(), {'request_attempted': False, 'body_complete': False}
        with patch('http.client.HTTPSConnection', Connection(response)):
            m.fetch(sink, receipt)
        return sink, receipt

    def test_fetch_success_and_refusals(self):
        Connection.calls = []
        body = json.dumps(meta()).encode()
        sink, receipt = self.fetch(Response(body))
        self.assertEqual((bytes(sink), receipt['http_status'], receipt['body_complete']), (body, 200, True))
        self.assertEqual(Connection.calls, ['api.hyperliquid.xyz', ('POST', '/info', m.BODY, 'identity')])
        cases = {
            'declared_body_byte_cap_or_invalid_length': Response(b'x' * (m.BODY_CAP + 1)),
            'body_cap_reached_without_complete_eof': Response(b'x' * (m.BODY_CAP + 1), length=False),
            'http_status_not_200': Response(body, status=429),
            'unsupported_content_encoding': Response(body, encoding='gzip'),
            'unsupported_content_type': Response(body, media='text/html'),
        }
        for code, response in cases.items():
            with self.subTest(code=code), self.assertRaises(m.Refusal) as caught:
                self.fetch(response)
            self.assertEqual(str(caught.exception), code)

    def worker(self, response):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(m, 'verify', return_value={}), \
                patch('http.client.HTTPSConnection', Connection(response)):
            out = Path(tmp)
            m.worker('a' * 64, out)
            files = {p.name: p.read_bytes() for p in out.iterdir()}
        return files, json.loads(files['terminal.json'])

    def test_worker_publishes_projection_and_gzip_raw(self):
        body = json.dumps(meta()).encode()
        files, terminal = self.worker(Response(body))
        self.assertEqual(gzip.decompress(files['response.json.gz']), body)
        self.assertEqual((terminal['status'], terminal['code']), ('structural_candidate', None))
        projection = json.loads(files['metadata.json'])
        self.assertEqual(projection['body_sha256'], m.digest(body))
        self.assertEqual(projection['detail_level'], 'full')
        self.assertNotIn('metadata.json.pending', files)

    def supervise(self, response=None, exitcode=0, hang=False, tamper=None, final_pins=True):
        Connection.calls = []
        body = json.dumps(meta()).encode()

        class Process:
            def __init__(self, out):
                self.out, self.exitcode, self.alive = out, None, False

            def start(self):
                if hang:
                    self.alive = True
                    return
                m.worker('a' * 64, self.out)
                self.exitcode = exitcode
                if tamper:
                    tamper(self.out)

            def join(self, _):
                pass

            def is_alive(self):
                return self.alive

            def kill(self):
                self.alive, self.exitcode = False, -9

        pins = iter([{}] * 4 + [{} if final_pins else m.Refusal('source_pin_mismatch')])
        def verify(_):
            value = next(pins, {})
            if isinstance(value, Exception):
                raise value
            return value
        with tempfile.TemporaryDirectory() as tmp, patch.object(m, 'verify', side_effect=verify), \
                patch('http.client.HTTPSConnection', Connection(response or Response(body))):
            out = Path(tmp)
            return m.supervise(Process(out), 0, out, 'a' * 64)

    def test_supervisor_conclusion_gate(self):
        good = self.supervise()
        self.assertTrue(good['conclusion_eligible'])
        self.assertEqual((good['conclusion_status'], good['request_attempts']), ('structural_candidate', 1))
        def bad_raw(out):
            (out / 'response.json.gz').unlink()
            (out / 'response.json.gz').write_bytes(gzip.compress(b'{}', mtime=0))
        def trailing_member(out):
            data = (out / 'response.json.gz').read_bytes() + gzip.compress(b'x', mtime=0)
            (out / 'response.json.gz').unlink()
            (out / 'response.json.gz').write_bytes(data)
        def pending(out):
            (out / 'metadata.json.pending').write_bytes(b'')
        def terminal(**changes):
            def tamper(out):
                value = dict(json.loads((out / 'terminal.json').read_bytes()), **changes)
                (out / 'terminal.json').unlink()
                (out / 'terminal.json').write_bytes(m.encoded(value))
            return tamper
        cases = [('worker_completed_exit_zero', dict(exitcode=1)),
                 ('raw_matches_terminal', dict(tamper=bad_raw)),
                 ('raw_matches_terminal', dict(tamper=trailing_member)),
                 ('raw_matches_terminal', dict(tamper=terminal(raw_gzip_bytes=1))),
                 ('terminal_without_failure', dict(tamper=terminal(http_status=204))),
                 ('terminal_without_failure', dict(tamper=terminal(body_complete=False))),
                 ('terminal_without_failure', dict(tamper=terminal(transport_code='x'))),
                 ('terminal_without_failure', dict(tamper=terminal(request_attempted=False))),
                 ('no_pending_publication', dict(tamper=pending)),
                 ('final_plan_and_source_pins', dict(final_pins=False))]
        for check, kwargs in cases:
            with self.subTest(check=check, kwargs=kwargs):
                record = self.supervise(**kwargs)
                self.assertFalse(record['checks'][check])
                self.assertEqual((record['conclusion_eligible'], record['conclusion_status']),
                                 (False, 'inconclusive'))
        killed = self.supervise(hang=True)
        self.assertEqual((killed['status'], killed['request_attempts']), ('process_deadline', 'unknown_0_or_1'))
        self.assertFalse(killed['conclusion_eligible'])

    def test_worker_keeps_partial_raw_on_transport_failure(self):
        files, terminal = self.worker(Response(b'{"outcomes":', status=503))
        self.assertEqual(gzip.decompress(files['response.json.gz']), b'{"outcomes":')
        self.assertEqual((terminal['code'], terminal['transport_code']), ('http_status_not_200',) * 2)
        self.assertEqual(terminal['status'], 'inconclusive')
        self.assertNotIn('metadata.json', files)


if __name__ == '__main__':
    unittest.main()
