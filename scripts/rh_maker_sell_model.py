"""Separate RH maker-sell / HL taker-buy quote research model.

This module shares only book/timing validation and bounded calibration storage
with the frozen buy model. It changes no buy-side fit, code, or policy. Public
trade-through is a flow condition, never a private maker fill.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import math

from scripts.rh_maker_model import (
    RhMakerModel, NS, SIZES, MAX_PENDING, MAX_BOOK_AGE_NS, MAX_PAIR_SKEW_NS,
    FLOW_DUE_NS, CLOSE_EARLIEST_NS, CLOSE_LATEST_NS,
    _num, _dec, _metadata, _common_step, _walk, _parse_book,
)

SELL_MODEL_VERSION = 1
MAX_SIZE_SEGMENTS = 16384
ORIENTATION = 'rh_maker_sell_hl_taker_buy'


def _ceil_tick(price, tick):
    return int((Decimal(str(price))/tick).to_integral_value(rounding=ROUND_CEILING))


def _floor_tick(price, tick):
    return int((Decimal(str(price))/tick).to_integral_value(rounding=ROUND_FLOOR))


class RhMakerSellModel(RhMakerModel):
    """Sell-side calibration and a bounded exact tick search within each lot segment.

    At each ask tick, quantity is the largest common lot affordable at that
    *own ask*. Since quantity changes in steps, the search jumps between
    constant-quantity price segments and binary-searches ticks inside each.
    A hard segment cap fails closed; it never silently selects a later quote.
    Calibration anchors size at the contemporaneous RH best ask; an actual
    higher own ask may require a smaller lot. The per-unit forecast across
    those nearby sizes is an approximation, while quote checks and any later
    simulated fills must use the selected original own-ask quantity.
    """

    def _valid_q(self, asset, q, rh, hl, ask_price, budget):
        rmeta,hmeta=_metadata(self.metadata,asset)
        if q<=0 or ask_price<=rh['bids'][0][0]: return False
        step=_common_step(rmeta['size_step'],hmeta['size_step'])
        qd,pd=Decimal(str(q)),Decimal(str(ask_price))
        if qd%step!=0:return False
        maker_value=qd*pd
        if maker_value>Decimal(str(budget)) or maker_value>Decimal(str(rmeta['max_quote'])):
            return False
        if maker_value<Decimal(str(rmeta['min_notional'])): return False
        if q<float(rmeta['min_qty']) or (rmeta.get('max_qty') is not None and q>float(rmeta['max_qty'])):
            return False
        if hmeta.get('min_qty') is not None and q<float(hmeta['min_qty']): return False
        if hmeta.get('max_qty') is not None and q>float(hmeta['max_qty']): return False
        hl_buy=_walk(hl['asks'],q)
        if hl_buy is None or hl_buy<float(hmeta['min_notional']): return False
        return _walk(hl['bids'],q) is not None and _walk(rh['asks'],q) is not None

    def _qty(self, asset, budget, rh, hl):
        rmeta,hmeta=_metadata(self.metadata,asset)
        step=_common_step(rmeta['size_step'],hmeta['size_step'])
        ask=Decimal(str(rh['asks'][0][0]))
        cap=min(Decimal(str(budget)),Decimal(str(rmeta['max_quote'])))
        q=(cap/ask/step).to_integral_value(rounding=ROUND_FLOOR)*step
        if q<=0: return None
        q=float(q)
        return q if self._valid_q(asset,q,rh,hl,float(ask),float(cap)) else None

    def _close(self, rh, hl, q):
        rh_buy=_walk(rh['asks'],q)
        hl_sell=_walk(hl['bids'],q)
        return None if rh_buy is None or hl_sell is None else (rh_buy-hl_sell)/q

    def _anchor_flow(self, event, now):
        asset=str(event.get('asset'))
        if (asset not in self.assets or str(event.get('venue'))!='rh_lighter'
                or event.get('side')!='buy' or event.get('clock_valid') is False):
            return
        try:
            source=int(event['source_ns'])
            price=_num(event['price'],'trade price')
            _num(event['qty'],'trade quantity')
            if source<=0 or source>now: return
        except (KeyError,TypeError,ValueError):
            return
        pair=self._pair(asset,now)
        if not pair: return
        rh,hl=pair
        # A book produced after a delayed trade cannot label its old flow.
        if rh['source_ns']>source or price+1e-9<rh['asks'][0][0]: return
        trade_id=str(event.get('trade_id',''))
        for size in SIZES:
            key=(asset,size)
            if now-self.last_flow_anchor.get(key,-10**30)<NS: continue
            if trade_id and trade_id in self.last_trade_ids[key]: continue
            q=self._qty(asset,size,rh,hl)
            if q is None: continue
            hl_buy=_walk(hl['asks'],q)
            if hl_buy is None: continue
            if len(self.pending_flow[key])>=MAX_PENDING:
                self.pending_flow[key].popleft()
                self._count(key,'flow_censored_overflow')
            self.pending_flow[key].append({
                'time':now,'due':now+FLOW_DUE_NS,'deadline':now+NS,
                'q':q,'h0':hl_buy/q,'hl_source':hl['source_ns'],
                'hl_generation':hl['generation']})
            self.last_flow_anchor[key]=now
            if trade_id: self.last_trade_ids[key].append(trade_id)
            self._count(key,'flow_admitted')

    def _resolve_pending(self, asset, now, venue):
        for size in SIZES:
            key=(asset,size)
            flow=self.pending_flow[key]
            if venue=='hyperliquid':
                hl=self.books.get(('hyperliquid',asset))
                for a in list(flow):
                    if now>a['deadline']:
                        flow.remove(a);self._count(key,'flow_censored_late');continue
                    if not hl or hl['generation']!=a['hl_generation']:
                        flow.remove(a);self._count(key,'flow_censored_generation');continue
                    if (hl['source_ns']<a['due'] or hl['received_ns']<a['due']
                            or hl['source_ns']<=a['hl_source']):
                        continue
                    flow.remove(a)
                    value=_walk(hl['asks'],a['q'])
                    if value is None:
                        self._count(key,'flow_censored_shallow');continue
                    h1=value/a['q']
                    d=10000*(h1-a['h0'])/a['h0']
                    if math.isfinite(d):
                        self.flow_rows[key].append((a['time'],d))
                        self._count(key,'flow_resolved')
                        if d>10:self._count(key,'flow_above_10bp')
                    else:self._count(key,'flow_censored_nonfinite')
            close=self.pending_close[key]
            for a in list(close):
                if now>a['deadline']:
                    close.remove(a);self._count(key,'close_censored_late');continue
                pair=self._pair(asset,now)
                if not pair:continue
                rh,hl=pair
                if rh['generation']!=a['rh_generation'] or hl['generation']!=a['hl_generation']:
                    close.remove(a);self._count(key,'close_censored_generation');continue
                if min(rh['source_ns'],rh['received_ns'],hl['source_ns'],hl['received_ns'])<a['due']:
                    continue
                if rh['source_ns']<=a['rh_source'] or hl['source_ns']<=a['hl_source']:
                    continue
                close.remove(a)
                future=self._close(rh,hl,a['q'])
                if future is None:
                    self._count(key,'close_censored_shallow');continue
                delta=future-a['c0']
                if math.isfinite(delta):
                    self.close_rows[key].append((a['time'],delta))
                    self._count(key,'close_resolved')
                else:self._count(key,'close_censored_nonfinite')

    def freeze(self, cutoff_ns=None):
        fit=super().freeze(cutoff_ns)
        fit['orientation']=ORIENTATION
        fit['model_version']=SELL_MODEL_VERSION
        fit['assumptions']['flow_side']='RH buy aggressor at/through ask'
        fit['assumptions']['hedge_price']='HL ask VWAP at first postdue book'
        fit['assumptions']['closing_liability']='RH ask walk minus HL bid walk per base unit'
        fit['assumptions']['quote_size']='largest common lot affordable at each own RH ask tick'
        fit['assumptions']['calibration_quantity_basis']='RH best ask reference; per-unit forecast may transfer to smaller own-ask lot'
        fit['assumptions']['max_size_segments']=MAX_SIZE_SEGMENTS
        return fit

    def _quote_pair(self, asset, now, books):
        if books is None:return self._pair(asset,now)
        try:
            rh=books.get('rh',books.get('rh_lighter'))
            hl=books.get('hl',books.get('hyperliquid'))
            pair=(_parse_book(rh),_parse_book(hl))
        except (KeyError,TypeError,ValueError,OverflowError,AttributeError):return None
        if (pair[0]['venue']!='rh_lighter' or pair[1]['venue']!='hyperliquid'
                or pair[0]['asset']!=asset or pair[1]['asset']!=asset):return None
        for b in pair:
            cached=self.books.get((b['venue'],asset))
            if cached and (b['received_ns']<cached['received_ns'] or b['source_ns']<cached['source_ns']):
                return None
        if (any(now<b['received_ns'] or now-b['received_ns']>MAX_BOOK_AGE_NS
                or now<b['source_ns'] or now-b['source_ns']>MAX_BOOK_AGE_NS for b in pair)
                or abs(pair[0]['received_ns']-pair[1]['received_ns'])>MAX_PAIR_SKEW_NS
                or abs(pair[0]['source_ns']-pair[1]['source_ns'])>MAX_PAIR_SKEW_NS):return None
        return pair

    def _economics(self, asset, q, rh, hl, route, policy):
        rmeta,hmeta=_metadata(self.metadata,asset)
        hl_buy=_walk(hl['asks'],q)
        rh_exit=_walk(rh['asks'],q)
        hl_exit=_walk(hl['bids'],q)
        if None in (hl_buy,rh_exit,hl_exit):return None,'shallow_depth'
        h0=hl_buy/q
        c0=(rh_exit-hl_exit)/q
        c_hat=c0+(route['closing_delta_median_per_unit'] or 0.0)
        adverse=route['adverse_p75_bps'] or 0.0
        h_hat=h0*(1+adverse/10000) if policy=='adaptive' else h0
        rh_exit_hat=rh_exit+q*(c_hat-c0)
        if (not all(math.isfinite(x) and x>0 for x in (h0,h_hat,rh_exit_hat,hl_exit))
                or h_hat*q<float(hmeta['min_notional'])):
            return None,'invalid_forecast'
        fees=(float(rmeta['maker_fee_bps']),float(rmeta['taker_fee_bps']),float(hmeta['taker_fee_bps']))
        if not all(0<=x<10000 for x in fees):return None,'invalid_fee_profile'
        return {'h0':h0,'h_hat':h_hat,'c0':c0,'c_hat':c_hat,
                'rh_exit_hat':rh_exit_hat,'hl_exit':hl_exit,'adverse':adverse,
                'fees':fees},None

    @staticmethod
    def _net(price,q,e):
        entry_rh=price*q
        entry_hl=e['h_hat']*q
        rm,rt,ht=e['fees']
        fee=(entry_rh*rm+entry_hl*ht+e['rh_exit_hat']*rt+e['hl_exit']*ht)/10000
        reserve=max(entry_rh,entry_hl)*5/10000
        capital=(entry_rh+entry_hl)*.05*10/(365*24*3600)
        return q*(price-e['h_hat']-e['c_hat'])-fee-reserve-capital

    def quote(self, asset, budget_usd, policy, books=None, now_ns=None):
        if policy not in ('adaptive','persistence','fixed_best'):raise ValueError('unknown policy')
        budget=_num(budget_usd,'budget')
        if budget not in SIZES:raise ValueError('unfrozen size')
        now=self.last_event_ns if now_ns is None else int(now_ns)
        out={'policy':policy,'orientation':ORIENTATION,'model_version':SELL_MODEL_VERSION,
             'asset':asset,'budget_usd':budget,'price':None,'quantity':None,
             'forecast_net_usd':None,'reason':None,'quote_time_ns':now,
             'rh_bid':None,'rh_ask':None,'hl_ask_vwap':None,
             'size_forecast_approximation':'calibration best-ask lot to selected own-ask lot'}
        if self.fit is None or now<self.cutoff_ns or now>=self.end_ns:
            out['reason']='outside_holdout';return out
        if asset not in self.assets:out['reason']='unknown_asset';return out
        pair=self._quote_pair(asset,now,books)
        if pair is None:out['reason']='invalid_pair';return out
        rh,hl=pair
        out.update(rh_bid=rh['bids'][0][0],rh_ask=rh['asks'][0][0])
        route=self.fit['routes'][f'{asset}|{int(budget)}']
        out['model_ready']=route['ready']
        if policy!='fixed_best' and not route['ready']:
            out['reason']='model_unready';return out
        rmeta,hmeta=_metadata(self.metadata,asset)
        tick=_dec(rmeta['price_tick'],'price_tick')
        step=_common_step(rmeta['size_step'],hmeta['size_step'])
        cap=min(Decimal(str(budget)),Decimal(str(rmeta['max_quote'])))
        min_tick=max(1,_floor_tick(rh['bids'][0][0],tick)+1)
        # No valid positive quantity beyond this tick. Decimal arithmetic
        # avoids floating point budget overruns on tiny order grids.
        max_tick=int((cap/step/tick).to_integral_value(rounding=ROUND_FLOOR))
        if min_tick>max_tick:out['reason']='no_valid_tick';return out
        def candidate(k,q):
            p=float(tick*k)
            if not self._valid_q(asset,q,rh,hl,p,budget):return None,'no_valid_order'
            e,reason=self._economics(asset,q,rh,hl,route,policy)
            if e is None:return None,reason
            return {'k':k,'p':p,'q':q,'e':e,'net':self._net(p,q,e)},None
        selected=None
        if policy=='fixed_best':
            raw=Decimal(str(rh['asks'][0][0]))/tick
            if raw!=raw.to_integral_value():out['reason']='best_ask_off_grid';return out
            k=int(raw)
            if not min_tick<=k<=max_tick:out['reason']='no_valid_tick';return out
            units=int((cap/(tick*k)/step).to_integral_value(rounding=ROUND_FLOOR))
            selected,reason=candidate(k,float(step*units))
            if selected is None:out['reason']=reason;return out
        else:
            k=min_tick;segments=0
            while k<=max_tick and segments<MAX_SIZE_SEGMENTS:
                segments+=1
                units=int((cap/(tick*k)/step).to_integral_value(rounding=ROUND_FLOOR))
                if units<=0:break
                q=float(step*units)
                if q<float(rmeta['min_qty']) or (hmeta.get('min_qty') is not None and q<float(hmeta['min_qty'])):
                    break
                if _walk(hl['asks'],q) is not None and _walk(hl['asks'],q)<float(hmeta['min_notional']):
                    break
                end=min(max_tick,int((cap/(step*units)/tick).to_integral_value(rounding=ROUND_FLOOR)))
                if end<k:raise AssertionError('quantity segment regressed')
                at_end,reason=candidate(end,q)
                if at_end is not None and at_end['net']>=.10:
                    lo,hi=k,end
                    while lo<hi:
                        mid=(lo+hi)//2
                        at_mid,_=candidate(mid,q)
                        if at_mid is not None and at_mid['net']>=.10:hi=mid
                        else:lo=mid+1
                    selected,reason=candidate(lo,q)
                    if selected is not None and selected['net']>=.10:break
                    selected=None
                k=end+1
            if selected is None:
                out['reason']='size_segment_limit' if segments>=MAX_SIZE_SEGMENTS and k<=max_tick else 'forecast_below_target_or_invalid'
                out['size_segments_checked']=segments
                return out
            out['size_segments_checked']=segments
        e=selected['e']
        out.update(price=selected['p'],quantity=selected['q'],forecast_net_usd=selected['net'],
                   reason='quote',hl_ask_vwap=e['h0'],forecast_hedge_vwap=e['h_hat'],
                   forecast_closing_liability_per_unit=e['c_hat'],
                   flow_adverse_p75_bps=e['adverse'] if policy=='adaptive' else 0.0,
                   rh_tick=str(tick))
        return out

    def snapshot(self):
        result=super().snapshot()
        result['model_version']=SELL_MODEL_VERSION
        result['orientation']=ORIENTATION
        return result
