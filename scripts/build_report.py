#!/usr/bin/env python3
"""Render the offline research report from auditable derived tables."""
import csv,json,pathlib,datetime as dt,collections,statistics,re
ROOT=pathlib.Path(__file__).resolve().parents[1];D=ROOT/'data/derived';R=ROOT/'reports'

def read(name):return list(csv.DictReader((D/name).open())) if (D/name).exists() else []
def f(v,n=2):
    try:return f'{float(v):,.{n}f}'
    except (ValueError,TypeError):return '—'
def table(headers,rows):return '\n'.join(['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|']+['| '+' | '.join(map(str,r))+' |' for r in rows])
def top(rows,field='net_median_bps',n=12):return sorted(rows,key=lambda x:float(x[field]),reverse=True)[:n]
def timefmt(ms):return dt.datetime.fromtimestamp(ms/1000,dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
def same_size(rows,n=10000):return [r for r in rows if float(r['target_notional'])==n]

def main():
    q=json.loads((D/'live_quality.json').read_text());rhq=json.loads((D/'rh_lighter_quality.json').read_text());core=q['live'];domain=rhq['quality']['exclude']
    histdir=sorted(D.glob('history*/history_perp_pairs.csv'))[-1].parent;hist=list(csv.DictReader((histdir/'history_perp_pairs.csv').open()));cash=list(csv.DictReader((histdir/'history_cash_carry.csv').open()))
    rh=read('robinhood_summary.csv');perps=same_size(read('rh_lighter_perps_summary.csv'));cl=same_size(read('live_summary.csv'));supp=same_size(read('supplement_summary.csv'))
    # Direction is chosen descriptively after observation; not a tradable historical selection rule.
    best={}
    for x in same_size(rh):
        if x['symbol'] not in best or float(x['median_bps'])>float(best[x['symbol']]['median_bps']):best[x['symbol']]=x
    rt=read('rh_lighter_roundtrip_scenarios.csv');rt10=[x for x in rt if float(x['target_notional'])==10000]
    ct=read('roundtrip_scenarios.csv');ct10=[x for x in ct if float(x['target_notional'])==10000]
    now=dt.datetime.now(dt.timezone.utc).isoformat();parts=[]
    parts.append(f'''# Robinhood Chain × Hyperliquid arbitrage survey

Generated {now}. Research only; public data and read-only swap simulations. **No trades were placed.**

## Assessment

**The strongest follow-up candidates are the separate Robinhood Chain Lighter perpetual markets against Hyperliquid. The sampled Robinhood Uniswap stock-token pools generally do not clear their costs.** Small positive opening spreads also exist against Lighter Core and Aster, but an opening spread on two perpetuals is not realized arbitrage profit. Funding, the eventual unwind, and margin capital determine the outcome.

This survey distinguishes three Robinhood routes: (1) canonical stock tokens in Uniswap pools on Robinhood L2, (2) stock-token spot books on Robinhood's Lighter domain, and (3) perpetuals on that domain. Lighter Core is a fourth, separate comparator. Conflating them would mix different books, collateral and fee schedules.

The result is a research shortlist, not evidence of guaranteed or durable profits. Consecutive live samples cover one overnight US-equity session. The 30-day historical studies use candle closes and funding records; they cannot reconstruct historical executable fills.

## What was measured

| Dataset | Observed coverage |
|---|---|
| Robinhood mainnet | Chain ID4663, verified RPC; official registry195 stock tokens; full canonical pool scan |
| Hyperliquid census | 529 perp listings, 328 active; 330 spot pairs; native and all10 HIP-3 DEX entries |
| Robinhood Lighter census | 57 active perps and27 active spot markets; separate API and app-chain466324 |
| Main Core comparison | {core['markets_planned']} books planned per round, {core['rounds_observed']} rounds, {core['requests']:,} requests; {core['duration_minutes']:.1f} minutes |
| Robinhood Lighter paired comparison | {domain['rounds_observed']} rounds; {domain['valid_size_observations']:,} valid size/direction observations in matched perps |
| Robinhood AMMs | {len(best)} canonical stocks with direct active Hyperliquid hedges; repeated fixed-block v3/v4 quotes |
| Sizes | $1,000 / $10,000 / $100,000 for main books and seven core AMM names; expanded AMM universe at $10,000 |
| Historical model | 20 days for direction selection followed by a10-day holdout; native crypto, RWA perps, spot cash carry and token/share-normalized RH pool histories |

Core live window: **{timefmt(core['start_ms'])}–{timefmt(core['end_ms'])}**. Robinhood Lighter paired window: **{timefmt(domain['start_ms'])}–{timefmt(domain['end_ms'])}**. Both fall in US overnight trading, not the regular cash session. The supplemental Aster/Korean book window and per-AMM windows are recorded in their manifests.

[Robinhood's mainnet announcement](https://robinhood.com/us/en/newsroom/robinhood-accelerates-global-expansion-robinhood-chain-mainnet-stock-tokens-agentic-trading/?lang=en), [domain separation](https://docs.robinhood.com/chain/lighter-domains/), and the saved API inventories establish venue identity. Counts are listings/observations, not counts of profitable markets.

## Fees, units and capital

All headline book edges use **taker execution on both opening legs**. Hyperliquid native perps use4.5bp, spot7bp, and HIP-3 applies actual per-market deployer/growth settings; sampled xyz equity/index/silver markets generally use0.9bp and gold9bp. Lighter Standard is0bp. Premium sensitivity uses **3.5bp on Robinhood Lighter versus2.8bp on Core**; Plus is0.5bp. Aster USDT perps use4bp and dYdX 5bp. These are current public base tiers, not authenticated user fees. [Detailed fee model and sources](../research/fees.md).

AMM Quoter output **already includes pool fees and price impact**. Pool fees are not subtracted a second time. Separate columns reserve $1 gas or $5 total incidental cost; those are budgets, not measured full execution fees. Main book tables show5/10bp additional-cost sensitivity and conservative lot-rounding reserves. Larger v4 TVL did not necessarily produce a better quote than a smaller5bp v3 pool; the sampled COIN v4 pool charged100bp.

RH stock tokens represent `currentMultiplier` shares each. Dividends are reinvested and change that ratio. We use canonical contract identity and the correct quantity conversion; the historical model reconstructs multiplier effective times from on-chain events. A token is a Jersey-issued debt security providing equity exposure; the perpetual has separate funding/oracle and liquidation terms. Primary issuance is restricted to authorized participants, and redemption is not an unconditional instant public conversion. [Stock-token mechanics](https://docs.robinhood.com/chain/stock-tokens/), [issuer FAQ](https://docs.robinhood.com/rhj/faq/).

**Robinhood Lighter collateral is USDG; Hyperliquid and Core use USDC for these markets, and the sampled Aster contracts quote USDT.** The base comparison assumes stablecoin parity. A10bp relative conversion difference can consume a10bp edge. An independent price index helps detect errors but is not an executable bridge or redemption quote. [Robinhood Lighter deposits](https://apidocs.rh.lighter.xyz/docs/deposits-transfers-and-withdrawals).

For funding strategies, the capital illustration charges5% per year on40% of matched notional for two perp margins, or120% for fully funded spot plus margin. Over10 days that costs5.48bp or16.44bp. Neither is a leverage prescription; operational margin may need to be larger.
''')
    t=[]
    for x in top(perps,n=12):
        t.append([x['asset'],f"{x['buy_venue']} → {x['sell_venue']}",x['samples'],f(x['net_median_bps']),f(x['net_p05_bps'])+' / '+f(x['net_p95_bps']),f(x['premium_net_median_bps']),f(float(x['net_median_bps'])-5),f(100*float(x['positive_fraction']),0)+'%'])
    parts.append('## Robinhood Lighter perps versus Hyperliquid\n\n$10,000 target size, equal economic quantity, walking both books. Arrow means buy the first venue / short the second. The5th–95th percentile is an observed range across correlated samples, not a confidence interval. Direction ranking below is descriptive and selected after observing this window.\n\n'+table(['Asset','Buy → short','Samples','Standard median bp','5–95% bp','Premium median bp','Standard minus5bp','Positive entries'],t)+'''\n
![Robinhood Lighter fee-sensitive entry spreads](figures/rh_lighter_entries.png)

These are the most promising **entry conditions** in the current sample. Positive values create a two-position basis exposure; neither leg delivers a security that settles the other leg. A persistent premium can remain open for an indefinite period. At $10,000,10bp is only $10 before the later close and funding. A1% adverse basis movement is $100.

Both sides must have prefunded collateral. Economically offsetting P&L does not automatically move collateral between venues or prevent one side's liquidation. Different internal oracles during external-market closures can sustain apparent gaps. [XYZ oracle behavior](https://docs.trade.xyz/perpetuals/mechanics/oracle-price), [Lighter RWA pricing](https://docs.lighter.xyz/trading/real-world-assets-rwas/rwa-pricing-mechanism).
''')
    rhhist=[x for x in hist if x['venue']=='rh_lighter']
    if rhhist:
        rr=[]
        for x in rhhist:
            if x['other_coin']=='SPY':continue
            fade=float(x['holdout_funding_edge_bps'])*(1 if x['side_hl']=='long' else -1)
            rr.append([x['other_coin'],x['side_hl'],f(x['holdout_funding_edge_bps']),f(fade),x['holdout_funding_win_days']+'/10'])
        parts.append('### Funding can oppose the observed entry trade\n\nThe ten-day historical holdout for the actual Robinhood Lighter instance is below. The final numeric column applies the funding difference to a **long-HL / short-RH** trade, the direction of many current equity entry signals. Its sign can differ from the direction chosen by historical training. These are realized rate sums, not a forecast or ledger dollar return.\n\n'+table(['Asset','Train-selected HL side','Selected holdout funding bp','Long HL / short RH funding bp','Selected winning days'],rr)+'\n\nFor example, a current META or silver premium on RH can favor shorting RH on entry while that same direction would have **paid** net funding during the holdout. Include the funding direction of the proposed trade instead of adding the most favorable historical funding number to it. The historical counterparties settle in USDG versus USDC, adding conversion risk.')
    fee_budget=[]
    for asset in ('NVDA','META','XAG','MSFT'):
        x=next((x for x in rhhist if x['other_coin']==asset),None)
        if x:
            funding=float(x['holdout_funding_edge_bps'])*(1 if x['side_hl']=='long' else -1)
            hfees=2*float(x['hl_taker_fee_bps_per_side']);finance=.05*.4*10/365*10000
            fee_budget.append([asset,f(funding),f(hfees),f(finance),f(funding-hfees-finance),f(funding-hfees-finance-7)])
    parts.append('A simple ten-day funding budget for long HL / short RH demonstrates the fee constraint. Hold both opening notionals constant for this illustration; subtract two HL taker fees and the40%-capital charge, before any book spread, impact, conversion or basis change. Premium adds two3.5bp RH trades. This budget assumes the historical funding repeats, which is not a forecast.\n\n'+table(['Asset','Funding bp','HL roundtrip fee bp','Capital bp','Standard remainder bp','Premium remainder bp'],fee_budget)+'\n\nNVDA’s historical funding advantage leaves approximately zero under this funding-only Standard budget before execution costs. Its positive opening premium would need to converge, or future funding/capital conditions improve, for a robust trade. META and silver require particular care because the funding sign opposes the current entry direction.')
    size_rows=[]
    allp=read('rh_lighter_perps_summary.csv')
    for asset in ('NVDA','MSFT','META','GOOGL','XAG','BTC','ETH'):
        vals=[]
        for n in (1000,10000,100000):
            match=next((x for x in allp if x['asset']==asset and x['buy_venue']=='hyperliquid' and x['sell_venue']=='rh_lighter' and float(x['target_notional'])==n),None)
            vals.append(f(match['net_median_bps'])+' ('+match['samples']+')' if match else 'Insufficient / unavailable')
        size_rows.append([asset,*vals])
    parts.append('Size sensitivity for buying HL / shorting RH Lighter, Standard account; entry bp with valid sample count in parentheses. Missing size observations are not filled from smaller quotes.\n\n'+table(['Asset','$1k','$10k','$100k'],size_rows))
    if rt10:
        g=collections.defaultdict(list)
        for x in rt10:g[(x['asset'],x['horizon_minutes'])].append(float(x['four_leg_net_bps']))
        tab=[[a,h,len(v),f(statistics.median(v)),f(min(v)),f(max(v)),f(sum(z>0 for z in v)/len(v)*100,0)+'%'] for (a,h),v in sorted(g.items())]
        parts.append('## Does an opening spread cover an unwind?\n\nFor each positive opening signal, we also examine a5- or10-minute later close at the opposite books, with all four trading fees. These are independent, overlapping hypothetical scenarios. They do not simulate a single portfolio, partial fills, competition, or queue position; **do not sum their P&L**. Funding-hour boundaries are excluded rather than assigning unknown funding a zero value.\n\n'+table(['Asset','$10k hold, min','Scenarios','Median bp','Worst bp','Best bp','Positive'],tab)+f'''\n
Across {len(rt10)} Robinhood-domain $10k unwind scenarios, {sum(float(x['four_leg_net_bps'])>0 for x in rt10)} were positive before stablecoin conversion, capital cost and adverse execution. The separate Core sample had {sum(float(x['four_leg_net_bps'])>0 for x in ct10)} positive outcomes among {len(ct10)} eligible $10k 5/15-minute scenarios. A positive opening spread alone therefore substantially overstates the evidence for profit.

![Observed Robinhood Lighter unwind scenarios](figures/rh_lighter_unwind.png)
''')
    tab=[]
    for x in sorted(best.values(),key=lambda x:float(x['median_bps']),reverse=True):
        tab.append([x['symbol'],x['direction'],x['samples'],f(x['median_bps']),f(x['max_bps']),x['positive_samples']])
    parts.append('## Robinhood stock-token AMMs versus Hyperliquid\n\nThe table chooses the better median direction **after** observing each token, making it an optimistic descriptive screen. Reverse trades need existing token inventory or verified borrowing. Results include pool fee/impact plus the Hyperliquid entry fee and assume USDG/USDC parity; gas, conversion, financing and eventual exit costs reduce them further.\n\n'+table(['Token','Better direction, $10k','Samples','Median bp','Best sample bp','Positive samples'],tab)+'''\n
![Canonical Robinhood AMM comparison](figures/robinhood_amm.png)

Some smaller $1k reverse observations can look marginally positive before gas and rounding. Exact fractional-share hedges can fall between Hyperliquid lot sizes. The derived tables expose the residual and reserve a full lot's notional; these small values are not established arbitrage profits. At $100k, returned Hyperliquid depth sometimes cannot fill the requested quantity; those cases are excluded rather than extrapolated.

The195-token scan found143 tokens with indexed pairs,139 with canonical USDG pairs, and33 whose largest USDG pool had both at least$100k estimated liquidity and$100k24h volume. Nineteen also had a same-ticker active xyz perp above$1m24h volume. The study quotes these19 direct equity candidates, plus ETF pool examples. Indexer coverage is capped and does not prove other routes are absent. [Full token inventory](../data/derived/robinhood_inventory.csv), [pool methods and contract evidence](../research/robinhood.md).

Robinhood Lighter **stock-token spot** is a separate route. Its asset metadata matches canonical ERC-20 addresses and multipliers. Book quantity is documented as base-token amount; token-denominated pricing is the supported interpretation, with a share-price alternative retained as a sensitivity because price/multiplier semantics are not explicit in every API document. `rh_lighter_spot_raw_token_summary.csv` and `rh_lighter_spot_shares_summary.csv` preserve both. These continuously sized screens also need transformed token-lot handling and residual hedges. A same-domain spot/perp premium can motivate cash-carry research; it has no guaranteed convergence date.
''')
    hb=list(csv.DictReader((histdir/'history_robinhood_hl_basis.csv').open()))
    parts.append('### Historical Robinhood pool/share basis\n\nThirty days of closed-hour canonical pool prices in **USDG per token**, divided by the event-correct shares-per-token multiplier, versus the same stock’s HL perp candle close. USDG/USDC parity remains an assumption. These are price-reference discrepancies, not tradeable spreads; candle trade times and depth differ.\n\n'+table(['Stock','Paired hours','Median absolute basis bp','90th percentile absolute bp','Regular-session median abs bp','Weekend median abs bp'],[[x['symbol'],x['quote_paired_hours'],f(x['quote_median_abs_basis_bps']),f(x['quote_p90_abs_basis_bps']),f(x['quote_regular_median_abs_bps']),f(x['quote_weekend_median_abs_bps'])] for x in hb])+'\n\nAMZN’s corrected quote-unit 90th-percentile absolute basis is about46.5bp, versus411.9bp under the flawed indexer USD conversion. This illustrates why candle discrepancies must be validated against token units, stablecoin conversions and actual executable routes.')
    tab=[]
    for x in hist:
        if x['match_type']=='same_underlying' and x['gross_minus_known_fees_bps'] and x['venue'] in ('lighter','aster'):
            finance=.05*.4*10/365*1e4
            tab.append([x['hl_coin'],x['venue'],x['side_hl'],f(x['holdout_funding_edge_bps']),f(x['gross_minus_known_fees_bps']),f(float(x['gross_minus_known_fees_bps'])-finance),x['holdout_funding_win_days']+'/10'])
    parts.append('## Historical carry: a10-day holdout\n\nDirection is chosen using August 30–September 19, 2026 at03:00 UTC, then held fixed over September 19–29 at03:00 UTC (20-day training /10-day holdout). The model uses actual funding event timestamps and native units: Hyperliquid/Lighter hourly, Aster variable settlement intervals. Lighter rates are percentages with a separate payer direction; blindly annualizing or mixing units would be wrong. Funding-dollar calculations use preceding-hour closing prices as proxies for settlement index prices.\n\n'+table(['Asset','Other venue','HL side','Holdout funding bp','Basis+funding−fees bp','Also−capital bp','Positive funding days'],tab)+'''\n
Current public fee schedules are applied to each leg's own entry and exit notional; historical account fees are not reconstructed. These results still omit historical bid/ask spreads, impact, liquidation path, collateral conversion and execution failures. The candle-based result is a scenario estimate, not realized P&L. Pair selection and the universe itself have hindsight bias even though direction selection has a holdout.
''')
    rhcash=list(csv.DictReader((histdir/'history_rh_lighter_cash.csv').open())) if (histdir/'history_rh_lighter_cash.csv').exists() else []
    if rhcash:
        parts.append('Same-domain Robinhood Lighter token spot / short perp, Standard fee scenario:\n\n'+table(['Token','10d funding bp','Basis+funding bp','After capital bp'],[[x['spot_token'],f(x['holdout_funding_bps']),f(x['gross_fixed_token_bps']),f(x['gross_minus_illustrative_financing_bps'])] for x in rhcash])+'\n\nNVDA token spot had only about $62k trailing daily turnover and 45% zero-volume holdout hours. Its apparent positive candle-based carry result is excluded because the endpoint prices were supported by very small trade volumes. The much larger perpetual market does not cure this spot-data limitation. Premium execution would add roughly14bp across four trades before stake discounts; cash carry also retains token issuer and custody risk. SPY was liquid in spot, but this particular holdout did not cover the illustrative capital charge.')
    tab=[]
    for x in cash:tab.append([x['perp_coin'],f(x['holdout_funding_bps']),f(x['gross_minus_known_fees_bps']),f(float(x['gross_minus_known_fees_bps'])-.05*1.2*10/365*1e4)])
    parts.append('Native Hyperliquid cash carry uses fully funded spot/wrapped spot and a short perp.\n\n'+table(['Asset','10d funding bp','Basis+funding−fees bp','Also−120% capital charge bp'],tab)+'''\n
![Historical fees and capital effects](figures/historical_costs.png)

HYPE versus Aster and HYPE cash carry warrant follow-up under the modeled conditions. Many other margins are consumed by fees and capital before historical execution costs. BTC's direction selected against Lighter Core reversed in the holdout; Brent's funding advantage also reversed. A large one-month funding sum cannot be assumed to persist.

[Full historical notebook](../research/history-analysis.md) includes RWA funding, daily outcomes, coverage, candle-quality filters, and Robinhood pool/share comparisons. Thin dYdX HYPE/ZEC/silver price histories are excluded where zero-volume hours make the price-based estimate unreliable.
''')
    tab=[]
    for x in top(cl,n=8):tab.append([x['asset'],x['buy_venue']+' → '+x['sell_venue'],f(x['net_median_bps']),x['samples'],f(x['premium_net_median_bps'])])
    parts.append('## Other liquid venues and asset classes\n\nLighter Core $10k entry screen, after Standard opening fees:\n\n'+table(['Asset','Buy → short','Median bp','Samples','Premium median bp'],tab)+'\n\nSynchronized supplemental observations:\n\n'+table(['Asset','Buy market → short market','Median bp','Samples'],[[x['asset'],str(x['buy_market'])+' → '+str(x['sell_market']),f(x['net_median_bps']),x['samples']] for x in top(supp,n=8)])+'''\n
| Asset class | What is liquid enough to survey | Hedge interpretation / decision |
|---|---|---|
| Major crypto | BTC, ETH, SOL, HYPE, ZEC; native HL, Core/RH Lighter, Aster | Best data/depth coverage. Include wrapped-spot custody and redemption risk in cash carry. |
| US equities |19 canonical RH/xyz overlaps plus separate RH Lighter perps/spot | Compare exact share class and current shares/token. No dividends paid directly to perp holders. |
| International equities | SKHX/SMSN common-share USD perps against Core SKHYNIXUSD/SAMSUNGUSD; Japan/Korea index listings in census | FX conversion and share identity verified for sampled Korean common shares. SKHY ADS is distinct; don't substitute it one-for-one. |
| Equity indices / ETFs | SP500/US500, XYZ100/US100, tokenized SPY/QQQ, leveraged-sector funds | Index points are not ETF shares. Funding, dividends, constituents and leverage reset introduce basis; SPX crypto is not S&P500. |
| Precious metals | Gold and silver have deep perp books; smaller platinum/palladium available | One troy ounce per relevant metal contract. GLD/SLV ETF tokens add fund economics; PAXG/XAUT add issuer/delivery differences. |
| Energy / industrial commodities | WTI/Brent, copper, natural gas; USO token pools | Verify benchmark and futures roll calendar. USO units are not barrels. Off-hours/internal pricing and differing roll times can sustain spreads. |
| FX | EUR/USD and USD/JPY; GBP smaller | Match quote direction. XYZ JPY represents USD/JPY, not dollars per yen. No RH stock-token direct FX deliverable was established. |
| Rates / bonds | para10Y/2Y/30Y, Lighter US10Y; RH SGOV/BND/SHY token inventory | Rates depth/turnover much smaller. Bond prices require duration/convexity hedges against yields. SGOV indexed liquidity was sizeable but only about$16k24h volume; no liquid exact hedge established. |
| Pre-IPO / prediction / exotic | Listings surveyed where returned, but distinct payoff/settlement | Excluded from direct arbitrage ranking without an equivalent event/payoff and sufficient matched liquidity. SPCX is now a public stock, not a pre-IPO instrument. |

GMX supplies oracle/pool capacity rather than a resting book. Its reported capacity ceilings are not executable depth; borrowing, price impact and side-specific fees must be quoted separately. Jupiter also uses pool-based execution and borrowing costs. Drift's documented public hosts were inaccessible from this environment; no fabricated zero-liquidity conclusion is drawn. PancakeSwap/Ondo and UniswapX token quotes require exact issuer, rights and size-specific routing. The supplied Japan VPN was not needed; all data here came from accessible public endpoints. [Comparator notebook and sources](../research/comparators.md).

## Data quality findings that changed the conclusion

1. **Spot identity:** Hyperliquid returned330 market definitions but885 contexts. Joining them by list position misidentified tokens; the corrected join uses `coin`.
2. **Share multipliers:** Raw RH token prices are not one-share prices. Reconstructed on-chain update effective times correct the historical hedge ratio; hours spanning a multiplier change are omitted.
3. **False historical premiums:** GeckoTerminal's USD-converted pool candles embedded a USDG/USD conversion factor as high as1.0561 at an inspected time, while independent USDG/USD was about0.999946. Pool candles in quote-token units remove that artifact. The original responses are retained for audit; their apparent5% premium is not an arbitrage result.
4. **Rate limits:** An initial broad Core sampler exceeded Lighter's 60 public requests/minute and received405 responses. It was stopped and replaced with a 30-book/minute Core plan. Failed data were retained and excluded. Subsequent valid rounds do not fill those gaps.
5. **Missing depth/freshness:** Book walks reject insufficient returned levels, crossed books, stale HL engine timestamps and more than5s receipt skew. Lighter has no engine timestamp in this response, so close receipt times cannot prove engine freshness. The separate15s Aster/dYdX sensitivity is not the synchronized headline; a later paired supplemental run resolves Aster timing.
6. **Lots and fees:** Marginal positives may be smaller than residual hedge lots. Conservative rounding reserves are exposed. Fee tiers are venue-specific and pool fee is not double-counted.
7. **No independence claim:** Consecutive books are strongly correlated; repeated positive counts are persistence observations, not independent statistical trials or guaranteed fill probabilities.

## Next research decision

Continue a **paper-only** monitor of RH Lighter/HL equity-perp spreads, with exact account fees, USDG/USDC executable conversion costs and fixed holding-period exits. Prioritize candidates that remain positive after Premium/Plus fees and a material execution reserve. Add regular US sessions, market open/close, weekend/reopening and stress days before estimating durable capacity. Collect funding and oracle snapshots alongside books.

For stock-token AMMs, pursue a route only when the best size-aware buy/sell quote clears both legs' fees, rounding, gas and conversion. Current pool measurements provide little support for a broad taker arbitrage. Fully funded spot/perp carry is a separate slower research track and must be assessed against capital costs and issuer/bridge risk.

Do not advance a candidate merely because its candle basis or entry spread is positive. Require valid contract units, prefunded operational access, feasible lot sizes, stable funding economics, and an observed exit that survives the complete cost budget.

## Reproduction and evidence

See [README](../README.md) for installation and offline rebuild commands, [fee assumptions](../research/fees.md), [methodology](../research/01-methodology.md), [journal](../research/00-journal.md), [independent audit](../research/audit.md), and [derived CSVs](../data/derived/). Raw timestamped responses and requests are retained locally and in the committed compressed evidence archive. Its manifest records archive and per-file SHA-256 checksums. No account key or `.env` is included.
''')
    R.mkdir(exist_ok=True);report='\n\n'.join(parts)
    for old,new in [('ID4663','ID 4663'),('registry195','registry 195'),('all10','all 10'),('and27','and 27'),('app-chain466324','app-chain 466324'),('a10-day','a 10-day'),('a1%','a 1%'),('a10bp','a 10 bp'),('a5-','a 5-'),('first20days','first 20 days'),('final10days','final 10 days'),('The195-token','The 195-token'),('found143','found 143'),('pairs,139','pairs, 139'),('and33','and 33'),('these19','these 19'),('at least$100k','at least $100k'),('and$100k24h','and $100k 24h'),('above$1m24h','above $1m 24h'),('about$16k24h','about $16k 24h'),('some5%','some 5%')]:report=report.replace(old,new)
    chunks=re.split(r'(\[[^\]]*\]\([^)]*\)|`[^`]+`)',report)
    for i,chunk in enumerate(chunks):
        if chunk.startswith('[') or chunk.startswith('`'):continue
        chunk=re.sub(r'([a-z]{2,})(\d)',r'\1 \2',chunk)
        chunk=re.sub(r'(\d)(bp|days|hours|minutes)\b',r'\1 \2',chunk)
        chunk=chunk.replace('A10 bp','A 10 bp').replace('A1%','A 1%').replace('At $10,000,10 bp','At $10,000, 10 bp')
        chunks[i]=chunk
    report=''.join(chunks)
    (R/'REPORT.md').write_text(report);print(R/'REPORT.md')
if __name__=='__main__':main()
