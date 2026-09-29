"""Frozen, public-data RH maker quote calibration and pure quote pricing.

This is a quote-screen experiment. It never simulates private fills or sends
orders. Receipt/source checks are timing proxies, not synchronized execution.
"""
from __future__ import annotations

from collections import Counter, deque
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_CEILING
import math
import statistics

MODEL_VERSION = 1
NS = 1_000_000_000
SIZES = (100, 250, 500, 1000)
MAX_SAMPLES = 4096
MAX_PENDING = 4
MAX_BOOK_AGE_NS = 2 * NS
MAX_PAIR_SKEW_NS = NS
FLOW_DUE_NS = 150_000_000
FLOW_DEADLINE_NS = NS
CLOSE_EARLIEST_NS = 10 * NS
CLOSE_LATEST_NS = 16 * NS


def _num(value, label, *, zero=False):
    x = float(value)
    if not math.isfinite(x) or x < 0 or (not zero and x == 0):
        raise ValueError(f'invalid {label}')
    return x


def _dec(value, label, *, zero=False):
    try:
        x = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f'invalid {label}') from exc
    if not x.is_finite() or x < 0 or (not zero and x == 0):
        raise ValueError(f'invalid {label}')
    return x


def _pct(values, pct):
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * pct
    lo, hi = math.floor(k), math.ceil(k)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def _walk(levels, qty):
    left = qty
    value = 0.0
    for p, size in levels:
        take = min(left, size)
        value += p * take
        left -= take
        if left <= qty * 1e-12:
            return value
    return None


def _levels(rows, descending):
    if not isinstance(rows, (list, tuple)) or not rows:
        raise ValueError('missing levels')
    out = []
    for row in rows:
        if isinstance(row, dict):
            p = row.get('price', row.get('px'))
            q = row.get('qty', row.get('size', row.get('sz')))
        else:
            p, q = row[:2]
        p, q = _num(p, 'price'), _num(q, 'size')
        out.append((p, q))
    for a, b in zip(out, out[1:]):
        if (a[0] <= b[0]) if descending else (a[0] >= b[0]):
            raise ValueError('unordered book')
    return out


def _common_step(a, b):
    a, b = _dec(a, 'size_step'), _dec(b, 'size_step')
    scale = 10 ** max(0, -a.as_tuple().exponent, -b.as_tuple().exponent)
    return Decimal(math.lcm(int(a * scale), int(b * scale))) / scale


def _metadata(data, asset):
    if asset in data:
        x = data[asset]
        return x.get('rh', x.get('rh_lighter')), x.get('hl', x.get('hyperliquid'))
    return data['rh_lighter'][asset], data['hyperliquid'][asset]


def _stamp(event):
    return int(event.get('received_ns', event.get('receipt_ns')))


def _parse_book(event):
    ts = _stamp(event)
    source = int(event['source_ns'])
    if ts <= 0 or source <= 0 or source > ts or event.get('clock_valid') is False or event.get('valid') is False:
        raise ValueError('invalid timestamps or book')
    bids = _levels(event['bids'], True)
    asks = _levels(event['asks'], False)
    if bids[0][0] >= asks[0][0]:
        raise ValueError('crossed book')
    return {'asset': str(event['asset']), 'venue': str(event['venue']), 'received_ns': ts,
            'source_ns': source, 'generation': str(event['generation']),
            'sequence': str(event.get('sequence', '')), 'bids': bids, 'asks': asks}


class RhMakerModel:
    """Bounded calibration with strictly prior data and immutable holdout fit."""

    def __init__(self, metadata_by_asset, start_ns, calibration_seconds=1800, holdout_seconds=1200):
        self.metadata = metadata_by_asset
        self.start_ns = int(start_ns)
        self.cutoff_ns = self.start_ns + int(calibration_seconds * NS)
        self.end_ns = self.cutoff_ns + int(holdout_seconds * NS)
        if self.start_ns <= 0 or self.cutoff_ns <= self.start_ns or self.end_ns <= self.cutoff_ns:
            raise ValueError('invalid timeline')
        self.books = {}
        self.pending_flow = {}
        self.pending_close = {}
        self.flow_rows = {}
        self.close_rows = {}
        self.last_flow_anchor = {}
        self.last_close_anchor = {}
        self.last_trade_ids = {}
        self.counts = Counter()
        self.route_counts = {}
        self.fit = None
        self.last_event_ns = self.start_ns
        self.assets = sorted(metadata_by_asset.keys() if 'rh_lighter' not in metadata_by_asset else metadata_by_asset['rh_lighter'].keys())
        for asset in self.assets:
            rh, hl = _metadata(self.metadata, asset)
            if not rh or not hl:
                raise ValueError(f'missing venue metadata {asset}')
            # Economic assumptions must be frozen by caller, never silently free.
            for label, meta, fields in [('rh', rh, ('price_tick','size_step','min_qty','min_notional','max_quote','maker_fee_bps','taker_fee_bps')),
                                        ('hl', hl, ('size_step','min_notional','taker_fee_bps'))]:
                for field in fields:
                    _dec(meta[field], f'{asset} {label} {field}', zero=field.endswith('fee_bps'))
            _common_step(rh['size_step'], hl['size_step'])
            for size in SIZES:
                key = (asset, size)
                self.pending_flow[key] = deque(maxlen=MAX_PENDING)
                self.pending_close[key] = deque(maxlen=MAX_PENDING)
                self.flow_rows[key] = deque(maxlen=MAX_SAMPLES)
                self.close_rows[key] = deque(maxlen=MAX_SAMPLES)
                self.route_counts[key] = Counter()
                self.last_trade_ids[key] = deque(maxlen=256)

    def _count(self, key, reason):
        self.counts[reason] += 1
        self.route_counts[key][reason] += 1

    def _pair(self, asset, now):
        rh = self.books.get(('rh_lighter', asset))
        hl = self.books.get(('hyperliquid', asset))
        if not rh or not hl:
            return None
        if any(now < b['received_ns'] or now - b['received_ns'] > MAX_BOOK_AGE_NS or now < b['source_ns'] or now - b['source_ns'] > MAX_BOOK_AGE_NS for b in (rh, hl)):
            return None
        if abs(rh['received_ns'] - hl['received_ns']) > MAX_PAIR_SKEW_NS or abs(rh['source_ns'] - hl['source_ns']) > MAX_PAIR_SKEW_NS:
            return None
        return rh, hl

    def _qty(self, asset, budget, rh, hl):
        rmeta, hmeta = _metadata(self.metadata, asset)
        step = _common_step(rmeta['size_step'], hmeta['size_step'])
        qty = (Decimal(str(budget)) / Decimal(str(rh['asks'][0][0])) / step).to_integral_value(rounding=ROUND_FLOOR) * step
        if qty <= 0:
            return None
        q = float(qty)
        hl_bid = _walk(hl['bids'], q)
        if hl_bid is None:
            return None
        if q < float(rmeta['min_qty']) or (rmeta.get('max_qty') is not None and q > float(rmeta['max_qty'])):
            return None
        # RH maker bid does not consume asks; its actual candidate price
        # receives the min/max notional check in quote().
        if hl_bid < float(hmeta['min_notional']):
            return None
        if hmeta.get('min_qty') is not None and q < float(hmeta['min_qty']):
            return None
        if hmeta.get('max_qty') is not None and q > float(hmeta['max_qty']):
            return None
        return q

    def _close(self, rh, hl, q):
        hb = _walk(hl['asks'], q)
        rs = _walk(rh['bids'], q)
        return None if hb is None or rs is None else (hb-rs)/q

    def _invalidate(self, venue, asset, reason):
        self.books.pop((venue, asset), None)
        for size in SIZES:
            key = (asset, size)
            if key not in self.pending_flow:
                continue
            for name, table in [('flow', self.pending_flow), ('close', self.pending_close)]:
                while table[key]:
                    table[key].popleft()
                    self._count(key, f'{name}_censored_{reason}')

    def _expire_pending(self, now):
        for key in self.pending_flow:
            for name, table in [('flow', self.pending_flow), ('close', self.pending_close)]:
                for anchor in list(table[key]):
                    if anchor['deadline'] < now:
                        table[key].remove(anchor)
                        self._count(key, f'{name}_censored_late')

    def consume(self, event):
        kind = event.get('type', event.get('kind'))
        if kind == 'end':
            return
        now = _stamp(event)
        if now < self.last_event_ns:
            raise ValueError('events out of receipt order')
        self.last_event_ns = now
        if self.fit is None:
            self._expire_pending(min(now, self.cutoff_ns))
        if self.fit is None and now >= self.cutoff_ns:
            self.freeze(self.cutoff_ns)
        if kind == 'invalidate':
            asset = str(event['asset'])
            if asset in self.assets:
                self._invalidate(str(event.get('venue')), asset, 'invalidated')
            return
        if kind == 'book':
            venue, asset = str(event['venue']), str(event['asset'])
            if venue not in ('rh_lighter','hyperliquid') or asset not in self.assets:
                return
            try:
                book = _parse_book(event)
            except (KeyError, TypeError, ValueError, OverflowError):
                self._invalidate(venue, asset, 'invalid_book')
                return
            old = self.books.get((venue,asset))
            if old and (old['generation'] != book['generation'] or book['source_ns'] < old['source_ns'] or book['received_ns'] < old['received_ns']):
                self._invalidate(venue, asset, 'generation_or_regression')
            self.books[(venue,asset)] = book
            if self.fit is None:
                self._resolve_pending(asset, now, venue)
                self._anchor_closing(asset, now)
            return
        if kind == 'trade' and self.fit is None:
            self._anchor_flow(event, now)

    def _resolve_pending(self, asset, now, venue):
        for size in SIZES:
            key = (asset,size)
            flow = self.pending_flow[key]
            if venue == 'hyperliquid':
                hl = self.books.get(('hyperliquid',asset))
                for a in list(flow):
                    if now > a['deadline']:
                        flow.remove(a); self._count(key,'flow_censored_late'); continue
                    if not hl or hl['generation'] != a['hl_generation']:
                        flow.remove(a); self._count(key,'flow_censored_generation'); continue
                    if hl['source_ns'] < a['due'] or hl['received_ns'] < a['due'] or hl['source_ns'] <= a['hl_source']:
                        continue
                    flow.remove(a)
                    value = _walk(hl['bids'], a['q'])
                    if value is None:
                        self._count(key,'flow_censored_shallow'); continue
                    h1 = value/a['q']
                    d = 10000*(a['h0']-h1)/a['h0']
                    if math.isfinite(d):
                        self.flow_rows[key].append((a['time'], d))
                        self._count(key,'flow_resolved')
                        if d > 10: self._count(key,'flow_above_10bp')
                    else:
                        self._count(key,'flow_censored_nonfinite')
            close = self.pending_close[key]
            for a in list(close):
                if now > a['deadline']:
                    close.remove(a); self._count(key,'close_censored_late'); continue
                pair = self._pair(asset, now)
                if not pair:
                    continue
                rh, hl = pair
                if rh['generation'] != a['rh_generation'] or hl['generation'] != a['hl_generation']:
                    close.remove(a); self._count(key,'close_censored_generation'); continue
                if min(rh['source_ns'],rh['received_ns'],hl['source_ns'],hl['received_ns']) < a['due']:
                    continue
                if rh['source_ns'] <= a['rh_source'] or hl['source_ns'] <= a['hl_source']:
                    continue
                close.remove(a)
                future = self._close(rh,hl,a['q'])
                if future is None:
                    self._count(key,'close_censored_shallow'); continue
                delta = future-a['c0']
                if math.isfinite(delta):
                    self.close_rows[key].append((a['time'],delta))
                    self._count(key,'close_resolved')
                else:
                    self._count(key,'close_censored_nonfinite')

    def _anchor_closing(self, asset, now):
        pair = self._pair(asset, now)
        if not pair: return
        rh, hl = pair
        for size in SIZES:
            key = (asset,size)
            if now - self.last_close_anchor.get(key, -10**30) < CLOSE_EARLIEST_NS:
                continue
            q = self._qty(asset,size,rh,hl)
            if q is None: continue
            c = self._close(rh,hl,q)
            if c is None: continue
            if len(self.pending_close[key]) >= MAX_PENDING:
                self._count(key,'close_censored_overflow')
                self.pending_close[key].popleft()
            self.pending_close[key].append({'time':now,'due':now+CLOSE_EARLIEST_NS,'deadline':now+CLOSE_LATEST_NS,
                                            'q':q,'c0':c,'rh_source':rh['source_ns'],'hl_source':hl['source_ns'],
                                            'rh_generation':rh['generation'],'hl_generation':hl['generation']})
            self.last_close_anchor[key] = now
            self._count(key,'close_admitted')

    def _anchor_flow(self, event, now):
        asset = str(event.get('asset'))
        if asset not in self.assets or str(event.get('venue')) != 'rh_lighter' or event.get('side') != 'sell' or event.get('clock_valid') is False:
            return
        try:
            source = int(event['source_ns'])
            price = _num(event['price'],'trade price')
            trade_qty = _num(event['qty'],'trade quantity')
            if source > now or source <= 0: return
        except (KeyError,TypeError,ValueError):
            return
        pair = self._pair(asset,now)
        if not pair: return
        rh,hl = pair
        if rh['source_ns'] > source:
            # A late trade cannot be labelled against a book produced later.
            return
        if price > rh['bids'][0][0] + 1e-9: return
        trade_id = str(event.get('trade_id',''))
        for size in SIZES:
            key=(asset,size)
            if now-self.last_flow_anchor.get(key,-10**30) < NS: continue
            if trade_id and trade_id in self.last_trade_ids[key]: continue
            q=self._qty(asset,size,rh,hl)
            if q is None: continue
            value=_walk(hl['bids'],q)
            if value is None: continue
            if len(self.pending_flow[key]) >= MAX_PENDING:
                self._count(key,'flow_censored_overflow'); self.pending_flow[key].popleft()
            self.pending_flow[key].append({'time':now,'due':now+FLOW_DUE_NS,'deadline':now+FLOW_DEADLINE_NS,
                                           'q':q,'h0':value/q,'hl_source':hl['source_ns'],'hl_generation':hl['generation']})
            self.last_flow_anchor[key]=now
            if trade_id: self.last_trade_ids[key].append(trade_id)
            self._count(key,'flow_admitted')

    def freeze(self, cutoff_ns=None):
        cutoff = self.cutoff_ns if cutoff_ns is None else int(cutoff_ns)
        if cutoff != self.cutoff_ns: raise ValueError('freeze at declared cutoff only')
        if self.fit is not None: return self.fit
        for key in self.pending_flow:
            for name,table in [('flow',self.pending_flow),('close',self.pending_close)]:
                while table[key]:
                    table[key].popleft(); self._count(key,f'{name}_censored_cutoff')
        routes={}
        for key in self.flow_rows:
            asset,size=key
            fc=self.route_counts[key]
            flows=list(self.flow_rows[key]); closes=list(self.close_rows[key])
            fspan=(flows[-1][0]-flows[0][0])/NS if len(flows)>1 else 0
            cspan=(closes[-1][0]-closes[0][0])/NS if len(closes)>1 else 0
            fcover=len(flows)/fc['flow_admitted'] if fc['flow_admitted'] else 0
            ccover=len(closes)/fc['close_admitted'] if fc['close_admitted'] else 0
            fready=len(flows)>=20 and fspan>=600 and fcover>=.5
            cready=len(closes)>=30 and cspan>=600 and ccover>=.5
            routes[f'{asset}|{size}']={'asset':asset,'size':size,'flow_admitted':fc['flow_admitted'],
                'flow_resolved':len(flows),'flow_coverage':fcover,'flow_span_seconds':fspan,
                'close_admitted':fc['close_admitted'],'close_resolved':len(closes),
                'close_coverage':ccover,'close_span_seconds':cspan,
                'flow_ready':fready,'close_ready':cready,'ready':fready and cready,
                'adverse_p75_bps':max(0.0,_pct([d for _,d in flows],.75)) if flows else None,
                'closing_delta_median_per_unit':statistics.median(d for _,d in closes) if closes else None,
                'flow_distribution_bps':{'p10':_pct([d for _,d in flows],.1),'p50':_pct([d for _,d in flows],.5),'p75':_pct([d for _,d in flows],.75),'p90':_pct([d for _,d in flows],.9)},
                'closing_delta_distribution_per_unit':{'p10':_pct([d for _,d in closes],.1),'p50':_pct([d for _,d in closes],.5),'p90':_pct([d for _,d in closes],.9)},
                'flow_samples_time_bps':[[t,d] for t,d in flows],
                'closing_samples_time_delta_per_unit':[[t,d] for t,d in closes],
                'counts':dict(fc)}
        self.fit={'model_version':MODEL_VERSION,'cutoff_ns':cutoff,'start_ns':self.start_ns,
                  'end_ns':self.end_ns,'routes':routes,'assumptions':{
                    'flow_due_ms':150,'flow_deadline_ms':1000,'close_window_seconds':[10,16],
                    'flow_min_resolved':20,'close_min_resolved':30,'min_span_seconds':600,
                    'min_resolution_fraction':.5,'flow_quantile':.75,'reserve_bps':5,
                    'capital_annual_rate':.05,'capital_hold_seconds':10,
                    'target_net_usd':.10,'standard_fee_profile':'caller_frozen_metadata'}}
        return self.fit

    def quote(self, asset, budget_usd, policy, books=None, now_ns=None):
        if policy not in ('adaptive','persistence','fixed_best'):
            raise ValueError('unknown policy')
        budget = _num(budget_usd,'budget')
        if budget not in SIZES: raise ValueError('unfrozen size')
        now = self.last_event_ns if now_ns is None else int(now_ns)
        out={'policy':policy,'asset':asset,'budget_usd':budget,'price':None,'quantity':None,
             'forecast_net_usd':None,'reason':None,'quote_time_ns':now,'model_version':MODEL_VERSION,
             'rh_bid':None,'rh_ask':None,'hl_bid_vwap':None}
        if self.fit is None or now < self.cutoff_ns or now >= self.end_ns:
            out['reason']='outside_holdout'; return out
        if asset not in self.assets: out['reason']='unknown_asset'; return out
        if books is None:
            pair=self._pair(asset,now)
        else:
            rh=books.get('rh',books.get('rh_lighter')); hl=books.get('hl',books.get('hyperliquid'))
            try: pair=(_parse_book(rh),_parse_book(hl))
            except (KeyError,TypeError,ValueError,OverflowError): pair=None
            if pair and (any(now < b['received_ns'] or now-b['received_ns']>MAX_BOOK_AGE_NS or now < b['source_ns'] or now-b['source_ns']>MAX_BOOK_AGE_NS for b in pair)
                         or abs(pair[0]['received_ns']-pair[1]['received_ns'])>MAX_PAIR_SKEW_NS
                         or abs(pair[0]['source_ns']-pair[1]['source_ns'])>MAX_PAIR_SKEW_NS): pair=None
        if not pair: out['reason']='invalid_pair'; return out
        rh,hl=pair
        out.update(rh_bid=rh['bids'][0][0],rh_ask=rh['asks'][0][0])
        q=self._qty(asset,budget,rh,hl)
        if q is None: out['reason']='no_valid_order'; return out
        out['quantity']=q
        h0=_walk(hl['bids'],q)/q
        out['hl_bid_vwap']=h0
        c0=self._close(rh,hl,q)
        if c0 is None: out['reason']='shallow_close'; return out
        route=self.fit['routes'][f'{asset}|{int(budget)}']
        out['model_ready']=route['ready']
        if policy!='fixed_best' and not route['ready']:
            out['reason']='model_unready'; return out
        rmeta,hmeta=_metadata(self.metadata,asset)
        tick=_dec(rmeta['price_tick'],'price_tick')
        max_tick=int((Decimal(str(rh['asks'][0][0]))/tick).to_integral_value(rounding=ROUND_CEILING))-1
        min_tick=max(1,int((Decimal(str(rmeta['min_notional']))/(Decimal(str(q))*tick)).to_integral_value(rounding=ROUND_CEILING)))
        max_tick=min(max_tick,int((Decimal(str(rmeta['max_quote']))/(Decimal(str(q))*tick)).to_integral_value(rounding=ROUND_FLOOR)),
                     int((Decimal(str(budget))/(Decimal(str(q))*tick)).to_integral_value(rounding=ROUND_FLOOR)))
        if min_tick>max_tick: out['reason']='no_valid_tick'; return out
        c_hat=c0+(route['closing_delta_median_per_unit'] or 0.0)
        adverse=route['adverse_p75_bps'] or 0.0
        h_hat=h0*(1-adverse/10000) if policy=='adaptive' else h0
        if not math.isfinite(h_hat) or h_hat <= 0:
            out['reason']='invalid_hedge_forecast'; return out
        if h_hat*q < float(hmeta['min_notional']):
            out['reason']='forecast_hedge_below_minimum'; return out
        exit_rh=_walk(rh['bids'],q)
        exit_hl=_walk(hl['asks'],q)
        if exit_rh is None or exit_hl is None: out['reason']='shallow_close'; return out
        # Allocate the predicted closing-basis change to HL buyback for fee
        # estimation; RH exit stays at its current executable bid walk.
        exit_hl_hat=exit_hl+q*(c_hat-c0)
        if not math.isfinite(exit_hl_hat) or exit_hl_hat <= 0:
            out['reason']='invalid_exit_forecast'; return out
        rh_maker=float(rmeta['maker_fee_bps']); rh_taker=float(rmeta['taker_fee_bps']); hl_taker=float(hmeta['taker_fee_bps'])
        def net(t):
            p=float(tick*t)
            entry_rh=p*q; entry_hl=h_hat*q
            fees=(entry_rh*rh_maker+entry_hl*hl_taker+exit_rh*rh_taker+exit_hl_hat*hl_taker)/10000
            reserve=max(entry_rh,entry_hl)*5/10000
            capital=(entry_rh+entry_hl)*.05*10/(365*24*3600)
            return q*(h_hat-p-c_hat)-fees-reserve-capital
        if policy=='fixed_best':
            bid_tick=Decimal(str(rh['bids'][0][0]))/tick
            if bid_tick!=bid_tick.to_integral_value() or not min_tick<=int(bid_tick)<=max_tick:
                out['reason']='best_bid_off_grid'; return out
            selected=int(bid_tick)
        else:
            if net(min_tick)<.10:
                out['reason']='forecast_below_target'; out['forecast_net_usd']=net(min_tick); return out
            lo,hi=min_tick,max_tick
            while lo<hi:
                mid=(lo+hi+1)//2
                if net(mid)>=.10: lo=mid
                else: hi=mid-1
            selected=lo
        out.update(price=float(tick*selected),forecast_net_usd=net(selected),reason='quote',
                   forecast_hedge_vwap=h_hat,forecast_closing_liability_per_unit=c_hat,
                   flow_adverse_p75_bps=adverse if policy=='adaptive' else 0.0,
                   rh_tick=str(tick))
        return out

    def snapshot(self):
        return {'model_version':MODEL_VERSION,'start_ns':self.start_ns,'cutoff_ns':self.cutoff_ns,
                'end_ns':self.end_ns,'frozen':self.fit is not None,'fit':self.fit,
                'counts':dict(self.counts),'pending_flow':sum(map(len,self.pending_flow.values())),
                'pending_close':sum(map(len,self.pending_close.values()))}
