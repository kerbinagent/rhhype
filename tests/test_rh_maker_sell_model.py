import json
import math
import random
import unittest
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path

from scripts.rh_maker_sell_model import RhMakerSellModel, NS, ORIENTATION
from scripts.rh_maker_model import _common_step, _metadata

T0 = 2_000_000_000_000


def metadata(rh_maker='1', rh_taker='2', hl_taker='3'):
    return {'BTC': {'rh': {'price_tick':'0.1','size_step':'0.1','min_qty':'0.1',
                           'min_notional':'10','max_quote':'2000',
                           'maker_fee_bps':rh_maker,'taker_fee_bps':rh_taker},
                    'hl': {'size_step':'0.1','min_notional':'10',
                           'taker_fee_bps':hl_taker}}}


def book(venue, at, bid=9.8, ask=10.0, depth=500, generation='a', source=None):
    return {'type':'book','venue':venue,'asset':'BTC','generation':generation,
            'received_ns':at,'source_ns':at if source is None else source,
            'valid':True,'clock_valid':True,
            'bids':[[bid,depth]],'asks':[[ask,depth]]}


def pair(m,at,rh_bid=9.8,rh_ask=10,hl_bid=9.8,hl_ask=10):
    m.consume(book('rh_lighter',at,bid=rh_bid,ask=rh_ask))
    m.consume(book('hyperliquid',at,bid=hl_bid,ask=hl_ask))


def trade(at, side='buy', price=10, source=None, ident='x'):
    return {'type':'trade','venue':'rh_lighter','asset':'BTC','side':side,
            'price':price,'qty':1,'trade_id':ident,'received_ns':at,
            'source_ns':at if source is None else source,'clock_valid':True}


class SellModelTest(unittest.TestCase):
    def test_sign_correct_closing_liability_and_trade_label(self):
        m=RhMakerSellModel(metadata(),T0,calibration_seconds=30)
        pair(m,T0,rh_bid=9.8,rh_ask=10.2,hl_bid=9.7,hl_ask=10)
        rh,hl=m._pair('BTC',T0)
        self.assertAlmostEqual(m._close(rh,hl,1),.5)
        m.consume(trade(T0+1,side='sell',price=9.8,ident='sell'))
        self.assertEqual(m.route_counts[('BTC',1000)]['flow_admitted'],0)
        m.consume(trade(T0+2,side='buy',price=10.2,ident='buy'))
        self.assertEqual(m.route_counts[('BTC',1000)]['flow_admitted'],1)
        self.assertEqual(m.pending_flow[('BTC',1000)][0]['h0'],10)

    def test_first_postdue_hl_ask_uses_original_quantity_and_censors_shallow(self):
        m=RhMakerSellModel(metadata(),T0,calibration_seconds=30)
        pair(m,T0)
        m.consume(trade(T0+1))
        q=m.pending_flow[('BTC',1000)][0]['q']
        self.assertEqual(q,100)
        m.consume(book('hyperliquid',T0+200_000_000,bid=9.8,ask=10.1,depth=.1))
        self.assertEqual(m.route_counts[('BTC',1000)]['flow_censored_shallow'],1)
        m.consume(book('hyperliquid',T0+300_000_000,bid=9.8,ask=10.2))
        self.assertEqual(m.route_counts[('BTC',1000)]['flow_resolved'],0)

    def test_adverse_ask_move_is_positive_and_over_cap_retained(self):
        m=RhMakerSellModel(metadata(),T0,calibration_seconds=30)
        pair(m,T0)
        m.consume(trade(T0+1))
        m.consume(book('hyperliquid',T0+200_000_000,bid=10.0,ask=10.1))
        d=m.flow_rows[('BTC',1000)][0][1]
        self.assertAlmostEqual(d,100)
        self.assertEqual(m.route_counts[('BTC',1000)]['flow_above_10bp'],1)

    def test_first_future_pair_shallow_censors_original_quantity(self):
        m=RhMakerSellModel(metadata(),T0,calibration_seconds=40)
        pair(m,T0)
        q=m.pending_close[('BTC',1000)][0]['q']
        self.assertEqual(q,100)
        m.consume(book('rh_lighter',T0+11*NS,bid=9.8,ask=10,depth=.1))
        m.consume(book('hyperliquid',T0+11*NS,bid=9.8,ask=10))
        self.assertEqual(m.route_counts[('BTC',1000)]['close_censored_shallow'],1)
        m.consume(book('rh_lighter',T0+12*NS,bid=9.8,ask=10))
        self.assertEqual(m.route_counts[('BTC',1000)]['close_resolved'],0)

    def test_cutoff_excludes_current_and_future_books(self):
        m=RhMakerSellModel(metadata(),T0,calibration_seconds=20)
        pair(m,T0+19*NS)
        m.consume(trade(T0+19*NS+1))
        m.consume(book('hyperliquid',T0+20*NS,bid=9.8,ask=12))
        self.assertEqual(m.fit['orientation'],ORIENTATION)
        self.assertEqual(m.fit['routes']['BTC|1000']['flow_resolved'],0)
        self.assertEqual(m.route_counts[('BTC',1000)]['flow_censored_cutoff'],1)
        fit=m.fit
        m.consume(book('rh_lighter',T0+21*NS))
        self.assertIs(m.fit,fit)

    def test_quote_grid_budget_fee_sign_and_adverse_adjustment(self):
        m=RhMakerSellModel(metadata(),T0,calibration_seconds=20)
        pair(m,T0);m.freeze();at=T0+20*NS;pair(m,at)
        fixed=m.quote('BTC',1000,'fixed_best',now_ns=at)
        self.assertEqual(fixed['price'],10)
        self.assertLess(fixed['forecast_net_usd'],0)
        self.assertEqual(fixed['orientation'],ORIENTATION)
        self.assertEqual(m.quote('BTC',1000,'adaptive',now_ns=at)['reason'],'model_unready')
        route=m.fit['routes']['BTC|1000']
        route.update(ready=True,flow_ready=True,close_ready=True,
                     adverse_p75_bps=100,closing_delta_median_per_unit=0)
        persist=m.quote('BTC',1000,'persistence',now_ns=at)
        adaptive=m.quote('BTC',1000,'adaptive',now_ns=at)
        self.assertEqual(persist['reason'],'quote')
        self.assertEqual(adaptive['reason'],'quote')
        self.assertGreaterEqual(adaptive['price'],persist['price'])
        self.assertLessEqual(adaptive['price']*adaptive['quantity'],1000+1e-8)
        self.assertGreaterEqual(adaptive['forecast_net_usd'],.10)
        self.assertLess(adaptive['quantity'],100)  # own ask above best shrinks size
        # Four fee-bearing notionals with correct signs, plus reserve/capital.
        e,_=m._economics('BTC',adaptive['quantity'],*m._pair('BTC',at),route,'adaptive')
        p,q=adaptive['price'],adaptive['quantity']
        rm,rt,ht=e['fees']
        fees=(p*q*rm+e['h_hat']*q*ht+e['rh_exit_hat']*rt+e['hl_exit']*ht)/10000
        reserve=max(p*q,e['h_hat']*q)*5/10000
        capital=(p*q+e['h_hat']*q)*.05*10/(365*24*3600)
        expected=q*(p-e['h_hat']-e['c_hat'])-fees-reserve-capital
        self.assertAlmostEqual(adaptive['forecast_net_usd'],expected)

    def test_segment_search_finds_lowest_feasible_joint_tick_and_lot(self):
        m=RhMakerSellModel(metadata('0','0','0'),T0,calibration_seconds=20)
        pair(m,T0);m.freeze();at=T0+20*NS;pair(m,at)
        route=m.fit['routes']['BTC|100']
        route.update(ready=True,adverse_p75_bps=0,closing_delta_median_per_unit=0)
        got=m.quote('BTC',100,'persistence',now_ns=at)
        self.assertEqual(got['reason'],'quote')
        rh,hl=m._pair('BTC',at)
        best=None
        for tick in range(99,201):
            price=tick/10
            q=float((Decimal('100')/Decimal(str(price))/Decimal('0.1')).to_integral_value(rounding=ROUND_FLOOR)*Decimal('0.1'))
            if not m._valid_q('BTC',q,rh,hl,price,100):continue
            e,reason=m._economics('BTC',q,rh,hl,route,'persistence')
            if e is not None and m._net(price,q,e)>=.10:
                best=(price,q);break
        self.assertIsNotNone(best)
        self.assertEqual(got['price'],best[0])
        self.assertAlmostEqual(got['quantity'],best[1])

    def test_segment_search_matches_bounded_brute_price_grid(self):
        rng=random.Random(7)
        for _ in range(50):
            m=RhMakerSellModel(metadata('0','0','0'),T0,calibration_seconds=20)
            rb=round(rng.uniform(7,12),1)
            ra=round(rb+rng.uniform(.1,.5),1)
            hb=round(rng.uniform(7,12),1)
            ha=round(hb+rng.uniform(.1,.5),1)
            at=T0+20*NS
            for t in (T0,at):
                m.consume(book('rh_lighter',t,bid=rb,ask=ra))
                m.consume(book('hyperliquid',t,bid=hb,ask=ha))
                if t==T0:m.freeze()
            route=m.fit['routes']['BTC|100']
            route.update(ready=True,adverse_p75_bps=0,
                         closing_delta_median_per_unit=rng.uniform(-.3,.3))
            got=m.quote('BTC',100,'persistence',now_ns=at)
            rh,hl=m._pair('BTC',at)
            want=None
            for k in range(int(rb/.1)+1,401):
                price=float(Decimal('0.1')*k)
                q=float((Decimal('100')/Decimal(str(price))/Decimal('0.1')).to_integral_value(
                    rounding=ROUND_FLOOR)*Decimal('0.1'))
                if not m._valid_q('BTC',q,rh,hl,price,100):continue
                e,_=m._economics('BTC',q,rh,hl,route,'persistence')
                if e is not None and m._net(price,q,e)>=.10:
                    want=(price,q);break
            if want is not None:
                self.assertEqual(got['reason'],'quote')
                self.assertEqual((got['price'],got['quantity']),want)
            elif got['reason']=='quote':
                self.assertGreater(got['price'],40)

    def test_natural_chronological_warmup_and_immutable_holdout_fit(self):
        m=RhMakerSellModel(metadata('0','0','0'),T0)
        for i in range(52):
            t=T0+i*12*NS
            pair(m,t)
            m.consume(trade(t+1_000_000,ident=str(i)))
            m.consume(book('hyperliquid',t+200_000_000,bid=9.8,ask=10.1))
        # Advance one more first-eligible paired close quote, then cross the
        # exact 30-minute cutoff before any holdout quote can train.
        pair(m,T0+52*12*NS)
        cutoff=T0+1800*NS
        pair(m,cutoff)
        route=m.fit['routes']['BTC|1000']
        self.assertTrue(route['ready'])
        self.assertGreaterEqual(route['close_resolved'],30)
        self.assertGreaterEqual(route['flow_resolved'],20)
        self.assertGreaterEqual(route['close_span_seconds'],600)
        self.assertGreaterEqual(route['flow_span_seconds'],600)
        self.assertGreater(route['adverse_p75_bps'],0)
        self.assertGreaterEqual(route['close_coverage'],.5)
        self.assertGreaterEqual(route['flow_coverage'],.5)
        quote=m.quote('BTC',1000,'adaptive',now_ns=cutoff)
        self.assertEqual(quote['reason'],'quote')
        self.assertGreaterEqual(quote['forecast_net_usd'],.10)
        self.assertLessEqual(quote['price']*quote['quantity'],1000)
        frozen=json.dumps(m.fit,sort_keys=True)
        later=cutoff+12*NS
        pair(m,later)
        m.consume(trade(later+1_000_000,ident='holdout'))
        m.consume(book('hyperliquid',later+200_000_000,bid=9.8,ask=15))
        self.assertEqual(json.dumps(m.fit,sort_keys=True),frozen)

    def test_late_trade_cannot_use_future_rh_book(self):
        m=RhMakerSellModel(metadata(),T0,calibration_seconds=20)
        pair(m,T0)
        m.consume(book('rh_lighter',T0+100_000_000,bid=9.8,ask=10))
        m.consume(trade(T0+100_000_001,source=T0+1))
        self.assertEqual(m.route_counts[('BTC',1000)]['flow_admitted'],0)


if __name__=='__main__':unittest.main()
