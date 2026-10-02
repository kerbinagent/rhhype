#!/usr/bin/env python3
"""Bounded exploratory passive-PERP strict-print conditional cash scanner.

Public placement proxies and trade-through witnesses never authenticate orders.
No predictor, queue simulation, cancellation ledger or actual strategy P&L.
"""
from collections import Counter, defaultdict
from contextlib import contextmanager
from decimal import Decimal as D, getcontext
from pathlib import Path
import datetime, gzip, hashlib, platform, sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import single_venue_queue_ofi as q

ordinary, inventory, rolling = q.ordinary, q.inventory, q.rolling
NS = q.NS
PLAN = ROOT / 'reports/experiment-storage/single-venue-passive-through-v1.json'
HELPER_SHA = 'b549671eede741992df7d47dddb9247278b308f2775facb515c66de15014ff96'
PREVIOUS_SHA = '485213e9cc671344d228724ee3be1462e91de352156bb8ffbf0bd2de7fc0e881'
INPUT_PROVENANCE = 'reports/single-venue-research/queue-ofi-publication-fix-v1/provenance.json'
INPUT_PROVENANCE_SHA = 'e3c3220f97c70226b9c48cd7340af497deddce59d0d384d96bdd07df73458100'
FIRST, SECOND = q.FIT, q.EVALUATION
PARAMS = dict(assets=list(q.ASSETS), venues=list(q.VENUES), directions=[1, -1],
    anchor_start_seconds=30, anchor_stop_seconds_inclusive=570, anchor_step_seconds=20,
    entry_delay_ns=400000000, fixed_exit_request_after_ns=10000000000,
    exit_delay_ns=400000000, max_execution_lateness_ns=2000000000,
    maximum_profile_span_ns=12400000000, book_age_ns=250000000,
    max_interbook_gap_ns=500000000, max_trade_age_ns=500000000,
    notionals=['100', '1000', '10000'], sizing_headroom='1.01', annual_capital_rate='0.05',
    year_seconds=31536000, extra_cost_stress_bps=[1, 2, 5],
    minimum_witnessed_anchors_per_chunk=3, max_decoded_bytes_per_chunk=1073741824,
    max_records_per_chunk=1000000, max_ids_per_chunk=500000,
    max_same_receipt_events=10000, max_profiles_per_chunk=3360)
CAPS = dict(source=65536, tests=32768, protocol=32768, gzip_per_chunk=524288,
    decoded_per_chunk=16777216, summary_gzip=131072, summary_decoded=4194304,
    readout=32768, provenance=32768, control=16384)
ACTIVE = {'pending_proxy', 'searching_witness', 'pending_close'}
ASSUMPTIONS = dict(acceptance='unverified', live_order='unverified',
    post_only_acknowledgment='unverified', exact_fill_time='unknown',
    earlier_same_price_fills='possible', account_margin_and_dynamic_mark_checks='unverified',
    expiry_and_cancellation='unverified', unchanged_aggressive_flow='assumed',
    action_delay='fixed_400ms_model_scenario_not_measured_acknowledgment',
    Core_priority='documented_price_time_and_maker_price',
    RH_priority='unverified_price_priority_and_maker_price_venue_model_assumptions')


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def publish(path, value, cap, *, compressed=False, decoded_cap=None):
    return q.publish(path, value, cap, compressed=compressed, decoded_cap=decoded_cap)


def verify():
    plan = rolling.read_json(PLAN, CAPS['protocol'])
    if plan.get('status') != 'frozen':
        raise ValueError('passive_protocol_not_frozen')
    if (plan.get('schema') != 'single-venue-passive-through-v1'
            or plan.get('parameters') != PARAMS or plan.get('output_caps') != CAPS):
        raise ValueError('frozen_passive_specification_differs')
    if (plan.get('first_stage_chunks') != list(FIRST)
            or plan.get('conditional_second_stage_chunks') != list(SECOND)
            or plan.get('output_root') != 'reports/single-venue-research/passive-through-v1'
            or plan.get('store_root') != 'data/rolling/market-research-v1'
            or plan.get('pin_owner') != 'inventory_context_v1'
            or plan.get('reserved_bytes') != 4194304):
        raise ValueError('fixed_paths_chunks_or_allocation_differ')
    if (plan.get('runtime_requirements') != {'python': '3.13.9', 'decimal_precision': 28}
            or platform.python_version() != '3.13.9' or getcontext().prec != 28):
        raise ValueError('frozen_passive_runtime_differs')
    paths = [pin['path'] for pin in plan.get('source_pins', [])]
    required = {'scripts/single_venue_passive_through.py',
                'tests/test_single_venue_passive_through.py', 'scripts/single_venue_queue_ofi.py'}
    if len(paths) != len(set(paths)) or not required.issubset(paths):
        raise ValueError('unique_own_test_helper_pins_required')
    q.source_pins(plan['source_pins'])
    for relative, cap in (('scripts/single_venue_passive_through.py', CAPS['source']),
                          ('tests/test_single_venue_passive_through.py', CAPS['tests'])):
        if (ROOT / relative).stat().st_size > cap:
            raise ValueError('own_source_or_test_byte_cap')
    if (plan.get('helper_source') != 'scripts/single_venue_queue_ofi.py'
            or plan.get('helper_source_sha256') != HELPER_SHA
            or q.digest(ROOT / plan['helper_source']) != HELPER_SHA):
        raise ValueError('frozen_helper_changed')
    if (plan.get('previous') != 'reports/experiment-storage/single-venue-queue-ofi-publication-fix-v1.json'
            or plan.get('previous_sha256') != PREVIOUS_SHA
            or q.digest(ROOT / plan['previous']) != PREVIOUS_SHA):
        raise ValueError('frozen_previous_plan_changed')
    if (plan.get('input_validation_plan') != 'reports/experiment-storage/single-venue-inventory-context-ordinary-feed-fix-v1.json'
            or plan.get('input_validation_plan_sha256') != q.VALIDATION_SHA):
        raise ValueError('validation_identity_differs')
    frozen = plan.get('frozen_input_identities', {})
    if (frozen.get('provenance_path') != INPUT_PROVENANCE
            or frozen.get('provenance_sha256') != INPUT_PROVENANCE_SHA
            or q.digest(ROOT / INPUT_PROVENANCE) != INPUT_PROVENANCE_SHA
            or set(frozen.get('snapshot', {})) != {'1', '2'}):
        raise ValueError('frozen_input_provenance_changed')
    # Original helper verification rechecks its frozen method, runtime, own
    # direct pins, the original capture plan and all 45 validation dependencies.
    _, validation = q.verify()
    return plan, validation


@contextmanager
def adapter_configuration():
    # The helper scopes original adapter bounds and raw snapshot identity.
    # This outer hook preserves both decimal fields after its ordinary checks.
    with q.adapter_configuration():
        previous = ordinary._trade
        def exact_trade(row, raw, *args, **kwargs):
            event = previous(row, raw, *args, **kwargs)
            price, qty = q.number(raw['price']), q.number(raw['size'])
            if price <= 0 or qty <= 0:
                raise ValueError('invalid_exact_print')
            return dict(event, price=str(price), qty=str(qty), exact_native_print=True)
        try:
            ordinary._trade = exact_trade
            yield
        finally:
            ordinary._trade = previous


def constraints(market, qty, value):
    step, minimum = q.number(market['qty_step']), q.number(market['min_qty'])
    if step <= 0 or minimum <= 0 or not q.grid(qty, step) or qty < minimum:
        return 'native_minimum_quantity_reject'
    min_value = q.number(market['min_notional'])
    if min_value < 0 or value < min_value:
        return 'native_minimum_notional_reject'
    maximum = market.get('max_qty')
    if maximum is not None:
        maximum = q.number(maximum)
        if maximum <= 0 or qty > maximum:
            return 'maximum_quantity_reject'
    maximum = market.get('max_quote')
    if maximum is not None:
        maximum = q.number(maximum)
        if maximum <= 0 or value > maximum:
            return 'maximum_quote_reject'
    return None


def fee_rates(market):
    rates = [q.number(market[k]) / 10000 for k in ('maker_fee_bps', 'taker_fee_bps')]
    if any(x < 0 for x in rates):
        raise ValueError('negative_fee_metadata')
    return rates


def funding_crosses(now):
    return (now // (3600 * NS) + 1) * (3600 * NS) <= now + PARAMS['maximum_profile_span_ns']


class Study:
    """Isolated bounded calendar observations, never an inventory ledger."""
    def __init__(self, metadata, start, chunk, *, assets=None):
        self.metadata, self.start, self.chunk = metadata, start, chunk
        self.assets = tuple(PARAMS['assets'] if assets is None else assets)
        self.books = {}
        self.pending = defaultdict(list)
        self.rows = []
        self.counts = Counter()
        self.next_anchor = start + PARAMS['anchor_start_seconds'] * NS
        self.last_group = None
        self.seen_ids = set()
        self.profile_count = 0

    def fail(self, profile, reason):
        if profile['status'] not in ACTIVE:
            return
        profile.update(failed_stage=profile['status'], status=reason,
                       cash_status='unknown', net_cash=None)

    def fail_key(self, key, reason, *, trade_only=False):
        for row in self.pending[key]:
            for profile in row['profiles']:
                if trade_only and profile['witness'] is not None:
                    continue
                self.fail(profile, reason)

    def anchor(self, now):
        slot = (now - self.start - PARAMS['anchor_start_seconds'] * NS) // (PARAMS['anchor_step_seconds'] * NS)
        for asset in self.assets:
            for venue in PARAMS['venues']:
                key = (asset, venue)
                book = self.books.get(key)
                market = self.metadata.get(venue, {}).get(asset)
                failure, bbo = None, None
                if funding_crosses(now):
                    failure = 'funding_boundary_excluded'
                elif market is None:
                    failure = 'decision_metadata_missing'
                elif book is None:
                    failure = 'decision_book_missing'
                elif not q.fresh(book, now, PARAMS['book_age_ns']):
                    failure = 'decision_book_stale'
                else:
                    try:
                        bbo = q.native_book(book, market)
                    except (ValueError, KeyError, IndexError):
                        failure = 'decision_native_book_failure'
                row = dict(chunk=self.chunk, slot=slot, asset=asset, venue=venue,
                    collateral='USDC' if venue == 'lighter' else 'USDG', decision_ns=now,
                    eligibility_ns=now + PARAMS['entry_delay_ns'],
                    exit_request_ns=now + PARAMS['fixed_exit_request_after_ns'],
                    exit_due_ns=now + PARAMS['fixed_exit_request_after_ns'] + PARAMS['exit_delay_ns'],
                    decision_failure=failure, generation=None if book is None else book['generation'],
                    decision_book=None if book is None else {k: book[k] for k in ('received_ns', 'source_ns', 'generation')},
                    placement_proxy=None, profiles=[])
                for target in PARAMS['notionals']:
                    N = q.number(target)
                    qty = None
                    if failure is None:
                        try:
                            qty = q.quantity(market, book, N)
                        except (ValueError, KeyError, ArithmeticError):
                            qty = None
                    for direction in PARAMS['directions']:
                        reason = failure
                        limit = None if bbo is None else bbo[0 if direction == 1 else 2]
                        value = None if qty is None or limit is None else qty * limit
                        rates = None
                        if reason is None:
                            try:
                                if qty is None:
                                    reason = 'decision_quantity_metadata_failure'
                                else:
                                    reason = constraints(market, qty, value)
                                    if reason is None and value > N:
                                        reason = 'entry_quote_above_target_cap'
                                    rates = fee_rates(market)
                            except (ValueError, KeyError, ArithmeticError):
                                reason = 'decision_native_or_fee_metadata_failure'
                        profile = dict(target=target, direction=direction,
                            quantity=None if qty is None else str(qty),
                            limit=None if limit is None else str(limit),
                            entry_value=None if value is None else str(value),
                            fee_rates=None if rates is None else [str(x) for x in rates],
                            maximum_base_quantity_unknown=bool(market is None or market.get('max_qty') is None),
                            maximum_quote_unknown=bool(market is None or market.get('max_quote') is None),
                            status='pending_proxy' if reason is None else reason,
                            cash_status='unknown', net_cash=None, witness=None,
                            smaller_through_count=0, first_smaller_through=None)
                        row['profiles'].append(profile)
                self.profile_count += len(row['profiles'])
                if self.profile_count > PARAMS['max_profiles_per_chunk']:
                    raise ValueError('profile_count_cap')
                self.rows.append(row)
                if any(p['status'] in ACTIVE for p in row['profiles']):
                    self.pending[key].append(row)

    def fire(self, now, *, inclusive=False):
        stop = self.start + PARAMS['anchor_stop_seconds_inclusive'] * NS
        while self.next_anchor <= stop and (self.next_anchor < now or inclusive and self.next_anchor == now):
            self.anchor(self.next_anchor)
            self.next_anchor += PARAMS['anchor_step_seconds'] * NS

    def advance(self, now):
        for key, rows in self.pending.items():
            for row in rows:
                for profile in row['profiles']:
                    stage = profile['status']
                    if stage == 'pending_proxy' and now > row['eligibility_ns'] + PARAMS['max_execution_lateness_ns']:
                        self.fail(profile, 'placement_first_eligible_missing')
                    elif stage == 'searching_witness' and now >= row['exit_request_ns']:
                        self.fail(profile, 'smaller_through_only_unknown' if profile['smaller_through_count'] else 'no_full_witness_unknown')
                    elif stage == 'pending_close' and now > row['exit_due_ns'] + PARAMS['max_execution_lateness_ns']:
                        self.fail(profile, 'close_first_eligible_missing')
            self.pending[key] = [row for row in rows if any(p['status'] in ACTIVE for p in row['profiles'])]

    def book(self, event):
        now = event['received_ns']
        key = event['asset'], event['venue']
        market = self.metadata[key[1]][key[0]]
        self.books[key] = event
        checked, bbo, native_failure = False, None, None
        for row in self.pending[key]:
            for profile in row['profiles']:
                stage = profile['status']
                if stage not in ('pending_proxy', 'pending_close'):
                    continue
                due = row['eligibility_ns'] if stage == 'pending_proxy' else row['exit_due_ns']
                if now < due or event['source_ns'] < due:
                    continue
                if now > due + PARAMS['max_execution_lateness_ns']:
                    self.fail(profile, 'placement_first_eligible_missing' if stage == 'pending_proxy' else 'close_first_eligible_missing')
                    continue
                if not checked:
                    checked = True
                    try:
                        bbo = q.native_book(event, market)
                    except (ValueError, KeyError, IndexError):
                        native_failure = 'endpoint_native_book_failure'
                if native_failure:
                    self.fail(profile, native_failure)
                    continue
                endpoint = {k: event[k] for k in ('received_ns', 'source_ns', 'generation')}
                if stage == 'pending_proxy':
                    row['placement_proxy'] = endpoint
                    limit = q.number(profile['limit'])
                    crossed = limit >= bbo[2] if profile['direction'] == 1 else limit <= bbo[0]
                    if crossed:
                        self.fail(profile, 'placement_crossed_proxy_unknown')
                    else:
                        profile['status'] = 'searching_witness'
                else:
                    profile['exit_observation'] = endpoint
                    try:
                        qty, N = q.number(profile['quantity']), q.number(profile['target'])
                        value, reason = q.quote_value(event, market, qty, -profile['direction'], N, entry=False)
                        if reason is None:
                            reason = constraints(market, qty, value)
                        if reason:
                            self.fail(profile, reason)
                            continue
                        maker, taker = fee_rates(market)
                        entry = q.number(profile['entry_value'])
                        gross = D(profile['direction']) * (value - entry)
                        fees = entry * maker + value * taker
                        capital = N * q.number(PARAMS['annual_capital_rate']) * D(now - row['eligibility_ns']) / (NS * PARAMS['year_seconds'])
                        net = gross - fees - capital
                        profile.update(status='complete_conditional_value', cash_status='conditional_value',
                            exit_value=str(value), gross_cash=str(gross), fee_cash=str(fees),
                            capital_cash=str(capital), net_cash=str(net), net_bps=str(net / entry * 10000),
                            stressed_cash={str(bp): str(net - entry * D(bp) / 10000) for bp in PARAMS['extra_cost_stress_bps']})
                    except (ValueError, KeyError, ArithmeticError):
                        self.fail(profile, 'close_native_or_fee_metadata_failure')

    def trade(self, event):
        key = event['asset'], event['venue']
        ident = (key, event['generation'], event['trade_id'])
        if ident in self.seen_ids:
            self.counts['duplicate_print_ignored'] += 1
            return
        if len(self.seen_ids) >= PARAMS['max_ids_per_chunk']:
            raise ValueError('scanner_trade_id_cap')
        self.seen_ids.add(ident)
        now, source = event['received_ns'], event['source_ns']
        try:
            market = self.metadata[key[1]][key[0]]
            price, qty = q.number(event['price']), q.number(event['qty'])
            if not event.get('exact_native_print') or not q.grid(price, q.number(market['price_tick'])) or not q.grid(qty, q.number(market['qty_step'])):
                self.counts['non_native_or_inexact_print'] += 1
                return
        except (ValueError, KeyError, ArithmeticError):
            self.counts['non_native_or_inexact_print'] += 1
            return
        for row in self.pending[key]:
            proxy = row['placement_proxy']
            if (proxy is None or event['generation'] != row['generation']
                    or not event.get('clock_valid') or not isinstance(source, int)
                    or not proxy['received_ns'] < source <= now
                    or not proxy['received_ns'] < now < row['exit_request_ns']
                    or now - source > PARAMS['max_trade_age_ns']):
                continue
            for profile in row['profiles']:
                if profile['status'] != 'searching_witness':
                    continue
                limit = q.number(profile['limit'])
                through = (not event['buy_aggressor'] and price < limit) if profile['direction'] == 1 else (event['buy_aggressor'] and price > limit)
                if not through:
                    continue
                observed = dict(trade_id=event['trade_id'], price=str(price), quantity=str(qty),
                    buy_aggressor=event['buy_aggressor'], received_ns=now, source_ns=source,
                    generation=event['generation'])
                if qty < q.number(profile['quantity']):
                    profile['smaller_through_count'] += 1
                    if profile['first_smaller_through'] is None:
                        profile['first_smaller_through'] = observed
                    continue
                profile.update(witness=observed, status='pending_close',
                    conditional_full_quantity=profile['quantity'],
                    fill_time_status='unknown_executed_by_witness_under_assumptions')

    def process_group(self, group):
        if not group:
            return
        if len(group) > PARAMS['max_same_receipt_events']:
            raise ValueError('same_receipt_group_cap')
        now = group[0]['received_ns']
        if any(e['received_ns'] != now for e in group) or self.last_group is not None and now < self.last_group:
            raise ValueError('receipt_group_order')
        self.fire(now)
        self.advance(now)
        blocked_books, blocked_trades = set(), set()
        previous = dict(self.books)
        # Prepass: every same-clock invalidation and path breach dominates all
        # existing obligations, irrespective of raw event order in this group.
        for event in group:
            key = event.get('asset'), event.get('venue')
            if key[0] not in self.metadata.get(key[1], {}):
                continue
            kind = event['type']
            if kind == 'invalidate':
                scope = event['scope']
                self.counts['invalidate:' + scope + ':' + str(event.get('reason'))] += 1
                if scope == 'trade':
                    self.fail_key(key, 'trade_path_unresolved', trade_only=True)
                    blocked_trades.add(key)
                else:
                    self.fail_key(key, 'book_path_unresolved')
                    blocked_books.add(key)
                    self.books.pop(key, None)
                continue
            if kind != 'book':
                continue
            old = previous.get(key)
            reason = None
            try:
                q.native_bbo(event, self.metadata[key[1]][key[0]])
                if not q.fresh(event, now, PARAMS['book_age_ns']):
                    reason = 'book_path_stale_clock'
            except (ValueError, KeyError, IndexError):
                reason = 'book_path_native_bbo_failure'
            if reason is None and event.get('book_snapshot'):
                reason = 'book_path_snapshot_reset'
            if reason is None and old is not None and old['generation'] != event['generation']:
                reason = 'book_path_generation_change'
            if reason is None and old is not None and now - old['received_ns'] > PARAMS['max_interbook_gap_ns']:
                reason = 'book_path_interbook_gap'
            if reason:
                self.fail_key(key, reason)
                self.counts[reason] += 1
                # Fresh snapshots and fresh books after a gap can initialize a
                # later independent observation; failed obligations stay failed.
                if reason in ('book_path_stale_clock', 'book_path_native_bbo_failure'):
                    blocked_books.add(key)
                    self.books.pop(key, None)
            previous[key] = event
        for event in group:
            key = event.get('asset'), event.get('venue')
            if key[0] not in self.metadata.get(key[1], {}):
                continue
            if event['type'] == 'book' and key not in blocked_books:
                self.book(event)
            elif event['type'] == 'trade' and key not in blocked_trades and key not in blocked_books:
                self.trade(event)
        if any(e['type'] == 'end' for e in group):
            for key in list(self.pending):
                self.fail_key(key, 'unresolved_at_capture_end')
        self.advance(now)
        self.fire(now, inclusive=True)
        self.last_group = now

    def result(self):
        expected = 28 * len(self.assets) * len(PARAMS['venues'])
        if len(self.rows) != expected or self.profile_count != expected * 6:
            raise ValueError('calendar_denominator_differs')
        if any(p['status'] in ACTIVE for r in self.rows for p in r['profiles']):
            raise ValueError('unresolved_active_scanner_state')
        return dict(chunk=self.chunk, scheduled_anchors=expected, scheduled_profiles=self.profile_count,
            assumptions=ASSUMPTIONS, all_calendar_strategy_cash=None, anchors=self.rows,
            scanner_counts=dict(self.counts))


def stream_chunk(record):
    directory = Path(record['capture'])
    metadata = rolling.read_json(directory / 'metadata/normalized.json', 131072)['markets']
    study = Study(metadata, record['started_ns'], record['chunk'])
    group, last, terminal = [], None, None
    with adapter_configuration():
        for event in ordinary.iter_events(directory,
                expected_manifest_sha256=record['manifest_sha256'], expected_raw_sha256=record['raw_sha256'],
                max_raw_bytes=inventory.RAW_CAP, max_decoded_bytes=PARAMS['max_decoded_bytes_per_chunk'],
                max_records=PARAMS['max_records_per_chunk'], max_ids=PARAMS['max_ids_per_chunk']):
            now = event['received_ns']
            if last is not None and now != last:
                study.process_group(group)
                group = []
            if len(group) >= PARAMS['max_same_receipt_events']:
                raise ValueError('same_receipt_group_cap')
            group.append(event)
            last = now
            if event['type'] == 'end':
                terminal = event
        study.process_group(group)
    if terminal is None or terminal['truncated'] or terminal['reason'] != 'duration_limit':
        raise ValueError('unverified_complete_capture')
    result = study.result()
    result['adapter'] = {k: terminal[k] for k in ('decoded_bytes', 'archive_bytes', 'counts',
        'metadata_sha256', 'raw_gzip_sha256', 'manifest_sha256', 'max_receipt_gap_ns')}
    return result


def summarize(chunks, *, stage):
    names = tuple(c['chunk'] for c in chunks)
    expected = FIRST if stage == 'first' else FIRST + SECOND
    if names != expected:
        raise ValueError('summary_chunk_identity_differs')
    indexed = {}
    for chunk in chunks:
        if chunk['scheduled_anchors'] != 560 or chunk['scheduled_profiles'] != 3360:
            raise ValueError('summary_calendar_denominator_differs')
        lookup = {}
        for row in chunk['anchors']:
            ident = row['asset'], row['venue'], row['slot']
            if ident in lookup or row['chunk'] != chunk['chunk']:
                raise ValueError('summary_duplicate_calendar_identity')
            lookup[ident] = row
        want = {(a, v, slot) for a in PARAMS['assets'] for v in PARAMS['venues'] for slot in range(28)}
        if set(lookup) != want:
            raise ValueError('summary_missing_calendar_identity')
        for row in lookup.values():
            identities = [(p['target'], p['direction']) for p in row['profiles']]
            if len(identities) != 6 or set(identities) != {(n, s) for n in PARAMS['notionals'] for s in PARAMS['directions']}:
                raise ValueError('summary_profile_identity_differs')
        indexed[chunk['chunk']] = lookup
    arms = []
    for asset in PARAMS['assets']:
        for venue in PARAMS['venues']:
            for target in PARAMS['notionals']:
                for direction in PARAMS['directions']:
                    arm = dict(asset=asset, venue=venue, target=target, direction=direction,
                        collateral='USDC' if venue == 'lighter' else 'USDG', chunks=[])
                    for name in names:
                        pairs = [(slot, next(p for p in indexed[name][asset, venue, slot]['profiles']
                            if p['target'] == target and p['direction'] == direction)) for slot in range(28)]
                        witnessed = [(slot, p) for slot, p in pairs if p['witness'] is not None]
                        complete = [p for _, p in pairs if p['status'] == 'complete_conditional_value']
                        if any(p['witness'] is None or p['net_cash'] is None for p in complete):
                            raise ValueError('conditional_complete_without_witness_or_cash')
                        statuses = Counter(p['status'] for _, p in pairs)
                        slots = [slot for slot, _ in witnessed]
                        identities = sorted({(p['witness']['generation'], p['witness']['trade_id'])
                                             for _, p in witnessed})
                        ids = [dict(generation=generation, trade_id=trade_id)
                               for generation, trade_id in identities]
                        cash = {k: str(sum((q.number(p[k]) for p in complete), D(0))) for k in ('gross_cash', 'fee_cash', 'capital_cash', 'net_cash')}
                        mean = None if not complete else q.number(cash['net_cash']) / len(complete)
                        passed = (len(slots) >= PARAMS['minimum_witnessed_anchors_per_chunk']
                            and len(complete) == len(witnessed) and mean is not None and mean > 0)
                        arm['chunks'].append(dict(chunk=name, scheduled=28, status_counts=dict(statuses),
                            smaller_through_anchors=sum(p['smaller_through_count'] > 0 for _, p in pairs),
                            full_witnesses=len(witnessed), witnessed_anchor_slots=slots,
                            distinct_witness_ids=ids, distinct_witness_count=len(ids),
                            full_witness_close_failures=len(witnessed) - len(complete),
                            complete_conditional_values=len(complete), conditional_complete_cash=cash,
                            conditional_mean_net_cash=None if mean is None else str(mean),
                            maximum_base_quantity_unknown=sum(p['maximum_base_quantity_unknown'] for _, p in pairs),
                            maximum_quote_unknown=sum(p['maximum_quote_unknown'] for _, p in pairs),
                            all_calendar_strategy_cash=None, gate=passed))
                    arm['first_stage_gate'] = all(x['gate'] for x in arm['chunks'][:3])
                    arm['all_six_gate'] = all(x['gate'] for x in arm['chunks']) if stage == 'final' else None
                    arms.append(arm)
    def identity(arm):
        return {k: arm[k] for k in ('asset', 'venue', 'target', 'direction')}
    first_passing = [identity(a) for a in arms if a['first_stage_gate']]
    final_passing = [identity(a) for a in arms if a['all_six_gate']]
    return dict(schema='single-venue-passive-through-summary-v1', stage=stage,
        processed_chunks=list(names), assumptions=ASSUMPTIONS, arms=arms,
        scheduled_profiles=3360 * len(chunks), first_stage_passing=first_passing,
        second_stage_open=bool(first_passing), all_six_passing=final_passing,
        unprocessed_chunks=list(SECOND) if stage == 'first' else [],
        all_calendar_strategy_cash=None,
        decision=('further_order_observability_research_only' if final_passing else
                  'conditional_second_stage_eligible' if stage == 'first' and first_passing else 'park_fixed_screen'),
        limitations='All inputs exploratory. Public proxy is not acceptance. Full quantity and cash are conditional, exact fill time unknown. Non-witness/partial cash and all-calendar strategy cash remain unknown. Sizes, simultaneous cells and adjacent chunks are dependent; native currencies and alternative arms are never summed.')


def run():
    plan, validation = verify()
    plan_hash = q.digest(PLAN)
    out = ROOT / plan['output_root']
    out.mkdir(parents=True, exist_ok=False)
    outputs, before = {}, None
    summary_bytes = control_bytes = 0
    def control(name, value):
        nonlocal control_bytes
        body = q.encode(value)
        if control_bytes + len(body) > CAPS['control']:
            raise ValueError('total_control_byte_cap')
        result = publish(out / name, value, CAPS['control'] - control_bytes)
        control_bytes += len(body)
        outputs[name] = result
        return result
    store = rolling.Store(ROOT / plan['store_root'])
    def snapshot():
        with store.locked():
            current = {str(batch): inventory.check_inputs(store, validation, batch) for batch in (1, 2)}
        if current != plan['frozen_input_identities']['snapshot']:
            raise ValueError('frozen_input_identities_changed')
        return current
    def recheck():
        verify()
        if q.digest(PLAN) != plan_hash or snapshot() != before:
            raise ValueError('frozen_source_or_input_changed')
    def save(name, value, *, summary=False):
        nonlocal summary_bytes
        recheck()
        cap = CAPS['summary_gzip'] - summary_bytes if summary else CAPS['gzip_per_chunk']
        decoded = CAPS['summary_decoded'] if summary else CAPS['decoded_per_chunk']
        outputs[name] = publish(out / name, value, cap, compressed=True, decoded_cap=decoded)
        if summary:
            summary_bytes += (out / name).stat().st_size
    opened = False
    barrier_sha = None
    try:
        before = snapshot()
        if tuple(r['chunk'] for r in before['1']['inputs']) != FIRST or tuple(r['chunk'] for r in before['2']['inputs']) != SECOND:
            raise ValueError('sealed_chunk_order_differs')
        recheck()
        control('started.json', dict(plan_sha256=plan_hash, started_utc=utc(), state='first_stage', no_retry=True))
        chunks = []
        for record in before['1']['inputs']:
            result = stream_chunk(record)
            result['plan_sha256'] = plan_hash
            save(record['chunk'] + '.json.gz', result)
            chunks.append(result)
        first = summarize(chunks, stage='first')
        first['plan_sha256'] = plan_hash
        save('first-stage-summary.json.gz', first, summary=True)
        first_sha = outputs['first-stage-summary.json.gz']
        opened = first['second_stage_open']
        recheck()
        barrier_sha = control('first-stage-sha.json', dict(plan_sha256=plan_hash,
            first_stage_summary_sha256=first_sha, second_stage_open=opened))
        # Re-read bounded immutable summary and barrier before any second decode.
        encoded = (out / 'first-stage-summary.json.gz').read_bytes()
        if len(encoded) > CAPS['summary_gzip'] or hashlib.sha256(encoded).hexdigest() != first_sha:
            raise ValueError('first_stage_summary_changed')
        with gzip.open(out / 'first-stage-summary.json.gz', 'rb') as handle:
            decoded = handle.read(CAPS['summary_decoded'] + 1)
        if len(decoded) > CAPS['summary_decoded']:
            raise ValueError('first_stage_summary_decoded_cap')
        import json
        sealed_first = json.loads(decoded)
        if sealed_first != first or q.digest(out / 'first-stage-sha.json') != barrier_sha:
            raise ValueError('first_stage_barrier_changed')
        if opened:
            for record in before['2']['inputs']:
                if q.digest(out / 'first-stage-summary.json.gz') != first_sha or q.digest(out / 'first-stage-sha.json') != barrier_sha:
                    raise ValueError('first_stage_barrier_changed')
                result = stream_chunk(record)
                result['plan_sha256'] = plan_hash
                save(record['chunk'] + '.json.gz', result)
                chunks.append(result)
            final = summarize(chunks, stage='final')
        else:
            final = dict(first, second_stage_status='second_stage_not_opened')
        final.update(plan_sha256=plan_hash, first_stage_summary_sha256=first_sha,
            first_stage_barrier_sha256=barrier_sha)
        save('summary.json.gz', final, summary=True)
        recheck()
        provenance = dict(schema='single-venue-passive-through-provenance-v1',
            plan_sha256=plan_hash, source_pins=plan['source_pins'],
            helper_source_sha256=HELPER_SHA, input_validation_plan_sha256=q.VALIDATION_SHA,
            inputs=before, outputs=dict(outputs), second_stage_open=opened,
            encoding='gzip UTF-8 JSON for tables/summaries; bounded decompression required',
            decoded_table_cap=CAPS['decoded_per_chunk'], decoded_summary_cap=CAPS['summary_decoded'],
            summary_total_on_disk_cap=CAPS['summary_gzip'], assumptions=ASSUMPTIONS)
        outputs['provenance.json'] = publish(out / 'provenance.json', provenance, CAPS['provenance'])
        recheck()
        control('terminal.json', dict(success=True, state='finished', ended_utc=utc(),
            plan_sha256=plan_hash, second_stage_open=opened, first_stage_barrier_sha256=barrier_sha,
            decision=final['decision'], output_count=len(outputs)))
    except Exception as exc:
        control('terminal.json', dict(success=False, state='finished', ended_utc=utc(),
            plan_sha256=plan_hash, second_stage_open=opened, first_stage_barrier_sha256=barrier_sha,
            error=type(exc).__name__ + ': ' + str(exc)[:2000]))
        raise


def main():
    if sys.argv[1:] != ['run']:
        raise SystemExit('usage: single_venue_passive_through.py run')
    run()


if __name__ == '__main__':
    main()
