#!/usr/bin/env python3
"""Fixed 15-slot, zero-cost necessary-price screen; never execution or profit.

The quote bound uses conditional nominal pUSD units. Snapshot timestamp units
and freshness are interpretive diagnostics; conversion/source equivalence,
fees, depth, minimum-order units, fills and settlement remain unproved.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
from decimal import Decimal, localcontext
import gzip
import http.client
import multiprocessing
import os
from pathlib import Path
import re
import ssl
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import polymarket_no_basket_chain_metadata_v2 as chain
from scripts import polymarket_no_basket_metadata as metadata

Refusal = metadata.Refusal
SOURCE = 'scripts/polymarket_no_basket_optimistic_books.py'
TEST = 'tests/test_polymarket_no_basket_optimistic_books.py'
PLAN = ROOT / 'reports/experiment-storage/polymarket-no-basket-optimistic-books-v1.json'
OUT = 'reports/polymarket-no-basket/optimistic-books-v1'
HOST = 'clob.polymarket.com'
ENDPOINT = 'https://' + HOST + '/books'
BODY_SHA = 'c12bb47d5d5d55012e7a7a9229cb30396dfa6bf884162a53008d87592ab5121b'
CHAIN_PLAN = {'path': 'reports/experiment-storage/polymarket-no-basket-chain-metadata-v2.json',
              'bytes': 29554, 'sha256': '690f657d353ad965debddc8dc00e2a74a6eaa4a64cb722a86f7cc797e3fb5e02'}
CHAIN_SUMMARY = {'path': 'reports/polymarket-no-basket/chain-metadata-v2/summary.json',
                 'bytes': 8030, 'sha256': 'bbca4e635dd829766be7bd8e3a77afeccf5502b1d3ce8962aee6c4b5dbfadf4a'}
LIMITS = {'slots': 15, 'slot_interval_seconds': 4, 'anchor_after_claim_seconds': 2,
          'maximum_start_lateness_seconds': 0.25, 'request_seconds': 3,
          'request_work_seconds': 64, 'process_seconds': 75, 'response_bytes': 131072,
          'total_response_bytes': 1048576, 'trace_plaintext_bytes_in_memory': 1048576,
          'trace_gzip_bytes': 196608, 'derived_receipts_bytes': 65536,
          'maximum_levels_per_side': 5000}


class FieldInvalid(Exception):
    """A known-identity unavailable slot; the next scheduled slot still occurs."""


def verify(plan_sha):
    if not isinstance(plan_sha, str) or not re.fullmatch('[0-9a-f]{64}', plan_sha):
        raise Refusal('expected_plan_sha_required')
    raw = metadata.bounded_read(PLAN, 20000)
    if chain.sha(raw) != plan_sha:
        raise Refusal('plan_sha_mismatch')
    p = metadata.strict_json(raw)
    if p.get('schema') != 'polymarket-no-basket-optimistic-books-v1' or p.get('status') != 'frozen_optimistic_books_probe':
        raise Refusal('plan_schema_or_not_frozen')
    for key, expected in {'endpoint': ENDPOINT, 'output_dir': OUT, 'event_id': chain.EVENT,
                          'limits': LIMITS, 'chain_plan': CHAIN_PLAN, 'chain_summary': CHAIN_SUMMARY,
                          'request_body_sha256': BODY_SHA, 'reserved_bytes': 0}.items():
        if chain.canonical(p.get(key)) != chain.canonical(expected):
            raise Refusal('fixed_plan_scope_changed')
    pins = p.get('source_pins')
    if not isinstance(pins, list) or len(pins) != 2 or sorted(
        pin.get('path', '') for pin in pins if isinstance(pin, dict)
    ) != sorted((SOURCE, TEST)):
        raise Refusal('own_source_test_pins_required')
    package_bytes = len(raw)
    for pin in pins:
        path = ROOT / pin['path']
        if path.resolve() != ROOT.resolve() / pin['path']:
            raise Refusal('source_symlink')
        package_bytes += len(chain.file_identity(path, pin, 52000))
    if package_bytes > 52000:
        raise Refusal('source_package_cap')
    chain.file_identity(ROOT / CHAIN_PLAN['path'], CHAIN_PLAN, 32768)
    parent = chain.verify(CHAIN_PLAN['sha256'])
    if p.get('markets') != parent['markets']:
        raise Refusal('market_mapping_changed')
    body = [{'token_id': market['no_token_id']} for market in parent['markets']]
    if p.get('request_body') != body or chain.sha(chain.canonical(body)) != BODY_SHA:
        raise Refusal('request_body_changed')
    summary = metadata.strict_json(chain.file_identity(ROOT / CHAIN_SUMMARY['path'], CHAIN_SUMMARY, 16384))
    observations = summary.get('observations')
    if summary.get('status') != 'metadata_mapping_compatible_conversion_unproven' or not isinstance(observations, list) or len(observations) != 55 or [r.get('id') for r in observations] != list(range(1, 56)):
        raise Refusal('chain_summary_incomplete')
    if observations[26]['observation'].get('uint') != '5':
        raise Refusal('chain_question_count_mismatch')
    for k, market in enumerate(parent['markets']):
        for offset, name in ((30, 'yes_token_id'), (31, 'no_token_id')):
            if observations[offset + 5 * k]['observation'].get('uint') != market[name]:
                raise Refusal('chain_token_mapping_mismatch')
    if (ROOT / OUT).resolve() != ROOT.resolve() / OUT:
        raise Refusal('output_symlink')
    return p


def utc_ns(ns):
    seconds, nanos = divmod(ns, 1000000000)
    return dt.datetime.fromtimestamp(seconds, dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + f'.{nanos:09d}Z'


def decimal_field(value):
    if not isinstance(value, str) or len(value) > 32 or not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,6})?', value):
        raise FieldInvalid('invalid_plain_decimal_field')
    return Decimal(value)


def snapshot_time(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:[0-9]{10}|[0-9]{13})', value):
        raise FieldInvalid('invalid_snapshot_timestamp')
    unit = 'seconds' if len(value) == 10 else 'milliseconds'
    return {'original': value, 'inferred_unit': unit,
            'interpreted_unix_ns': int(value) * (1000000000 if unit == 'seconds' else 1000000)}


def evaluate(obj, markets, receipt_ns):
    # Identity invalidations precede all book-field interpretation.
    expected = {market['no_token_id']: market for market in markets}
    if not isinstance(obj, list) or len(obj) != 5 or len(expected) != 5:
        raise Refusal('book_set_identity_count')
    books = {}
    for book in obj:
        if not isinstance(book, dict):
            raise Refusal('invalid_book_identity_object')
        asset = book.get('asset_id')
        if not isinstance(asset, str) or asset not in expected or asset in books:
            raise Refusal('missing_extra_or_duplicate_asset_identity')
        if book.get('market') != expected[asset]['condition_id'] or book.get('neg_risk') is not True:
            raise Refusal('condition_or_negative_risk_identity')
        books[asset] = book
    details, best_asks = [], []
    empty = False
    for market in markets:
        book = books[market['no_token_id']]
        tick = decimal_field(book.get('tick_size'))
        minimum = decimal_field(book.get('min_order_size'))
        if not 0 < tick <= 1 or minimum <= 0:
            raise FieldInvalid('invalid_tick_or_minimum')
        hash_value = book.get('hash')
        if not isinstance(hash_value, str) or not 1 <= len(hash_value) <= 128:
            raise FieldInvalid('missing_or_invalid_book_hash')
        stamp = snapshot_time(book.get('timestamp'))
        prices = {}
        for side in ('asks', 'bids'):
            levels = book.get(side)
            if not isinstance(levels, list) or len(levels) > LIMITS['maximum_levels_per_side']:
                raise FieldInvalid('invalid_or_excessive_side_levels')
            values = []
            for level in levels:
                if not isinstance(level, dict):
                    raise FieldInvalid('invalid_level_object')
                price = decimal_field(level.get('price'))
                size = decimal_field(level.get('size'))
                with localcontext() as context:
                    context.prec = 64
                    if not 0 < price <= 1 or size <= 0 or price % tick != 0:
                        raise FieldInvalid('invalid_price_size_or_native_tick')
                values.append(price)
            prices[side] = sorted(values)
        if prices['asks'] and prices['bids'] and prices['bids'][-1] >= prices['asks'][0]:
            raise FieldInvalid('crossed_book')
        ask = prices['asks'][0] if prices['asks'] else None
        empty |= ask is None
        if ask is not None:
            best_asks.append(ask)
        details.append({'asset_id': market['no_token_id'], 'hash_sha256': chain.sha(hash_value.encode('utf-8')),
                        'timestamp': stamp, 'tick_size': book['tick_size'],
                        'min_order_size': book['min_order_size'], 'minimum_order_unit': 'unresolved',
                        'best_ask': str(ask) if ask is not None else None})
    times = [row['timestamp']['interpreted_unix_ns'] for row in details]
    future = any(value > receipt_ns + 250000000 for value in times)
    stale = any(value < receipt_ns - 5000000000 for value in times)
    span = max(times) - min(times)
    diagnostics = {'fresh_coherent': not future and not stale and span <= 500000000,
                   'future_timestamp': future, 'stale_timestamp': stale,
                   'cross_book_span_ns': span, 'timestamp_units_interpretive': True}
    if empty:
        return {'status': 'unavailable_slot', 'reason': 'empty_ask_side', 'field_valid': False,
                'availability_class': 'missing', 'optimistic_margin': None,
                'books': details, 'time_diagnostics': diagnostics}
    with localcontext() as context:
        context.prec = 64
        margin = Decimal(4) - sum(best_asks, Decimal(0))
    return {'status': 'conditional_nominal_nonpositive_recorded_set' if margin <= 0 else 'necessary_price_condition_only',
            'reason': None, 'field_valid': True, 'availability_class': 'observed',
            'optimistic_margin': str(margin), 'quote_unit': 'conditional_nominal_pUSD',
            'books': details, 'time_diagnostics': diagnostics}


def empty_slots(anchor_wall_ns):
    return [{'slot': k, 'planned_start_utc': utc_ns(anchor_wall_ns + 4000000000 * k),
             'request_attempted': False, 'status': 'unavailable_slot', 'reason': 'future_unavailable',
             'field_valid': False, 'availability_class': 'missing', 'optimistic_margin': None}
            for k in range(15)]


def summarize(slots, plan_sha):
    if len(slots) != 15 or [slot['slot'] for slot in slots] != list(range(15)):
        raise Refusal('slot_denominator_changed')
    valid = [slot for slot in slots if slot['field_valid']]
    fresh = [slot for slot in valid if slot['time_diagnostics']['fresh_coherent']]
    positive = [slot for slot in valid if Decimal(slot['optimistic_margin']) > 0]
    attempts = [slot['request_attempted'] for slot in slots]
    counts = {'scheduled': 15, 'requests_attempted': None if None in attempts else sum(attempts),
              'requests_attempted_known_lower_bound': sum(value is True for value in attempts),
              'requests_attempted_unknown_slots': sum(value is None for value in attempts),
              'field_valid': len(valid), 'invalid': sum(slot['availability_class'] == 'invalid' for slot in slots),
              'missing': sum(slot['availability_class'] == 'missing' for slot in slots),
              'fresh_coherent_valid': len(fresh), 'positive': len(positive),
              'nonpositive': len(valid) - len(positive)}
    return {'schema': 'polymarket-no-basket-optimistic-books-summary-v1', 'plan_sha256': plan_sha,
            'counts': counts, 'all_scheduled_sets_fresh_nonpositive': len(fresh) == 15 and not positive,
            'maximum_conclusion': 'necessary_price_condition_on_recorded_sets_only',
            'quote_unit': 'conditional_nominal_pUSD', 'all_costs_assumed_zero': True,
            'snapshot_units_and_freshness_interpretive': True,
            'chain_snapshot_is_earlier_than_quotes': True,
            'conversion_source_equivalence_and_execution': 'unproved', 'slots': slots}


def publish(out, name, value):
    body = metadata.encoded(value)
    used = sum(path.stat().st_size for path in out.glob('*.json'))
    # metadata.publish hard-links one inode before unlinking its pending name;
    # the receipt body is not copied during atomic publication.
    if used + len(body) > LIMITS['derived_receipts_bytes']:
        raise Refusal('derived_receipts_total_cap')
    metadata.publish(out / name, value, 60000)


class Trace:
    def __init__(self, out):
        self.out, self.plaintext = out, bytearray()

    def append(self, record):
        line = metadata.encoded(record)
        if len(self.plaintext) + len(line) > LIMITS['trace_plaintext_bytes_in_memory']:
            raise Refusal('trace_plaintext_cap')
        data = gzip.compress(bytes(self.plaintext) + line, mtime=0)
        if len(data) > LIMITS['trace_gzip_bytes']:
            raise Refusal('trace_gzip_cap')
        pending = self.out / 'trace.pending.gz'
        with pending.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, self.out / 'trace.jsonl.gz')
        self.plaintext.extend(line)


def transport(body, record, budget, deadline):
    cap = min(LIMITS['response_bytes'], LIMITS['total_response_bytes'] - budget['bytes'])
    seconds = min(LIMITS['request_seconds'], deadline - time.monotonic())
    if cap <= 0 or seconds <= 0:
        raise Refusal('remaining_response_or_work_budget')
    connection, raw = None, bytearray()
    try:
        with metadata.hard_deadline(seconds, 'request_deadline'):
            connection = http.client.HTTPSConnection(HOST, timeout=seconds, context=ssl.create_default_context())
            if time.monotonic() > record['planned_monotonic'] + 0.25:
                raise FieldInvalid('missed_start_lateness')
            record.update(request_attempted=True, request_start_wall_ns=time.time_ns(),
                          request_start_monotonic=time.monotonic())
            record['actual_start_lateness_seconds'] = record['request_start_monotonic'] - record['planned_monotonic']
            if record['actual_start_lateness_seconds'] > 0.25:
                record['request_attempted'] = False
                raise FieldInvalid('missed_start_lateness')
            budget['requests'] += 1
            connection.request('POST', '/books', body=chain.canonical(body), headers={
                'Accept': 'application/json', 'Content-Type': 'application/json',
                'Accept-Encoding': 'identity', 'Connection': 'close', 'User-Agent': 'rhhype-public-book-bound/1.0'})
            response = connection.getresponse()
            record['http_status'] = response.status
            http_date = response.getheader('Date')
            record['http_date'] = http_date if isinstance(http_date, str) and len(http_date) <= 128 else None
            length = response.getheader('Content-Length')
            if length is not None and (not re.fullmatch(r'[0-9]{1,12}', length) or int(length) > cap):
                raise Refusal('declared_body_exceeds_remaining_cap')
            expected = int(length) if length is not None else None
            complete = False
            while len(raw) < cap:
                read_limit = min(16384, cap - len(raw))
                try:
                    chunk = response.read1(read_limit)
                except http.client.IncompleteRead as exc:
                    if not isinstance(exc.partial, bytes) or len(exc.partial) > read_limit:
                        raise Refusal('transport_read_contract_violation') from None
                    raw.extend(exc.partial)
                    budget['bytes'] += len(exc.partial)
                    raise Refusal('incomplete_response_body') from None
                if not isinstance(chunk, bytes) or len(chunk) > read_limit:
                    raise Refusal('transport_read_contract_violation')
                if not chunk:
                    complete = True
                    break
                raw.extend(chunk)
                budget['bytes'] += len(chunk)
            complete |= expected is not None and len(raw) == expected
            record['body_complete'] = complete
            if not complete or expected is not None and len(raw) != expected:
                raise Refusal('incomplete_body_or_unproven_eof_boundary')
            if response.status != 200:
                raise Refusal('http_status_not_200')
            if response.getheader('Content-Encoding', 'identity').lower() != 'identity' or response.getheader('Content-Type', '').split(';', 1)[0].strip().lower() != 'application/json':
                raise Refusal('unsupported_response_encoding_or_type')
    finally:
        record.update(receipt_wall_ns=time.time_ns(), receipt_monotonic=time.monotonic(),
                      body_bytes=len(raw), body_sha256=chain.sha(raw),
                      body_base64=base64.b64encode(raw).decode('ascii'))
        if record.get('request_start_wall_ns') is not None:
            record.update(request_start_utc=utc_ns(record['request_start_wall_ns']),
                          receipt_utc=utc_ns(record['receipt_wall_ns']),
                          request_duration_seconds=record['receipt_monotonic'] - record['request_start_monotonic'])
        if connection is not None:
            connection.close()
    return bytes(raw)


def sample(plan, plan_sha, out, anchor_mono, anchor_wall_ns, work_deadline, slots, terminal):
    trace, budget = Trace(out), {'bytes': 0, 'requests': 0}
    try:
        with metadata.hard_deadline(max(0.000001, work_deadline - time.monotonic()), 'request_work_deadline'):
            for k, slot in enumerate(slots):
                target = anchor_mono + 4 * k
                delay = target - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                lateness = time.monotonic() - target
                slot['start_lateness_seconds'] = lateness
                if lateness > 0.25:
                    slot['reason'] = 'missed_start_lateness'
                    trace.append({'slot': k, 'observation': slot})
                    continue
                record = {'slot': k, 'planned_start_utc': slot['planned_start_utc'],
                          'planned_monotonic': target,
                          'request_body_sha256': BODY_SHA, 'request_attempted': False,
                          'body_complete': False, 'code': None}
                try:
                    raw = transport(plan['request_body'], record, budget, work_deadline)
                    obj = metadata.strict_json(raw)
                    try:
                        slot.update(evaluate(obj, plan['markets'], record['receipt_wall_ns']))
                    except FieldInvalid as exc:
                        slot.update(status='unavailable_slot', reason=str(exc), availability_class='invalid')
                except FieldInvalid as exc:
                    slot.update(reason=str(exc), availability_class='missing')
                except Refusal as exc:
                    record['code'] = str(exc)
                    slot.update(reason=str(exc), availability_class='invalid')
                    raise
                except Exception:
                    record['code'] = 'transport_or_internal_failure'
                    slot.update(reason=record['code'], availability_class='invalid')
                    raise Refusal(record['code']) from None
                finally:
                    slot['request_attempted'] = record['request_attempted']
                    for key in ('request_start_utc', 'receipt_utc', 'request_duration_seconds', 'actual_start_lateness_seconds'):
                        if key in record:
                            slot[key] = record[key]
                    date = record.get('http_date')
                    slot['http_date_sha256'] = chain.sha(date.encode('utf-8')) if isinstance(date, str) else None
                    record['observation'] = slot
                    terminal['last_request_receipt'] = {key: value for key, value in record.items()
                                                       if key not in ('body_base64', 'observation')}
                    trace.append(record)
    finally:
        terminal.update(requests_attempted=budget['requests'], total_response_bytes=budget['bytes'],
                        trace_plaintext_bytes=len(trace.plaintext))
        path = out / 'trace.jsonl.gz'
        if path.exists():
            raw = metadata.bounded_read(path, LIMITS['trace_gzip_bytes'])
            terminal.update(trace_gzip_bytes=len(raw), trace_gzip_sha256=chain.sha(raw))


def worker(plan_sha, out, anchor_mono, anchor_wall_ns, work_deadline):
    slots = empty_slots(anchor_wall_ns)
    terminal = {'schema': 'polymarket-no-basket-optimistic-books-terminal-v1', 'plan_sha256': plan_sha,
                'status': 'inconclusive', 'code': None, 'started_utc': metadata.utc()}
    try:
        plan = verify(plan_sha)
        sample(plan, plan_sha, out, anchor_mono, anchor_wall_ns, work_deadline, slots, terminal)
        terminal['status'] = 'fixed_sampling_finished'
    except Refusal as exc:
        terminal['code'] = str(exc)
    except Exception:
        terminal['code'] = 'internal_failure'
    finally:
        try:
            verify(plan_sha)
        except Exception:
            terminal.update(status='inconclusive', code='post_run_pin_check_failed')
        terminal['ended_utc'] = metadata.utc()
        publish(out, 'summary.json', summarize(slots, plan_sha))
        publish(out, 'terminal.json', terminal)


def run(plan_sha):
    began = time.monotonic()
    with metadata.hard_deadline(LIMITS['process_seconds'], 'process_deadline_before_claim'):
        verify(plan_sha)
    out = ROOT / OUT
    out.mkdir(parents=True, exist_ok=False)
    claim_mono, claim_wall_ns = time.monotonic(), time.time_ns()
    anchor_mono, anchor_wall_ns = claim_mono + 2, claim_wall_ns + 2000000000
    publish(out, 'claim.json', {'schema': 'polymarket-no-basket-optimistic-books-claim-v1',
                               'plan_sha256': plan_sha, 'request_body_sha256': BODY_SHA,
                               'claim_utc': utc_ns(claim_wall_ns), 'anchor_utc': utc_ns(anchor_wall_ns),
                               'anchor_wall_ns': anchor_wall_ns, 'anchor_monotonic': anchor_mono,
                               'slots': 15, 'purpose': 'zero_cost_necessary_price_bound_only'})
    process = multiprocessing.get_context('fork').Process(target=worker, args=(
        plan_sha, out, anchor_mono, anchor_wall_ns, claim_mono + 64))
    process.start()
    deadline = began + 75
    process.join(max(0, deadline - time.monotonic() - 1))
    expired = process.is_alive()
    if expired:
        process.kill()
        process.join(max(0, deadline - time.monotonic()))
    result = {'schema': 'polymarket-no-basket-optimistic-books-supervisor-v1', 'plan_sha256': plan_sha,
              'status': 'process_deadline' if expired else 'worker_finished', 'worker_exitcode': process.exitcode,
              'terminal_exists': (out / 'terminal.json').exists(), 'summary_exists': (out / 'summary.json').exists()}
    if not expired and (process.exitcode != 0 or not result['terminal_exists']):
        result['status'] = 'worker_failed_without_terminal'
    if not result['summary_exists']:
        # A killed worker leaves its checkpoint. Publish every calendar slot as
        # unavailable, without inventing validated observations from raw bodies.
        unknown = empty_slots(anchor_wall_ns)
        for slot in unknown:
            slot['reason'] = 'worker_interrupted_observation_unresolved'
            slot['request_attempted'] = None
        publish(out, 'summary.json', summarize(unknown, plan_sha))
        result.update(summary_exists=True, summary_reconstructed_as_unresolved=True)
    publish(out, 'supervisor.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--plan-sha256')
    args = parser.parse_args(argv)
    if not args.run:
        result = {'status': 'dry_no_http', 'http_requests': 0, 'maximum_slots': 15, 'endpoint': ENDPOINT}
    else:
        try:
            result = run(args.plan_sha256)
        except Refusal as exc:
            result = {'status': 'refused_no_retry', 'code': str(exc)}
        except FileExistsError:
            result = {'status': 'refused_no_retry', 'code': 'existing_output'}
        except Exception:
            result = {'status': 'failed_no_retry', 'code': 'internal_failure'}
    print(metadata.encoded(result).decode('ascii'), end='')
    return 0 if result['status'] in ('dry_no_http', 'worker_finished') else 1


if __name__ == '__main__':
    raise SystemExit(main())
