#!/usr/bin/env python3
"""Fixed-schedule dated-carry quote diagnostics; never claim fills or closed P&L."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import gzip
import hashlib
import json
from math import gcd
from pathlib import Path
import re
import time

BUDGETS = (100, 250, 500, 1000)
SLOTS = 864
INTERVAL = 300
DURATION = SLOTS * INTERVAL
DECISIONS = (0, 144, 288, 432, 576, 720)
YEAR_SECONDS = 365 * 86400
UNRESOLVED = [
    'future_spot_liquidation_price_and_fee_notional',
    'future_delivery_index_and_applicable_delivery_fee',
    'spot_exit_versus_settlement_index_residual',
    'usdc_usd_conversion_and_terminal_valuation',
    'full_margin_path_and_collateral_buffers',
    'private_execution_and_account_eligibility',
    'rules_and_fees_after_frozen_public_metadata',
    'spot_fee_debit_currency_and_net_acquired_inventory',
    'underlying_exchange_event_age_beyond_api_timestamp',
]


class InvalidQuote(ValueError):
    pass


def number(value) -> Fraction:
    if isinstance(value, bool) or value is None:
        raise InvalidQuote('invalid_number')
    text = str(value)
    if len(text) > 80:
        raise InvalidQuote('numeric_length')
    try:
        dec = Decimal(text)
    except InvalidOperation as exc:
        raise InvalidQuote('invalid_number') from exc
    if not dec.is_finite() or len(dec.as_tuple().digits) > 40 or abs(dec.adjusted()) > 18:
        raise InvalidQuote('numeric_bounds')
    return Fraction(dec)


def positive(value) -> Fraction:
    result = number(value)
    if result <= 0:
        raise InvalidQuote('nonpositive_number')
    return result


def common_lot(a, b) -> Fraction:
    a, b = positive(a), positive(b)
    return Fraction(a.numerator * b.numerator // gcd(a.numerator, b.numerator),
                    gcd(a.denominator, b.denominator))


def json_bytes(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def fraction_text(value: Fraction) -> str:
    return f'{value.numerator}/{value.denominator}'


def generated_fraction(value: str) -> Fraction:
    """Generated rational output has larger integers than individual API inputs."""
    if not isinstance(value, str) or not re.fullmatch(r'-?\d{1,512}/[1-9]\d{0,511}', value):
        raise ValueError('generated_fraction_bounds')
    return Fraction(value)


def utc_fraction(value) -> Fraction:
    if isinstance(value, str) and 'T' in value:
        # ISO inputs support exact microseconds; launch uses whole UTC seconds.
        if re.search(r'\.\d{7,}', value):
            raise InvalidQuote('unsupported_iso_time_precision')
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise InvalidQuote('timezone_required')
        delta = stamp - datetime(1970, 1, 1, tzinfo=timezone.utc)
        return Fraction(delta.days*86400+delta.seconds) + Fraction(delta.microseconds,10**6)
    return number(value)


def select_markets(future_response: dict, spot_response: dict, activation: float) -> dict:
    """Select by identity and expiry alone, without inspecting market prices."""
    start = number(activation)
    if not isinstance(future_response, dict) or not isinstance(spot_response, dict):
        raise InvalidQuote('metadata_envelope')
    future_rows = future_response.get('result')
    spot_rows = spot_response.get('result')
    if not isinstance(future_rows, list) or not isinstance(spot_rows, list):
        raise InvalidQuote('metadata_result')
    if len(future_rows) > 4096 or len(spot_rows) > 256:
        raise InvalidQuote('metadata_count')
    candidates = []
    names = set()
    for item in future_rows:
        if not isinstance(item, dict):
            raise InvalidQuote('metadata_row')
        name = item.get('instrument_name')
        if not isinstance(name, str) or not 1 <= len(name) <= 100:
            raise InvalidQuote('metadata_identity_type')
        if name in names:
            raise InvalidQuote('duplicate_metadata_identity')
        names.add(name)
        if not (item.get('base_currency') == 'BTC' and item.get('quote_currency') == 'USDC'
                and item.get('settlement_currency') == 'USDC' and item.get('kind') == 'future'
                and item.get('instrument_type') == 'linear'
                and item.get('settlement_period') != 'perpetual'
                and item.get('is_active') is True and item.get('state') == 'open'
                and isinstance(name, str) and name.startswith('BTC_USDC-')
                and 'PERPETUAL' not in name):
            continue
        expiry = positive(item.get('expiration_timestamp')) / 1000
        if 7 * 86400 <= expiry - start <= 30 * 86400:
            candidates.append((expiry, name, item))
    if not candidates:
        raise InvalidQuote('no_eligible_fixed_expiry')
    candidates.sort(key=lambda x: (x[0], x[1]))
    selected_spots = [x for x in spot_rows if isinstance(x, dict)
                      and x.get('instrument_name') == 'BTC_USDC']
    if len(selected_spots) != 1:
        raise InvalidQuote('spot_identity_count')
    spot = selected_spots[0]
    future = candidates[0][2]
    if not (spot.get('kind') == 'spot' and spot.get('base_currency') == 'BTC'
            and spot.get('quote_currency') == 'USDC' and spot.get('state') == 'open'
            and spot.get('is_active') is True and spot.get('instrument_type') == 'linear'
            and spot.get('price_index') == future.get('price_index') == 'btc_usdc'
            and spot.get('index_id') == future.get('index_id')):
        raise InvalidQuote('spot_future_identity_mismatch')
    for market in (spot, future):
        positive(market.get('min_trade_amount'))
        positive(market.get('contract_size'))
        positive(market.get('tick_size'))
        fee = number(market.get('taker_commission'))
        if fee < 0 or fee > Fraction(1, 100):
            raise InvalidQuote('fee_outside_scenario_bounds')
        if market.get('tick_size_steps'):
            raise InvalidQuote('tiered_ticks_require_separate_method')
    return {'spot': spot, 'future': future}


def validate_book(book: dict, market: dict) -> dict:
    if not isinstance(book, dict) or book.get('instrument_name') != market['instrument_name']:
        raise InvalidQuote('book_identity')
    if book.get('state') != 'open':
        raise InvalidQuote('book_not_open')
    stamp = book.get('timestamp')
    if isinstance(stamp, bool) or not isinstance(stamp, int) or stamp <= 0:
        raise InvalidQuote('source_timestamp')
    tick = positive(market['tick_size'])
    result = {'source_utc': Fraction(stamp, 1000)}
    for side in ('bids', 'asks'):
        levels = book.get(side)
        if not isinstance(levels, list) or not 1 <= len(levels) <= 10:
            raise InvalidQuote('depth_length')
        parsed = []
        for level in levels:
            if not isinstance(level, list) or len(level) != 2:
                raise InvalidQuote('depth_shape')
            price, amount = map(positive, level)
            if (price / tick).denominator != 1:
                raise InvalidQuote('price_grid')
            if parsed and ((side == 'bids' and price >= parsed[-1][0])
                           or (side == 'asks' and price <= parsed[-1][0])):
                raise InvalidQuote('depth_order_or_duplicate')
            parsed.append((price, amount))
        result[side] = parsed
    if result['bids'][0][0] >= result['asks'][0][0]:
        raise InvalidQuote('crossed_or_locked_book')
    for key in ('min_price', 'max_price'):
        if book.get(key) is not None:
            result[key] = positive(book[key])
    if 'min_price' in result and 'max_price' in result and result['min_price'] > result['max_price']:
        raise InvalidQuote('invalid_price_band')
    return result


def walk(levels, quantity: Fraction, *, with_worst=False):
    remaining, total = quantity, Fraction(0)
    for price, amount in levels:
        take = min(remaining, amount)
        total += price * take
        remaining -= take
        if remaining == 0:
            return (total, price) if with_worst else total
    raise InvalidQuote('insufficient_depth')


def invalid_rows(slot: int, reason: str) -> list[dict]:
    return [{'slot': slot, 'budget_usd': b, 'primary_decision': slot in DECISIONS and b == 1000,
             'status': reason, 'conditional_proxy_usd': None, 'all_in_headroom_usd': None,
             'closed_net_usd': None} for b in BUDGETS]


def evaluate_record(record: dict, config: dict) -> list[dict]:
    """Evaluate normalized collector evidence offline after the study endpoint."""
    if not isinstance(record, dict):
        raise InvalidQuote('slot_envelope')
    slot = record.get('slot')
    if isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot < SLOTS:
        raise InvalidQuote('slot_identity')
    try:
        if 'status' in record and record['status'] != 'sampled':
            raise InvalidQuote('collector_' + str(record['status'])[:80])
        planned = utc_fraction(config['t0_utc']) + slot * INTERVAL
        planned_record = (number(record['planned_utc_ns']) / 10**9 if 'planned_utc_ns' in record
                          else number(record['planned_utc']))
        if planned_record != planned:
            raise InvalidQuote('planned_time_mismatch')
        actual = (number(record['actual_utc_ns']) / 10**9 if 'actual_utc_ns' in record
                  else number(record['actual_utc']))
        if not 0 <= actual - planned <= Fraction(1, 4):
            raise InvalidQuote('dispatch_lateness')
        if abs(number(record['clock_drift_s'])) > Fraction(1, 4):
            raise InvalidQuote('clock_mapping_drift')
        if record.get('error'):
            raise InvalidQuote(str(record['error'])[:100])
        books = {}
        for role in ('spot', 'future'):
            response = record['responses'][role]
            if not isinstance(response, dict):
                raise InvalidQuote(role + '_response_shape')
            if response.get('error'):
                raise InvalidQuote(role + '_request_failed')
            if response.get('http_status', response.get('status')) != 200:
                raise InvalidQuote(role + '_http_status')
            received = (number(response['received_utc_ns']) / 10**9 if 'received_utc_ns' in response
                        else number(response['received_utc']))
            requested = (number(response['request_utc_ns']) / 10**9 if 'request_utc_ns' in response
                         else number(response['request_utc']))
            if 'deadline_admitted' in response and response['deadline_admitted'] is not True:
                raise InvalidQuote(role + '_deadline_not_admitted')
            if not planned-1 <= requested <= received <= planned:
                raise InvalidQuote(role + '_receipt_after_decision_or_before_request')
            if 'start_clock_drift_s' in response and abs(number(response['start_clock_drift_s'])) > Fraction(1, 4):
                raise InvalidQuote(role + '_request_clock_drift')
            if abs(number(response['clock_drift_s'])) > Fraction(1, 4):
                raise InvalidQuote(role + '_receipt_clock_drift')
            body = response['raw_utf8']
            if not isinstance(body, str) or len(body.encode()) > 65536:
                raise InvalidQuote(role + '_response_cap')
            payload = json.loads(body, parse_float=Decimal)
            if not isinstance(payload, dict) or payload.get('error') or payload.get('jsonrpc') != '2.0':
                raise InvalidQuote(role + '_rpc_error')
            books[role] = validate_book(payload.get('result'), config['markets'][role])
            source = books[role]['source_utc']
            if not source <= received or not 0 <= actual - source <= 2 or not 0 <= actual - received <= 2:
                raise InvalidQuote(role + '_source_or_receipt_age')
        if abs(books['spot']['source_utc'] - books['future']['source_utc']) > Fraction(1, 4):
            raise InvalidQuote('paired_source_skew')
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        return invalid_rows(slot, str(exc) if isinstance(exc, InvalidQuote) else 'malformed_slot')
    return [evaluate_size(slot, budget, planned, books, config) for budget in BUDGETS]


def evaluate_size(slot, budget, planned, books, config):
    row = invalid_rows(slot, 'unclassified')[BUDGETS.index(budget)]
    try:
        spot, future = books['spot'], books['future']
        lot = common_lot(config['markets']['spot']['min_trade_amount'],
                         config['markets']['future']['min_trade_amount'])
        divisor = max(spot['asks'][0][0], future['bids'][0][0])
        q = (Fraction(budget) // (divisor * lot)) * lot
        if q <= 0:
            raise InvalidQuote('quantity_rounds_to_zero')
        if q > 100:
            raise InvalidQuote('published_default_btc_spot_quantity_limit')
        for role in ('spot', 'future'):
            if q < positive(config['markets'][role]['min_trade_amount']):
                raise InvalidQuote('minimum_quantity')
        # Both opposite sides are also walked to expose current liquidation coverage.
        spot_buy, spot_worst = walk(spot['asks'], q, with_worst=True)
        future_sell, future_worst = walk(future['bids'], q, with_worst=True)
        for book, price in ((spot, spot_worst), (future, future_worst)):
            if ('min_price' in book and price < book['min_price']) or ('max_price' in book and price > book['max_price']):
                raise InvalidQuote('known_entry_price_band')
        spot_sell, future_buy = walk(spot['bids'], q), walk(future['asks'], q)
        if max(spot_buy, future_sell) > budget:
            raise InvalidQuote('walked_entry_budget_exceeded')
        expiry = number(config['expiry_utc'])
        if expiry != number(config['markets']['future']['expiration_timestamp']) / 1000:
            raise InvalidQuote('configured_expiry_mismatch')
        duration = expiry + 3600 - planned
        if duration <= 0:
            raise InvalidQuote('expiry_elapsed')
        sf = number(config['fees']['spot_taker'])
        ff = number(config['fees']['future_taker'])
        df = number(config['fees']['delivery_proxy'])
        if sf != number(config['markets']['spot']['taker_commission']) or ff != number(config['markets']['future']['taker_commission']):
            raise InvalidQuote('configured_public_entry_fee_mismatch')
        if any(x < 0 or x > Fraction(1, 100) for x in (sf, ff, df)):
            raise InvalidQuote('fee_scenario_bounds')
        entry_fees = spot_buy * sf + future_sell * ff
        fee_proxy = entry_fees + spot_buy * sf + future_sell * df
        gross = future_sell - spot_buy
        stress = max(spot_buy, future_sell) / 2000
        # Includes separately held entry-fee cash; future fee/buffer requirements remain unknown.
        allocated = 2 * budget + entry_fees
        capital = allocated * Fraction(5, 100) * duration / YEAR_SECONDS
        proxy = gross - fee_proxy - capital - stress
        row.update(status='conditional_quote_valid', quantity=fraction_text(q),
                   gross_entry_premium_usd=float(gross), spot_entry_notional_usdc=float(spot_buy),
                   future_entry_reference_usdc=float(future_sell),
                   current_roundtrip_gross_usdc=float(spot_sell - spot_buy + future_sell - future_buy),
                   allocated_capital_proxy_usdc=float(allocated),
                   remaining_capital_seconds=float(duration), entry_fees_usdc=float(entry_fees),
                   terminal_fee_proxy_usdc=float(fee_proxy-entry_fees),
                   capital_5pct_proxy_usdc=float(capital), stress_proxy_usdc=float(stress),
                   conditional_proxy_usd=float(proxy), conditional_proxy_exact=fraction_text(proxy),
                   capital_sensitivity_usd={str(r): float(gross-fee_proxy-stress-allocated*Fraction(r,100)*duration/YEAR_SECONDS)
                                            for r in (0, 5, 10)},
                   fee_basis='frozen_public_entry_rates_and_entry_notional_terminal_proxies',
                   actual_fees_complete=False, contract_rule_completeness='partial',
                   cashflow_currency='USDC', usd_parity_assumed=True)
    except (KeyError, TypeError, ValueError) as exc:
        row['status'] = str(exc) if isinstance(exc, InvalidQuote) else 'malformed_configuration'
    return row


def summarize(rows: list[dict]) -> dict:
    expected = {(s, b) for s in range(SLOTS) for b in BUDGETS}
    if len(rows) != len(expected) or {(r['slot'], r['budget_usd']) for r in rows} != expected:
        raise ValueError('incomplete_or_duplicate_denominator')
    groups = {}
    for budget in BUDGETS:
        subset = [r for r in rows if r['budget_usd'] == budget]
        valid = [r for r in subset if r['status'] == 'conditional_quote_valid']
        values = sorted(generated_fraction(r['conditional_proxy_exact']) for r in valid)
        median = None
        if values:
            n = len(values)
            median = float(values[n//2] if n % 2 else (values[n//2-1]+values[n//2])/2)
        groups[str(budget)] = {
            'scheduled': SLOTS, 'valid': len(valid), 'invalid': SLOTS-len(valid),
            'invalid_reasons': dict(Counter(r['status'] for r in subset if r['status'] != 'conditional_quote_valid')),
            'conditional_proxy_positive': sum(x > 0 for x in values),
            'conditional_proxy_median_usd': median,
            'conditional_proxy_max_usd': float(values[-1]) if values else None,
        }
    decisions = [r for r in rows if r['primary_decision']]
    if {(r['slot'], r['budget_usd']) for r in decisions} != {(s, 1000) for s in DECISIONS}:
        raise ValueError('primary_decision_identity')
    positive = [r for r in decisions if r['conditional_proxy_usd'] is not None
                and generated_fraction(r['conditional_proxy_exact']) > 0]
    return {
        'schema': 'dated-carry-quote-summary-v1', 'scheduled_rows': len(rows),
        'groups': groups, 'primary_decisions': decisions,
        'conditional_prerequisite': {
            'coverage_80pct': groups['1000']['valid'] * 5 >= SLOTS * 4,
            'positive_decisions': len(positive),
            'positive_days': len({r['slot']//288 for r in positive}),
        },
        'all_cost_feasibility_gate': 'unresolved', 'unresolved': UNRESOLVED,
        'all_in_headroom_usd': None, 'closed_net_usd': None,
        'private_execution_verified': False, 'automatic_successor': False,
        'interpretation': 'Conditional entry-price/fee/capital proxies only; missing future cashflows are not zero.',
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    print(json.dumps({'mode': 'dry', 'slots': SLOTS, 'budgets': BUDGETS,
                      'rows': SLOTS*len(BUDGETS), 'decision_slots': DECISIONS,
                      'all_in_economics': 'unresolved'}, sort_keys=True))
