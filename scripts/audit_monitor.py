#!/usr/bin/env python3
"""Read-only snapshot and audit of monitor signals. Never modifies the running DB."""
import argparse
import bisect
import collections
import csv
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import statistics
import time
from monitor import aster_fee

ROOT = Path(__file__).resolve().parents[1]


def write_csv(path, rows):
    if rows:
        with path.open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)


def freeze(run, dest):
    dest.mkdir(parents=True, exist_ok=True)
    # A read transaction gives totals and observations from the same committed state.
    c = sqlite3.connect((run/'window.sqlite3').resolve().as_uri()+'?mode=ro', uri=True, timeout=10)
    c.execute('BEGIN')
    meta = {k: json.loads(v) for k,v in c.execute('SELECT key,value FROM meta')}
    with gzip.open(dest/'observations.jsonl.gz', 'wt', compresslevel=6) as f:
        for ident,payload in c.execute('SELECT id,payload FROM observations ORDER BY id'):
            f.write(json.dumps({'id':ident, **json.loads(payload)}, separators=(',',':'))+'\n')
    c.close()
    meta['snapshot_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    meta['source'] = str(run)
    meta['evidence_sha256'] = hashlib.sha256((dest/'observations.jsonl.gz').read_bytes()).hexdigest()
    for name in ('config.json','leaderboard.json','markets.json'):
        # Informational companion files can be a report interval apart from the DB transaction.
        if (run/name).exists(): (dest/name).write_bytes((run/name).read_bytes())
    (dest/'snapshot.json').write_text(json.dumps(meta,indent=2)+'\n')


def quantile(values, fraction):
    v = sorted(values)
    return v[min(len(v)-1, int((len(v)-1)*fraction))] if v else None


def adjusted_budget(r, lighter_tier='standard', hl_base=4.5, corrected_aster=False):
    rates = []
    for side in ('buy','sell'):
        venue = r[side].split(':')[0]
        old = r[side+'_fee_bps']
        if venue == 'hyperliquid': rate = old * hl_base / 4.5
        elif venue in ('lighter','rh_lighter'):
            rate = {'standard':0, 'plus':.5, 'premium':3.5 if venue=='rh_lighter' else 2.8}[lighter_tier]
        elif venue == 'aster' and corrected_aster:
            rate = aster_fee(r[side].split(':',1)[1], r['category']=='RWA/xyz')[0]
        else: rate = old
        rates.append(rate)
    fees = (r['buy_cost_usd']*rates[0]+r['sell_proceeds_usd']*rates[1])/10000
    opening = r['sell_proceeds_usd']-r['buy_cost_usd']-fees
    budget = opening-fees-r['additional_cost_reserve_usd']
    return opening, budget


def persistence(groups, tier='standard', hl_base=4.5, gap=600, corrected_aster=False):
    episodes=[]
    for route, rs in groups.items():
        active=None; prev=None
        def finish(next_negative=None, reason='window_end'):
            nonlocal active
            if active is None: return
            first,last=active['first'],active['last']
            before=active['before']
            episodes.append({'asset':first['asset'],'route':route,'tier':tier,'hl_base_bps':hl_base,
                'first_positive_utc':first['utc'],'last_positive_utc':last['utc'],
                'positive_samples':active['count'],
                'observed_first_to_last_seconds':last['timestamp']-first['timestamp'],
                'preceding_nonpositive_utc':before['utc'] if before else None,
                'following_nonpositive_utc':next_negative['utc'] if next_negative else None,
                'outer_bracket_seconds':next_negative['timestamp']-before['timestamp'] if before and next_negative else None,
                'right_censored':next_negative is None,'left_censored':before is None,'end_reason':reason,
                'first_opening_edge_usd':active['opening'],'first_budgeted_edge_usd':active['budget'],
                'peak_budgeted_edge_usd':active['peak']})
            active=None
        for r in rs:
            if prev and r['timestamp']-prev['timestamp']>gap:
                finish(reason='data_gap');prev=None
            opening,budget=adjusted_budget(r,tier,hl_base,corrected_aster)
            if budget>0:
                if active is None:
                    active={'first':r,'last':r,'before':prev,'count':1,'opening':opening,'budget':budget,'peak':budget}
                else:
                    active['last']=r;active['count']+=1;active['peak']=max(active['peak'],budget)
            else:
                finish(next_negative=r,reason='observed_nonpositive')
            prev=r
        finish()
    return episodes


def latency_and_fees(groups, out):
    standard=persistence(groups)
    write_csv(out/'persistence_episodes.csv',standard)
    latency=[]
    for asset in sorted({r['asset'] for r in standard}):
        es=[e for e in standard if e['asset']==asset]
        rs=[v for key,vals in groups.items() if vals[0]['asset']==asset for v in vals]
        intervals=[b['timestamp']-a['timestamp'] for vals in groups.values() if vals[0]['asset']==asset for a,b in zip(vals,vals[1:])]
        closed=[e['outer_bracket_seconds'] for e in es if e['outer_bracket_seconds'] is not None]
        latency.append({'asset':asset,'episodes':len(es),'single_sample_episodes':sum(e['positive_samples']==1 for e in es),
            'median_poll_seconds':statistics.median(intervals),'p95_poll_seconds':quantile(intervals,.95),
            'median_observed_span_seconds':statistics.median(e['observed_first_to_last_seconds'] for e in es),
            'max_observed_span_seconds':max(e['observed_first_to_last_seconds'] for e in es),
            'median_outer_bracket_seconds':statistics.median(closed) if closed else None,
            'left_censored_episodes':sum(e['left_censored'] for e in es),'right_censored_episodes':sum(e['right_censored'] for e in es)})
    route_summary=[]
    for route,rs in groups.items():
        es=[e for e in standard if e['route']==route]
        if not es:continue
        intervals=[b['timestamp']-a['timestamp'] for a,b in zip(rs,rs[1:])]
        route_summary.append({'asset':rs[0]['asset'],'route':route,'episodes':len(es),
            'positive_observations':sum(e['positive_samples'] for e in es),
            'single_sample_episodes':sum(e['positive_samples']==1 for e in es),
            'median_poll_seconds':statistics.median(intervals) if intervals else None,
            'median_observed_span_seconds':statistics.median(e['observed_first_to_last_seconds'] for e in es),
            'longest_observed_span_seconds':max(e['observed_first_to_last_seconds'] for e in es),
            'left_censored':sum(e['left_censored'] for e in es),'right_censored':sum(e['right_censored'] for e in es)})
    route_summary.sort(key=lambda x:x['positive_observations'],reverse=True)
    write_csv(out/'persistence_routes.csv',route_summary)
    latency.sort(key=lambda e:e['episodes'],reverse=True)
    write_csv(out/'latency_summary.csv',latency)
    fee_summary=[]
    for label,base in [('tier0',4.5),('tier1',4),('tier2',3.5),('tier3',3),('tier4',2.8),('tier5',2.6),('tier6',2.4),('tier6_diamond',1.44)]:
        for tier in ('standard','plus','premium'):
            es=persistence(groups,tier,base)
            fee_summary.append({'hl_account':label,'hl_native_taker_bps':base,'lighter_tier':tier,
                'positive_episodes':len(es),'positive_samples':sum(e['positive_samples'] for e in es),
                'single_sample_episodes':sum(e['positive_samples']==1 for e in es),
                'median_observed_span_seconds':statistics.median(e['observed_first_to_last_seconds'] for e in es) if es else None,
                'opening_edge_sum_usd':sum(e['first_opening_edge_usd'] for e in es),
                'budgeted_edge_sum_usd':sum(e['first_budgeted_edge_usd'] for e in es),
                'rh_positive_episodes':sum('rh_lighter:' in e['route'] for e in es),
                'core_positive_episodes':sum('|lighter:' in e['route'] for e in es),
                'aster_positive_episodes':sum('aster:' in e['route'] for e in es)})
    write_csv(out/'fee_scenarios.csv',fee_summary)
    corrected=[]
    for tier in ('standard','plus','premium'):
        es=persistence(groups,tier,corrected_aster=True)
        corrected.append({'lighter_tier':tier,'positive_episodes':len(es),'positive_samples':sum(e['positive_samples'] for e in es),
                'single_sample_episodes':sum(e['positive_samples']==1 for e in es),
                'median_observed_span_seconds':statistics.median(e['observed_first_to_last_seconds'] for e in es) if es else None,
            'opening_edge_sum_usd':sum(e['first_opening_edge_usd'] for e in es),
            'budgeted_edge_sum_usd':sum(e['first_budgeted_edge_usd'] for e in es),
            'rh_positive_episodes':sum('rh_lighter:' in e['route'] for e in es),
            'core_positive_episodes':sum('|lighter:' in e['route'] for e in es),
            'aster_positive_episodes':sum('aster:' in e['route'] for e in es)})
    write_csv(out/'corrected_aster_fee_scenarios.csv',corrected)
    return {'episodes':len(standard),'single_sample_episodes':sum(e['positive_samples']==1 for e in standard),
        'median_observed_span_seconds':statistics.median(e['observed_first_to_last_seconds'] for e in standard),
        'max_observed_span_seconds':max(e['observed_first_to_last_seconds'] for e in standard),
        'latency_limit':'Polling brackets and repeated positive observations do not establish continuous lifetime or a subsecond execution deadline.'}


def audit(snapshot, out):
    out.mkdir(parents=True,exist_ok=True)
    meta = json.loads((snapshot/'snapshot.json').read_text())
    with gzip.open(snapshot/'observations.jsonl.gz','rt') as f:
        rows = [json.loads(line) for line in f]
    if meta['config'].get('lighter_tier')!='standard' or meta['config'].get('hl_fee_bps')!=4.5 or not meta['config'].get('reserve_exit_fees'):
        raise ValueError('Fee/persistence sensitivity currently supports Standard Lighter, HL base 4.5bp and exit-fee reserves; use a baseline snapshot.')
    rows = [r for r in rows if r['target_notional_usd']==1000]
    state, episodes, groups = {}, [], collections.defaultdict(list)
    for r in rows:
        groups[r['route']].append(r)
        prev = state.get(r['route'])
        positive = r['budgeted_edge_usd'] > 0
        if positive and (prev is None or not prev['positive'] or r['timestamp']-prev['timestamp']>meta['config']['episode_gap']):
            reason = 'first_seen' if prev is None else 'data_gap' if r['timestamp']-prev['timestamp']>meta['config']['episode_gap'] else 'crossed_back_above_zero'
            episodes.append(r | {'episode_reason':reason,'prior_budgeted_edge_usd':prev['budget'] if prev else None,
                                 'seconds_since_prior_observation':r['timestamp']-prev['timestamp'] if prev else None})
        state[r['route']] = {'positive':positive,'timestamp':r['timestamp'],'budget':r['budgeted_edge_usd']}
    per_asset=[]
    for asset in sorted({r['asset'] for r in episodes}):
        es=[r for r in episodes if r['asset']==asset]
        per_asset.append({'asset':asset,'episodes':len(es),
            'opening_edge_sum_usd':sum(r['net_entry_usd'] for r in es),
            'closing_fee_reserve_sum_usd':sum(r['estimated_exit_fee_reserve_usd'] for r in es),
            'other_reserve_sum_usd':sum(r['additional_cost_reserve_usd'] for r in es),
            'budgeted_edge_sum_usd':sum(r['budgeted_edge_usd'] for r in es),
            'median_episode_budget_usd':statistics.median(r['budgeted_edge_usd'] for r in es),
            'max_episode_budget_usd':max(r['budgeted_edge_usd'] for r in es),
            'retriggered_after_nonpositive':sum(r['episode_reason']=='crossed_back_above_zero' for r in es)})
    per_asset.sort(key=lambda r:r['opening_edge_sum_usd'],reverse=True)
    for rs in groups.values(): rs.sort(key=lambda r:r['timestamp'])
    times={key:[r['timestamp'] for r in rs] for key,rs in groups.items()}
    persistence_summary=latency_and_fees(groups,out)
    exits=[]
    # Independent overlapping diagnostics: not a finite-capital portfolio.
    for entry in episodes:
        reverse=f"{entry['asset']}|{entry['sell']}|{entry['buy']}"
        rs=groups.get(reverse,[]); ts=times.get(reverse,[])
        for minutes in (0,5,15,30,60):
            target=entry['timestamp']+minutes*60
            i=bisect.bisect_left(ts,target)
            if i==len(rs): continue
            close=rs[i]
            delay=close['timestamp']-target
            if delay>(.001 if minutes==0 else 180): continue
            q=float(entry['base_quantity']); close_q=float(close['base_quantity'])
            relative=close_q/q-1
            if abs(relative)>.01: continue
            # Saved opposite-direction VWAPs, scaled to original q. Full old books
            # are absent. A larger reference q is conservative on both sorted books;
            # a smaller one may overstate exit proceeds. Neither is an exact rewalk.
            sell_long=q*close['sell_vwap']; buy_short=q*close['buy_vwap']
            exit_fees=(sell_long*close['sell_fee_bps']+buy_short*close['buy_fee_bps'])/10000
            pnl=(sell_long-entry['buy_cost_usd'])+(entry['sell_proceeds_usd']-buy_short)-entry['entry_fees_usd']-exit_fees
            same_hour=int(entry['timestamp']//3600)==int(close['timestamp']//3600)
            exits.append({'asset':entry['asset'],'route':entry['route'],'entry_utc':entry['utc'],'close_utc':close['utc'],
                'horizon_minutes':minutes,'delay_seconds':delay,'same_utc_hour':same_hour,
                'quantity_reference_difference_pct':relative*100,'reference_quantity_at_least_entry':close_q>=q,
                'opening_edge_usd':entry['net_entry_usd'],'budgeted_entry_usd':entry['budgeted_edge_usd'],
                'exit_gap_cost_usd':buy_short-sell_long,'entry_fees_usd':entry['entry_fees_usd'],
                'exit_fees_usd':exit_fees,'four_fee_price_pnl_proxy_usd':pnl,
                'also_minus_other_reserve_usd':pnl-entry['additional_cost_reserve_usd'],
                'funding_included':False})
    exit_summary=[]
    for minutes in (0,5,15,30,60):
        for subset in ('all_funding_unmodeled','same_utc_hour'):
            es=[r for r in exits if r['horizon_minutes']==minutes and (subset!='same_utc_hour' or r['same_utc_hour'])]
            if not es: continue
            vs=[r['four_fee_price_pnl_proxy_usd'] for r in es]
            exit_summary.append({'horizon_minutes':minutes,'subset':subset,'scenarios':len(es),
                'positive':sum(v>0 for v in vs),'positive_fraction':sum(v>0 for v in vs)/len(vs),
                'median_proxy_pnl_usd':statistics.median(vs),'mean_proxy_pnl_usd':statistics.mean(vs),
                'sum_overlapping_proxy_pnl_usd':sum(vs),'worst_proxy_pnl_usd':min(vs),'best_proxy_pnl_usd':max(vs),
                'quantity_difference_p95_abs_pct':quantile([abs(r['quantity_reference_difference_pct']) for r in es],.95)})
    # Verify fee algebra and recomputed sums, before interpreting economics.
    fee_errors=[]; budget_errors=[]
    for r in rows:
        fee=(r['buy_cost_usd']*r['buy_fee_bps']+r['sell_proceeds_usd']*r['sell_fee_bps'])/10000
        fee_errors.append(abs(fee-r['entry_fees_usd']))
        budget=r['sell_proceeds_usd']-r['buy_cost_usd']-fee-r['estimated_exit_fee_reserve_usd']-r['additional_cost_reserve_usd']
        budget_errors.append(abs(budget-r['budgeted_edge_usd']))
    opening=sum(r['net_entry_usd'] for r in episodes)
    budget=sum(r['budgeted_edge_usd'] for r in episodes)
    summary={'snapshot_utc':meta['snapshot_utc'],'evidence_sha256':meta['evidence_sha256'],
        'start_utc':min(r['utc'] for r in rows),'end_utc':max(r['utc'] for r in rows),
        'hours':(max(r['timestamp'] for r in rows)-min(r['timestamp'] for r in rows))/3600,
        'observations':len(rows),'routes':len(groups),'assets':len({r['asset'] for r in rows}),
        'episodes_reconstructed':len(episodes),'stored_totals':meta['totals'],
        'persistence':persistence_summary,
        'matches_stored_totals':len(episodes)==meta['totals']['paper_1000_episodes'] and abs(opening-meta['totals']['paper_1000_net_entry_sum_usd'])<1e-7 and abs(budget-meta['totals']['paper_1000_budgeted_sum_usd'])<1e-7,
        'opening_edge_sum_usd':opening,'closing_fee_reserve_sum_usd':sum(r['estimated_exit_fee_reserve_usd'] for r in episodes),
        'other_reserve_sum_usd':sum(r['additional_cost_reserve_usd'] for r in episodes),'budgeted_edge_sum_usd':budget,
        'median_episode_budget_usd':statistics.median(r['budgeted_edge_usd'] for r in episodes),
        'episode_reasons':dict(collections.Counter(r['episode_reason'] for r in episodes)),
        'episodes_budget_below_10c':sum(r['budgeted_edge_usd']<.1 for r in episodes),
        'max_fee_algebra_error_usd':max(fee_errors),'max_budget_algebra_error_usd':max(budget_errors),
        'p95_hl_engine_age_ms':quantile([r['hl_engine_age_ms'] for r in rows],.95),
        'p95_receipt_skew_ms':quantile([r['receipt_skew_ms'] for r in rows],.95),
        'episode_counts_by_comparator':dict(collections.Counter((r['sell'] if r['buy'].startswith('hyperliquid:') else r['buy']).split(':')[0] for r in episodes)),
        'note':'Exit diagnostics scale opposite-direction saved VWAPs to original quantity, require <=1% quantity mismatch; no full-book exact historical fills or funding ledger. Sums overlap and are not portfolio P&L.'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    write_csv(out/'episodes.csv',episodes); write_csv(out/'asset_contributions.csv',per_asset)
    write_csv(out/'unwind_diagnostics.csv',exits); write_csv(out/'unwind_summary.csv',exit_summary)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    fig,axes=plt.subplots(3,1,figsize=(11,8),sharex=True)
    routes=['NVDA|hyperliquid:xyz:NVDA|rh_lighter:15','XPL|lighter:71|hyperliquid:XPL','INTC|hyperliquid:xyz:INTC|rh_lighter:30']
    for ax,route in zip(axes,routes):
        rs=groups.get(route,[])
        for positive,color in [(False,'#a64646'),(True,'#16836a')]:
            subset=[r for r in rs if (r['budgeted_edge_usd']>0)==positive]
            ax.scatter([dt.datetime.fromtimestamp(r['timestamp'],dt.timezone.utc) for r in subset],
                       [r['budgeted_edge_bps'] for r in subset],s=7,color=color,alpha=.75)
        ax.axhline(0,color='black',linewidth=.7)
        ax.set_title(route.replace('|',' / '),fontsize=10,loc='left')
        ax.set_ylabel('Budgeted entry bp')
        ax.grid(alpha=.2)
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%H:%M',tz=dt.timezone.utc))
    axes[-1].set_xlabel('2026-09-29 UTC; points are sampled quotes, not continuous fills')
    fig.suptitle('$1,000 opening-spread signals: persistence and threshold crossings')
    fig.tight_layout();fig.savefig(out/'persistence.png',dpi=160);plt.close(fig)
    print(json.dumps(summary,indent=2));print(json.dumps(exit_summary,indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,default=ROOT/'data/monitor')
    p.add_argument('--snapshot',type=Path,help='Reuse a frozen snapshot for offline reanalysis')
    p.add_argument('--out',type=Path,default=ROOT/'reports/monitor-audit')
    args=p.parse_args()
    snap=args.snapshot or ROOT/'data/raw/monitor_audit'/dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    if not args.snapshot:freeze(args.run,snap)
    print('Snapshot:',snap)
    audit(snap,args.out)

if __name__=='__main__':main()
