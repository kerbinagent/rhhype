import sys
from pathlib import Path

import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from rh_maker_model import RhMakerModel, NS

T0 = 2_000_000_000_000


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(fn) for name, fn in
                              sorted(globals().items())
                              if name.startswith('test_') and callable(fn))


def metadata():
    return {'BTC': {'rh': {'price_tick': '0.1', 'size_step': '0.001', 'min_qty': '0.001',
                           'min_notional': '10', 'max_quote': '2000',
                           'maker_fee_bps': '0', 'taker_fee_bps': '0'},
                    'hl': {'size_step': '0.001', 'min_notional': '10', 'taker_fee_bps': '4.5'}}}


def book(venue, at, generation='a', bid=99.0, ask=100.0, depth=100.0, source=None):
    return {'type': 'book', 'venue': venue, 'asset': 'BTC', 'generation': generation,
            'received_ns': at, 'source_ns': at if source is None else source,
            'valid': True, 'clock_valid': True,
            'bids': [[bid, depth]], 'asks': [[ask, depth]]}


def trade(at, trade_id='1', price=99.0):
    return {'type': 'trade', 'venue': 'rh_lighter', 'asset': 'BTC', 'side': 'sell',
            'received_ns': at, 'source_ns': at, 'price': price, 'qty': 1, 'trade_id': trade_id,
            'clock_valid': True}


def pair(model, at, rh_bid=99, hl_bid=101, depth=100):
    model.consume(book('rh_lighter', at, bid=rh_bid, ask=rh_bid+1, depth=depth))
    model.consume(book('hyperliquid', at, bid=hl_bid, ask=hl_bid+1, depth=depth))


def test_first_eligible_shallow_flow_censors_and_later_depth_does_not_rescue():
    m = RhMakerModel(metadata(), T0, calibration_seconds=30)
    pair(m, T0)
    m.consume(trade(T0+1_000_000, 'a'))
    key = ('BTC', 1000)
    assert m.route_counts[key]['flow_admitted'] == 1
    m.consume(book('hyperliquid', T0+200_000_000, bid=101, ask=102, depth=.001))
    assert m.route_counts[key]['flow_censored_shallow'] == 1
    m.consume(book('hyperliquid', T0+300_000_000, bid=100, ask=101))
    assert m.route_counts[key]['flow_resolved'] == 0


def test_flow_uses_original_quantity_and_records_over_limit_move():
    m = RhMakerModel(metadata(), T0, calibration_seconds=30)
    pair(m, T0)
    m.consume(trade(T0+1_000_000, 'a'))
    original_q = m.pending_flow[('BTC', 1000)][0]['q']
    assert original_q == 10
    m.consume(book('hyperliquid', T0+200_000_000, bid=100, ask=101, depth=20))
    assert m.route_counts[('BTC',1000)]['flow_resolved'] == 1
    assert m.route_counts[('BTC',1000)]['flow_above_10bp'] == 1
    assert m.flow_rows[('BTC',1000)][0][1] > 10


def test_closing_first_eligible_shallow_censors_no_later_recovery():
    m = RhMakerModel(metadata(), T0, calibration_seconds=40)
    pair(m, T0)
    key=('BTC',1000)
    assert m.route_counts[key]['close_admitted'] == 1
    m.consume(book('rh_lighter', T0+11*NS, depth=.001))
    m.consume(book('hyperliquid', T0+11*NS, depth=100, bid=101, ask=102))
    assert m.route_counts[key]['close_censored_shallow'] == 1
    m.consume(book('rh_lighter', T0+12*NS))
    assert m.route_counts[key]['close_resolved'] == 0


def test_cutoff_censors_pending_and_holdout_never_trains():
    m = RhMakerModel(metadata(), T0, calibration_seconds=20)
    pair(m, T0+19*NS)
    m.consume(trade(T0+19*NS+1, 'a'))
    m.consume(book('hyperliquid', T0+20*NS, bid=80, ask=81))
    fit=m.fit
    assert fit['cutoff_ns'] == T0+20*NS
    assert fit['routes']['BTC|1000']['flow_resolved'] == 0
    assert fit['routes']['BTC|1000']['close_resolved'] == 0
    m.consume(book('rh_lighter', T0+21*NS))
    assert m.fit is fit
    assert m.route_counts[('BTC',1000)]['flow_admitted'] == 1
    assert m.route_counts[('BTC',1000)]['flow_censored_cutoff'] == 1


def test_generation_gap_censors_pending():
    m = RhMakerModel(metadata(), T0, calibration_seconds=30)
    pair(m,T0)
    m.consume(trade(T0+1_000_000,'a'))
    m.consume(book('hyperliquid',T0+200_000_000,generation='b'))
    assert m.route_counts[('BTC',1000)]['flow_censored_generation_or_regression'] == 1
    assert not m.pending_flow[('BTC',1000)]


def test_quote_binary_search_and_fixed_best_independent_of_readiness():
    m = RhMakerModel(metadata(),T0,calibration_seconds=20)
    pair(m,T0)
    m.freeze()
    at=T0+20*NS
    pair(m,at,rh_bid=99,hl_bid=103)
    fixed=m.quote('BTC',1000,'fixed_best',now_ns=at)
    assert fixed['reason']=='quote' and fixed['price']==99
    assert m.quote('BTC',1000,'adaptive',now_ns=at)['reason']=='model_unready'
    route=m.fit['routes']['BTC|1000']
    route.update(ready=True,close_ready=True,flow_ready=True,
                 adverse_p75_bps=0,closing_delta_median_per_unit=-1.0)
    adaptive=m.quote('BTC',1000,'adaptive',now_ns=at)
    assert adaptive['reason']=='quote'
    assert adaptive['price'] < 100 and adaptive['price'] > 0
    assert adaptive['forecast_net_usd'] >= .10
    assert m.quote('BTC',1000,'persistence',now_ns=at)['price']==adaptive['price']


def test_invalid_metadata_fee_and_book_time_fail_closed():
    meta=metadata(); meta['BTC']['hl']['taker_fee_bps']=None
    with unittest.TestCase().assertRaises((ValueError,TypeError)):
        RhMakerModel(meta,T0)
    m=RhMakerModel(metadata(),T0,calibration_seconds=20)
    m.consume(book('rh_lighter',T0,source=T0+1))
    assert ('rh_lighter','BTC') not in m.books


def test_trade_only_seller_at_bid_and_once_per_second():
    m=RhMakerModel(metadata(),T0,calibration_seconds=20)
    pair(m,T0)
    m.consume(trade(T0+1,'a',price=99.1))
    m.consume(trade(T0+2,'a',price=99))
    m.consume(trade(T0+3,'b',price=99))
    assert m.route_counts[('BTC',1000)]['flow_admitted']==1


def test_late_trade_cannot_use_newer_rh_bid():
    m=RhMakerModel(metadata(),T0,calibration_seconds=20)
    pair(m,T0)
    m.consume(book('rh_lighter',T0+100_000_000,bid=100,ask=101))
    x=trade(T0+100_000_001,'late',price=100)
    x['source_ns']=T0+1
    m.consume(x)
    assert m.route_counts[('BTC',1000)]['flow_admitted']==0

def test_impossible_projected_exit_fails_closed():
    m=RhMakerModel(metadata(),T0,calibration_seconds=20)
    pair(m,T0);m.freeze();at=T0+20*NS;pair(m,at,rh_bid=99,hl_bid=103)
    r=m.fit['routes']['BTC|1000']
    r.update(ready=True,closing_delta_median_per_unit=-1000,adverse_p75_bps=0)
    assert m.quote('BTC',1000,'adaptive',now_ns=at)['reason']=='invalid_exit_forecast'


def test_pending_expiry_on_unrelated_event_is_late_not_cutoff():
    m=RhMakerModel(metadata(),T0,calibration_seconds=30)
    pair(m,T0)
    m.consume(trade(T0+1,'a'))
    m.consume(trade(T0+2*NS,'later',price=101))
    assert m.route_counts[('BTC',1000)]['flow_censored_late']==1
    m.freeze()
    assert m.route_counts[('BTC',1000)]['flow_censored_cutoff']==0
