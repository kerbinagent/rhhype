"""Native ETH grids, positive cash admission, and unresolved small partials."""
from decimal import Decimal as D
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from scripts.core_spot_passive_cashentry_branch import CashEntrySpotBranch
from scripts.core_passive_hedged_base import Book, Config, NS

def book(role, t):
    bid, ask = ('2700', '2700.30') if role == 'spot' else ('2700.65', '2700.67')
    return dict(type='book', venue='lighter' if role=='spot' else 'rh_lighter',
                asset='ETH', received_ns=t, source_ns=t, generation='g',
                clock_valid=True, bids=[[bid, '2']], asks=[[ask, '2']])

def make(t):
    rules = dict(price_tick='.01', qty_step='.0001', min_notional='10',
                 max_quote='2500000', max_qty=None, maker_fee_bps='0', taker_fee_bps='0')
    metadata = dict(maker={'ETH': dict(rules, min_qty='.005', venue='lighter', market='2048', market_kind='spot')},
                    hedge={'ETH': dict(rules, min_qty='.002', venue='lighter', market='0', market_kind='perp')})
    cfg = Config('ETH', D(100), 'fixed_best', maker_latency_ns=100_000_000,
                 max_pair_skew_ns=500_000_000, hedge_limit_bps=D(1), take_profit_usd=D('.01'))
    b = CashEntrySpotBranch(cfg, metadata, exit_policy='control10s')
    b.capture_start_ns = 0
    b.books = dict(maker=Book.parse(book('spot', t)), hedge=Book.parse(book('perp', t)))
    b.references.extend((t-i*NS, D('.5')) for i in range(120,1,-2))
    b.last_sample = t-2*NS
    return b

def test_eth_native_grid_cash_entry_below_five_basis_points():
    t = 200*NS; b = make(t); diag = b.model(t)
    assert diag['reason']=='quote' and 0 < D(diag['excursion_bps']) < 5
    assert D(diag['forecast_cash_after_capital']) >= D('.01')
    b._on_diagnostic({}, t)
    assert b.quote.price==D('2700.01') and b.quote.qty==D('.0370')
    assert b.quote.qty*b.quote.price<=100 and b.quote.qty%D('.0001')==0

def test_eth_partial_below_native_minimum_remains_unknown_inventory():
    t = 200*NS; b = make(t); b._on_diagnostic({}, t)
    b.process(book('spot', t+100_000_000), {})
    b.process(dict(type='trade', venue='lighter', asset='ETH', received_ns=t+200_000_000,
                   source_ns=t+200_000_000, generation='g', clock_valid=True,
                   side='sell', price='2700', qty='.003', trade_id=1))
    assert b.maker_pos==D('.003') and b.hedge_pos==0
    b.process(book('perp', t+600_000_000), {})
    b.process(book('spot', t+NS), {})
    assert b.unknown_reason=='exit_order_lot_or_minimum_unknown'
    assert b.maker_pos==D('.003') and b.hedge_pos==0

if __name__ == '__main__':
    test_eth_native_grid_cash_entry_below_five_basis_points()
    test_eth_partial_below_native_minimum_remains_unknown_inventory()
