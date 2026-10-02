#!/usr/bin/env python3
"""One frozen anonymous metadata lookup; default is offline and performs no HTTP.

Only the Gamma public-search field projection below is analytical. The raw body
may contain incidental economics and is retained without printing or using them.
Schema: https://docs.polymarket.com/api-reference/search/search-markets-events-and-profiles
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import http.client
import json
import math
import multiprocessing
import os
from pathlib import Path
import re
import signal
import ssl
import time

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'reports/experiment-storage/polymarket-no-basket-metadata-v1.json'
SOURCE = 'scripts/polymarket_no_basket_metadata.py'
TEST = 'tests/test_polymarket_no_basket_metadata.py'
OUT = 'reports/polymarket-no-basket/metadata-v1'
URL = 'https://gamma-api.polymarket.com/public-search?q=Fed%20decision%20October%202026'
HOST = 'gamma-api.polymarket.com'
TARGET = '/public-search?q=Fed%20decision%20October%202026'
TITLE = r'(?i)^Fed decision in October(?: 2026)?[?]?$'
DATE = '2026-10-28'
BODY_CAP = 524288
PROJECTION_CAP = 131072
CONTROL_CAP = 32768
REQUEST_SECONDS = 20
PROCESS_SECONDS = 60
SUMMARY_FIELDS = ('id', 'title', 'slug', 'endDate')
EVENT_FIELDS = SUMMARY_FIELDS + (
    'description', 'resolutionSource', 'startDate', 'creationDate', 'eventDate',
    'startTime', 'closedTime', 'active', 'closed', 'archived', 'restricted',
    'enableOrderBook', 'negRisk', 'negRiskMarketID', 'negRiskFeeBips',
    'negRiskAugmented', 'enableNegRisk', 'showAllOutcomes', 'automaticallyResolved',
    'pendingDeployment', 'deploying', 'deployingTimestamp',
    'scheduledDeploymentTimestamp',
)
MARKET_FIELDS = (
    'id', 'slug', 'question', 'description', 'resolutionSource', 'conditionId',
    'questionID', 'outcomes', 'clobTokenIds', 'shortOutcomes', 'groupItemTitle',
    'groupItemThreshold', 'groupItemRange', 'startDate', 'endDate', 'endDateIso',
    'startDateIso', 'closedTime', 'eventStartTime', 'active', 'closed', 'archived',
    'restricted', 'enableOrderBook', 'acceptingOrders', 'acceptingOrdersTimestamp',
    'orderPriceMinTickSize', 'orderMinSize', 'secondsDelay', 'negRisk',
    'negRiskMarketID', 'negRiskFeeBips', 'negRiskOther', 'negRiskAugmented',
    'umaResolutionStatus', 'umaResolutionStatuses', 'automaticallyResolved',
    'denominationToken', 'fee', 'makerBaseFee', 'takerBaseFee', 'feesEnabled',
    'pendingDeployment', 'deploying', 'deployingTimestamp',
    'scheduledDeploymentTimestamp',
)
# Do not retain rebateRate: it is unrelated to the short cash cycle.
FEE_FIELDS = ('exponent', 'rate', 'takerOnly')
BOOL_FIELDS = frozenset((
    'active', 'closed', 'archived', 'restricted', 'enableOrderBook', 'negRisk',
    'negRiskAugmented', 'enableNegRisk', 'showAllOutcomes', 'automaticallyResolved',
    'pendingDeployment', 'deploying', 'acceptingOrders', 'negRiskOther',
    'feesEnabled', 'takerOnly',
))
NUMBER_FIELDS = frozenset((
    'negRiskFeeBips', 'orderPriceMinTickSize', 'orderMinSize', 'secondsDelay',
    'makerBaseFee', 'takerBaseFee', 'exponent', 'rate',
))


class Refusal(Exception):
    """Fixed public error codes only; never include response or exception text."""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=True, allow_nan=False,
                       separators=(',', ':'), sort_keys=True) + '\n').encode('ascii')


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def bounded_read(path, cap):
    with Path(path).open('rb') as stream:
        data = stream.read(cap + 1)
    if len(data) > cap:
        raise Refusal('file_byte_cap')
    return data


def strict_json(raw):
    """Reject duplicate keys, nonfinite numbers, surrogate text, depth and size.

    The lexical depth guard runs before the JSON decoder to bound recursion.
    No excluded numeric value is interpreted for selection or reporting.
    """
    if len(raw) > BODY_CAP:
        raise Refusal('body_byte_cap')
    try:
        text = raw.decode('utf-8', errors='strict')
    except UnicodeError:
        raise Refusal('invalid_utf8') from None
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '[{':
            depth += 1
            if depth > 32:
                raise Refusal('json_depth_cap')
        elif char in ']}':
            depth -= 1
    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise Refusal('duplicate_json_key')
            obj[key] = value
        return obj
    def reject_constant(_):
        raise Refusal('nonfinite_json_number')
    try:
        obj = json.loads(text, object_pairs_hook=pairs, parse_constant=reject_constant)
    except (ValueError, RecursionError):
        raise Refusal('malformed_json') from None
    nodes = 0
    stack = [obj]
    while stack:
        item = stack.pop()
        nodes += 1
        if nodes > 50000:
            raise Refusal('json_node_cap')
        if isinstance(item, str):
            if any(0xD800 <= ord(c) <= 0xDFFF for c in item):
                raise Refusal('invalid_unicode_scalar')
        elif isinstance(item, float) and not math.isfinite(item):
            raise Refusal('nonfinite_json_number')
        elif isinstance(item, dict):
            stack.extend(item.keys())
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return obj


def verify(plan_sha256):
    if not isinstance(plan_sha256, str) or not re.fullmatch('[0-9a-f]{64}', plan_sha256):
        raise Refusal('expected_plan_sha_required')
    raw = bounded_read(PLAN, 32768)
    if digest(raw) != plan_sha256:
        raise Refusal('plan_sha_mismatch')
    p = strict_json(raw)
    if not isinstance(p, dict) or p.get('schema') != 'polymarket-no-basket-metadata-v1':
        raise Refusal('plan_schema')
    if p.get('status') != 'frozen_metadata_probe':
        raise Refusal('plan_not_frozen')
    required = {
        'count': 1, 'method': 'GET', 'url': URL, 'max_body_bytes': BODY_CAP,
        'max_total_body_bytes': BODY_CAP, 'request_deadline_seconds': REQUEST_SECONDS,
        'process_deadline_seconds': PROCESS_SECONDS, 'retry': False,
        'redirects': False, 'environment_proxies': False, 'pagination': False,
        'fallbacks': [],
    }
    request = p.get('request_plan')
    if not isinstance(request, dict) or any(
        encoded(request.get(k)) != encoded(v) for k, v in required.items()
    ):
        raise Refusal('request_plan_changed')
    selection = p.get('event_selection', {})
    for k, expected in {
        'query': 'Fed decision October 2026', 'candidate_title_pattern': TITLE,
        'candidate_end_utc_date': DATE, 'max_returned_events': 10,
        'required_unique_candidate': 1, 'candidate_market_count_range': [2, 8],
    }.items():
        if encoded(selection.get(k)) != encoded(expected):
            raise Refusal('selection_plan_changed')
    if p.get('output_dir') != OUT or p.get('reserved_bytes') != 2097152:
        raise Refusal('output_plan_changed')
    if p.get('output_limits_bytes') != {
        'raw_body_or_partial': BODY_CAP, 'metadata_projection': PROJECTION_CAP,
        'claim_terminal_and_supervisor_receipts': CONTROL_CAP,
    }:
        raise Refusal('output_caps_changed')
    if (ROOT / OUT).resolve() != ROOT.resolve() / OUT:
        raise Refusal('output_symlink')
    pins = p.get('source_pins')
    if not isinstance(pins, list) or len(pins) != 2:
        raise Refusal('missing_source_pins')
    paths = []
    for pin in pins:
        if not isinstance(pin, dict):
            raise Refusal('invalid_source_pin')
        path = pin.get('path')
        if path not in (SOURCE, TEST):
            raise Refusal('invalid_source_pin')
        if path in paths or (ROOT / path).resolve() != ROOT.resolve() / path:
            raise Refusal('duplicate_or_symlink_pin')
        paths.append(path)
        data = bounded_read(ROOT / path, 262144)
        if type(pin.get('bytes')) is not int or len(data) != pin['bytes'] or digest(data) != pin.get('sha256'):
            raise Refusal('source_pin_mismatch')
    if SOURCE not in paths or TEST not in paths:
        raise Refusal('own_source_test_pins_required')
    previous = p.get('previous')
    if not isinstance(previous, str) or Path(previous).is_absolute() or '..' in Path(previous).parts:
        raise Refusal('invalid_previous_plan')
    if digest(bounded_read(ROOT / previous, 262144)) != p.get('previous_sha256'):
        raise Refusal('previous_plan_sha_mismatch')
    return p


def scalar_projection(obj, fields):
    values, missing, invalid = {}, [], []
    for key in fields:
        if key not in obj:
            values[key] = None
            missing.append(key)
            continue
        value = obj[key]
        if value is not None:
            allowed = type(value) is bool if key in BOOL_FIELDS else (
                type(value) in (int, float) if key in NUMBER_FIELDS else type(value) is str)
            if not allowed:
                invalid.append(key)
                # Container content might contain excluded fields. Never copy it.
                value = None
        values[key] = value
    return {'values': values, 'missing_fields': missing, 'invalid_type_fields': invalid}


def end_date(value):
    if not isinstance(value, str) or not re.fullmatch(
        r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})', value
    ):
        return None
    try:
        stamp = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        return stamp.astimezone(dt.timezone.utc).date().isoformat()
    except ValueError:
        return None


def project(obj):
    if not isinstance(obj, dict) or not isinstance(obj.get('events'), list):
        raise Refusal('missing_events_array')
    events = obj['events']
    result = {'schema': 'polymarket-no-basket-metadata-projection-v1',
              'conclusion': 'availability_only_no_economics', 'event_count': len(events),
              'search_summaries': [], 'candidate_indices': [], 'candidate': None,
              'status': 'inconclusive', 'reasons': []}
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            result['search_summaries'].append({'index': index, 'invalid_event_object': True,
                                             **scalar_projection({}, SUMMARY_FIELDS),
                                             'title_match': False, 'date_match': False,
                                             'match_reasons': ['invalid_event_object']})
            result['reasons'].append('invalid_event_object')
            continue
        row = scalar_projection(event, SUMMARY_FIELDS)
        title = row['values']['title']
        title_ok = isinstance(title, str) and re.fullmatch(TITLE, title) is not None
        actual_date = end_date(row['values']['endDate'])
        date_ok = actual_date == DATE
        reasons = []
        if not title_ok:
            reasons.append('title_missing_invalid_or_mismatch')
        if not date_ok:
            reasons.append('endDate_missing_invalid_or_mismatch')
        result['search_summaries'].append({'index': index, **row, 'title_match': title_ok,
                                         'date_match': date_ok, 'end_utc_date': actual_date,
                                         'match_reasons': reasons or ['exact_title_and_date']})
        if title_ok and date_ok:
            result['candidate_indices'].append(index)
    if len(events) > 10:
        result['reasons'].append('returned_event_cap_exceeded')
    if len(result['candidate_indices']) != 1:
        result['reasons'].append('candidate_not_unique')
        return result
    event = events[result['candidate_indices'][0]]
    candidate = scalar_projection(event, EVENT_FIELDS)
    candidate.update(markets=None, market_count=None, market_structure='unavailable')
    markets = event.get('markets')
    if isinstance(markets, list):
        candidate['market_count'] = len(markets)
        if 2 <= len(markets) <= 8:
            candidate['market_structure'] = 'projected'
            candidate['markets'] = []
            for market in markets:
                if not isinstance(market, dict):
                    candidate['markets'].append({'invalid_market_object': True,
                                                **scalar_projection({}, MARKET_FIELDS),
                                                'feeSchedule': None})
                    result['reasons'].append('invalid_market_object')
                    continue
                row = scalar_projection(market, MARKET_FIELDS)
                fee = market.get('feeSchedule')
                row['feeSchedule'] = scalar_projection(fee, FEE_FIELDS) if isinstance(fee, dict) else None
                row['feeSchedule_state'] = ('missing' if 'feeSchedule' not in market else
                                            'null' if fee is None else
                                            'projected' if isinstance(fee, dict) else 'invalid_type')
                candidate['markets'].append(row)
        else:
            result['reasons'].append('candidate_market_count_out_of_range')
    else:
        result['reasons'].append('candidate_markets_missing_or_invalid')
    result['candidate'] = candidate
    # Explicit metadata availability checks, with no false defaults or inferred
    # completeness. Textual exhaustiveness and chain identity remain unverified.
    for key, wanted in {'active': True, 'closed': False, 'archived': False,
                        'negRisk': True, 'negRiskAugmented': False}.items():
        if candidate['values'][key] is not wanted:
            result['reasons'].append('candidate_' + key + '_unknown_or_incompatible')
    if not candidate['values']['negRiskMarketID']:
        result['reasons'].append('candidate_negRiskMarketID_unavailable')
    if candidate['markets'] is not None:
        for row in candidate['markets']:
            for key, wanted in {'active': True, 'closed': False, 'archived': False,
                                'enableOrderBook': True, 'acceptingOrders': True,
                                'negRisk': True}.items():
                if row['values'][key] is not wanted:
                    result['reasons'].append('market_' + key + '_unknown_or_incompatible')
            for key in ('id', 'question', 'conditionId', 'outcomes', 'clobTokenIds', 'negRiskMarketID'):
                if not row['values'][key]:
                    result['reasons'].append('market_' + key + '_unavailable')
            if row['invalid_type_fields']:
                result['reasons'].append('market_projected_field_invalid_type')
    result['reasons'] = list(dict.fromkeys(result['reasons']))
    # Only identity/structure availability is automated; semantic eligibility is manual.
    if any(row['missing_fields'] or row['invalid_type_fields'] for row in result['search_summaries']):
        result['reasons'].append('search_identity_incomplete')
    if not result['reasons']:
        result['status'] = 'unique_candidate_metadata_available_semantic_review_required'
    return result


@contextlib.contextmanager
def hard_deadline(seconds, code):
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    began = time.monotonic()
    def expired(*_):
        raise Refusal(code)
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL,
                            max(0.000001, previous_timer[0] - (time.monotonic() - began)),
                            previous_timer[1])


def publish(path, value, cap, controls=False):
    body = encoded(value)
    if len(body) > cap:
        raise Refusal('publication_byte_cap')
    if controls:
        used = sum(p.stat().st_size for p in path.parent.glob('*.json') if p.name != 'metadata.json')
        if used + len(body) * 2 > CONTROL_CAP:
            raise Refusal('control_total_byte_cap')
    temporary = path.with_suffix(path.suffix + '.pending')
    with temporary.open('xb') as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(temporary, path)  # Atomic and refuses overwrite.
    temporary.unlink()


def fetch(raw_path, receipt):
    """One HTTPS request; HTTPConnection ignores proxies and follows no redirects."""
    connection = None
    with raw_path.open('xb') as sink:
        try:
            with hard_deadline(REQUEST_SECONDS, 'request_deadline'):
                connection = http.client.HTTPSConnection(HOST, timeout=REQUEST_SECONDS,
                                                        context=ssl.create_default_context())
                receipt['request_attempted'] = True
                connection.request('GET', TARGET, headers={
                    'Accept': 'application/json', 'Accept-Encoding': 'identity',
                    'User-Agent': 'rhhype-public-metadata/1.0', 'Connection': 'close',
                })
                response = connection.getresponse()
                receipt['http_status'] = response.status
                length = response.getheader('Content-Length')
                if length is not None and (not re.fullmatch(r'[0-9]{1,12}', length) or
                                           int(length) > BODY_CAP):
                    raise Refusal('declared_body_byte_cap_or_invalid_length')
                expected = int(length) if length is not None else None
                while receipt['raw_bytes'] < BODY_CAP:
                    chunk = response.read1(min(16384, BODY_CAP - receipt['raw_bytes']))
                    if not chunk:
                        receipt['body_complete'] = True
                        break
                    sink.write(chunk)
                    sink.flush()
                    receipt['raw_bytes'] += len(chunk)
                if expected is not None and receipt['raw_bytes'] == expected:
                    receipt['body_complete'] = True
                if not receipt['body_complete']:
                    raise Refusal('body_cap_reached_without_complete_eof')
                if expected is not None and receipt['raw_bytes'] != expected:
                    raise Refusal('incomplete_body')
                if response.status != 200:
                    raise Refusal('http_status_not_200')
                if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                    raise Refusal('unsupported_content_encoding')
                media = response.getheader('Content-Type', '').split(';', 1)[0].strip().lower()
                if media != 'application/json':
                    raise Refusal('unsupported_content_type')
        finally:
            if connection is not None:
                connection.close()


def worker(plan_sha256, out):
    receipt = {'schema': 'polymarket-no-basket-metadata-terminal-v1', 'started_utc': utc(),
               'plan_sha256': plan_sha256, 'status': 'inconclusive', 'request_attempted': False,
               'raw_bytes': 0, 'body_complete': False, 'http_status': None,
               'projection_published': False, 'code': None}
    raw_path = out / 'response.body'
    try:
        verify(plan_sha256)
        fetch(raw_path, receipt)
        # Recheck pins before interpreting any allowed metadata.
        verify(plan_sha256)
        projection = project(strict_json(bounded_read(raw_path, BODY_CAP)))
        projection['plan_sha256'] = plan_sha256
        verify(plan_sha256)
        publish(out / 'metadata.json', projection, PROJECTION_CAP)
        receipt['projection_published'] = True
        receipt['status'] = projection['status']
    except Refusal as exc:
        receipt['code'] = str(exc)
    except Exception:
        receipt['code'] = 'transport_or_internal_failure'
    finally:
        if raw_path.exists():
            raw = bounded_read(raw_path, BODY_CAP)
            receipt.update(raw_bytes=len(raw), raw_sha256=digest(raw))
        receipt['ended_utc'] = utc()
        try:
            verify(plan_sha256)
        except Exception:
            receipt['code'] = 'post_run_pin_check_failed'
            receipt['status'] = 'inconclusive'
        publish(out / 'terminal.json', receipt, 8192, controls=True)


def supervise(process, deadline, out, plan_sha256):
    process.start()
    process.join(max(0, deadline - time.monotonic() - 0.5))
    timed_out = process.is_alive()
    if timed_out:
        process.kill()
        process.join(max(0, deadline - time.monotonic()))
    terminal = out / 'terminal.json'
    raw_path = out / 'response.body'
    record = {'schema': 'polymarket-no-basket-metadata-supervisor-v1',
              'plan_sha256': plan_sha256, 'ended_utc': utc(),
              'status': 'process_deadline' if timed_out else
                        'worker_finished' if terminal.exists() else 'worker_failed_without_terminal',
              'worker_exitcode': process.exitcode, 'terminal_exists': terminal.exists(),
              'raw_bytes': raw_path.stat().st_size if raw_path.exists() else 0}
    if record['raw_bytes'] > BODY_CAP:
        raise Refusal('raw_byte_cap_breached')
    publish(out / 'supervisor.json', record, 8192, controls=True)
    return record


def run(plan_sha256):
    deadline = time.monotonic() + PROCESS_SECONDS
    with hard_deadline(PROCESS_SECONDS, 'process_deadline_before_claim'):
        verify(plan_sha256)
    out = ROOT / OUT
    out.mkdir(parents=True, exist_ok=False)
    publish(out / 'claim.json', {
        'schema': 'polymarket-no-basket-metadata-claim-v1', 'started_utc': utc(),
        'plan_sha256': plan_sha256, 'source_sha256': digest(bounded_read(ROOT / SOURCE, 65536)),
        'request_count_max': 1, 'url': URL, 'purpose': 'metadata_availability_only',
    }, 8192, controls=True)
    # Fork retains the already pinned code. The worker independently verifies again.
    process = multiprocessing.get_context('fork').Process(target=worker, args=(plan_sha256, out))
    return supervise(process, deadline, out, plan_sha256)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--plan-sha256')
    args = parser.parse_args(argv)
    if not args.run:
        print(encoded({'status': 'dry_no_http', 'request_count': 0, 'url': URL}).decode(), end='')
        return 0
    try:
        result = run(args.plan_sha256)
    except Refusal as exc:
        result = {'status': 'refused_no_retry', 'code': str(exc)}
    except FileExistsError:
        result = {'status': 'refused_no_retry', 'code': 'existing_output'}
    except Exception:
        result = {'status': 'failed_no_retry', 'code': 'internal_failure'}
    print(encoded(result).decode(), end='')
    return 0 if result['status'] == 'worker_finished' else 1


if __name__ == '__main__':
    raise SystemExit(main())
