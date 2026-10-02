#!/usr/bin/env python3
"""HIP-4 continuation live v1: one frozen match question's touch stream over one scheduled window.

Default is dry and performs no network I/O. A run needs the exact sha256 of a root-frozen plan
that names one target question from TARGETS. It reads outcomeMeta once before the window, holds
one public websocket with bbo for every member YES coin, one default l2Book probe on the
lowest named coin and outcomeMetaUpdates, then reads outcomeMeta again. Every delivered application
message, sent frame and connection event is retained in a capped gzip bundle; a cap, disconnect or
liveness stop is a censored prefix, never a failure to hide. The analysis replays receipts causally
in capture order behind frozen source-clock gates and screens supported paths with complete route
cost. It makes no fill, fee, precision, identity, settlement or profit claim.
Design: reports/hip4-research-continuation/live-v1-design.md
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import datetime as dt
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
PROJECTION_CAP, CONTROL_CAP, QUAL_CAP, LONG_CAP, META_LIST_CAP = 65536, 16384, 16, 8, 20
MIN_DURATION_MS, MS = 1000, 1000000
FUTURE_MS, STALE_MS, CARRY_MS = 250, 2000, 35000  # frozen source-clock gates; carried-state liveness
RAW_STOP = RAW_LIMIT - 1048576                    # live-only stop: pending, one frame, stop and meta_post still parse
SUPERVISOR_GRACE_S = 300
ZERO, ONE = b.ZERO, b.ONE
META_PAYLOAD = b'{"type":"outcomeMeta"}'
PING_PAYLOAD = b'{"method":"ping"}'
HEADER_KEYS = ('index', 'kind', 'label', 'wall_ms', 'mono_ns', 'sent_ms', 'sent_mono_ns',
               'http_status', 'code', 'declared_length', 'over_cap', 'body_bytes')
STOPS = ('window_closed', 'cap_reserve_reached', 'ws_closed', 'ws_error', 'liveness_lost',
         'ws_connect_failed', 'transport_failure', 'meta_pre_failed')
LIVE_STOPS = STOPS + ('raw_reserve_reached',)  # settle keeps the shared STOPS unchanged
ROUTES = ('forward', 'inverse_full')
DISPOSITIONS = ('forward_closed', 'forward_residual', 'inverse_full')
COVERAGE = ('censored', 'invalidated', 'initial', 'gap', 'supported')  # precedence: first match wins
ANOMALY_KEYS = frozenset((
    'frame_binary', 'frame_close', 'frame_closing', 'frame_closed', 'frame_error', 'invalid_json',
    'unexpected_ack', 'bbo_invalid', 'bbo_crossed', 'level_invalid', 'level_out_of_range',
    'decimal_invalid_or_unbounded', 'l2book_invalid', 'meta_update_unparsed', 'channel_unexpected', 'channel_error',
    'channel_invalid'))
REQUEST_PLAN = {
    'rest': {'url': 'https://api.hyperliquid.xyz/info', 'payload': META_PAYLOAD.decode(),
             'reads': ['meta_pre at open-60 s', 'meta_post after the websocket closes (any stop after '
                       'meta_pre succeeded)'],
             'weight_each': 20, 'body_cap': b.META_CAP,
             'transport': 'frozen books-v1 fetch_all: one request each, no retry, redirect or proxy'},
    'websocket': {'url': WS_URL, 'connections': 1, 'reconnect': False, 'redirects': False, 'compression': False,
                  'proxies': False, 'max_frame_bytes': MAX_FRAME, 'connect_timeout_seconds': CONNECT_S,
                  'subscriptions': ['bbo for each member YES coin #<10*outcome>, members ascending',
                                    'l2Book {coin, no nSigFigs/mantissa/fast} for the lowest named member',
                                    'outcomeMetaUpdates'],
                  'ping': {'payload': PING_PAYLOAD.decode(), 'every_seconds': PING_S},
                  'liveness_stop_seconds': LIVENESS_S},
    'window': {'open': 'scheduledStart hint - 600 s', 'close': 'scheduledStart hint + 7500 s',
               'launch': 'between open - 900 s and open - 120 s, else refused'},
    'stops': list(LIVE_STOPS),
    'retention': {'retained': 'every delivered application message, sent frame and connection event, and both '
                              'REST bodies; protocol ping/pong consumed by aiohttp autoping are not retained',
                  'members': 'gzip member every 10 s or 32768 raw bytes', 'cap': BUNDLE_CAP,
                  'reserve': RESERVE, 'raw_stop': RAW_STOP,
                  'cap_rule': 'stop reading once the bundle reaches cap - reserve or raw bytes reach raw_stop; '
                  'the pending records, stop event and meta_post then fit; a stop is a censored prefix'},
}
ANALYSIS_PLAN = {
    'state': 'one causal pass in capture (receipt) order: an accepted frame changes state at its own receipt; '
             'nothing is re-sorted, re-applied or backdated; bbo and the l2Book probe keep separate state',
    'clock': 'one wall/mono anchor at ws_open (meta_pre if never opened), never re-anchored, also used by the '
             'capture to end the window; window, liveness, qualification and invalidation are monotonic instants '
             'on half-open intervals',
    'gates': {'future_ms': FUTURE_MS, 'stale_ms': STALE_MS, 'key': '(channel, coin)',
              'rule': 'an identical equal-time repeat is ignored without refresh; a changed equal-time or regressed '
                      'source time, a future or stale frame, or an unusable update suspends the coin until its next '
                      'accepted frame'},
    'support': 'every named coin accepted and unsuspended; every required subscription acknowledged exactly once '
               'so far; an application message within carry_ms; before the first relevant meta receipt (target '
               'or member event, or any unparsed update) and before falsification; the fallback is traded only '
               'when supported, otherwise it is unsold residual; inverse_full needs every member supported with an ask',
    'carry_ms': CARRY_MS, 'carry_premise': 'unchanged-unless-pushed is an unverified change-feed premise',
    'probe': 'compared with the latest accepted probe-coin bbo received before it: unknown, superseded (bbo time '
             'later), match or mismatch; a compared mismatch suspends the probe coin until a later compared match '
             '(a new bbo alone does not restore it); two consecutive compared mismatches falsify; unknown and '
             'superseded probes leave the streak unchanged; a future, stale, order-failed or unusable probe '
             'suspends the probe coin until the next accepted probe',
    'unattributable': 'invalid JSON, a missing, non-string, empty, unexpected or error channel, a non-text frame '
                      'or a bbo without a coin suspends every member until its next accepted bbo',
    'meta_ids': 'questionUpdated needs uint question and fallbackOutcome and uint lists namedOutcomes and '
                'settledNamedOutcomes; outcomeCreated needs a uint outcome; settled ids are uint; otherwise '
                'unparsed, which invalidates',
    'routes': {'forward': 'hold complete sets made at par by splitOutcome+negateOutcome (basis 1 per '
                          'unit); sell every supported member YES that has a bid; immediate cash = sum(bids) - 1; '
                          'forward_closed (zero residual) only when every member including the fallback is sold; '
                          'otherwise forward_residual, unsold members valued 0 until observable settlement',
               'inverse_full': 'buy every member YES at its ask, fallback included, then mergeQuestion; '
                               'closed cash = 1 - sum(asks); needs every member supported with an ask'},
    'runs': 'maximal supported positive interval per (route, disposition, sold set); it qualifies iff start + '
            'qualifying_min_duration_ms is strictly before its end, so invalidation and support loss win ties; '
            'decision attributes use only pieces begun by the qualification instant',
    'qualifying_min_duration_ms': MIN_DURATION_MS, 'dispositions': list(DISPOSITIONS),
    'coverage': 'per route, exhaustive over the window, precedence ' + ' > '.join(COVERAGE),
    'arithmetic': 'exact decimal context (prec 120, Inexact and Rounded trapped)',
    'scope': 'displayed touches only, not takerability, fills, fees, conversion granularity, collateral '
             'identity or units; no whole-window or losslessness negative',
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


class LiveCapture(Capture):
    """Live only: also counts raw framed bytes so reading stops before the parser's raw limit."""
    raw = 0

    def flush(self):
        self.raw += len(self.buffer)
        super().flush()

    def raw_reached(self):
        return self.raw + len(self.buffer) >= RAW_STOP


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
    if reason not in LIVE_STOPS:
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
    """Labels for documented updates (WsOutcomeMetaUpdate) touching the target question or its members.
    None marks unparsed: an unknown key or a recognized key whose ids do not validate."""
    labels, members = [], set(lay['coins'].values())
    ids = lambda v: isinstance(v, list) and all(h.uint(x) for x in v)  # noqa: E731
    for item in data if isinstance(data, list) else [data]:
        if not isinstance(item, dict) or len(item) != 1:
            return None
        (key, value), = item.items()
        if key in ('questionSettled', 'outcomeSettled'):
            if not h.uint(value):
                return None
            hit = value == lay['question'] if key == 'questionSettled' else value in members
            labels += ['question_settled' if key == 'questionSettled' else 'member_settled'] if hit else []
        elif key == 'questionUpdated':
            if not (isinstance(value, dict) and h.uint(value.get('question')) and h.uint(value.get('fallbackOutcome'))
                    and ids(value.get('namedOutcomes')) and ids(value.get('settledNamedOutcomes'))):
                return None
            touched = {value['fallbackOutcome'], *value['namedOutcomes'], *value['settledNamedOutcomes']}
            labels += ['question_updated'] if value['question'] == lay['question'] or touched & members else []
        elif key == 'outcomeCreated':
            if not (isinstance(value, dict) and h.uint(value.get('outcome'))):
                return None
            labels += ['member_created'] if value['outcome'] in members else []
        else:
            return None
    return labels


def note(counter, key):
    counter[key if key in ANOMALY_KEYS else 'other'] += 1


def gate(last, key, tm, value, wall_ns):
    """Frozen source-clock gate for one (channel, coin); None accepts and records the frame. An identical
    equal-time repeat is ignored without refresh; a changed equal-time or regressed time fails order."""
    prev = last.get(key)
    if prev == (tm, value):
        return 'repeat'
    age = wall_ns - tm * MS
    verdict = ('future' if age < -FUTURE_MS * MS else 'stale' if age > STALE_MS * MS
               else 'order' if prev is not None and tm <= prev[0] else None)
    if verdict is None:
        last[key] = (tm, value)
    return verdict


def replay(records, lay, win):
    """One causal pass in capture order. An accepted frame changes state at its own receipt; nothing is
    re-sorted, re-applied or backdated, and source time feeds only the frozen gates. Each received frame
    leaves a mark: the route states in force from its receipt until the next one."""
    anchor = next((r for r in records if (r['kind'], r['label']) == ('event', 'ws_open')), records[0])
    off = anchor['wall_ms'] * MS - anchor['mono_ns']  # the only wall/mono mapping; never re-anchored
    s = {'acks': collections.Counter(), 'anomalies': collections.Counter(), 'gates': collections.Counter(),
         'probe': collections.Counter(), 'accepted': collections.Counter(), 'echoes': {}, 'meta': [], 'marks': [],
         'pongs': 0, 'r_meta': None, 'r_false': None, 'stop': None, 'anchor': anchor['index'], 'off': off,
         'open': ms(win['open']) * MS - off, 'close': ms(win['close']) * MS - off}
    state, sus, last, streak, probe_sus, probe_gate, last_in = {}, set(), {}, 0, False, False, None
    members = set(lay['coins'])
    for r in records:
        t = r['mono_ns']
        if (r['kind'], r['label']) == ('event', 'stop'):
            s['stop'] = r
        if r['kind'] != 'in':
            continue
        if r['label'] in ('text', 'binary'):
            last_in = t
        channel = data = None
        if r['label'] != 'text':
            note(s['anomalies'], f"frame_{r['label']}")
            sus |= members  # unattributable: every member waits for a causal reseed (its next accepted bbo)
        else:
            try:
                obj = pm.strict_json(r['body'])
                channel, data = obj['channel'], obj.get('data')
            except Exception:
                note(s['anomalies'], 'invalid_json')
                sus |= members
            else:
                if not isinstance(channel, str) or not channel:  # validated before dispatch
                    note(s['anomalies'], 'channel_invalid')
                    sus |= members
                    channel = None
        if channel == 'subscriptionResponse':
            sub = data.get('subscription') if isinstance(data, dict) else None
            match = [i for i, x in enumerate(lay['subs']) if isinstance(sub, dict) and data.get('method') == 'subscribe'
                     and all(sub.get(k) == v for k, v in x.items())
                     and all(k in x or k in ('nSigFigs', 'mantissa', 'fast') for k in sub)]
            if len(match) == 1:
                s['acks'][match[0]] += 1
                extra = {k: sub[k] for k in sorted(sub) if k not in lay['subs'][match[0]]}
                if extra:
                    s['echoes'][match[0]] = encoded(extra).decode().strip()[:200]
            else:
                note(s['anomalies'], 'unexpected_ack')
        elif channel == 'bbo':
            try:
                coin, tm, bid, ask = parse_bbo(data, lay['coins'])
            except (ValueError, Refusal) as exc:
                note(s['anomalies'], str(exc))
                coin = data.get('coin') if isinstance(data, dict) else None
                if coin in lay['coins']:
                    sus.add(coin)  # an unusable update for a member ends its support
                elif not isinstance(coin, str):
                    sus |= members  # unattributable
            else:
                verdict = gate(last, ('bbo', coin), tm, (bid, ask), t + off)
                if verdict is None:
                    state[coin] = (tm, bid, ask)
                    sus.discard(coin)
                    s['accepted'][coin] += 1
                else:
                    s['gates'][f'bbo_{verdict}'] += 1
                    if verdict != 'repeat':
                        sus.add(coin)
        elif channel == 'l2Book':
            try:
                book = b.parse_book(data, lay['probe'])
            except (ValueError, Refusal):
                note(s['anomalies'], 'l2book_invalid')
                probe_gate = True  # an unusable probe suspends the probe coin until the next accepted probe
            else:
                top = (book['bids'][0] if book['bids'] else None, book['asks'][0] if book['asks'] else None)
                verdict, cur = gate(last, ('l2Book', lay['probe']), book['time'], top, t + off), state.get(lay['probe'])
                cls = None
                if verdict is not None:
                    s['gates'][f'l2Book_{verdict}'] += 1
                    probe_gate = probe_gate or verdict != 'repeat'
                else:
                    probe_gate = False
                    cls = ('unknown' if cur is None or lay['probe'] in sus else 'superseded' if cur[0] > book['time']
                           else 'match' if cur[1:] == top else 'mismatch')
                    s['probe'][cls] += 1
                if cls == 'match':
                    streak, probe_sus = 0, False
                elif cls == 'mismatch':
                    s['probe']['suspensions'] += not probe_sus
                    streak, probe_sus = streak + 1, True
                    if streak >= 2 and s['r_false'] is None:
                        s['r_false'] = t
        elif channel == 'outcomeMetaUpdates':
            labels = meta_relevance(data, lay)
            if labels is None:
                note(s['anomalies'], 'meta_update_unparsed')
            s['meta'] += [{'index': r['index'], 'event': label} for label in labels or []]
            if (labels is None or labels) and s['r_meta'] is None:
                s['r_meta'] = t  # an unparsed update might be a target event
        elif channel == 'pong':
            s['pongs'] += 1
        elif channel == 'error':
            note(s['anomalies'], 'channel_error')
            sus |= members
        elif channel is not None:
            note(s['anomalies'], 'channel_unexpected')
            sus |= members
        acked = all(s['acks'][i] == 1 for i in range(len(lay['subs'])))
        view = {c: v[1:] for c, v in state.items()
                if c not in sus and not ((probe_sus or probe_gate) and c == lay['probe'])}
        cash = route_cash(view, lay) if acked else None
        mark = {'live': t if last_in is None else last_in + CARRY_MS * MS,
                'bad': s['r_meta'] is not None or s['r_false'] is not None, 'forward': None, 'inverse_full': None}
        if cash is not None:
            fwd = cash['forward']
            sold = tuple(c for c in sorted(lay['coins']) if c not in fwd['residual'])
            mark['forward'] = ('forward_residual' if fwd['residual'] else 'forward_closed', sold), fwd
            if cash['inverse_full'] is not None:  # every member supported with an ask
                mark['inverse_full'] = ('inverse_full', ()), cash['inverse_full']
        s['marks'].append((t, mark))
    return s


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


def pieces(marks, stop_ns, open_ns, close_ns):
    """Half-open monotonic pieces [a, z) inside the window: the mark in force and whether the stream was
    live (an application message within CARRY_MS)."""
    out = []
    for k, (t, mark) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else stop_ns
        for a, z, live in ((t, min(end, mark['live']), True), (max(t, mark['live']), end, False)):
            a, z = max(a, open_ns), min(z, close_ns)
            if a < z:
                out.append((a, z, mark, live))
    return out


def supported(mark, live, route):
    return live and not mark['bad'] and mark[route] is not None


def partition(items, route, open_ns, close_ns, stop_ns, censored, bad_ns):
    """Exhaustive window coverage for one route; each instant takes the first matching class of COVERAGE."""
    first = next((a for a, _, mark, live in items if supported(mark, live, route)), close_ns)
    spans, cursor = [], open_ns
    for a, z, mark, live in items:
        spans += [(cursor, a, False)] if a > cursor else []
        spans.append((a, z, supported(mark, live, route)))
        cursor = z
    spans += [(cursor, close_ns, False)] if cursor < close_ns else []
    totals = dict.fromkeys(COVERAGE, 0)
    for a, z, good in spans:
        cuts = sorted({a, z} | {x for x in (stop_ns, bad_ns, first) if x is not None and a < x < z})
        for left, right in zip(cuts, cuts[1:]):
            totals['censored' if censored and left >= stop_ns else 'invalidated' if bad_ns is not None
                   and left >= bad_ns else 'initial' if left < first else 'supported' if good else 'gap'] += right - left
    return totals


def finish(cur, cause, open_ns):
    q_at = cur['start'] + MIN_DURATION_MS * MS
    early = [leg for a, leg in cur['legs'] if a <= q_at]
    run = {'disposition': cur['key'][0], 'sold': list(cur['key'][1]), 'start_ns': cur['start'] - open_ns,
           'duration_ns': cur['end'] - cur['start'], 'end_cause': cause, 'qualified': q_at < cur['end'],
           'max_cash_run': max(leg['cash'] for _, leg in cur['legs'])}
    if run['qualified']:
        run['decision'] = {'cash': early[-1]['cash'], 'min_cash': min(x['cash'] for x in early),
                           'units': early[-1]['units'], 'min_units': min(x['units'] for x in early),
                           'basis_per_unit': early[-1]['basis'], 'residual': early[-1]['residual']}
    return run


def runs_of(items, open_ns, close_ns):
    """Maximal positive supported runs per (route, disposition, sold set). A run qualifies only if its start
    plus MIN_DURATION_MS is strictly before its end, so an end at that instant (support loss, invalidation,
    stop or a changed state) wins the tie. Decision attributes use only pieces begun by then."""
    out = []
    for route in ROUTES:
        cur = None
        for a, z, mark, live in items + [(None, None, None, False)]:
            key, leg = mark[route] if mark is not None and supported(mark, live, route) else (None, None)
            positive = leg is not None and leg['cash'] > ZERO
            if cur is not None and not (positive and key == cur['key'] and a == cur['end']):
                cause = (('close' if cur['end'] >= close_ns else 'stop') if a != cur['end']
                         else 'invalidated' if mark['bad'] else 'liveness' if not live
                         else 'support' if mark[route] is None else 'frame')
                out.append(finish(cur, cause, open_ns))
                cur = None
            if positive:
                cur = cur or {'key': key, 'start': a, 'legs': []}
                cur['end'] = z
                cur['legs'].append((a, leg))
    return out


def analyze(records, cohort, qid, stop):
    lay, win = layout(cohort, qid), window(qid)
    rest = {r['label']: r for r in records if r['kind'] == 'rest'}
    meta = {label: b.meta_check(rest.get(label), cohort)[0][qid] for label in ('meta_pre', 'meta_post')}
    s = replay(records, lay, win)
    open_ns, close_ns, censored, stop_ns = s['open'], s['close'], stop != 'window_closed', s['stop']['mono_ns']
    bad_ns = min((x for x in (s['r_meta'], s['r_false']) if x is not None), default=None)
    items = pieces(s['marks'], stop_ns, open_ns, close_ns)
    coverage = {route: partition(items, route, open_ns, close_ns, stop_ns, censored, bad_ns) for route in ROUTES}
    runs = runs_of(items, open_ns, close_ns)
    acked = {p.decode(): s['acks'][i] for i, p in enumerate(lay['payloads'])}
    reasons = [f'{label}_not_unchanged' for label, v in meta.items() if v != 'unchanged']
    for reason, flag in (('subscriptions_not_acked_once', any(v != 1 for v in acked.values())),
                         ('stream_anomalies', bool(s['anomalies'])), ('target_meta_event', s['r_meta'] is not None),
                         ('meta_change_unlocated', meta['meta_post'] != 'unchanged' and s['r_meta'] is None),
                         ('bbo_reconstruction_falsified', s['r_false'] is not None),
                         (f'censored_{stop}', censored), ('no_supported_forward_coverage',
                                                          not coverage['forward']['supported'])):
        reasons += [reason] if flag else []
    gated = (meta['meta_pre'] == 'unchanged' and all(v == 1 for v in acked.values()) and s['r_false'] is None
             and 'meta_change_unlocated' not in reasons)
    status = ('candidate_supported_path' if gated and any(r['qualified'] for r in runs)
              else 'inconclusive' if reasons else 'no_qualifying_supported_path')
    rel = lambda x: None if x is None else x - open_ns  # noqa: E731
    longest = lambda xs: sorted(xs, key=lambda r: (-r['duration_ns'], r['start_ns']))  # noqa: E731
    dispositions = {}
    for d in DISPOSITIONS:
        xs = [r for r in runs if r['disposition'] == d]
        qual = [r for r in xs if r['qualified']]
        dispositions[d] = {'runs': len(xs), 'qualifying': len(qual),
                           'max_cash': max((r['max_cash_run'] for r in xs), default=None),
                           'positive_ns': sum(r['duration_ns'] for r in xs),
                           'qualifying_runs': qual[:QUAL_CAP], 'longest_runs': longest(xs)[:LONG_CAP]}
    return {
        'schema': 'hip4-continuation-live-projection-v2', 'status': status, 'reasons': reasons,
        'question': qid, 'members': sorted(lay['coins'].values()), 'fallback': lay['fallback'],
        'probe_coin': lay['probe'], 'stop': stop, 'censored': censored,
        'clock': {'anchor_index': s['anchor'], 'wall_minus_mono_ns': s['off'],
                  'stop_wall_drift_ms': s['stop']['wall_ms'] - (stop_ns + s['off']) // MS},
        'window_ns': {'length': close_ns - open_ns, 'stop': rel(stop_ns), 'meta_invalidated': rel(s['r_meta']),
                      'falsified': rel(s['r_false'])},
        'meta': meta, 'meta_events': s['meta'][:META_LIST_CAP], 'meta_events_total': len(s['meta']),
        'subscription_acks': acked,
        'ack_echo_extras': {lay['payloads'][i].decode(): v for i, v in sorted(s['echoes'].items())},
        'anomalies': dict(sorted(s['anomalies'].items())), 'gates': dict(sorted(s['gates'].items())),
        'pongs': s['pongs'], 'bbo_accepted': {c: s['accepted'][c] for c in sorted(lay['coins'])},
        'probe': dict(sorted(s['probe'].items()), status='falsified' if s['r_false'] is not None else 'not_falsified'),
        'coverage_ns': coverage, 'dispositions': dispositions,
        'max_forward_cash_supported': max((m['forward'][1]['cash'] for _, _, m, live in items
                                           if supported(m, live, 'forward')), default=None),
        'claim': 'causal receipt-order screen of displayed touches: complete route basis, residual claims valued 0 '
                 'until observable settlement; carry is an unverified change-feed premise; zero fees optimistic; no '
                 'takerability, fill, conversion granularity, collateral identity, unit or profit claim; no '
                 'whole-window or losslessness negative',
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
    stop, redirected = 'transport_failure', []

    async def refuse_redirect(session, context, params):  # ws_connect would otherwise follow redirects
        redirected.append(True)
        raise Refusal('ws_redirect')
    trace = aiohttp.TraceConfig()
    trace.on_request_redirect.append(refuse_redirect)
    try:
        async with aiohttp.ClientSession(trust_env=False, trace_configs=[trace]) as session:
            try:
                ws = await asyncio.wait_for(session.ws_connect(
                    WS_URL, autoping=True, heartbeat=None, max_msg_size=MAX_FRAME, compress=0), CONNECT_S)
            except Exception:
                capture.add('event', 'ws_open_failed', encoded({'cause': 'redirect'}) if redirected else b'{}',
                            wall_ms=wall_ms(), mono_ns=mono_ns())
                stop = 'ws_connect_failed'
                return stop
            receipt['ws_connections_opened'] += 1
            opened_wall, opened_mono = wall_ms(), mono_ns()
            capture.add('event', 'ws_open', b'{}', wall_ms=opened_wall, mono_ns=opened_mono)
            close_mono = opened_mono + (ms(close) - opened_wall) * MS  # the analysis anchor: a wall step cannot close
            try:
                for payload in lay['payloads']:
                    await ws.send_str(payload.decode())
                    capture.add('out', 'subscribe', payload, wall_ms=wall_ms(), mono_ns=mono_ns())
                last_ping = last_in = time.monotonic()
                while True:
                    remaining = (close_mono - mono_ns()) / 1e9
                    if remaining <= 0:
                        stop = 'window_closed'
                        break
                    if capture.reserve_reached():
                        stop = 'cap_reserve_reached'
                        break
                    if capture.raw_reached():
                        stop = 'raw_reserve_reached'
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
        capture = LiveCapture(out / 'capture.bundle.gz')
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
    return checks, terminal if valid else None, projection


def supervise(process, deadline, out, plan_sha256, question=None):
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
    checks, terminal, projection = conclusion_checks(out, plan_sha256, finished)
    eligible = all(checks.values())
    counts = ({d: projection['dispositions'][d]['qualifying'] for d in DISPOSITIONS} if eligible
              else dict.fromkeys(DISPOSITIONS))  # unavailable: counts unknown, never zero
    record = {'schema': 'hip4-continuation-live-supervisor-v1', 'plan_sha256': plan_sha256, 'ended_utc': utc(),
              'status': 'start_failed' if not started else 'process_deadline' if timed_out
              else 'worker_finished' if terminal else 'worker_failed_without_valid_terminal',
              'worker_exitcode': process.exitcode if started else None, 'checks': checks,
              'conclusion_eligible': eligible,
              'conclusion_status': terminal['status'] if eligible else 'inconclusive',
              'stop': terminal.get('stop') if terminal else None,
              'denominator': {'question': question, 'availability': 'available' if eligible else 'unavailable',
                              'qualifying': counts}}
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
    return supervise(process, deadline, out, plan_sha256, plan['target_question'])


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
