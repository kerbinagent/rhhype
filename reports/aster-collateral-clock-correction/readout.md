# Aster collateral funding budget

Offline reused-history development screen; no additional public market request and no executable cashflow/P&L. ETHprimary andBTCnonstakingcontrol, Aug31 00:00 throughSep29 00:00UTC. Full29days overlap four7dayblocks andone-daytail.

The original exact-timestamp assertion failed before economic analysis. Both raw histories contain90unique8hoursettlements with0–11ms reporting lag. The frozen correction allows atmost1s lag, normalizes to nominal settlement buckets and requires the complete original grid. Both interval-boundary settlements are deliberately excluded. Original failure and source retained.

Accounting scenario:1.1xspotprincipal committed,5%annualcapital,8bpfor two ordinary4bpperptakerfills,5bpstress. Zero stakingincome,USDF rewards,pointsorairdrops assumed. Collateral feasibility has not been established. Required extraAPR is simpleannualizedyield ononelegprincipal before every missingcost.

| Asset | Period offsets, days | Funding bp | Residual bp | Extra simple APR needed |
|---|---|---:|---:|---:|
| ETH | 0–29 | 53.233 | -3.465 | 0.436% |
| ETH | 0–7 | 14.062 | -9.486 | 4.946% |
| ETH | 7–14 | 9.257 | -14.291 | 7.452% |
| ETH | 14–21 | 9.837 | -13.711 | 7.149% |
| ETH | 21–28 | 16.355 | -7.193 | 3.751% |
| ETH | 28–29 | 0.722 | -13.785 | 50.314% |
| BTC | 0–29 | 40.998 | -15.701 | 1.976% |
| BTC | 0–7 | 9.481 | -14.067 | 7.335% |
| BTC | 7–14 | 9.936 | -13.612 | 7.098% |
| BTC | 14–21 | 12.259 | -11.289 | 5.887% |
| BTC | 21–28 | 6.134 | -17.414 | 9.080% |
| BTC | 28–29 | 1.078 | -13.429 | 49.016% |

ETH needs only0.436%additionalannualyield over the aggregatewindow, but3.75–7.45%overindividualweeks before allmissingcosts. This leaves a staked-collateral mechanism to investigate, not an established strategy. BTC requires1.976%additionalyield over theaggregate; no such BTCincome is assumed. One-dayannualizations magnify fixedentry/exitcosts and are notyieldforecasts.

Current Aster documentation lists WBETH at90%collateralvalue, nativeETH/BTC95%, asBNB95%; haircuts do not establish a margin path. NegativeUSDT/USD1balances have separate$1,000interest-freethresholds, then hourlyinterest(doccurrently4%annual) beyondthethreshold. Automaticexchange andhaircuts addpossiblecosts.

USDF depositrewards andtrade rewards aredifferent. Thelatterrequiresactivityatleast2days/week and$50,000weeklyvolume; thissmallcarrydesign doesnotassumethosecashflows. asBNBlaunchpoolincome changesNAV,whileHODLer/Megadroprewards needclaims; withdrawalsreturnslisBNB andmayqueue3–5businessdays. PromotionalmaxAPY isnot measuredyield.

Missing: actualstakedtokenexchangerate/rewardhistory,entryandexitconversioncosts,fixedquantitydollarfunding,basis/spreads,marginandinterestpaths,gas,redemptionqueues,execution. No newcollector followsautomatically. Rechecked12rate/cost/required-yield identities andbothpinnedinputhashes.

[Collateral](https://docs.asterdex.com/trading/perpetuals/single-asset-mode-and-multi-asset-mode), [fees](https://docs.asterdex.com/trading/perpetuals/fees-and-specs/fees), [rewardrules](https://docs.asterdex.com/program-and-rewards/trade-and-earn), [asBNB](https://docs.asterdex.com/earn/overview/mint-asbnb).
