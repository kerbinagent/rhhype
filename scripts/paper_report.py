#!/usr/bin/env python3
"""Read a short SQLite snapshot and print a bounded paper-monitor audit as JSON."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import sqlite3
import time

def latency_summary(stats):
    observed=stats.get("observed",0);triggered=stats.get("triggered",0);missing=stats.get("missing",0)
    return dict(stats,actual_delay_mean_ms=stats.get("actual_delay_ms_sum",0)/observed if observed else None,
        observed_coverage_fraction=observed/triggered if triggered else None,
        survival_fraction_of_observed=stats.get("survived",0)/observed if observed else None,
        missing_fraction=missing/triggered if triggered else None,
        pending=max(0,triggered-observed-missing))


def report(path):
    path=Path(path)
    if path.is_dir():path=path/'paper.sqlite3'
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
    try:
        db.execute('BEGIN')
        row=db.execute('SELECT payload,updated FROM engine_state WHERE id=1').fetchone()
        if row is None:raise ValueError('No checkpoint yet')
        state=json.loads(row[0]);updated=row[1]
        trades=[json.loads(r[0]) for r in db.execute('SELECT payload FROM trades ORDER BY ts DESC LIMIT 5000')]
        top=[json.loads(r[0]) for r in db.execute('SELECT payload FROM top_signals ORDER BY score DESC LIMIT 10')]
    finally:db.close()
    engine=state['engine'];portfolios={}
    by_id={p['id']:p for p in trades};by_id.update(engine['positions'])
    trades=list(by_id.values())
    grouped=defaultdict(lambda:{'closed':0,'wins':0,'net_pnl_usd':0.0})
    fill_delays=defaultdict(list)
    for p in trades:
        for leg in p['legs']:
            if leg.get('entry_time') is not None:
                fill_delays[leg['venue']].append((leg['entry_time']-p['created_at'])*1000)
        if p['status'] not in ('CLOSED','CLOSED_ESTIMATED'):continue
        g=grouped[p['strategy']+'|'+p['asset']+'|'+p['pair_id']]
        pnl=p.get('net_pnl',p.get('net_pnl_usd',0))
        g['closed']+=1;g['wins']+=int(pnl>0);g['net_pnl_usd']+=pnl
    for name,ledger in engine['ledgers'].items():
        current=[p for p in engine['positions'].values() if p['strategy']==name]
        active_cash=sum(sum(l['price_pnl']-l['fees_usd'] for l in p['legs'])
                        -p.get('other_costs_usd',0)-p.get('capital_costs_usd',0) for p in current)
        expected=ledger['initial_capital']+ledger['closed_pnl_exact']+ledger['closed_pnl_estimated']+active_cash
        portfolios[name]=dict(ledger,active_positions=len(current),
            wallet_reconciliation_error_usd=sum(ledger['wallets'].values())-expected)
    episodes=engine.get('episode_history',[])
    spans=sorted(e['observed_span_seconds'] for e in episodes)
    return {'checkpoint_at':updated,'checkpoint_age_seconds':max(0,time.time()-updated),
        'portfolios':portfolios,'top_signals_not_trade_pnl':top,
        'retained_trade_groups_not_lifetime_totals':dict(grouped),
        'retained_trade_count':len(trades),'latency':{k:latency_summary(v) for k,v in engine.get('probe_stats',{}).items()},
        'retained_entry_fill_delay_ms_by_venue':{k:{'count':len(v),'median':sorted(v)[len(v)//2],
            'p95':sorted(v)[math.ceil(.95*len(v))-1],'max':max(v)} for k,v in fill_delays.items()},
        'latency_by_strategy':engine.get('probe_stats_by_strategy',{}),
        'episodes':{'retained':len(episodes),'right_censored':sum(e.get('right_censored',False) for e in episodes),
            'single_sample':sum(e.get('samples',0)==1 for e in episodes),
            'observed_span_median_seconds':spans[len(spans)//2] if spans else None,
            'observed_span_max_seconds':max(spans) if spans else None},
        'stats':engine['stats'],
        'limitations':['Public displayed depth is a paper fill model, not execution proof.',
            'Exact means complete modeled costs; estimated funding is counted separately.',
            'Latency probes use first fresh updates after each target delay; actual delay can be longer.',
            'Retained episodes and trade rows are a bounded window; portfolio counters are cumulative.']}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('path',nargs='?',default=Path(__file__).resolve().parents[1]/'data/paper-monitor',type=Path)
    args=p.parse_args()
    print(json.dumps(report(args.path),indent=2,allow_nan=False))


if __name__=='__main__':main()
