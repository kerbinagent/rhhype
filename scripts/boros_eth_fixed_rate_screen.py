"""Constant-price fee illustration, NOT a fixed-dollar payoff or execution."""
import gzip,hashlib,json
from decimal import Decimal as D
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/boros-eth-book-assets/fixed-rate-screen.json'
pins={}


def read(path,compressed=False):
    b=(ROOT/path).read_bytes();pins[path]=hashlib.sha256(b).hexdigest()
    return json.loads(gzip.decompress(b) if compressed else b,parse_float=D)


def main():
    book=read('reports/boros-eth-depth-corrected/book.json.gz',True)
    markets=read('reports/boros-core-eth-markets/summary.json')['exact_stream_matches']
    market=next(m for m in markets if m['marketId']==199)
    assets=read('reports/boros-eth-book-assets/assets.json.gz',True)['results']
    asset=next(a for a in assets if a['tokenId']==market['tokenId'])
    assert asset['symbol']=='WETH' and market['metadata']['fundingRateSymbol']=='lighter-eth'
    px=D(asset['usdPrice']);step=D('.0001')
    rates=[D(i)*step for i in book['long']['ia']]
    depth=[D(s)/D(10**18) for s in book['long']['sz']]
    assert len(rates)==len(depth) and rates==sorted(rates,reverse=True)
    # Aggregation rounding direction is not assumed known: one bucket lower
    # is a declared sensitivity, not a verified executable-rate lower bound.
    rate=rates[0]-step
    anchor=book['syncStatus']['timestamp']//3600*3600
    years=D(market['imData']['maturity']-anchor)/D(31536000)
    entry_fee=D(market['config']['takerFee'])/D(10**18)
    settle_fee=D(market['extConfig']['settleFeeRate'])/D(10**18)
    costs={100:D('.032736'),250:D('.089354'),500:D('.208522'),1000:D('.472528')}
    rows=[]
    for amount in (100,250,500,1000):
        n=D(amount);q=n/px
        assert q<=depth[0]
        gross=n*rate*years
        capital=n*D('1.1')*D('.05')*years
        fees=n*(entry_fee+settle_fee)*years
        entrance=D('.00027')*px  # Published ETH example; no private fee lookup.
        stress=n*D('.0005')
        value=gross-capital-fees-entrance-costs[amount]-stress
        rows.append({'notional_usd':amount,'hypothetical_swap_yu_eth':str(q),
                     'fixed_gross_constant_price_usd':str(gross),'capital_usd':str(capital),
                     'swap_and_settlement_fees_usd':str(fees),'illustrative_entrance_usd':str(entrance),
                     'earlier_median_spread_cost_usd':str(costs[amount]),'stress_usd':str(stress),
                     'conditional_residual_usd':str(value)})
    result={'actual_pnl':None,'fixed_usd_return_established':False,
            'market_id':199,'collateral':'WETH','aggregated_top_rate':str(rates[0]),
            'rate_sensitivity_used':str(rate),'top_depth_eth':str(depth[0]),
            'funding_period_anchor':anchor,'years_to_maturity':str(years),
            'price_usd_sensitivity':str(px),'source_sha256':pins,'rows':rows,
            'omitted':['gas/bridge/deposit/withdrawal','future basis','currency rehedging',
                       'margin replenishment path','actual fills','exact personal entrance fee'],
            'capital_assumption':'Spot plus10%cash; Boros margin carved from held ETH, not free extra capital'}
    b=(json.dumps(result,indent=2)+'\n').encode();assert len(b)<=8192
    assert Path(__file__).stat().st_size+(ROOT/'scripts/boros_eth_book_assets.py').stat().st_size<=8192
    with OUT.open('xb') as f:f.write(b)
    print(json.dumps(result))


if __name__=='__main__':main()
