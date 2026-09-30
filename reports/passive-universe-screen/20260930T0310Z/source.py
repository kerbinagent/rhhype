#!/usr/bin/env python3
"""Bounded public RH/HL quote screen; conditional quoted margins, never fills."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
from pathlib import Path
import statistics
import time
import datetime as dt

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
METHOD = ROOT / 'research/passive-universe-screen-method.md'
PLAN = ROOT / 'data/paper-monitor/markets.json'
HL = 'https://api.hyperliquid.xyz/info'
WS = 'wss://api.rh.lighter.xyz/stream?readonly=true'
REQUESTS = {
    'rh_order_book_details': ('GET', 'https://api.rh.lighter.xyz/api/v1/orderBookDetails', None),
    'hl_meta_native': ('POST', HL, {'type': 'metaAndAssetCtxs', 'dex': ''}),
    'hl_meta_xyz': ('POST', HL, {'type': 'metaAndAssetCtxs', 'dex': 'xyz'}),
}
CRYPTO = set('BTC ETH LIT SOL HYPE ZEC NEAR XRP'.split())
EQUITY = set('NVDA AAPL SNDK GOOGL MSFT MU TSLA META CRCL AMD AMZN INTC'.split())
ALLOW = CRYPTO | EQUITY | {'XAU', 'XAG'}
BUDGETS = [100, 250, 500, 1000]
CAP = 16_000_000
RAW_CAP = 11_000_000  # includes metadata/source; leaves 5 MB for derived output
TRADE_CAP = 20_000
AGE_NS = 2_000_000_000
KEEPALIVE_SECONDS = 30


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def dec(value, positive=False):
    d = Decimal(str(value))
    if not d.is_finite() or (positive and d <= 0):
        raise ValueError('nonfinite_or_nonpositive_decimal')
    return d


def grid(n):
    if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= 12:
        raise ValueError('invalid_decimals')
    return Decimal(10) ** -n


class CapReached(Exception):
    pass


class Store:
    def __init__(self, out):
        self.out = Path(out)
        self.used = sum(p.stat().st_size for p in self.out.rglob('*') if p.is_file())

    def write(self, name, value, *, raw=False, append=False, byte_data=False):
        b = value if byte_data else (json.dumps(value, separators=(',', ':'), allow_nan=False) + '\n').encode()
        path = self.out / name
        prior = 0 if append or not path.exists() else path.stat().st_size
        limit = RAW_CAP if raw else CAP
        if self.used + len(b) - prior > limit:
            raise CapReached('total_file_cap_or_derived_reserve')
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('ab' if append else 'wb') as f:
            f.write(b)
        self.used += len(b) - prior


def select(plan, responses):
    routes = {}
    for row in plan['pairs']:
        if row['other']['venue'] != 'rh_lighter' or row['hl']['venue'] != 'hyperliquid':
            continue
        a = row['asset']
        route = (str(row['other']['market']), row['hl']['market'])
        if a in routes and routes[a] != route:
            raise ValueError('conflicting_route_' + a)
        routes[a] = route
    rh = responses['rh_order_book_details']
    if rh.get('code') != 200:
        raise ValueError('rh_metadata_code')
    rows = rh['order_book_details']
    rb = {str(x['market_id']): x for x in rows}
    if len(rb) != len(rows):
        raise ValueError('duplicate_rh_id')
    hb = {}
    for name in ('hl_meta_native', 'hl_meta_xyz'):
        meta, ctxs = responses[name]
        if meta.get('collateralToken') != 0 or len(meta['universe']) != len(ctxs):
            raise ValueError('hl_collateral_or_context')
        for h, c in zip(meta['universe'], ctxs):
            if h['name'] in hb:
                raise ValueError('duplicate_hl_id')
            hb[h['name']] = (h, c)
    selected, exclusions = [], []
    for a, (rm, hm) in routes.items():
        try:
            if a not in ALLOW:
                raise ValueError('underlying_equivalence_not_admitted')
            expected = a if a in CRYPTO else {'XAU': 'xyz:GOLD', 'XAG': 'xyz:SILVER'}.get(a, 'xyz:' + a)
            if hm != expected:
                raise ValueError('hl_underlying_alias')
            r = rb[rm]
            h, c = hb[hm]
            if r['symbol'] != a or r['market_type'] != 'perp' or r['status'] != 'active' or h.get('isDelisted', False):
                raise ValueError('identity_or_inactive')
            if dec(r['multiplier'], True) != 1 or dec(r['quote_multiplier'], True) != 1:
                raise ValueError('multipliers')
            pd, sd = r['supported_price_decimals'], r['supported_size_decimals']
            pt, rs, hs = grid(pd), grid(sd), grid(h['szDecimals'])
            if (r['price_decimals'], r['size_decimals'], r['supported_quote_decimals']) != (pd, sd, pd + sd):
                raise ValueError('current_supported_grid')
            if h['szDecimals'] > 6:
                raise ValueError('hl_price_decimal_rule')
            rv, hv = dec(r['daily_quote_token_volume']), dec(c['dayNtlVlm'])
            if min(rv, hv) < 1_000_000:
                raise ValueError('venue_volume_below_1m')
            rp, hp = dec(r['index_price'], True), dec(c['oraclePx'], True)
            if abs(rp / hp - 1) > Decimal('.1'):
                raise ValueError('reference_price_disagrees_over_10pct')
            fee = Decimal('4.5')
            scale, growth = None, None
            if hm.startswith('xyz:'):
                scale, growth = dec(h['deployerFeeScale']), h['growthMode']
                if scale < 0 or growth not in ('enabled', 'disabled'):
                    raise ValueError('unknown_fee_scale_or_growth')
                fee *= (scale + 1 if scale < 1 else 2 * scale) * (Decimal('.1') if growth == 'enabled' else 1)
            p = {'asset': a, 'rh_market': rm, 'hl_market': hm,
                 'unit': 'native_coin' if a in CRYPTO else 'troy_ounce' if a in {'XAU', 'XAG'} else 'one_share',
                 'rh_price_tick': str(pt), 'rh_size_step': str(rs), 'hl_size_step': str(hs),
                 'hl_size_decimals': h['szDecimals'], 'common_step': str(max(rs, hs)),
                 'rh_min_qty': str(dec(r['min_base_amount'], True)),
                 'rh_min_notional': str(max(Decimal(10), dec(r['min_quote_amount'], True))),
                 'rh_max_quote': str(dec(r['order_quote_limit'], True)),
                 'rh_maker_fee_bps': str(dec(r['maker_fee']) * 100), 'hl_taker_fee_bps': str(fee),
                 'deployer_fee_scale': None if scale is None else str(scale), 'growth_mode': growth,
                 'rh_24h_volume': str(rv), 'hl_24h_volume': str(hv), 'min_24h_volume': str(min(rv, hv)),
                 'rh_daily_trade_count': r.get('daily_trades_count'),
                 'rh_index_price': str(rp), 'hl_oracle_price': str(hp)}
            selected.append(p)
        except (KeyError, ValueError, ArithmeticError, TypeError) as exc:
            exclusions.append({'asset': a, 'rh_market': rm, 'hl_market': hm, 'reason': str(exc)})
    selected.sort(key=lambda p: (-dec(p['min_24h_volume']), p['asset']))
    if len(selected) > 22 or len({x['rh_market'] for x in selected}) != len(selected):
        raise ValueError('universe_bound_or_duplicate_market')
    return {'selected': selected, 'excluded': exclusions, 'denominator': len(routes)}


def hl_price_valid(p, sd):
    if p == p.to_integral():
        return True
    n = p.normalize()
    return -n.as_tuple().exponent <= 6 - sd and len(n.as_tuple().digits) <= 5


def walk(levels, quantity):
    remaining, notional = quantity, Decimal(0)
    for price, size in levels:
        used = min(remaining, size)
        notional += price * used
        remaining -= used
        if remaining == 0:
            return notional
    raise ValueError('insufficient_hl_depth')


def score(row, market, budget):
    result = {'budget': budget, 'valid': False}
    try:
        if 'error' in row:
            raise ValueError(row['error'])
        rh = row['rh_ticker']
        if rh is None:
            raise ValueError('missing_rh_ticker')
        hl = row['hl_book']
        if hl['coin'] != market['hl_market']:
            raise ValueError('hl_book_identity')
        rs, rr = rh['source_ns'], rh['received_ns']
        hs, hr = int(hl['time']) * 1_000_000, row['hl_received_ns']
        if rr > row['hl_started_ns']:
            raise ValueError('future_ticker_selection')
        if rs > rr or hs > hr:
            raise ValueError('source_ahead_of_receipt')
        if not all(0 <= hr - x <= AGE_NS for x in (rs, rr, hs, hr)):
            raise ValueError('stale_source_or_receipt')
        if abs(rs - hs) > AGE_NS or abs(rr - hr) > AGE_NS:
            raise ValueError('cross_venue_skew')
        ticker = rh['payload']['ticker']
        if ticker['s'] != market['asset']:
            raise ValueError('ticker_symbol')
        bid, ask = dec(ticker['b']['price'], True), dec(ticker['a']['price'], True)
        for side in ('b', 'a'):
            p, s = dec(ticker[side]['price'], True), dec(ticker[side]['size'], True)
            if p % dec(market['rh_price_tick']) or s % dec(market['rh_size_step']):
                raise ValueError('rh_quote_off_grid')
        if bid >= ask:
            raise ValueError('crossed_rh')
        sides = [[(dec(x['px'], True), dec(x['sz'], True)) for x in side] for side in hl['levels']]
        if len(sides) != 2 or not all(sides):
            raise ValueError('empty_hl')
        for side in sides:
            for p, s in side:
                if not hl_price_valid(p, market['hl_size_decimals']) or s % dec(market['hl_size_step']):
                    raise ValueError('hl_quote_off_grid')
        if any(sides[0][i][0] <= sides[0][i+1][0] for i in range(len(sides[0])-1)) or any(sides[1][i][0] >= sides[1][i+1][0] for i in range(len(sides[1])-1)):
            raise ValueError('unsorted_or_duplicate_hl')
        if sides[0][0][0] >= sides[1][0][0]:
            raise ValueError('crossed_hl')
        step = dec(market['common_step'])
        q = (dec(budget) / ask / step).to_integral(rounding=ROUND_FLOOR) * step
        if q <= 0 or q < dec(market['rh_min_qty']):
            raise ValueError('quantity_below_minimum')
        buy, sell = q * bid, q * ask
        if min(buy, sell) < dec(market['rh_min_notional']) or max(buy, sell) > dec(market['rh_max_quote']) or sell > budget:
            raise ValueError('rh_notional_bounds')
        hedge_sell, hedge_buy = walk(sides[0], q), walk(sides[1], q)
        if min(hedge_sell, hedge_buy) < 10:
            raise ValueError('hl_minimum_notional')
        rh_spread = sell - buy
        hl_roundtrip = hedge_sell - hedge_buy
        gross = rh_spread + hl_roundtrip
        fee = (buy + sell) * dec(market['rh_maker_fee_bps']) / 10000 + (hedge_sell + hedge_buy) * dec(market['hl_taker_fee_bps']) / 10000
        margin = gross - fee
        stress = max(buy, hedge_sell) * Decimal('.0005')
        result.update(valid=True, quantity=str(q), rh_bid=str(bid), rh_ask=str(ask),
                      rh_bid_size=ticker['b']['size'], rh_ask_size=ticker['a']['size'],
                      rh_buy_notional=str(buy), rh_sell_notional=str(sell),
                      hl_sell_notional=str(hedge_sell), hl_buy_notional=str(hedge_buy),
                      rh_spread_capture=str(rh_spread), hl_roundtrip_spread_impact=str(hl_roundtrip),
                      gross=str(gross), modeled_fill_fees=str(fee), fee_only_margin=str(margin),
                      after_target=str(margin - Decimal('.10')), stress_allowance=str(stress),
                      after_target_stress=str(margin - Decimal('.10') - stress),
                      rh_source_ns=rs, rh_received_ns=rr, hl_source_ns=hs, hl_received_ns=hr)
    except (KeyError, ValueError, ArithmeticError, TypeError) as exc:
        result['reason'] = str(exc)
    return result


class Feed:
    def __init__(self, markets, store):
        self.by_id = {p['rh_market']: p for p in markets}
        self.store, self.latest = store, {}
        self.ids = set()
        self.round = -1
        self.flow = defaultdict(lambda: {'buy_count': 0, 'sell_count': 0, 'buy_notional': Decimal(0), 'sell_notional': Decimal(0)})
        self.counters = Counter()
        self.incomplete = False
        self.connected = False
        self.subscribed_ns = {}
        self.socket_status = {}
        self.requested_close = False

    async def keepalive(self, ws):
        # Inbound traffic resets aiohttp transport heartbeat. RH independently
        # requires outbound application traffic at least every 120 seconds.
        while True:
            await asyncio.sleep(KEEPALIVE_SECONDS)
            await ws.send_json({'type': 'ping'})
            self.counters['outbound_application_pings'] += 1

    def process(self, payload, receipt):
        kind = payload.get('type', '')
        channel = payload.get('channel', '')
        if ':' not in channel:
            return
        name, mid = channel.split(':', 1)
        if mid not in self.by_id:
            return
        if name == 'ticker' and kind in ('subscribed/ticker', 'update/ticker'):
            try:
                source = int(payload['ticker']['last_updated_at']) * 1000
                old = self.latest.get(mid)
                if source <= 0 or (old and source < old['source_ns']):
                    raise ValueError('older_or_invalid_ticker')
                self.latest[mid] = {'source_ns': source, 'received_ns': receipt, 'payload': payload}
                self.counters['tickers'] += 1
            except (KeyError, ValueError, TypeError):
                self.latest.pop(mid, None)
                self.counters['invalid_tickers'] += 1
        if kind == 'subscribed/trade':
            self.subscribed_ns[mid] = receipt
            self.counters['trade_snapshot_rows_ignored'] += len(payload.get('trades', []))
        if name != 'trade' or kind != 'update/trade':
            return
        for t in payload.get('trades', []):
            try:
                if t['type'] != 'trade' or str(t['market_id']) != mid or not isinstance(t['is_maker_ask'], bool):
                    raise ValueError('trade_identity_or_side')
                ident = str(t.get('trade_id_str', t.get('trade_id')))
                if not ident.isdigit():
                    raise ValueError('trade_id')
                source = int(t['timestamp']) * 1_000_000
                if mid not in self.subscribed_ns or source < self.subscribed_ns[mid] or source > receipt:
                    self.counters['non_post_subscription_trade_ignored'] += 1
                    continue
                key = (mid, ident)
                if key in self.ids:
                    self.counters['duplicate_trades'] += 1
                    continue
                if len(self.ids) >= TRADE_CAP:
                    self.incomplete = True
                    continue
                p, q = dec(t['price'], True), dec(t['size'], True)
                side = 'buy' if t['is_maker_ask'] else 'sell'
                compact = {'asset': self.by_id[mid]['asset'], 'round': self.round,
                           'trade_id': ident, 'side': side, 'price': str(p), 'quantity': str(q),
                           'source_ns': source, 'received_ns': receipt}
                self.store.write('trades.jsonl', compact, raw=True, append=True)
                self.ids.add(key)
                f = self.flow[(self.round, compact['asset'])]
                f[side + '_count'] += 1
                f[side + '_notional'] += p * q
            except (KeyError, ValueError, TypeError, ArithmeticError):
                self.counters['malformed_trades'] += 1

    async def consume(self, ws):
        self.connected = True
        self.socket_status['connected_ns'] = time.time_ns()
        keeper = asyncio.create_task(self.keepalive(ws))
        try:
            async for msg in ws:
                self.socket_status['last_received_ns'] = time.time_ns()
                self.counters['messages'] += 1
                if msg.type == aiohttp.WSMsgType.TEXT:
                    payload = json.loads(msg.data)
                    if payload.get('type') == 'ping':
                        await ws.send_json({'type': 'pong'})
                    else:
                        self.process(payload, time.time_ns())
                elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                    break
        finally:
            self.connected = False
            self.latest.clear()
            keeper.cancel()
            await asyncio.gather(keeper, return_exceptions=True)
            self.socket_status.update(closed_ns=time.time_ns(), close_code=ws.close_code,
                                      requested_close=self.requested_close,
                                      exception=str(ws.exception()) if ws.exception() else None)


async def bounded(response, limit=5_000_000):
    chunks, total = [], 0
    async for b in response.content.iter_chunked(65536):
        total += len(b)
        if total > limit:
            raise CapReached('response_byte_cap')
        chunks.append(b)
    return b''.join(chunks)


async def prepare(out):
    out.mkdir(parents=True, exist_ok=False)
    store = Store(out)
    for name, path in [('source.py', Path(__file__)), ('method.md', METHOD), ('market_plan.json', PLAN),
                       ('tests.py', ROOT / 'tests/test_passive_universe_screen.py')]:
        store.write(name, path.read_bytes(), raw=True, byte_data=True)
    responses, provenance = {}, {}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        for name, (method, url, body) in REQUESTS.items():
            started = time.time_ns()
            async with session.request(method, url, json=body) as r:
                raw = await bounded(r)
                completed = time.time_ns()
                status = r.status
            store.write(name + '.json', raw, raw=True, byte_data=True)
            provenance[name] = {'method': method, 'url': url, 'json_body': body, 'status': status,
                                'started_ns': started, 'completed_ns': completed,
                                'sha256': digest(raw), 'bytes': len(raw)}
            store.write(name + '.request.json', provenance[name], raw=True)
            if status != 200:
                raise ValueError(name + '_http_' + str(status))
            responses[name] = json.loads(raw)
    universe = select(json.loads((out / 'market_plan.json').read_bytes()), responses)
    store.write('universe.json', universe, raw=True)
    hashes = {p.name: digest(p.read_bytes()) for p in out.iterdir() if p.is_file()}
    store.write('freeze.json', {'frozen_utc': utc(), 'hashes': hashes, 'metadata_requests': 3,
                               'rounds': 5, 'interval_seconds': 60, 'maximum_book_requests': 5 * len(universe['selected']),
                               'file_cap_bytes': CAP, 'trade_ledger_cap': TRADE_CAP,
                               'python': __import__('sys').version, 'aiohttp': aiohttp.__version__}, raw=True)
    print(json.dumps({'prepared': str(out), 'frozen_utc': utc(), 'assets': [x['asset'] for x in universe['selected']], 'excluded': universe['excluded']}), flush=True)


def summarize(rows, markets):
    by_asset = defaultdict(list)
    missing = Counter()
    for row in rows:
        for s in row['scores']:
            if not s['valid']:
                missing[s['reason']] += 1
            elif s['budget'] == 1000:
                by_asset[row['asset']].append(dec(s['after_target_stress']))
    ranking, coverage = [], []
    for p in markets:
        a, values = p['asset'], by_asset[p['asset']]
        item = {'asset': a, 'valid_1000_rounds': len(values), 'eligible': len(values) >= 3,
                'median_after_target_stress': str(statistics.median(values)) if values else None,
                'min_24h_volume': p['min_24h_volume']}
        coverage.append(item)
        if item['eligible']:
            ranking.append(item)
    ranking.sort(key=lambda r: (-dec(r['median_after_target_stress']), -dec(r['min_24h_volume']), r['asset']))
    return {'ranking': ranking, 'top_ten_eligible': ranking[:10], 'coverage': coverage,
            'missing_size_observations': dict(missing), 'valid_size_observations': sum(s['valid'] for r in rows for s in r['scores']),
            'total_size_observations': len(rows) * 4, 'interpretation': 'exploratory_static_quotes_not_realized_profit'}


async def capture(out):
    freeze = json.loads((out / 'freeze.json').read_bytes())
    for name, expected in freeze['hashes'].items():
        if digest((out / name).read_bytes()) != expected:
            raise ValueError('frozen_input_changed_' + name)
    if digest(Path(__file__).read_bytes()) != freeze['hashes']['source.py']:
        raise ValueError('execute_frozen_source')
    for name in REQUESTS:
        completed = json.loads((out / (name + '.request.json')).read_bytes())['completed_ns']
        if not 0 <= time.time_ns() - completed <= 30 * 60 * 1_000_000_000:
            raise ValueError('metadata_not_fresh')
    if (out / 'manifest.json').exists():
        raise ValueError('capture_already_attempted')
    markets = json.loads((out / 'universe.json').read_bytes())['selected']
    if not markets:
        raise ValueError('no_eligible_assets')
    store, rows = Store(out), []
    feed = Feed(markets, store)
    manifest = {'started_utc': utc(), 'book_requests': 0, 'round_starts_ns': [], 'rounds_completed': 0,
                'assets': [x['asset'] for x in markets], 'read_only': True, 'status': 'running',
                'warnings': ['Quotes only; no passive fills, funding, financing, USDG/USDC conversion or private queue evidence.']}
    store.write('manifest.json', manifest)
    print(json.dumps({'launch_utc': manifest['started_utc'], 'assets': manifest['assets'], 'max_hl_requests': len(markets) * 5}), flush=True)
    task = None
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.ws_connect(WS, heartbeat=20, max_msg_size=1_000_000) as ws:
                task = asyncio.create_task(feed.consume(ws))
                for p in markets:
                    for name in ('ticker', 'trade'):
                        await ws.send_json({'type': 'subscribe', 'channel': name + '/' + p['rh_market']})
                await asyncio.sleep(3)  # fixed subscription warmup; never quote-dependent
                prior_start = None
                for number in range(5):
                    if prior_start is not None:
                        await asyncio.sleep(max(0, 60 - (time.monotonic() - prior_start)))
                    if task.done():
                        await task
                        raise ValueError('rh_websocket_disconnected')
                    prior_start = time.monotonic()
                    feed.round = number
                    manifest['round_starts_ns'].append(time.time_ns())
                    for p in markets:
                        rh = feed.latest.get(p['rh_market'])  # immutable prior receipt, before HL request
                        row = {'round': number, 'asset': p['asset'], 'rh_ticker': rh, 'hl_started_ns': time.time_ns()}
                        manifest['book_requests'] += 1
                        try:
                            async with session.post(HL, json={'type': 'l2Book', 'coin': p['hl_market']}) as response:
                                raw = await bounded(response, 200_000)
                                row['hl_received_ns'] = time.time_ns()
                                row['hl_http_status'] = response.status
                            row['hl_raw_sha256'] = digest(raw)
                            row['hl_response_text'] = raw.decode('utf-8')
                            row['hl_book'] = json.loads(raw)
                            if row['hl_http_status'] != 200:
                                raise ValueError('hl_http_' + str(row['hl_http_status']))
                        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
                            row['error'] = type(exc).__name__ + ':' + str(exc)[:200]
                        row['scores'] = [score(row, p, b) for b in BUDGETS]
                        store.write('quotes.jsonl', row, raw=True, append=True)
                        rows.append(row)
                    manifest['rounds_completed'] = number + 1
                    store.write('manifest.json', manifest)
                    print(json.dumps({'round_completed': number + 1, 'book_requests': manifest['book_requests'], 'valid_sizes_so_far': sum(s['valid'] for r in rows for s in r['scores']), 'bytes': store.used}), flush=True)
                manifest['status'] = 'completed'
                feed.requested_close = True
                await ws.close()
    except (CapReached, ValueError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
        manifest['status'] = 'stopped'
        manifest['stop_reason'] = type(exc).__name__ + ':' + str(exc)
    finally:
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        manifest.update(finished_utc=utc(), feed_counters=dict(feed.counters), trade_ledger_incomplete=feed.incomplete,
                        bytes_before_final_outputs=store.used, socket_status=feed.socket_status,
                        trade_subscription_receipts_ns=feed.subscribed_ns,
                        captured_quote_rows=len(rows))
        store.write('manifest.json', manifest)
        flows = []
        for (r, a), f in sorted(feed.flow.items()):
            flows.append({'round': r, 'asset': a, **{k: str(v) if isinstance(v, Decimal) else v for k, v in f.items()}})
        store.write('trade_flow.json', {'incomplete': feed.incomplete, 'rows': flows, 'description': 'post-subscription observed aggressor flow; not maker fills'})
        summary = summarize(rows, markets)
        store.write('summary.json', summary)
        print(json.dumps({'status': manifest['status'], 'bytes': store.used, 'summary': summary}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'capture'))
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(prepare(args.out) if args.action == 'prepare' else capture(args.out))


if __name__ == '__main__':
    main()
