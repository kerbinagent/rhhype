#!/usr/bin/env python3
"""Read a short SQLite snapshot and print a bounded paper-monitor audit as JSON."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import sqlite3
import time

SHADOW_POLICIES=('shadow_baseline','cooldown','convergence','conservative')

def latency_summary(stats):
    observed=stats.get("observed",0);triggered=stats.get("triggered",0);missing=stats.get("missing",0)
    return dict(stats,actual_delay_mean_ms=stats.get("actual_delay_ms_sum",0)/observed if observed else None,
        observed_coverage_fraction=observed/triggered if triggered else None,
        survival_fraction_of_observed=stats.get("survived",0)/observed if observed else None,
        missing_fraction=missing/triggered if triggered else None,
        pending=max(0,triggered-observed-missing))


def shadow_comparison(engine,trades,updated,checkpoint_age_seconds):
    """Compare fresh shadow ledgers; use retained rows only for diagnostics."""
    started=engine.get('shadow_started_at')
    if started is None:
        return {'enabled':False,'status':'not_started'}
    window={'started_at':started,'checkpoint_at':updated,
            'seconds':max(0,updated-started),
            'checkpoint_age_seconds':checkpoint_age_seconds,
            'status':'matched' if started<=updated else 'start_after_checkpoint'}
    policies={}
    for name in SHADOW_POLICIES:
        ledger=engine.get('ledgers',{}).get(name)
        if ledger is None:continue
        closed=ledger.get('closed_trades',0)+ledger.get('estimated_trades',0)
        pnl=ledger.get('closed_pnl_exact',0)+ledger.get('closed_pnl_estimated',0)
        wins=ledger.get('closed_wins_exact',0)+ledger.get('closed_wins_estimated',0)
        current=[p for p in engine.get('positions',{}).values() if p['strategy']==name]
        retained=[p for p in trades if p.get('strategy')==name and
                  p.get('created_at',0)>=started and p.get('status') in ('CLOSED','CLOSED_ESTIMATED')]
        exit_reasons={}
        holds=[];forecast_pairs=[]
        for p in retained:
            reason=p.get('exit_reason','unknown')
            exit_reasons[reason]=exit_reasons.get(reason,0)+1
            opened,closed_at=p.get('opened_at'),p.get('closed_at')
            if isinstance(opened,(int,float)) and isinstance(closed_at,(int,float)) and closed_at>=opened:
                holds.append(closed_at-opened)
            forecast=p.get('signal',{}).get('entry_policy',{}).get('forecast_net_usd')
            actual=p.get('net_pnl_usd')
            if isinstance(forecast,(int,float)) and isinstance(actual,(int,float)) and \
                    math.isfinite(forecast) and math.isfinite(actual):
                forecast_pairs.append((forecast,actual))
        policies[name]={
            'fee_tier':'standard','initial_capital_usd':ledger.get('initial_capital'),
            'entry_policy_counts':(engine.get('entry_policy_state') or {}).get('counts',{}).get(name,{}),
            'status':'observed' if closed else 'insufficient_trades',
            'cumulative_closed_trades':closed,'cumulative_wins':wins,
            'cumulative_net_pnl_usd':pnl,
            'cumulative_net_per_trade_usd':pnl/closed if closed else None,
            'cumulative_fees_usd':ledger.get('fees_usd',0),
            'active_positions':len(current),
            'open_position_mark_usd':None,
            'open_position_mark_status':'unavailable_without_current_books',
            'retained_closed_trades':len(retained),
            'retained_exit_reasons':exit_reasons,
            'retained_failed_hedges':exit_reasons.get('entry_failure',0),
            'retained_mean_hold_seconds':sum(holds)/len(holds) if holds else None,
            'retained_forecast_vs_realized':{
                'count':len(forecast_pairs),
                'forecast_mean_usd':sum(f for f,_ in forecast_pairs)/len(forecast_pairs) if forecast_pairs else None,
                'realized_mean_usd':sum(a for _,a in forecast_pairs)/len(forecast_pairs) if forecast_pairs else None,
                'realized_minus_forecast_mean_usd':sum(a-f for f,a in forecast_pairs)/len(forecast_pairs) if forecast_pairs else None}}
    return {'enabled':True,'window':window,'policies':policies,
            'policy_version':(engine.get('entry_policy_state') or {}).get('version'),
            'criteria_changed_at':(engine.get('entry_policy_state') or {}).get('criteria_changed_at'),
            'decision_counts_include_previous_version':(engine.get('entry_policy_state') or {}).get('migrated_from_version') is not None,
            'limitations':['Each policy has independent configured paper capital; policy P&L must not be summed as one portfolio.',
                           'Policies share observed feeds and opportunities; this is a nonrandom observational comparison.',
                           'All shadow policies use Standard fees.',
                           'Cumulative P&L, trades, wins, and fees come from ledgers; retained trade diagnostics cover only stored rows.',
                           'Open position marks are unavailable without current order books.']}


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
    checkpoint_age=max(0,time.time()-updated)
    return {'checkpoint_at':updated,'checkpoint_age_seconds':checkpoint_age,
        'portfolios':portfolios,'top_signals_not_trade_pnl':top,
        'shadow_comparison':shadow_comparison(engine,trades,updated,checkpoint_age),
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
