#!/usr/bin/env python3
"""Prospective 32-route, 15-slot conditional nominal pUSD price screen.

Zero fees and top-of-book prices make a necessary price condition only. No
conversion, fill, source equivalence, or profit is established by this probe.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, localcontext
import multiprocessing
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import polymarket_no_basket_optimistic_books as prior
from scripts import polymarket_no_basket_chain_metadata_v2 as chain
from scripts import polymarket_no_basket_metadata as metadata

Refusal, FieldInvalid = prior.Refusal, prior.FieldInvalid
SOURCE = 'scripts/polymarket_subset_conversion_books.py'
TEST = 'tests/test_polymarket_subset_conversion_books.py'
PLAN = ROOT / 'reports/experiment-storage/polymarket-subset-conversion-books-v1.json'
OUT = 'reports/polymarket-no-basket/subset-conversion-books-v1'
HOST, ENDPOINT = prior.HOST, prior.ENDPOINT
CHAIN_PLAN, CHAIN_SUMMARY = prior.CHAIN_PLAN, prior.CHAIN_SUMMARY
PRIOR_PLAN = {'path': 'reports/experiment-storage/polymarket-no-basket-optimistic-books-v1.json',
              'bytes': 11489, 'sha256': '4bb8628338054ba1442b1a3568f5474b775d83bcfcf4841204522d9b620e4673'}
PRIOR_SOURCE = {'path': 'scripts/polymarket_no_basket_optimistic_books.py',
                'bytes': 24781, 'sha256': '829f244edd870784cd8c6fddb9da44af1da3e523eaec5aaab097b7c2413432fb'}
BODY_SHA = 'e709135e3d16e357e5958fe1bbe636d789eae69aeef34e2dff6b367255e374ff'
TOKEN_IDS = (
    '61725366781282351729996972759460154434089275036953062948669003249092837754960',
    '17010377994663817312158123655937348199252960045746746128731746451645055725586',
    '110888499829195123034987289109543572302716575133123608254293945182185650232552',
    '33268510350568915228897273528353467773422190590579607471427765079749830445947',
    '42038775866198212615491650114881818219665139981763207699110491615333273795415',
    '111061902544814266207267295505639408607400625795891618462682726460921782993748',
    '78632395083310670734315205502061249602319069653915932320155846460019107676757',
    '55159722761418013044126414276680602270318000841690689684819994448621694923050',
    '41864497411878191766967581422432961750808440991174085516384293402629587721839',
    '18246296022868501258060085368606280205967114341141276439803424448463050819498',
)
LIMITS = {**prior.LIMITS, 'derived_receipts_bytes': 98304}
ROUTE_FORMULA = '(cardinality(S)-1)+sum(YES best bids outside S)-sum(NO best asks inside S)'


def expected_routes():
    return ([{'route_id': 0, 'kind': 'mint_full_yes', 'fixed_bridge_index': 0,
              'formula': 'sum(all YES best bids)-1'}] +
            [{'route_id': mask, 'kind': 'convert_no_subset',
              'selected_indices': [k for k in range(5) if mask & (1 << k)],
              'formula': ROUTE_FORMULA} for mask in range(1, 32)])


def verify(plan_sha):
    if not isinstance(plan_sha, str) or not re.fullmatch('[0-9a-f]{64}', plan_sha):
        raise Refusal('expected_plan_sha_required')
    raw = metadata.bounded_read(PLAN, 22000)
    if chain.sha(raw) != plan_sha:
        raise Refusal('plan_sha_mismatch')
    p = metadata.strict_json(raw)
    if p.get('schema') != 'polymarket-subset-conversion-books-v1' or p.get('status') != 'frozen_subset_conversion_books_probe':
        raise Refusal('plan_schema_or_not_frozen')
    fixed = {'event_id': chain.EVENT, 'endpoint': ENDPOINT, 'output_dir': OUT,
             'request_body_sha256': BODY_SHA, 'limits': LIMITS,
             'chain_plan': CHAIN_PLAN, 'chain_summary': CHAIN_SUMMARY,
             'previous_polymarket_plan': PRIOR_PLAN, 'reserved_bytes': 0,
             'fixed_routes': expected_routes()}
    for key, value in fixed.items():
        if chain.canonical(p.get(key)) != chain.canonical(value):
            raise Refusal('fixed_plan_scope_changed')
    allocation = p.get('allocation')
    if not isinstance(allocation, dict) or allocation.get('new_source_test_plan_package_cap') != 98304 or allocation.get('transfer_derived_to_source') != 98304 or allocation.get('derived_after') != 425984 or allocation.get('source_after') != 360448:
        raise Refusal('allocation_changed')
    pins = p.get('source_pins')
    if not isinstance(pins, list) or len(pins) != 2 or sorted(pin.get('path', '') for pin in pins if isinstance(pin, dict)) != sorted((SOURCE, TEST)):
        raise Refusal('own_source_test_pins_required')
    # Retained committed preparation plan remains source allocation occupancy.
    package_bytes = 19816 + len(raw)
    for pin in pins:
        path = ROOT / pin['path']
        if path.resolve() != ROOT.resolve() / pin['path']:
            raise Refusal('source_symlink')
        package_bytes += len(chain.file_identity(path, pin, 65536))
    if package_bytes > 98304:
        raise Refusal('source_package_cap')
    chain.file_identity(ROOT / PRIOR_SOURCE['path'], PRIOR_SOURCE, 25000)
    chain.file_identity(ROOT / PRIOR_PLAN['path'], PRIOR_PLAN, 12000)
    chain.file_identity(ROOT / CHAIN_PLAN['path'], CHAIN_PLAN, 32768)
    parent = chain.verify(CHAIN_PLAN['sha256'])
    if p.get('markets') != parent['markets']:
        raise Refusal('market_mapping_changed')
    body = [entry for market in parent['markets'] for entry in
            ({'token_id': market['no_token_id']}, {'token_id': market['yes_token_id']})]
    if p.get('request_body') != body or tuple(x['token_id'] for x in body) != TOKEN_IDS or chain.sha(chain.canonical(body)) != BODY_SHA:
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


def _validated_book(book, market, side, receipt_ns):
    tick = prior.decimal_field(book.get('tick_size'))
    minimum = prior.decimal_field(book.get('min_order_size'))
    if not 0 < tick <= 1 or minimum <= 0:
        raise FieldInvalid('invalid_tick_or_minimum')
    hash_value = book.get('hash')
    if not isinstance(hash_value, str) or not 1 <= len(hash_value) <= 128:
        raise FieldInvalid('missing_or_invalid_book_hash')
    stamp = prior.snapshot_time(book.get('timestamp'))
    prices = {}
    for key in ('asks', 'bids'):
        levels = book.get(key)
        if not isinstance(levels, list) or len(levels) > LIMITS['maximum_levels_per_side']:
            raise FieldInvalid('invalid_or_excessive_side_levels')
        values = []
        for level in levels:
            if not isinstance(level, dict):
                raise FieldInvalid('invalid_level_object')
            price = prior.decimal_field(level.get('price'))
            size = prior.decimal_field(level.get('size'))
            with localcontext() as context:
                context.prec = 64
                if not 0 < price <= 1 or size <= 0 or price % tick != 0:
                    raise FieldInvalid('invalid_price_size_or_native_tick')
            values.append(price)
        prices[key] = values
    best_ask = min(prices['asks']) if prices['asks'] else None
    best_bid = max(prices['bids']) if prices['bids'] else None
    if best_ask is not None and best_bid is not None and best_bid >= best_ask:
        raise FieldInvalid('crossed_book')
    economic = best_ask if side == 'NO' else best_bid
    return ({'market_index': market['index'], 'side': side, 'asset_id': book['asset_id'],
             'hash_sha256': chain.sha(hash_value.encode('utf-8')), 'timestamp': stamp,
             'tick_size': book['tick_size'], 'min_order_size': book['min_order_size'],
             'minimum_order_unit': 'unresolved',
             'economic_best': str(economic) if economic is not None else None}, economic)


def route_margins(no_asks, yes_bids):
    """Economic invariant: selected NO converts to outside YES plus |S|-1 collateral."""
    if len(no_asks) != 5 or len(yes_bids) != 5:
        raise ValueError('five_market_vectors_required')
    with localcontext() as context:
        context.prec = 64
        values = [sum(yes_bids, Decimal(0)) - Decimal(1)]
        for mask in range(1, 32):
            selected = [k for k in range(5) if mask & (1 << k)]
            values.append(Decimal(len(selected) - 1) +
                          sum((yes_bids[k] for k in range(5) if k not in selected), Decimal(0)) -
                          sum((no_asks[k] for k in selected), Decimal(0)))
    return values


def evaluate(obj, markets, receipt_ns):
    expected = {token: (market, side) for market in markets for token, side in
                ((market['no_token_id'], 'NO'), (market['yes_token_id'], 'YES'))}
    if not isinstance(obj, list) or len(obj) != 10 or len(expected) != 10:
        raise Refusal('book_set_identity_count')
    books = {}
    for book in obj:
        if not isinstance(book, dict):
            raise Refusal('invalid_book_identity_object')
        asset = book.get('asset_id')
        if not isinstance(asset, str) or asset not in expected or asset in books:
            raise Refusal('missing_extra_or_duplicate_asset_identity')
        if book.get('market') != expected[asset][0]['condition_id'] or book.get('neg_risk') is not True:
            raise Refusal('condition_or_negative_risk_identity')
        books[asset] = book
    details, no_asks, yes_bids = [], [], []
    missing = False
    for market in markets:
        for key, side, vector in (('no_token_id', 'NO', no_asks), ('yes_token_id', 'YES', yes_bids)):
            row, price = _validated_book(books[market[key]], market, side, receipt_ns)
            details.append(row)
            vector.append(price)
            missing |= price is None
    times = [row['timestamp']['interpreted_unix_ns'] for row in details]
    future = any(value > receipt_ns + 250000000 for value in times)
    stale = any(value < receipt_ns - 5000000000 for value in times)
    span = max(times) - min(times)
    diagnostics = {'fresh_coherent': not future and not stale and span <= 500000000,
                   'future_timestamp': future, 'stale_timestamp': stale,
                   'cross_book_span_ns': span, 'timestamp_units_interpretive': True}
    if missing:
        return {'field_valid': False, 'availability_class': 'missing', 'reason': 'empty_economic_side',
                'books': details, 'time_diagnostics': diagnostics}
    margins = route_margins(no_asks, yes_bids)
    # Index is fixed route_id. Sign determines the explicit legend in summary.
    routes = [str(margin) for margin in margins]
    return {'field_valid': True, 'availability_class': 'observed', 'reason': None,
            'quote_unit': 'conditional_nominal_pUSD', 'books': details,
            'time_diagnostics': diagnostics, 'routes': routes}


def empty_slots(anchor_wall_ns):
    return [{'slot': k, 'planned_start_utc': prior.utc_ns(anchor_wall_ns + 4000000000 * k),
             'request_attempted': False, 'availability_class': 'missing',
             'reason': 'future_unavailable', 'field_valid': False} for k in range(15)]


def summarize(slots, plan_sha, source_pins_verified=False, sampling_finished=False):
    if len(slots) != 15 or [slot['slot'] for slot in slots] != list(range(15)):
        raise Refusal('slot_denominator_changed')
    routes = []
    for slot in slots:
        if slot['field_valid']:
            if len(slot.get('routes', [])) != 32:
                raise Refusal('route_denominator_changed')
            routes.extend(slot['routes'])
        else:
            slot['routes'] = [None] * 32
    valid = [slot for slot in slots if slot['field_valid']]
    fresh = [slot for slot in valid if slot['time_diagnostics']['fresh_coherent']]
    positive = sum(Decimal(route) > 0 for route in routes)
    attempts = [slot['request_attempted'] for slot in slots]
    counts = {'scheduled_slots': 15, 'planned_route_slots': 480,
              'requests_attempted': None if None in attempts else sum(attempts),
              'requests_attempted_known_lower_bound': sum(value is True for value in attempts),
              'requests_attempted_unknown_slots': sum(value is None for value in attempts),
              'field_valid_slots': len(valid),
              'invalid_slots': sum(slot['availability_class'] == 'invalid' for slot in slots),
              'missing_slots': sum(slot['availability_class'] == 'missing' for slot in slots),
              'fresh_coherent_valid_slots': len(fresh),
              'field_valid_route_slots': len(routes),
              'unavailable_route_slots': 480 - len(routes),
              'positive_route_slots': positive,
              'nonpositive_route_slots': len(routes) - positive}
    valid_conclusions = bool(source_pins_verified and sampling_finished)
    return {'schema': 'polymarket-subset-conversion-books-summary-v1', 'plan_sha256': plan_sha,
            'counts': counts,
            'source_pins_verified': bool(source_pins_verified),
            'economic_conclusions_valid': valid_conclusions,
            'all_scheduled_sets_fresh_nonpositive': valid_conclusions and len(fresh) == 15 and positive == 0,
            'maximum_conclusion': 'necessary_price_condition_on_recorded_sets_only' if valid_conclusions else 'no_economic_conclusion_unverified_or_incomplete',
            'quote_unit': 'conditional_nominal_pUSD', 'all_costs_assumed_zero': True,
            'snapshot_units_and_freshness_interpretive': True,
            'chain_snapshot_is_earlier_than_quotes': True,
            'conversion_source_equivalence_and_execution': 'unproved',
            'route_encoding': {'index': 'fixed route_id 0..31', 'value': 'exact Decimal optimistic margin or null',
                               'positive': 'necessary_price_condition_only',
                               'nonpositive': 'conditional_nominal_nonpositive_recorded_route',
                               'null': 'unavailable_slot'},
            'slots': slots}


def publish(out, name, value):
    body = metadata.encoded(value)
    current = out / name
    used = sum(path.stat().st_size for path in out.iterdir() if path.is_file() and
               (path.name.endswith('.json') or path.name.endswith('.pending')))
    # Reserve one extra copy of a replaced receipt during atomic publication.
    if used + len(body) > LIMITS['derived_receipts_bytes']:
        raise Refusal('derived_receipts_total_cap')
    if current.exists() and current.stat().st_size > LIMITS['derived_receipts_bytes']:
        raise Refusal('derived_receipt_corrupt')
    metadata.publish(current, value, 90000)


def sample(plan, plan_sha, out, anchor_mono, anchor_wall_ns, work_deadline, slots, terminal):
    trace, budget = prior.Trace(out), {'bytes': 0, 'requests': 0}
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
                          'planned_monotonic': target, 'request_body_sha256': BODY_SHA,
                          'request_attempted': False, 'body_complete': False, 'code': None}
                try:
                    raw = prior.transport(plan['request_body'], record, budget, work_deadline)
                    obj = metadata.strict_json(raw)
                    try:
                        slot.update(evaluate(obj, plan['markets'], record['receipt_wall_ns']))
                    except FieldInvalid as exc:
                        slot.update(reason=str(exc), availability_class='invalid')
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
                    try:
                        trace.append(record)
                    except Exception:
                        # An unretained body cannot support a price conclusion.
                        slot.update(field_valid=False, availability_class='invalid',
                                    reason='evidence_retention_failed', routes=[None] * 32)
                        slot.pop('books', None)
                        slot.pop('time_diagnostics', None)
                        record['code'] = 'evidence_retention_failed'
                        raise Refusal('evidence_retention_failed') from None
    finally:
        terminal.update(requests_attempted=budget['requests'], total_response_bytes=budget['bytes'],
                        trace_plaintext_bytes=len(trace.plaintext))
        path = out / 'trace.jsonl.gz'
        if path.exists():
            raw = metadata.bounded_read(path, LIMITS['trace_gzip_bytes'])
            terminal.update(trace_gzip_bytes=len(raw), trace_gzip_sha256=chain.sha(raw))


def worker(plan_sha, out, anchor_mono, anchor_wall_ns, work_deadline):
    slots = empty_slots(anchor_wall_ns)
    terminal = {'schema': 'polymarket-subset-conversion-books-terminal-v1',
                'plan_sha256': plan_sha, 'status': 'inconclusive',
                'code': None, 'started_utc': metadata.utc()}
    try:
        plan = verify(plan_sha)
        sample(plan, plan_sha, out, anchor_mono, anchor_wall_ns, work_deadline, slots, terminal)
        terminal['status'] = 'fixed_sampling_finished'
    except Refusal as exc:
        terminal['code'] = str(exc)
    except Exception:
        terminal['code'] = 'internal_failure'
    finally:
        pins_verified = False
        try:
            verify(plan_sha)
            pins_verified = True
        except Exception:
            terminal.update(status='inconclusive', code='post_run_pin_check_failed')
        terminal['ended_utc'] = metadata.utc()
        terminal['source_pins_verified'] = pins_verified
        publish(out, 'summary.json', summarize(slots, plan_sha, pins_verified,
                                                terminal['status'] == 'fixed_sampling_finished'))
        publish(out, 'terminal.json', terminal)


def run(plan_sha):
    began = time.monotonic()
    with metadata.hard_deadline(LIMITS['process_seconds'], 'process_deadline_before_claim'):
        verify(plan_sha)
    out = ROOT / OUT
    out.mkdir(parents=True, exist_ok=False)
    claim_mono, claim_wall_ns = time.monotonic(), time.time_ns()
    anchor_mono, anchor_wall_ns = claim_mono + 2, claim_wall_ns + 2000000000
    publish(out, 'claim.json', {'schema': 'polymarket-subset-conversion-books-claim-v1',
                               'plan_sha256': plan_sha, 'request_body_sha256': BODY_SHA,
                               'claim_utc': prior.utc_ns(claim_wall_ns),
                               'anchor_utc': prior.utc_ns(anchor_wall_ns),
                               'anchor_wall_ns': anchor_wall_ns, 'anchor_monotonic': anchor_mono,
                               'slots': 15, 'planned_route_slots': 480,
                               'purpose': 'zero_cost_necessary_price_bound_only'})
    process = multiprocessing.get_context('fork').Process(target=worker, args=(
        plan_sha, out, anchor_mono, anchor_wall_ns, claim_mono + 64))
    process.start()
    deadline = began + 75
    process.join(max(0, deadline - time.monotonic() - 1))
    expired = process.is_alive()
    if expired:
        process.kill()
        process.join(max(0, deadline - time.monotonic()))
    result = {'schema': 'polymarket-subset-conversion-books-supervisor-v1', 'plan_sha256': plan_sha,
              'status': 'process_deadline' if expired else 'worker_finished',
              'worker_exitcode': process.exitcode,
              'terminal_exists': (out / 'terminal.json').exists(),
              'summary_exists': (out / 'summary.json').exists()}
    if not expired and (process.exitcode != 0 or not result['terminal_exists']):
        result['status'] = 'worker_failed_without_terminal'
    if not result['summary_exists']:
        unknown = empty_slots(anchor_wall_ns)
        for slot in unknown:
            slot['reason'] = 'worker_interrupted_observation_unresolved'
            slot['request_attempted'] = None
        publish(out, 'summary.json', summarize(unknown, plan_sha))
        result.update(summary_exists=True, summary_reconstructed_as_unresolved=True)
    try:
        terminal = metadata.strict_json(metadata.bounded_read(out / 'terminal.json', 90000))
        summary = metadata.strict_json(metadata.bounded_read(out / 'summary.json', 90000))
        result['economic_conclusions_valid'] = bool(
            result['status'] == 'worker_finished' and terminal.get('status') == 'fixed_sampling_finished'
            and terminal.get('source_pins_verified') is True
            and summary.get('economic_conclusions_valid') is True)
    except Exception:
        result['economic_conclusions_valid'] = False
    publish(out, 'supervisor.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--plan-sha256')
    args = parser.parse_args(argv)
    if not args.run:
        result = {'status': 'dry_no_http', 'http_requests': 0,
                  'maximum_slots': 15, 'planned_route_slots': 480, 'endpoint': ENDPOINT}
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
