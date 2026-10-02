#!/usr/bin/env python3
"""HIP-4 continuation live v1: one frozen match question's touch stream over one scheduled window.

Default is dry and performs no network I/O. A run needs the exact sha256 of a root-frozen plan
that names one target question from TARGETS. It reads outcomeMeta once before the window, holds
one public websocket with bbo for every member YES coin, one default l2Book falsifier on the
lowest named coin and outcomeMetaUpdates, then reads outcomeMeta again. Every frame sent or
received is retained in a capped gzip bundle; a cap, disconnect or liveness stop is a censored
prefix, never a failure to hide. The analysis evaluates the frozen static certificate on the
reconstructed touch state over server time with complete route cost. It makes no fill, fee,
precision, identity, settlement or profit claim.
Design: reports/hip4-research-continuation/live-v1-design.md
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import datetime as dt
from decimal import Decimal
import json
import multiprocessing
import os
from pathlib import Path
import re
import sys
import time
import zlib

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import hip4_continuation_books as b  # frozen parsers, cohort, meta check, REST pass

h, pm = b.h, b.pm
Refusal = pm.Refusal
digest, encoded, utc, bounded_read = pm.digest, pm.encoded, pm.utc, pm.bounded_read

PLAN = ROOT / 'reports/experiment-storage/hip4-continuation-live-v1.json'
SCHEMA = 'hip4-continuation-live-v1'
SOURCE = 'scripts/hip4_continuation_live.py'
TEST = 'tests/test_hip4_continuation_live.py'
PINNED = (SOURCE, TEST, b.SOURCE, h.SOURCE, h.HELPER)
PREVIOUS = b.PREVIOUS
OUT = 'reports/hip4-research-continuation/live-v1'
WS_URL = 'wss://api.hyperliquid.xyz/ws'
UTC = dt.timezone.utc
# scheduledStart hints of the 11 frozen match questions (raw 5a84b598...); a test re-derives them.
# They place the window only; they are not kickoff, end-of-play or resolution evidence.
TARGETS = {357: '2026-10-02T18:45', 358: '2026-10-02T18:45', 359: '2026-10-03T16:00',
           361: '2026-10-03T18:45', 362: '2026-10-03T18:45', 363: '2026-10-04T18:45',
           366: '2026-10-04T18:45', 367: '2026-10-04T18:45', 368: '2026-10-04T18:45',
           369: '2026-10-05T18:45', 370: '2026-10-05T18:45'}
OPEN_BEFORE_S, CLOSE_AFTER_S = 600, 7500         # window: hint-10 min to hint+125 min
LAUNCH_EARLIEST_S, LAUNCH_LATEST_S = 900, 120    # launch between open-15 min and open-2 min
META_LEAD_S = 60                                 # meta_pre at open-60 s, then connect
PING_S, LIVENESS_S, CONNECT_S = 30, 90, 10
FLUSH_S, FLUSH_BYTES, MAX_FRAME = 10, 32768, 262144
BUNDLE_CAP, RESERVE, RAW_LIMIT = 3670016, 524288, 67108864
PROJECTION_CAP, CONTROL_CAP, LIST_CAP, META_LIST_CAP = 65536, 16384, 50, 20
MIN_DURATION_MS, NEAR, PROBE_MIN = 1000, Decimal('0.001'), 100
SUPERVISOR_GRACE_S = 300
ZERO, ONE = b.ZERO, b.ONE
META_PAYLOAD = b'{"type":"outcomeMeta"}'
PING_PAYLOAD = b'{"method":"ping"}'
HEADER_KEYS = ('index', 'kind', 'label', 'wall_ms', 'mono_ns', 'sent_ms', 'sent_mono_ns',
               'http_status', 'code', 'declared_length', 'over_cap', 'body_bytes')
STOPS = ('window_closed', 'cap_reserve_reached', 'ws_closed', 'ws_error', 'liveness_lost',
         'ws_connect_failed', 'transport_failure', 'meta_pre_failed')
REQUEST_PLAN = {
    'rest': {'url': 'https://api.hyperliquid.xyz/info', 'payload': META_PAYLOAD.decode(),
             'reads': ['meta_pre at open-60 s', 'meta_post after the websocket closes (any stop after '
                       'meta_pre succeeded)'],
             'weight_each': 20, 'body_cap': b.META_CAP,
             'transport': 'frozen books-v1 fetch_all: one request each, no retry, redirect or proxy'},
    'websocket': {'url': WS_URL, 'connections': 1, 'reconnect': False, 'compression': False,
                  'proxies': False, 'max_frame_bytes': MAX_FRAME, 'connect_timeout_seconds': CONNECT_S,
                  'subscriptions': ['bbo for each member YES coin #<10*outcome>, members ascending',
                                    'l2Book {coin, no nSigFigs/mantissa/fast} for the lowest named member',
                                    'outcomeMetaUpdates'],
                  'ping': {'payload': PING_PAYLOAD.decode(), 'every_seconds': PING_S},
                  'liveness_stop_seconds': LIVENESS_S},
    'window': {'open': 'scheduledStart hint - 600 s', 'close': 'scheduledStart hint + 7500 s',
               'launch': 'between open - 900 s and open - 120 s, else refused'},
    'stops': list(STOPS),
    'retention': {'every_frame': 'sent and received frames, connection events, both REST bodies',
                  'members': 'gzip member every 10 s or 32768 raw bytes', 'cap': BUNDLE_CAP,
                  'reserve': RESERVE, 'cap_rule': 'stop reading once the bundle reaches cap - reserve; '
                  'the pending records, stop event and meta_post then fit; a stop is a censored prefix'},
}
ANALYSIS_PLAN = {
    'state': 'per coin, the latest bbo at or before t, applied in (server time, receipt) order with '
             'equal times applied together; unknown before the first bbo for that coin',
    'routes': {'forward': 'hold complete sets made at par by splitOutcome+negateOutcome (basis 1 per '
                          'unit); sell every member YES that has a bid; immediate cash = sum(bids) - 1; '
                          'closed (zero residual) only when every member including the fallback is sold; '
                          'otherwise unsold members are residual claims valued 0 until observable settlement',
               'inverse_full': 'buy every member YES at its ask, fallback included, then mergeQuestion; '
                               'closed cash = 1 - sum(asks); available only with every ask present'},
    'excursion': 'maximal run of positive route cash with all named states known',
    'qualifying_min_duration_ms': MIN_DURATION_MS, 'near_binding_margin': str(NEAR),
    'falsifier': 'l2Book top of the probe coin vs reconstructed bbo state at its server time; '
                 'two consecutive mismatches falsify the reconstruction',
    'park_probe_min_comparisons': PROBE_MIN,
    'arithmetic': 'exact decimal context (prec 120, Inexact and Rounded trapped)',
    'scope': 'recorded-vector bounds only: displayed touch, not takerability, fills, fees, '
             'conversion granularity, collateral identity or units',
}
OUTPUT_LIMITS = {'bundle_gzip': BUNDLE_CAP, 'projection': PROJECTION_CAP,
                 'claim_terminal_and_supervisor_receipts': CONTROL_CAP}


def hint(qid):
    return dt.datetime.fromisoformat(TARGETS[qid]).replace(tzinfo=UTC)


def window(qid):
    start = hint(qid)
    return {'hint': start, 'open': start - dt.timedelta(seconds=OPEN_BEFORE_S),
            'close': start + dt.timedelta(seconds=CLOSE_AFTER_S),
            'launch_from': start - dt.timedelta(seconds=OPEN_BEFORE_S + LAUNCH_EARLIEST_S),
            'launch_until': start - dt.timedelta(seconds=OPEN_BEFORE_S + LAUNCH_LATEST_S),
            'meta_pre_at': start - dt.timedelta(seconds=OPEN_BEFORE_S + META_LEAD_S)}


def ms(moment):
    return int(moment.timestamp() * 1000)


def layout(cohort, qid):
    q = cohort[qid]
    named = [m for m in q['members'] if m != q['fallback']]
    coins = {f'#{10 * m}': m for m in q['members']}
    probe = f'#{10 * named[0]}'
    subs = [{'type': 'bbo', 'coin': coin} for coin in coins]
    subs += [{'type': 'l2Book', 'coin': probe}, {'type': 'outcomeMetaUpdates'}]
    payloads = [json.dumps({'method': 'subscribe', 'subscription': s}, separators=(',', ':')).encode()
                for s in subs]
    return {'question': qid, 'fallback': q['fallback'], 'named': named, 'coins': coins,
            'fallback_coin': f"#{10 * q['fallback']}", 'probe': probe, 'subs': subs, 'payloads': payloads}


def verify(plan_sha256):
    if not isinstance(plan_sha256, str) or not re.fullmatch('[0-9a-f]{64}', plan_sha256):
        raise Refusal('expected_plan_sha_required')
    try:
        raw = bounded_read(PLAN, 65536)
    except OSError:
        raise Refusal('plan_unreadable') from None
    if digest(raw) != plan_sha256:
        raise Refusal('plan_sha_mismatch')
    p = pm.strict_json(raw)
    if not isinstance(p, dict) or p.get('schema') != SCHEMA:
        raise Refusal('plan_schema')
    if p.get('status') != 'frozen_live_window':
        raise Refusal('plan_not_frozen')
    for key, expected in (('request_plan', REQUEST_PLAN), ('analysis_plan', ANALYSIS_PLAN),
                          ('output_limits_bytes', OUTPUT_LIMITS)):
        if encoded(p.get(key)) != encoded(expected):
            raise Refusal(f'{key}_changed')
    if type(p.get('target_question')) is not int or p['target_question'] not in TARGETS:
        raise Refusal('target_not_allowed')
    if p.get('output_dir') != OUT or (ROOT / OUT).resolve() != ROOT.resolve() / OUT:
        raise Refusal('output_plan_changed')
    pins = p.get('source_pins')
    if not isinstance(pins, list) or len(pins) != len(PINNED) or sorted(
            pin.get('path') for pin in pins if isinstance(pin, dict)) != sorted(PINNED):
        raise Refusal('missing_source_pins')
    for pin in pins:
        path = ROOT / pin['path']
        if path.resolve() != ROOT.resolve() / pin['path']:
            raise Refusal('symlinked_source_pin')
        data = bounded_read(path, 262144)
        if type(pin.get('bytes')) is not int or len(data) != pin['bytes'] or digest(data) != pin.get('sha256'):
            raise Refusal('source_pin_mismatch')
    if p.get('previous') != PREVIOUS or digest(bounded_read(ROOT / PREVIOUS, 65536)) != p.get('previous_sha256'):
        raise Refusal('previous_plan_sha_mismatch')
    frozen = bounded_read(ROOT / b.FROZEN_META, h.PROJECTION_CAP)
    if digest(frozen) != b.FROZEN_META_SHA:
        raise Refusal('frozen_metadata_changed')
    return p, b.frozen_cohort(pm.strict_json(frozen))


def gzip_member(data):
    stream = zlib.compressobj(9, zlib.DEFLATED, 31)  # deterministic: no name, mtime 0
    return stream.compress(data) + stream.flush(zlib.Z_FINISH)


class Capture:
    """Progressive write-once bundle of framed records in complete gzip members."""

    def __init__(self, path, cap=None):
        self.path, self.cap = path, BUNDLE_CAP if cap is None else cap
        self.pending = path.with_name(path.name + '.pending')
        self.stream = self.pending.open('xb')
        self.size, self.count, self.buffer, self.flushed_at = 0, 0, bytearray(), time.monotonic()

    def add(self, kind, label, body, **fields):
        header = {k: None for k in HEADER_KEYS}
        header.update(fields, index=self.count, kind=kind, label=label, body_bytes=len(body))
        self.buffer += encoded(header) + body + b'\n'
        self.count += 1
        if len(self.buffer) >= FLUSH_BYTES:
            self.flush()
        return header['index']

    def due(self):
        return time.monotonic() - self.flushed_at >= FLUSH_S

    def flush(self):
        self.flushed_at = time.monotonic()
        if not self.buffer:
            return
        member = gzip_member(bytes(self.buffer))
        if self.size + len(member) > self.cap:
            raise Refusal('bundle_cap_breached')  # the reserve rule makes this unreachable
        self.stream.write(member)
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.size += len(member)
        self.buffer.clear()

    def reserve_reached(self):
        return self.size >= self.cap - RESERVE

    def finish(self):
        self.flush()
        self.stream.close()
        os.link(self.pending, self.path)  # atomic, refuses overwrite
        self.pending.unlink()
        return bounded_read(self.path, self.cap)


def parse_bundle(packed):
    records, rest, total = [], packed, 0
    while rest:
        inflater = zlib.decompressobj(31)
        try:
            data = inflater.decompress(rest, RAW_LIMIT - total + 1)
        except zlib.error:
            raise Refusal('bundle_not_gzip') from None
        total += len(data)
        if not inflater.eof or inflater.unconsumed_tail or total > RAW_LIMIT:
            raise Refusal('bundle_incomplete_or_over_limit')
        rest, pos = inflater.unused_data, 0
        if not data:
            raise Refusal('bundle_framing')
        while pos < len(data):
            end = data.find(b'\n', pos)
            header = pm.strict_json(data[pos:end + 1]) if end >= 0 else None
            if not isinstance(header, dict) or tuple(sorted(header)) != tuple(sorted(HEADER_KEYS)) \
                    or not h.uint(header['body_bytes']):
                raise Refusal('bundle_header')
            body = data[end + 1:end + 1 + header['body_bytes']]
            if len(body) != header['body_bytes'] or data[end + 1 + len(body):end + 2 + len(body)] != b'\n':
                raise Refusal('bundle_body_mismatch')
            records.append(dict(header, body=body))
            pos = end + 2 + len(body)
    return records


def validate_records(records, lay):
    """Fixed opening and closing order, consecutive indexes and monotone local clocks."""
    previous = 0
    for i, r in enumerate(records):
        if r['index'] != i or r['kind'] not in ('rest', 'event', 'out', 'in'):
            raise Refusal('record_order_invalid')
        if not h.uint(r['wall_ms']) or not h.uint(r['mono_ns']) or r['mono_ns'] < previous:
            raise Refusal('record_clock_invalid')
        if r['kind'] == 'rest' and not (h.uint(r['sent_mono_ns']) and r['sent_mono_ns'] >= previous
                                        and r['sent_mono_ns'] <= r['mono_ns'] and h.uint(r['sent_ms'])):
            raise Refusal('record_clock_invalid')
        previous = r['mono_ns']
    kinds = [(r['kind'], r['label']) for r in records]
    if not kinds or kinds[0] != ('rest', 'meta_pre'):
        raise Refusal('record_plan_mismatch')
    stops = [i for i, k in enumerate(kinds) if k == ('event', 'stop')]
    if len(stops) != 1:
        raise Refusal('record_plan_mismatch')
    stop = stops[0]
    reason = pm.strict_json(records[stop]['body']).get('reason')
    if reason not in STOPS:
        raise Refusal('record_plan_mismatch')
    tail = kinds[stop + 1:]
    if reason == 'meta_pre_failed':
        if stop != 1 or tail or records[0]['code'] is None:
            raise Refusal('record_plan_mismatch')
        return reason
    if records[0]['code'] is not None or tail != [('rest', 'meta_post')]:
        raise Refusal('record_plan_mismatch')
    body = kinds[1:stop]
    if not body or body == [('event', 'ws_open_failed')]:
        if reason != ('ws_connect_failed' if body else 'transport_failure'):
            raise Refusal('record_plan_mismatch')
        return reason
    if body[0] != ('event', 'ws_open') or reason == 'ws_connect_failed':
        raise Refusal('record_plan_mismatch')
    sent = 0
    while 2 + sent < stop and kinds[2 + sent] == ('out', 'subscribe'):
        sent += 1
    if [r['body'] for r in records[2:2 + sent]] != lay['payloads'][:sent]:
        raise Refusal('record_plan_mismatch')
    if sent < len(lay['payloads']) and (reason != 'transport_failure' or 2 + sent != stop):
        raise Refusal('record_plan_mismatch')
    for r in records[2 + sent:stop]:
        if not (r['kind'] == 'in' or (r['kind'], r['label'], r['body']) == ('out', 'ping', PING_PAYLOAD)):
            raise Refusal('record_plan_mismatch')
    return reason


def level(raw):
    if raw is None:
        return None
    if not isinstance(raw, dict) or sorted(raw) != ['n', 'px', 'sz'] or not h.uint(raw['n']) or raw['n'] < 1:
        raise ValueError('level_invalid')
    px, sz = b.decimal_text(raw['px']), b.decimal_text(raw['sz'])
    if not ZERO <= px <= ONE or sz <= ZERO:
        raise ValueError('level_out_of_range')
    return (px, sz, raw['n'])


def parse_bbo(data, coins):
    if not isinstance(data, dict) or data.get('coin') not in coins or not h.uint(data.get('time')):
        raise ValueError('bbo_invalid')
    pair = data.get('bbo')
    if not isinstance(pair, list) or len(pair) != 2:
        raise ValueError('bbo_invalid')
    bid, ask = level(pair[0]), level(pair[1])
    if bid and ask and bid[0] >= ask[0]:
        raise ValueError('bbo_crossed')
    return data['coin'], data['time'], bid, ask


def meta_relevance(data, lay):
    """Labels for updates touching the target question or its members; None marks unparsed."""
    labels, members = [], set(lay['coins'].values())
    for item in data if isinstance(data, list) else [data]:
        if not isinstance(item, dict) or len(item) != 1:
            return None
        (key, value), = item.items()
        if key == 'questionUpdated' and isinstance(value, dict):
            labels += ['question_updated'] if value.get('question') == lay['question'] else []
        elif key == 'questionSettled' and h.uint(value):
            labels += ['question_settled'] if value == lay['question'] else []
        elif key == 'outcomeSettled' and h.uint(value):
            labels += ['member_settled'] if value in members else []
        elif key != 'outcomeCreated':
            return None
    return labels


def scan(records, lay):
    """Parse every received frame; anomalies are counted, never dropped silently."""
    acks, anomalies = collections.Counter(), collections.Counter()
    bbo, probe, meta, pongs, last_time, echoes = [], [], [], 0, {}, {}
    max_server = None
    for r in records:
        if r['kind'] != 'in':
            continue
        if r['label'] != 'text':
            anomalies[f"frame_{r['label']}"] += 1
            continue
        try:
            obj = pm.strict_json(r['body'])
            channel, data = obj['channel'], obj.get('data')
        except Exception:
            anomalies['invalid_json'] += 1
            continue
        if channel == 'subscriptionResponse':
            sub = data.get('subscription') if isinstance(data, dict) else None
            match = [i for i, s in enumerate(lay['subs']) if isinstance(sub, dict) and data.get('method') == 'subscribe'
                     and all(sub.get(k) == v for k, v in s.items())
                     and all(k in s or k in ('nSigFigs', 'mantissa', 'fast') for k in sub)]
            if len(match) == 1:
                acks[match[0]] += 1
                extra = {k: sub[k] for k in sorted(sub) if k not in lay['subs'][match[0]]}
                if extra:
                    echoes[match[0]] = encoded(extra).decode().strip()[:200]
            else:
                anomalies['unexpected_ack'] += 1
        elif channel == 'bbo':
            try:
                coin, t, bid, ask = parse_bbo(data, lay['coins'])
            except (ValueError, Refusal) as exc:
                anomalies[f'bbo_invalid_{exc}'[:48]] += 1
                continue
            if t < last_time.get(coin, 0):
                anomalies['bbo_time_regression'] += 1
            last_time[coin] = t
            bbo.append((t, r['index'], coin, bid, ask))
            max_server = t if max_server is None else max(max_server, t)
        elif channel == 'l2Book':
            try:
                book = b.parse_book(data, lay['probe'])
            except (ValueError, Refusal):
                anomalies['l2book_invalid'] += 1
                continue
            top = lambda side: side[0] if side else None  # noqa: E731
            probe.append((book['time'], r['index'], top(book['bids']), top(book['asks'])))
            max_server = book['time'] if max_server is None else max(max_server, book['time'])
        elif channel == 'outcomeMetaUpdates':
            labels = meta_relevance(data, lay)
            if labels is None:
                anomalies['meta_update_unparsed'] += 1
            for label in labels or []:
                meta.append({'index': r['index'], 'wall_ms': r['wall_ms'], 'event': label})
        elif channel == 'pong':
            pongs += 1
        else:
            anomalies[f'channel_{str(channel)[:32]}'] += 1
    return {'acks': acks, 'anomalies': anomalies, 'bbo': bbo, 'probe': probe, 'meta': meta,
            'pongs': pongs, 'max_server_ms': max_server, 'echoes': echoes}


def route_cash(state, lay):
    """Exact per-unit cash for both routes at one reconstructed state, with full basis; forward cash is
    closed only when its residual list is empty."""
    named = [state.get(f'#{10 * m}') for m in lay['named']]
    if any(s is None for s in named):
        return None
    fb = state.get(lay['fallback_coin'])
    legs = [(lay['fallback_coin'], fb)] if fb is not None else []
    legs += [(f'#{10 * m}', s) for m, s in zip(lay['named'], named)]
    with b.exact():
        sold = [(coin, s[0]) for coin, s in legs if s[0] is not None]
        forward = {'cash': sum((px for _, (px, _, _) in sold), ZERO) - ONE, 'basis': ONE,
                   'units': min((sz for _, (_, sz, _) in sold), default=ZERO),
                   'residual': sorted(set(lay['coins']) - {coin for coin, _ in sold})}
        inverse = None
        if fb is not None and all(s[1] is not None for _, s in legs):
            asks = [s[1] for _, s in legs]
            inverse = {'cash': ONE - sum((a[0] for a in asks), ZERO), 'basis': sum((a[0] for a in asks), ZERO),
                       'units': min(a[1] for a in asks), 'residual': []}
    return {'forward': forward, 'inverse_full': inverse}


def timeline(events, lay):
    """Piecewise-constant states keyed by server time; equal times are applied together."""
    state, out = {}, []
    events = sorted(events, key=lambda e: (e[0], e[1]))
    i = 0
    while i < len(events):
        t = events[i][0]
        while i < len(events) and events[i][0] == t:
            _, index, coin, bid, ask = events[i]
            state[coin] = (bid, ask)
            i += 1
        out.append((t, dict(state), index))
    return out


def falsifier(probe, events, coin):
    """Compare each probe top with the reconstructed state of the same coin at its server time."""
    own = sorted((e for e in events if e[2] == coin), key=lambda e: (e[0], e[1]))
    result, streak, worst, j, current = collections.Counter(), 0, 0, 0, None
    for t, _, bid, ask in sorted(probe, key=lambda p: (p[0], p[1])):
        while j < len(own) and own[j][0] <= t:
            current = (own[j][3], own[j][4])
            j += 1
        if current is None:
            result['unknown'] += 1
            continue
        if current == (bid, ask):
            result['match'] += 1
            streak = 0
        else:
            result['mismatch'] += 1
            streak += 1
            worst = max(worst, streak)
    status = 'falsified' if worst >= 2 else 'not_falsified'
    return {'comparisons': result['match'] + result['mismatch'], 'match': result['match'],
            'mismatch': result['mismatch'], 'unknown': result['unknown'],
            'max_consecutive_mismatch': worst, 'status': status}


def excursions(states, lay, start_ms, end_ms):
    """Maximal positive-cash runs per route inside [start_ms, end_ms] of server time."""
    runs = {'forward': [], 'inverse_full': []}
    near_ms, covered, first_known, best = 0, 0, None, None
    bounds = [(start_ms, {}, None)] + [s for s in states if s[0] > start_ms]
    for t, state, index in states:
        if t <= start_ms:
            bounds[0] = (start_ms, state, index)  # the state in force when the window opens
    segments = []
    for k, (t, state, index) in enumerate(bounds):
        right = min(bounds[k + 1][0] if k + 1 < len(bounds) else end_ms, end_ms)
        if right > t:
            segments.append((t, right, state, index))
    open_run = {'forward': None, 'inverse_full': None}
    for left, right, state, index in segments:
        cash = route_cash(state, lay)
        if cash is not None:
            covered += right - left
            first_known = left if first_known is None else first_known
            with b.exact():
                if cash['forward']['cash'] >= -NEAR:
                    near_ms += right - left
            best = cash['forward']['cash'] if best is None else max(best, cash['forward']['cash'])
        for route in runs:
            leg = cash and cash[route]
            run = open_run[route]
            if leg is not None and leg['cash'] > ZERO:
                if run is None:
                    run = open_run[route] = {'start_ms': left, 'end_ms': right, 'max_cash': leg['cash'],
                                             'units_at_max': leg['units'], 'min_units': leg['units'],
                                             'basis_per_unit': leg['basis'], 'residual': leg['residual'],
                                             'start_index': index, 'states': 1}
                    runs[route].append(run)
                else:
                    run['end_ms'], run['states'] = right, run['states'] + 1
                    run['min_units'] = min(run['min_units'], leg['units'])
                    if leg['cash'] > run['max_cash']:
                        run.update(max_cash=leg['cash'], units_at_max=leg['units'], residual=leg['residual'],
                                   basis_per_unit=leg['basis'])
            else:
                open_run[route] = None
    for route, items in runs.items():
        for run in items:
            run['duration_ms'] = run['end_ms'] - run['start_ms']
            run['right_censored'] = run['end_ms'] >= end_ms
    return runs, {'covered_ms': covered, 'first_all_named_known_ms': first_known,
                  'forward_cash_ge_minus_near_ms': near_ms, 'max_forward_cash': best}


def analyze(records, cohort, qid, stop):
    lay = layout(cohort, qid)
    win = window(qid)
    rest = {r['label']: r for r in records if r['kind'] == 'rest'}
    meta = {label: b.meta_check(rest.get(label), cohort)[0][qid] for label in ('meta_pre', 'meta_post')}
    s = scan(records, lay)
    open_ms, close_ms, hint_ms = ms(win['open']), ms(win['close']), ms(win['hint'])
    end_ms = min(close_ms, s['max_server_ms']) if s['max_server_ms'] is not None else open_ms
    states = timeline(s['bbo'], lay)
    runs, coverage = excursions(states, lay, open_ms, max(end_ms, open_ms))
    probe = falsifier(s['probe'], s['bbo'], lay['probe'])
    acked = {p.decode(): s['acks'][i] for i, p in enumerate(lay['payloads'])}
    echoes = {lay['payloads'][i].decode(): v for i, v in sorted(s['echoes'].items())}
    meta_events = s['meta'][:META_LIST_CAP]
    first_meta = min((e['index'] for e in s['meta']), default=None)
    qualifying = {route: [r for r in items if r['duration_ms'] >= MIN_DURATION_MS
                          and (first_meta is None or r['start_index'] is None or r['start_index'] < first_meta)]
                  for route, items in runs.items()}
    censored = stop != 'window_closed'
    counts = collections.Counter(e[2] for e in s['bbo'])
    reasons = []
    if meta['meta_pre'] != 'unchanged':
        reasons.append('meta_pre_not_unchanged')
    if meta['meta_post'] != 'unchanged':
        reasons.append('meta_post_not_unchanged')
    if any(v != 1 for v in acked.values()):
        reasons.append('subscriptions_not_acked_once')
    if s['anomalies']:
        reasons.append('stream_anomalies')
    if s['meta']:
        reasons.append('target_meta_event')
    if probe['status'] == 'falsified':
        reasons.append('bbo_reconstruction_falsified')
    if probe['comparisons'] < PROBE_MIN:
        reasons.append('falsifier_underpowered')
    if coverage['first_all_named_known_ms'] is None or coverage['first_all_named_known_ms'] > hint_ms:
        reasons.append('named_state_unknown_at_hint')
    if censored:
        reasons.append(f'censored_{stop}')
    if end_ms < close_ms - 10000:
        reasons.append('server_time_short_of_close')
    candidate_gate = (meta['meta_pre'] == 'unchanged' and all(v == 1 for v in acked.values())
                      and probe['status'] != 'falsified' and not any(k.startswith('bbo') for k in s['anomalies']))
    if candidate_gate and (qualifying['forward'] or qualifying['inverse_full']):
        status = 'candidate_recorded_vector'
    elif not reasons:
        status = 'park_no_qualifying_excursion_in_window'
    else:
        status = 'inconclusive'
    def view(items, cap):
        return [{k: v for k, v in r.items() if k != 'start_index'} for r in items[:cap]]
    longest = lambda items: sorted(items, key=lambda r: (-r['duration_ms'], r['start_ms']))  # noqa: E731
    return {
        'schema': 'hip4-continuation-live-projection-v1', 'status': status, 'reasons': reasons,
        'question': qid, 'members': sorted(lay['coins'].values()), 'fallback': lay['fallback'],
        'probe_coin': lay['probe'], 'stop': stop, 'censored': censored,
        'window_ms': {'open': open_ms, 'hint': hint_ms, 'close': close_ms, 'server_end': end_ms},
        'meta': meta, 'meta_events': meta_events, 'meta_events_total': len(s['meta']),
        'subscription_acks': acked, 'ack_echo_extras': echoes, 'anomalies': dict(sorted(s['anomalies'].items())), 'pongs': s['pongs'],
        'bbo_events': {c: counts.get(c, 0) for c in sorted(lay['coins'])}, 'falsifier': probe,
        'coverage': coverage,
        'routes': {route: {'excursions': len(items), 'qualifying': len(qualifying[route]),
                           'max_cash': max((r['max_cash'] for r in items), default=None),
                           'total_positive_ms': sum(r['duration_ms'] for r in items),
                           'qualifying_runs': view(qualifying[route], LIST_CAP),
                           'longest_runs': view(longest(items), META_LIST_CAP)}
                   for route, items in runs.items()},
        'claim': 'recorded-vector bound on one capture of displayed touches: complete route basis, '
                 'residual claims valued 0 until observable settlement; zero fees optimistic; no '
                 'takerability, fill, conversion granularity, collateral identity, unit or profit claim; '
                 'a censored capture cannot prove a whole-window negative',
    }


def build_projection(records, cohort, qid, stop, plan_sha256, packed):
    projection = b.stringify(analyze(records, cohort, qid, stop))
    projection.update(plan_sha256=plan_sha256, bundle_sha256=digest(packed), records=len(records))
    return projection


def now_utc():
    return dt.datetime.now(UTC)


def sleep(seconds):
    time.sleep(max(0.0, seconds))


def mono_ns():
    return time.monotonic_ns()


def wall_ms():
    return time.time_ns() // 1000000


class RestSink:
    """Adapter so the frozen books-v1 fetch_all writes one REST record into the capture."""

    def __init__(self, capture, label):
        self.capture, self.label = capture, label

    def room_for(self, cap):
        return self.capture.size + len(self.capture.buffer) + cap + 4096 <= self.capture.cap

    def add(self, record, body):
        self.capture.add('rest', self.label, body, wall_ms=record['received_ms'],
                         mono_ns=record['received_mono_ns'], sent_ms=record['sent_ms'],
                         sent_mono_ns=record['sent_mono_ns'], http_status=record['http_status'],
                         code=record['code'], declared_length=record['declared_length'],
                         over_cap=record['over_cap'])


def rest_read(capture, label, receipt):
    item = {'index': 0, 'kind': 'meta', 'coin': None, 'payload': META_PAYLOAD}
    inner = {'stop': None, 'connections_opened': 0, 'requests_attempted': 0}
    b.fetch_all([item], RestSink(capture, label), [], inner, time.monotonic() + b.REQUEST_SECONDS + 5)
    receipt['rest_attempted'] += inner['requests_attempted']
    capture.flush()
    return inner['stop']


async def stream(capture, lay, close, receipt):
    import aiohttp
    stop = 'transport_failure'
    try:
        async with aiohttp.ClientSession(trust_env=False) as session:
            try:
                ws = await asyncio.wait_for(session.ws_connect(
                    WS_URL, autoping=True, heartbeat=None, max_msg_size=MAX_FRAME, compress=0), CONNECT_S)
            except Exception:
                capture.add('event', 'ws_open_failed', b'{}', wall_ms=wall_ms(), mono_ns=mono_ns())
                stop = 'ws_connect_failed'
                return stop
            receipt['ws_connections_opened'] += 1
            capture.add('event', 'ws_open', b'{}', wall_ms=wall_ms(), mono_ns=mono_ns())
            try:
                for payload in lay['payloads']:
                    await ws.send_str(payload.decode())
                    capture.add('out', 'subscribe', payload, wall_ms=wall_ms(), mono_ns=mono_ns())
                last_ping = last_in = time.monotonic()
                while True:
                    remaining = (close - now_utc()).total_seconds()
                    if remaining <= 0:
                        stop = 'window_closed'
                        break
                    if capture.reserve_reached():
                        stop = 'cap_reserve_reached'
                        break
                    if time.monotonic() - last_in > LIVENESS_S:
                        stop = 'liveness_lost'
                        break
                    if time.monotonic() - last_ping >= PING_S:
                        await ws.send_str(PING_PAYLOAD.decode())
                        capture.add('out', 'ping', PING_PAYLOAD, wall_ms=wall_ms(), mono_ns=mono_ns())
                        last_ping = time.monotonic()
                    if capture.due():
                        capture.flush()
                    wait = max(0.01, min(1.0, remaining, PING_S - (time.monotonic() - last_ping)))
                    try:
                        msg = await ws.receive(timeout=wait)
                    except asyncio.TimeoutError:
                        continue
                    kind = msg.type.name.lower()
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        body = msg.data.encode('utf-8')
                    elif msg.type == aiohttp.WSMsgType.BINARY:
                        body = bytes(msg.data)
                    else:
                        body = encoded({'data': repr(msg.data)[:256], 'extra': repr(msg.extra)[:256]})
                    capture.add('in', kind, body, wall_ms=wall_ms(), mono_ns=mono_ns())
                    receipt['frames_in'] += 1
                    if msg.type in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
                        last_in = time.monotonic()
                        continue
                    stop = 'ws_error' if msg.type == aiohttp.WSMsgType.ERROR else 'ws_closed'
                    break
            finally:
                try:
                    await asyncio.wait_for(ws.close(), CONNECT_S)
                except Exception:
                    pass  # a close error never relabels the stop already decided
    except Exception:
        stop = 'transport_failure'
    return stop


def publish(path, value, cap, controls=False):
    data = encoded(value)
    if len(data) > cap:
        raise Refusal('publication_byte_cap')
    if controls:
        used = sum(p.stat().st_size for p in path.parent.glob('*.json') if p.name != 'projection.json')
        if used + 2 * len(data) > CONTROL_CAP:
            raise Refusal('control_total_byte_cap')
    h.write_once(path, data)


def worker(plan_sha256, out):
    receipt = {'schema': 'hip4-continuation-live-terminal-v1', 'started_utc': utc(), 'plan_sha256': plan_sha256,
               'status': 'inconclusive', 'code': None, 'stop': None, 'target_question': None,
               'rest_attempted': 0, 'ws_connections_opened': 0, 'frames_in': 0, 'records': 0,
               'bundle_bytes': 0, 'bundle_sha256': None, 'projection_published': False}
    capture = None
    try:
        plan, cohort = verify(plan_sha256)
        qid = receipt['target_question'] = plan['target_question']
        lay, win = layout(cohort, qid), window(qid)
        capture = Capture(out / 'capture.bundle.gz')
        try:
            sleep((win['meta_pre_at'] - now_utc()).total_seconds())
            if rest_read(capture, 'meta_pre', receipt):
                stop = 'meta_pre_failed'
            else:
                stop = asyncio.run(stream(capture, lay, win['close'], receipt))
            capture.add('event', 'stop', encoded({'reason': stop}), wall_ms=wall_ms(), mono_ns=mono_ns())
            receipt['stop'] = stop
            if stop != 'meta_pre_failed':
                rest_read(capture, 'meta_post', receipt)
        finally:
            packed = capture.finish()
            receipt.update(bundle_bytes=len(packed), bundle_sha256=digest(packed), records=capture.count)
        verify(plan_sha256)
        parsed = parse_bundle(packed)  # analyze the retained bytes, not process memory
        reason = validate_records(parsed, lay)
        if reason != receipt['stop']:
            raise Refusal('stop_mismatch')
        projection = build_projection(parsed, cohort, qid, reason, plan_sha256, packed)
        verify(plan_sha256)
        publish(out / 'projection.json', projection, PROJECTION_CAP)
        receipt.update(projection_published=True, status=projection['status'])
    except Refusal as exc:
        receipt['code'] = str(exc)
    except Exception:
        receipt['code'] = 'internal_failure'
    finally:
        receipt['ended_utc'] = utc()
        try:
            verify(plan_sha256)
        except Exception:
            receipt.update(code='post_run_pin_check_failed', status='inconclusive')
        publish(out / 'terminal.json', receipt, 4096, controls=True)


def conclusion_checks(out, plan_sha256, finished):
    def read(path, cap):
        try:
            return pm.strict_json(bounded_read(path, cap))
        except Exception:
            return None
    terminal = read(out / 'terminal.json', 4096)
    projection = read(out / 'projection.json', PROJECTION_CAP)
    valid = (isinstance(terminal, dict) and terminal.get('schema') == 'hip4-continuation-live-terminal-v1'
             and terminal.get('plan_sha256') == plan_sha256)
    checks = {'worker_completed_exit_zero': finished,
              'terminal_without_failure': valid and terminal.get('code') is None
                                          and terminal.get('projection_published') is True,
              'bundle_matches_terminal': False, 'records_match_plan': False, 'projection_reproduced': False,
              'no_pending_publication': not any(out.glob('*.pending'))}
    try:
        plan, cohort = verify(plan_sha256)
        checks['final_plan_and_source_pins'] = True
    except Exception:
        plan = cohort = None
        checks['final_plan_and_source_pins'] = False
    try:
        packed = bounded_read(out / 'capture.bundle.gz', BUNDLE_CAP)
        checks['bundle_matches_terminal'] = (valid and len(packed) == terminal.get('bundle_bytes')
                                             and digest(packed) == terminal.get('bundle_sha256'))
        if cohort is not None:
            qid = plan['target_question']
            parsed = parse_bundle(packed)
            reason = validate_records(parsed, layout(cohort, qid))
            checks['records_match_plan'] = valid and reason == terminal.get('stop') \
                and len(parsed) == terminal.get('records')
            recomputed = build_projection(parsed, cohort, qid, reason, plan_sha256, packed)
            checks['projection_reproduced'] = (isinstance(projection, dict)
                                               and encoded(recomputed) == encoded(projection)
                                               and valid and projection.get('status') == terminal.get('status'))
    except Exception:
        pass
    return checks, terminal if valid else None


def supervise(process, deadline, out, plan_sha256):
    try:
        process.start()
        started = True
    except Exception:
        started = False
    timed_out = False
    if started:
        process.join(max(0, deadline - time.monotonic() - 0.5))
        timed_out = process.is_alive()
        if timed_out:
            process.kill()
            process.join(max(0, deadline - time.monotonic()))
    finished = started and not timed_out and process.exitcode == 0
    checks, terminal = conclusion_checks(out, plan_sha256, finished)
    eligible = all(checks.values())
    record = {'schema': 'hip4-continuation-live-supervisor-v1', 'plan_sha256': plan_sha256, 'ended_utc': utc(),
              'status': 'start_failed' if not started else 'process_deadline' if timed_out
              else 'worker_finished' if terminal else 'worker_failed_without_valid_terminal',
              'worker_exitcode': process.exitcode if started else None, 'checks': checks,
              'conclusion_eligible': eligible,
              'conclusion_status': terminal['status'] if eligible else 'inconclusive',
              'stop': terminal.get('stop') if terminal else None}
    publish(out / 'supervisor.json', record, 2048, controls=True)
    return record


def run(plan_sha256):
    plan, _ = verify(plan_sha256)
    win = window(plan['target_question'])
    now = now_utc()
    if not win['launch_from'] <= now <= win['launch_until']:
        raise Refusal('outside_launch_window')
    out = ROOT / OUT
    out.mkdir(parents=True, exist_ok=False)
    publish(out / 'claim.json', {
        'schema': 'hip4-continuation-live-claim-v1', 'started_utc': utc(), 'plan_sha256': plan_sha256,
        'source_sha256': digest(bounded_read(ROOT / SOURCE, 131072)), 'target_question': plan['target_question'],
        'window_utc': [win['open'].isoformat(), win['close'].isoformat()],
        'purpose': 'public_touch_stream_certificate_only'}, 2048, controls=True)
    deadline = time.monotonic() + (win['close'] - now).total_seconds() + SUPERVISOR_GRACE_S
    process = multiprocessing.get_context('fork').Process(target=worker, args=(plan_sha256, out))
    return supervise(process, deadline, out, plan_sha256)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--plan-sha256')
    parser.add_argument('--target', type=int, default=363)
    args = parser.parse_args(argv)
    if not args.run:
        if args.target not in TARGETS:
            parser.error('target must be one of the frozen match questions')
        cohort = b.frozen_cohort(pm.strict_json(bounded_read(ROOT / b.FROZEN_META, h.PROJECTION_CAP)))
        lay, win = layout(cohort, args.target), window(args.target)
        print(encoded({'status': 'dry_no_network', 'network_calls': 0, 'target_question': args.target,
                       'window_utc': [win['open'].isoformat(), win['close'].isoformat()],
                       'launch_utc': [win['launch_from'].isoformat(), win['launch_until'].isoformat()],
                       'subscriptions': [p.decode() for p in lay['payloads']],
                       'rest_reads': 2, 'rest_weight': 40, 'bundle_cap': BUNDLE_CAP}).decode(), end='')
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
    return 0 if result.get('conclusion_eligible') is True else 1


if __name__ == '__main__':
    raise SystemExit(main())
