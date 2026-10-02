#!/usr/bin/env python3
"""HIP-4 continuation settle v1: one protocol recurring expiry, settlement records and post-record books.

Default is dry and performs no network I/O. A run needs the exact sha256 of a root-frozen plan
that names one expiry, its instruments and a pinned outcomeMeta snapshot. It reads outcomeMeta
once, holds one public websocket with bbo for every instrument YES coin and outcomeMetaUpdates
around the expiry, and on each outcomeSettled id reads settledOutcome and then, strictly after
that response is received, the instrument's l2Book. A sweep after the window covers instruments
without a valid record. Every frame and body is retained in a capped gzip bundle.

The decisive question is whether a book displaying a winner gap (winner YES ask below 1 or loser YES bid
above 0) is still returned after a bound settlement record is in hand; that ordering is proven by the
local monotonic clock alone. Once a record exists, tokens may already be retired and trading, splitting
and redemption may have ceased, so a displayed gap is a conditional recorded display, never closed cash.
The pre-record gap between determination and record stays unavailable, because no documented
source timestamps the adjacent mark pair. Book activity after the expiry and an ex-post bound are
reported separately and never select a trade. No fill, fee, takerability or profit claim.
Design: reports/hip4-research-continuation/settle-v1-design.md
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import datetime as dt
import gzip
import json
import multiprocessing
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import hip4_continuation_expiry as ex  # settlement binding (id, frozen spec, fraction)
from scripts import hip4_continuation_live as lv  # capture, bundle parser, bbo parser, REST adapter

b, h, pm = lv.b, lv.h, lv.pm
Refusal = pm.Refusal
digest, encoded, utc, bounded_read = pm.digest, pm.encoded, pm.utc, pm.bounded_read

PLAN = ROOT / 'reports/experiment-storage/hip4-continuation-settle-v1.json'
SCHEMA = 'hip4-continuation-settle-v1'
SOURCE = 'scripts/hip4_continuation_settle.py'
TEST = 'tests/test_hip4_continuation_settle.py'
PINNED = (SOURCE, TEST, lv.SOURCE, ex.SOURCE, b.SOURCE, h.SOURCE, h.HELPER)
OUT = 'reports/hip4-research-continuation/settle-v1'
URL = 'https://api.hyperliquid.xyz/info'
UTC = dt.timezone.utc
OPEN_BEFORE_S, CLOSE_AFTER_S = 120, 480          # window: expiry-2 min to expiry+8 min
LAUNCH_EARLIEST_S, LAUNCH_LATEST_S = 900, 120     # launch between open-15 min and open-2 min
META_LEAD_S, SUPERVISOR_GRACE_S = 60, 300
REST_TIMEOUT_S, REST_SPACING_S, REST_BODY_CAP = 10, 0.05, 8192
BUNDLE_CAP, RESERVE, SNAPSHOT_CAP = 2097152, 786432, 1048576
PROJECTION_CAP, CONTROL_CAP = 32768, 16384
MIN_RUN_MS, PROMPT_BOOK_NS = 1000, 5_000_000_000
SPEC_KEYS = ex.SPEC_KEYS
STOPS = lv.STOPS
HEADERS = {'Content-Type': 'application/json', 'Accept': 'application/json', 'Accept-Encoding': 'identity',
           'User-Agent': 'rhhype-public-metadata/1.0'}
REQUEST_PLAN = {
    'rest': {'url': URL, 'meta_pre': 'outcomeMeta at open - 60 s via the frozen books-v1 fetch_all (weight 20)',
             'follow_up': 'on the first outcomeSettled id of an instrument: settledOutcome, then l2Book for its YES '
                          'coin sent only after the settledOutcome response is received (weights 20 and 2)',
             'sweep': 'after the window, the same pair for each instrument without a valid bound record',
             'max_pairs_per_instrument': 2, 'body_cap': REST_BODY_CAP, 'timeout_seconds': REST_TIMEOUT_S,
             'min_spacing_seconds': REST_SPACING_S, 'retry': False, 'redirects': False, 'proxies': False,
             'decompression': False},
    'websocket': {'url': lv.WS_URL, 'connections': 1, 'reconnect': False, 'compression': False,
                  'max_frame_bytes': lv.MAX_FRAME, 'subscriptions': ['bbo for each instrument YES coin, ascending',
                                                                     'outcomeMetaUpdates'],
                  'ping': {'payload': lv.PING_PAYLOAD.decode(), 'every_seconds': lv.PING_S},
                  'liveness_stop_seconds': lv.LIVENESS_S},
    'window': {'open': 'expiry - 120 s', 'close': 'expiry + 480 s',
               'launch': 'between open - 900 s and open - 120 s, else refused'},
    'retention': {'cap': BUNDLE_CAP, 'reserve': RESERVE,
                  'rule': 'stop reading the websocket at cap - reserve; queued follow-ups, the stop event and the '
                          'sweep then fit; any stop other than window_closed censors the stream evidence'},
}
ANALYSIS_PLAN = {
    'record': 'the first settledOutcome response that binds to the requested id and the frozen spec with a '
              'fraction of exactly 0 or 1 (expiry-v1 binding)',
    'post_record_book': 'the first l2Book for the instrument whose send time follows that record\'s receipt on the '
                        'local monotonic clock; a winner gap is displayed if the winner YES ask < 1 or the loser YES '
                        'bid > 0; after a record, tokens may be retired and post-settlement purchases, splits and '
                        'redemption are unproven, so a displayed gap is a conditional display, never closed cash',
    'prompt_book_ns': PROMPT_BOOK_NS,
    'pre_record_gap': 'unavailable: no documented source timestamps the mark updates adjacent to the expiry',
    'post_expiry_activity': 'bbo changes with server time after the expiry; silence is not a halt',
    'ex_post_bound': f'per instrument, runs >= {MIN_RUN_MS} ms after the expiry where the bound winner would have '
                     'paid against the displayed touch; reported separately, never used to select a trade',
    'arithmetic': 'exact decimal context (prec 120, Inexact and Rounded trapped)',
}
OUTPUT_LIMITS = {'bundle_gzip': BUNDLE_CAP, 'projection': PROJECTION_CAP,
                 'claim_terminal_and_supervisor_receipts': CONTROL_CAP}


def now_utc():
    return dt.datetime.now(UTC)


def sleep(seconds):
    time.sleep(max(0.0, seconds))


def wall_ms():
    return time.time_ns() // 1000000


def mono_ns():
    return time.monotonic_ns()


def window(expiry):
    return {'expiry': expiry, 'open': expiry - dt.timedelta(seconds=OPEN_BEFORE_S),
            'close': expiry + dt.timedelta(seconds=CLOSE_AFTER_S),
            'launch_from': expiry - dt.timedelta(seconds=OPEN_BEFORE_S + LAUNCH_EARLIEST_S),
            'launch_until': expiry - dt.timedelta(seconds=OPEN_BEFORE_S + LAUNCH_LATEST_S),
            'meta_pre_at': expiry - dt.timedelta(seconds=OPEN_BEFORE_S + META_LEAD_S)}


def fields(description):
    parts = [p.split(':', 1) for p in description.split('|')] if isinstance(description, str) else []
    return dict(p for p in parts if len(p) == 2)


def instruments(plan):
    """Resolve the plan's instruments against the pinned snapshot; structural fields only."""
    snap = plan.get('snapshot') or {}
    try:
        packed = bounded_read(ROOT / snap['path'], SNAPSHOT_CAP)
    except (KeyError, TypeError, OSError):
        raise Refusal('snapshot_unreadable') from None
    if digest(packed) != snap.get('gz_sha256'):
        raise Refusal('snapshot_sha_mismatch')
    raw = gzip.decompress(packed)
    if digest(raw) != snap.get('raw_sha256'):
        raise Refusal('snapshot_raw_sha_mismatch')
    meta = pm.strict_json(raw)
    expiry = dt.datetime.fromisoformat(plan['expiry_utc'])
    stamp = expiry.strftime('%Y%m%d-%H%M')
    by_id = collections.defaultdict(list)
    for o in meta.get('outcomes', []):
        by_id[o.get('outcome')].append(o)
    questions = {q.get('question'): q for q in meta.get('questions', [])}
    out = []
    for item in plan.get('instruments', []):
        oid = item.get('outcome')
        entries = by_id.get(oid, [])
        if len(entries) != 1 or sorted(entries[0]) != sorted(SPEC_KEYS):
            raise Refusal('instrument_spec_invalid')
        spec = entries[0]
        if item.get('kind') == 'binary':
            f = fields(spec['description'])
            if (f.get('class'), f.get('expiry')) != ('priceBinary', stamp):
                raise Refusal('instrument_not_this_expiry')
        elif item.get('kind') == 'bucket':
            q = questions.get(item.get('question'))
            members = sorted([q['fallbackOutcome']] + q['namedOutcomes']) if q else []
            f = fields(q['description']) if q else {}
            if oid not in members or (f.get('class'), f.get('expiry')) != ('priceBucket', stamp):
                raise Refusal('instrument_not_this_expiry')
        else:
            raise Refusal('instrument_kind_invalid')
        out.append({'outcome': oid, 'kind': item['kind'], 'question': item.get('question'),
                    'coin': f'#{10 * oid}', 'spec': spec})
    if not out or len({i['outcome'] for i in out}) != len(out) or [i['outcome'] for i in out] != sorted(
            i['outcome'] for i in out):
        raise Refusal('instrument_list_invalid')
    return expiry, out


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
    if not isinstance(p, dict) or p.get('schema') != SCHEMA or p.get('status') != 'frozen_settle_window':
        raise Refusal('plan_not_frozen')
    for key, expected in (('request_plan', REQUEST_PLAN), ('analysis_plan', ANALYSIS_PLAN),
                          ('output_limits_bytes', OUTPUT_LIMITS)):
        if encoded(p.get(key)) != encoded(expected):
            raise Refusal(f'{key}_changed')
    if p.get('output_dir') != OUT or (ROOT / OUT).resolve() != ROOT.resolve() / OUT:
        raise Refusal('output_plan_changed')
    pins = p.get('source_pins')
    if not isinstance(pins, list) or len(pins) != len(PINNED) or sorted(
            pin.get('path') for pin in pins if isinstance(pin, dict)) != sorted(PINNED):
        raise Refusal('missing_source_pins')
    for pin in pins:
        data = bounded_read(ROOT / pin['path'], 262144)
        if (ROOT / pin['path']).resolve() != ROOT.resolve() / pin['path'] or type(pin.get('bytes')) is not int \
                or len(data) != pin['bytes'] or digest(data) != pin.get('sha256'):
            raise Refusal('source_pin_mismatch')
    if p.get('previous') != b.PREVIOUS or digest(bounded_read(ROOT / b.PREVIOUS, 65536)) != p.get('previous_sha256'):
        raise Refusal('previous_plan_sha_mismatch')
    expiry, items = instruments(p)
    return p, expiry, items


def payloads(items):
    subs = [{'type': 'bbo', 'coin': i['coin']} for i in items] + [{'type': 'outcomeMetaUpdates'}]
    return subs, [json.dumps({'method': 'subscribe', 'subscription': s}, separators=(',', ':')).encode()
                  for s in subs]


def rest_payload(kind, oid):
    body = ({'type': 'settledOutcome', 'outcome': oid} if kind == 'settled'
            else {'type': 'l2Book', 'coin': f'#{10 * oid}', 'nSigFigs': None})
    return json.dumps(body, separators=(',', ':')).encode()


class Capture(lv.Capture):
    def reserve_reached(self):
        return self.size >= self.cap - RESERVE


async def rest(session, capture, kind, oid, receipt):
    """One bounded POST, recorded whatever happens; never retried."""
    fields_ = {'sent_ms': wall_ms(), 'sent_mono_ns': mono_ns(), 'http_status': None, 'code': None,
               'declared_length': None, 'over_cap': False}
    body = bytearray()
    receipt['rest_attempted'] += 1
    try:
        async with asyncio.timeout(REST_TIMEOUT_S):
            async with session.post(URL, data=rest_payload(kind, oid), headers=HEADERS,
                                    allow_redirects=False) as response:
                fields_['http_status'] = response.status
                length = response.headers.get('Content-Length')
                if length is not None:
                    fields_['declared_length'] = length[:24]
                    if not re.fullmatch(r'[0-9]{1,9}', length) or int(length) > REST_BODY_CAP:
                        raise Refusal('declared_length_invalid_or_over_cap')
                while True:
                    chunk = await response.content.read(min(16384, REST_BODY_CAP + 1 - len(body)))
                    if not chunk:
                        break
                    body.extend(chunk)
                    if len(body) > REST_BODY_CAP:
                        del body[REST_BODY_CAP:]
                        fields_['over_cap'] = True
                        raise Refusal('body_over_cap')
                if length is not None and len(body) != int(length):
                    raise Refusal('incomplete_body')
                if (response.headers.get('Content-Encoding') or 'identity').lower() != 'identity':
                    raise Refusal('unsupported_content_encoding')
                if response.status != 200:
                    raise Refusal('http_status_not_200')
                media = (response.headers.get('Content-Type') or '').split(';', 1)[0].strip().lower()
                if media != 'application/json':
                    raise Refusal('unsupported_content_type')
    except Refusal as exc:
        fields_['code'] = str(exc)
    except Exception:
        fields_['code'] = 'transport_failure'
    capture.add('rest', f'{kind}:{oid}', bytes(body), wall_ms=wall_ms(), mono_ns=mono_ns(), **fields_)
    return fields_['code'], bytes(body)


async def pair(session, capture, item, receipt, state):
    """settledOutcome, then l2Book sent only after that response has been received and recorded."""
    oid = item['outcome']
    state['pairs'][oid] += 1
    code, body = await rest(session, capture, 'settled', oid, receipt)
    parsed = ex.settled({'body': body} if code is None else None, oid, item['spec'])
    if code is None and ex.valid(parsed) and parsed['fraction'] in (b.ZERO, b.ONE):
        state['valid'].add(oid)
    await asyncio.sleep(REST_SPACING_S)
    await rest(session, capture, 'book', oid, receipt)
    await asyncio.sleep(REST_SPACING_S)


def settled_ids(text, wanted):
    """Instrument ids named by outcomeSettled, or by questionSettled for their question, in one text frame."""
    try:
        obj = json.loads(text)
    except ValueError:
        return []
    if not isinstance(obj, dict) or obj.get('channel') != 'outcomeMetaUpdates':
        return []
    data = obj.get('data')
    out = []
    for entry in data if isinstance(data, list) else [data]:
        if not isinstance(entry, dict) or len(entry) != 1:
            continue
        if h.uint(entry.get('outcomeSettled')) and entry['outcomeSettled'] in wanted:
            out.append(entry['outcomeSettled'])
        elif h.uint(entry.get('questionSettled')):
            out += [oid for oid, item in sorted(wanted.items()) if item.get('question') == entry['questionSettled']]
    return out


async def collect(capture, items, close, receipt):
    import aiohttp
    _, subs = payloads(items)
    by_id = {i['outcome']: i for i in items}
    state = {'pairs': collections.Counter(), 'valid': set()}
    queue, stop = asyncio.Queue(), 'transport_failure'
    async with aiohttp.ClientSession(trust_env=False, auto_decompress=False) as session:
        async def consumer():
            while True:
                oid = await queue.get()
                if oid is None:
                    return
                await pair(session, capture, by_id[oid], receipt, state)
        worker = asyncio.create_task(consumer())
        queued = set()
        try:
            try:
                ws = await asyncio.wait_for(session.ws_connect(
                    lv.WS_URL, autoping=True, heartbeat=None, max_msg_size=lv.MAX_FRAME, compress=0), lv.CONNECT_S)
            except Exception:
                capture.add('event', 'ws_open_failed', b'{}', wall_ms=wall_ms(), mono_ns=mono_ns())
                ws, stop = None, 'ws_connect_failed'
            if ws is not None:
                receipt['ws_connections_opened'] += 1
                capture.add('event', 'ws_open', b'{}', wall_ms=wall_ms(), mono_ns=mono_ns())
                try:
                    stop = await stream(ws, aiohttp, capture, subs, by_id, queue, queued, close, receipt)
                finally:
                    try:
                        await asyncio.wait_for(ws.close(), lv.CONNECT_S)
                    except Exception:
                        pass
        except Exception:
            stop = 'transport_failure'
        finally:
            await queue.put(None)
            await worker
        capture.add('event', 'stop', encoded({'reason': stop}), wall_ms=wall_ms(), mono_ns=mono_ns())
        for item in items:  # sweep: one more pair only where no valid bound record exists yet
            if item['outcome'] not in state['valid'] and state['pairs'][item['outcome']] < 2:
                await pair(session, capture, item, receipt, state)
    return stop


async def stream(ws, aiohttp, capture, subs, by_id, queue, queued, close, receipt):
    for payload in subs:
        await ws.send_str(payload.decode())
        capture.add('out', 'subscribe', payload, wall_ms=wall_ms(), mono_ns=mono_ns())
    last_ping = last_in = time.monotonic()
    while True:
        remaining = (close - now_utc()).total_seconds()
        if remaining <= 0:
            return 'window_closed'
        if capture.reserve_reached():
            return 'cap_reserve_reached'
        if time.monotonic() - last_in > lv.LIVENESS_S:
            return 'liveness_lost'
        if time.monotonic() - last_ping >= lv.PING_S:
            await ws.send_str(lv.PING_PAYLOAD.decode())
            capture.add('out', 'ping', lv.PING_PAYLOAD, wall_ms=wall_ms(), mono_ns=mono_ns())
            last_ping = time.monotonic()
        if capture.due():
            capture.flush()
        wait = max(0.01, min(1.0, remaining, lv.PING_S - (time.monotonic() - last_ping)))
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
        if msg.type not in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
            return 'ws_error' if msg.type == aiohttp.WSMsgType.ERROR else 'ws_closed'
        last_in = time.monotonic()
        if msg.type == aiohttp.WSMsgType.TEXT:
            for oid in settled_ids(msg.data, by_id):
                if oid not in queued:
                    queued.add(oid)
                    await queue.put(oid)


def validate_records(records, items):
    """Opening order, consecutive indexes, monotone clocks, planned REST labels and pair order."""
    previous, labels = 0, {f'{k}:{i["outcome"]}' for i in items for k in ('settled', 'book')}
    for i, r in enumerate(records):
        if r['index'] != i or r['kind'] not in ('rest', 'event', 'out', 'in'):
            raise Refusal('record_order_invalid')
        if not h.uint(r['wall_ms']) or not h.uint(r['mono_ns']) or r['mono_ns'] < previous:
            raise Refusal('record_clock_invalid')
        if r['kind'] == 'rest' and not (h.uint(r['sent_mono_ns']) and previous <= r['sent_mono_ns'] <= r['mono_ns']):
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
    if reason == 'meta_pre_failed':
        if stop != 1 or len(records) != 2 or records[0]['code'] is None:
            raise Refusal('record_plan_mismatch')
        return reason
    if records[0]['code'] is not None:
        raise Refusal('record_plan_mismatch')
    _, subs = payloads(items)
    body = records[1:stop]
    opened = bool(body) and (body[0]['kind'], body[0]['label']) == ('event', 'ws_open')
    if not opened:
        if [(r['kind'], r['label']) for r in body if r['kind'] != 'rest'] not in ([], [('event', 'ws_open_failed')]):
            raise Refusal('record_plan_mismatch')
    else:
        sent = [r['body'] for r in body[1:] if (r['kind'], r['label']) == ('out', 'subscribe')]
        if sent != subs[:len(sent)] or (len(sent) < len(subs) and reason != 'transport_failure'):
            raise Refusal('record_plan_mismatch')
    for r in records[1:]:
        k = (r['kind'], r['label'])
        if r['kind'] == 'rest' and r['label'] not in labels:
            raise Refusal('record_plan_mismatch')
        if r['kind'] == 'out' and k != ('out', 'subscribe') and (k, r['body']) != (('out', 'ping'), lv.PING_PAYLOAD):
            raise Refusal('record_plan_mismatch')
        if r['kind'] == 'event' and r['label'] not in ('ws_open', 'ws_open_failed', 'stop'):
            raise Refusal('record_plan_mismatch')
        if r['index'] > stop and r['kind'] != 'rest':
            raise Refusal('record_plan_mismatch')
    for item in items:  # each l2Book directly follows its settledOutcome; at most two pairs
        seq = [r['label'].split(':')[0] for r in records if r['kind'] == 'rest' and r['label'] in
               (f'settled:{item["outcome"]}', f'book:{item["outcome"]}')]
        if len(seq) > 4 or seq != ['settled', 'book'] * (len(seq) // 2):
            raise Refusal('record_pair_invalid')
    return reason


def touch(state, fraction):
    """Exact displayed gap against the bound winner at one touch, or None (a display, not closed cash)."""
    bid, ask = state
    with b.exact():
        if fraction == b.ONE and ask is not None and ask[0] < b.ONE:
            return b.ONE - ask[0], ask[1], 'winner_yes_ask_below_1'
        if fraction == b.ZERO and bid is not None and bid[0] > b.ZERO:
            return bid[0], bid[1], 'loser_yes_bid_above_0'
    return None


def ex_post_runs(events, fraction, start_ms, end_ms):
    """Ex-post runs on one coin after the expiry; separate from any decision."""
    runs, current, state = [], None, (None, None)
    points = sorted(events, key=lambda e: (e[0], e[1]))
    timeline = [(start_ms, None)]
    for t, _, _, bid, ask in points:
        if t <= start_ms:
            state = (bid, ask)
        else:
            timeline.append((t, (bid, ask)))
    timeline[0] = (start_ms, state)
    for k, (t, st) in enumerate(timeline):
        right = min(timeline[k + 1][0] if k + 1 < len(timeline) else end_ms, end_ms)
        if right <= t:
            continue
        cash = touch(st, fraction)
        if cash:
            if current is None:
                current = {'start_ms': t, 'end_ms': right, 'max_cash': cash[0], 'units_at_max': cash[1],
                           'route': cash[2]}
                runs.append(current)
            else:
                current['end_ms'] = right
                if cash[0] > current['max_cash']:
                    current.update(max_cash=cash[0], units_at_max=cash[1])
        else:
            current = None
    for r in runs:
        r['duration_ms'] = r['end_ms'] - r['start_ms']
        r['right_censored'] = r['end_ms'] >= end_ms
    return [r for r in runs if r['duration_ms'] >= MIN_RUN_MS]


def post_record(record, fraction, coin):
    """Classify the first causally later l2Book response."""
    if record is None:
        return 'not_attempted', None
    if record['code'] is not None or record['http_status'] != 200:
        return 'unavailable', None
    try:
        obj = pm.strict_json(record['body'])
    except Refusal:
        return 'unavailable', None
    if obj is None:
        return 'no_book_after_record', None
    try:
        book = b.parse_book(obj, coin)
    except (ValueError, Refusal):
        return 'unavailable', None
    cash = touch((book['bid'], book['ask']), fraction)  # (px, sz) tops; touch reads only those two
    if cash:
        return 'winner_gap_displayed', {'displayed_gap_per_unit': cash[0], 'units': cash[1], 'route': cash[2],
                                     'book_time': book['time']}
    return 'no_winner_gap_display', {'book_time': book['time'], 'levels': book['levels']}


def analyze(records, items, expiry, stop):
    win = window(expiry)
    expiry_ms, close_ms = int(expiry.timestamp() * 1000), int(win['close'].timestamp() * 1000)
    coins = {i['coin']: i for i in items}
    stop_index = next(r['index'] for r in records if (r['kind'], r['label']) == ('event', 'stop'))
    _, subs = payloads(items)
    acks, anomalies, events, settled_at, max_server = collections.Counter(), collections.Counter(), [], {}, None
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
            sub = encoded(data.get('subscription')) if isinstance(data, dict) else None
            planned = [encoded(json.loads(p)['subscription']) for p in subs]
            if sub in planned and data.get('method') == 'subscribe':
                acks[sub] += 1
            else:
                anomalies['unexpected_ack'] += 1
        elif channel == 'bbo':
            try:
                coin, t, bid, ask = lv.parse_bbo(data, coins)
            except (ValueError, Refusal) as exc:
                anomalies[f'bbo_invalid_{exc}'[:48]] += 1
                continue
            events.append((t, r['index'], coin, bid, ask))
            max_server = t if max_server is None else max(max_server, t)
        elif channel == 'outcomeMetaUpdates':
            for oid in settled_ids(r['body'].decode('utf-8', 'replace'), {i['outcome']: i for i in items}):
                settled_at.setdefault(oid, {'wall_ms': r['wall_ms'], 'mono_ns': r['mono_ns'], 'index': r['index']})
        elif channel != 'pong':
            anomalies[f'channel_{str(channel)[:32]}'] += 1
    end_ms = min(close_ms, max_server) if max_server is not None else expiry_ms
    per, reasons = {}, []
    for item in items:
        oid, coin = item['outcome'], item['coin']
        rest = [r for r in records if r['kind'] == 'rest' and r['label'] in (f'settled:{oid}', f'book:{oid}')]
        reads = [(r, ex.settled(r if r['code'] is None else None, oid, item['spec']))
                 for r in rest if r['label'].startswith('settled')]
        first = next(((r, s) for r, s in reads if ex.valid(s) and s['fraction'] in (b.ZERO, b.ONE)), None)
        own = [e for e in events if e[2] == coin]
        after = [e[0] for e in own if e[0] > expiry_ms]
        entry = {'settled_event_receipt': settled_at.get(oid),
                 'settled_reads': [{'shape': s['shape'], 'issues': s['issues'], 'path': 'sweep' if r['index'] > stop_index
                                    else 'follow_up'} for r, s in reads],
                 'post_expiry_bbo_changes': len(after), 'first_post_expiry_bbo_ms': min(after, default=None),
                 'last_post_expiry_bbo_ms': max(after, default=None),
                 'pre_record_gap': 'unavailable_no_timestamped_mark_pair'}
        if first is None:
            entry.update(record='unavailable', post_record='unavailable', ex_post_runs=[])
            per[str(oid)] = entry
            continue
        record, parsed = first
        book = next((r for r in rest if r['label'].startswith('book') and r['sent_mono_ns'] > record['mono_ns']), None)
        status, detail = post_record(book, parsed['fraction'], coin)
        entry.update(record={'fraction': parsed['fraction'], 'price': parsed.get('price'), 'details': parsed['details'],
                             'receipt_wall_ms': record['wall_ms'], 'path': 'sweep' if record['index'] > stop_index
                             else 'follow_up'},
                     post_record=status, post_record_detail=detail,
                     book_delay_ns=None if book is None else book['sent_mono_ns'] - record['mono_ns'],
                     ex_post_runs=ex_post_runs(own, parsed['fraction'], expiry_ms, end_ms)[:10])
        per[str(oid)] = entry
    acked = all(acks.get(encoded(json.loads(p)['subscription']), 0) == 1 for p in subs)
    displayed = [o for o, v in per.items() if v['post_record'] == 'winner_gap_displayed']
    clean = all(v['record'] != 'unavailable' and v['record']['path'] == 'follow_up'
                and v['post_record'] in ('no_winner_gap_display', 'no_book_after_record')
                and v['book_delay_ns'] is not None and v['book_delay_ns'] <= PROMPT_BOOK_NS for v in per.values())
    if not acked:
        reasons.append('subscriptions_not_acked_once')
    if anomalies:
        reasons.append('stream_anomalies')
    if not clean:
        reasons.append('post_record_check_incomplete_late_or_sweep')
    if stop != 'window_closed':
        reasons.append(f'stream_censored_{stop}')
    status = ('candidate_post_record_display_conditional' if displayed else
              'park_no_post_record_winner_gap_display' if clean else 'inconclusive')
    return {'schema': 'hip4-continuation-settle-projection-v1', 'status': status, 'reasons': reasons,
            'expiry_utc': expiry.isoformat(), 'stop': stop, 'instruments': per, 'displayed_gap_instruments': displayed,
            'subscription_acks_once': acked, 'anomalies': dict(sorted(anomalies.items())),
            'window_ms': {'expiry': expiry_ms, 'close': close_ms, 'server_end': end_ms},
            'pre_record_gap': 'unavailable: no documented source timestamps the adjacent mark pair',
            'claim': 'post-record books are conditional recorded displays after a bound settlement record; '
                     'post-settlement purchases, splits and redemption are unproven, so no displayed gap is closed '
                     'cash; '
                     'post-expiry bbo changes show book activity, and silence is not a halt; ex-post runs use the '
                     'bound settlement and are not knowable or causal signals; no fill, fee, takerability or profit '
                     'claim; zero fees optimistic'}


def build_projection(records, items, expiry, stop, plan_sha256, packed):
    projection = b.stringify(analyze(records, items, expiry, stop))
    projection.update(plan_sha256=plan_sha256, bundle_sha256=digest(packed), records=len(records))
    return projection


def worker(plan_sha256, out):
    receipt = {'schema': 'hip4-continuation-settle-terminal-v1', 'started_utc': utc(), 'plan_sha256': plan_sha256,
               'status': 'inconclusive', 'code': None, 'stop': None, 'rest_attempted': 0,
               'ws_connections_opened': 0, 'frames_in': 0, 'records': 0, 'bundle_bytes': 0,
               'bundle_sha256': None, 'projection_published': False}
    try:
        _, expiry, items = verify(plan_sha256)
        win = window(expiry)
        capture = Capture(out / 'capture.bundle.gz', cap=BUNDLE_CAP)
        try:
            sleep((win['meta_pre_at'] - now_utc()).total_seconds())
            if lv.rest_read(capture, 'meta_pre', receipt):
                stop = 'meta_pre_failed'
                capture.add('event', 'stop', encoded({'reason': stop}), wall_ms=wall_ms(), mono_ns=mono_ns())
            else:
                sleep((win['open'] - now_utc()).total_seconds())
                stop = asyncio.run(collect(capture, items, win['close'], receipt))
            receipt['stop'] = stop
        finally:
            packed = capture.finish()
            receipt.update(bundle_bytes=len(packed), bundle_sha256=digest(packed), records=capture.count)
        verify(plan_sha256)
        parsed = lv.parse_bundle(packed)
        reason = validate_records(parsed, items)
        if reason != receipt['stop']:
            raise Refusal('stop_mismatch')
        projection = build_projection(parsed, items, expiry, reason, plan_sha256, packed)
        verify(plan_sha256)
        lv.publish(out / 'projection.json', projection, PROJECTION_CAP)
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
        lv.publish(out / 'terminal.json', receipt, 4096, controls=True)


def conclusion_checks(out, plan_sha256, finished):
    def read(path, cap):
        try:
            return pm.strict_json(bounded_read(path, cap))
        except Exception:
            return None
    terminal, projection = read(out / 'terminal.json', 4096), read(out / 'projection.json', PROJECTION_CAP)
    valid = (isinstance(terminal, dict) and terminal.get('schema') == 'hip4-continuation-settle-terminal-v1'
             and terminal.get('plan_sha256') == plan_sha256)
    checks = {'worker_completed_exit_zero': finished,
              'terminal_without_failure': valid and terminal.get('code') is None
                                          and terminal.get('projection_published') is True,
              'bundle_matches_terminal': False, 'records_match_plan': False, 'projection_reproduced': False,
              'no_pending_publication': not any(out.glob('*.pending'))}
    try:
        _, expiry, items = verify(plan_sha256)
        checks['final_plan_and_source_pins'] = True
    except Exception:
        items, checks['final_plan_and_source_pins'] = None, False
    try:
        packed = bounded_read(out / 'capture.bundle.gz', BUNDLE_CAP)
        checks['bundle_matches_terminal'] = (valid and len(packed) == terminal.get('bundle_bytes')
                                             and digest(packed) == terminal.get('bundle_sha256'))
        if items is not None:
            parsed = lv.parse_bundle(packed)
            reason = validate_records(parsed, items)
            checks['records_match_plan'] = valid and reason == terminal.get('stop') \
                and len(parsed) == terminal.get('records')
            checks['projection_reproduced'] = (isinstance(projection, dict) and valid and encoded(
                build_projection(parsed, items, expiry, reason, plan_sha256, packed)) == encoded(projection)
                and projection.get('status') == terminal.get('status'))
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
    record = {'schema': 'hip4-continuation-settle-supervisor-v1', 'plan_sha256': plan_sha256, 'ended_utc': utc(),
              'status': 'start_failed' if not started else 'process_deadline' if timed_out
              else 'worker_finished' if terminal else 'worker_failed_without_valid_terminal',
              'worker_exitcode': process.exitcode if started else None, 'checks': checks,
              'conclusion_eligible': eligible, 'pending_prefix_retained': any(out.glob('*.pending')),
              'conclusion_status': terminal['status'] if eligible else 'inconclusive',
              'stop': terminal.get('stop') if terminal else None}
    lv.publish(out / 'supervisor.json', record, 2048, controls=True)
    return record


def run(plan_sha256):
    _, expiry, items = verify(plan_sha256)
    win = window(expiry)
    now = now_utc()
    if not win['launch_from'] <= now <= win['launch_until']:
        raise Refusal('outside_launch_window')
    out = ROOT / OUT
    out.mkdir(parents=True, exist_ok=False)
    lv.publish(out / 'claim.json', {
        'schema': 'hip4-continuation-settle-claim-v1', 'started_utc': utc(), 'plan_sha256': plan_sha256,
        'source_sha256': digest(bounded_read(ROOT / SOURCE, 131072)), 'expiry_utc': expiry.isoformat(),
        'instruments': [i['outcome'] for i in items],
        'purpose': 'public_bbo_stream_settlement_records_and_post_record_books'}, 2048, controls=True)
    deadline = time.monotonic() + (win['close'] - now).total_seconds() + SUPERVISOR_GRACE_S
    process = multiprocessing.get_context('fork').Process(target=worker, args=(plan_sha256, out))
    return supervise(process, deadline, out, plan_sha256)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--plan-sha256')
    args = parser.parse_args(argv)
    if not args.run:
        draft = pm.strict_json(bounded_read(ROOT / 'reports/hip4-research-continuation/settle-v1-draft-plan.json',
                                            65536))
        expiry, items = instruments(draft)
        win = window(expiry)
        print(encoded({'status': 'dry_no_network', 'network_calls': 0, 'expiry_utc': expiry.isoformat(),
                       'window_utc': [win['open'].isoformat(), win['close'].isoformat()],
                       'instruments': [i['outcome'] for i in items],
                       'subscriptions': [p.decode() for p in payloads(items)[1]],
                       'max_rest_weight': 20 + len(items) * 2 * (20 + 2), 'bundle_cap': BUNDLE_CAP}).decode(), end='')
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
