#!/usr/bin/env python3
"""Independent derived-only check; never imports strategy or opens raw inputs."""
import csv, gzip, hashlib, io, json, math, statistics, sys
from collections import Counter, defaultdict
from fractions import Fraction as F
from pathlib import Path
NS=10**9
START=1790736777958514000
END=START+3000*NS
ASSETS=('BTC','ETH','NVDA','XAG')
BUDGETS=(100,250,500,1000)
HORIZONS=(10,30,60,300)
SCHEMA='fixed-quantity-delayed-taker-quote-diagnostic-v1'
REV='v3_cache_disabled_recovery'
RAW='c92c269e3bc3bb345beeaf834ad55d0a97601339b4506e36a9397287f8407bb6'
META='34249d999bf176b73a2f9e30aa1602f3ab135a7cadc9238a080bfe060f048aba'
MANIFEST='5a9e61438df592d895d3cfc5d550241b01f0696fdbd5c83f46666d9ff1274250'
C_FIELDS=('id','anchor_ns','stratum','asset','long_venue','budget','quantity','status','anchor_long_buy_notional','anchor_notional_exceeds_budget','entry_ns','entry_long_buy','entry_short_sell','entry_long_fee','entry_short_fee','entry_notional_exceeds_anchor_budget','entry_drift_from_anchor_walk','instant_adjusted_ex_funding','instant_deficit_to_010','anchor_rh_source_ns','anchor_rh_received_ns','anchor_rh_generation','anchor_hl_source_ns','anchor_hl_received_ns','anchor_hl_generation','rh_source_ns','rh_received_ns','rh_generation','hl_source_ns','hl_received_ns','hl_generation')
O_FIELDS=('candidate_id','horizon','status','exit_ns','exit_long_sell','exit_short_buy','gross','entry_long_fee','entry_short_fee','exit_long_fee','exit_short_fee','fee_only_net','stress','capital','adjusted_quote_net_ex_funding','improvement_from_instant','funding_unknown','utc_hour_boundary_crossed','funding_boundary_tie','rh_source_ns','rh_received_ns','rh_generation','hl_source_ns','hl_received_ns','hl_generation')
checks=Counter()
def check(ok,label):
    if not ok: raise AssertionError(label)
    checks[label]+=1
def sha(p):
    check(not p.is_symlink() and p.is_file(),'regular_published_file')
    return hashlib.sha256(p.read_bytes()).hexdigest()
def load_gz(p):
    with gzip.open(p,'rb') as h: data=h.read(80_000_001)
    check(len(data)<=80_000_000,'decompressed_80MB_bound')
    return data.decode()
def rows(p,fields,count):
    reader=csv.DictReader(io.StringIO(load_gz(p)))
    check(tuple(reader.fieldnames)==fields,'exact_csv_header')
    values=[]
    for row in reader:
        check(None not in row and all(v is not None for v in row.values()),'csv_complete_shape')
        values.append(row)
        check(len(values)<=count,'csv_count_upper_bound')
    check(len(values)==count,'csv_exact_count')
    return values
def truth(v):
    check(v in ('True','False'),'csv_boolean')
    return v=='True'
def same_fraction(value,expected,label): check(F(value)==expected,label)
def clock(row,prefix,now,baseline=None,due=None):
    for venue in ('rh','hl'):
        source=int(row[prefix+venue+'_source_ns']);receipt=int(row[prefix+venue+'_received_ns'])
        check(0<source<=receipt<=now and now-source<=2*NS and now-receipt<=2*NS,'clock_causal_fresh')
        check(bool(row[prefix+venue+'_generation']),'clock_generation_present')
        if baseline is not None:
            check(source>int(baseline[venue+'_source_ns']) and receipt>int(baseline[venue+'_received_ns']),'clock_strict_advance')
            check(source>=due and receipt>=due,'clock_at_or_after_due')
            check(row[prefix+venue+'_generation']==baseline[venue+'_generation'],'clock_same_generation')
    for suffix in ('source_ns','received_ns'):
        check(abs(int(row[prefix+'rh_'+suffix])-int(row[prefix+'hl_'+suffix]))<=NS,'clock_cross_venue_skew')
def stats(items):
    complete=[o for o in items if o['status']=='quote_complete']; vals=[F(o['adjusted_quote_net_ex_funding']) for o in complete]
    return dict(original=len(items),statuses=dict(Counter(o['status'] for o in items)),quote_complete=len(complete),fee_positive=sum(F(o['fee_only_net'])>0 for o in complete),adjusted_positive_ex_funding=sum(x>0 for x in vals),adjusted_at_least_010_ex_funding=sum(x>=F(1,10) for x in vals),hour_crossings=sum(truth(o['utc_hour_boundary_crossed']) for o in complete),adjusted_min_median_max_ex_funding=None if not vals else [min(vals),statistics.median(vals),max(vals)])
def verify_stats(actual,expected):
    check(set(actual)-{'key'}==set(expected),'summary_stat_fields')
    for k,v in expected.items():
        if k=='adjusted_min_median_max_ex_funding' and v is not None:
            check([F(x) for x in actual[k]]==v,'summary_exact_min_median_max')
        else:check(actual[k]==v,'summary_'+k)
def main(path):
    out=Path(path)
    check(out.name=='0252Z-v3' and not out.name.endswith('.building') and not out.is_symlink(),'completed_v3_path')
    check(out.is_dir(),'published_directory')
    before={p.name:sha(p) for p in out.iterdir()}
    publication=json.loads((out/'manifest.json').read_text())
    check(publication['schema']==SCHEMA and publication['status']=='complete' and publication['resource_revision']==REV,'complete_schema_revision')
    check(publication['verified_terminal'] is True and publication['input_hashes_unchanged'] is True and publication['level_validation_cache_enabled'] is False,'manifest_attestations')
    check(publication['network_calls']==0 and publication['raw_traversals']==1 and 0<publication['wall_seconds']<=1200,'manifest_resource_gates')
    check(publication['original_candidates_verified']==7200 and publication['original_horizon_rows_verified']==28800,'manifest_denominators')
    expected_files={'source.py','tests.py','method.md','metadata.json','freeze.json','candidates.csv.gz','outcomes.csv.gz','summary.json.gz','readout.md'}
    check(set(publication['output_hashes'])==expected_files,'manifest_exact_original_outputs')
    check(set(before)==expected_files|{'manifest.json'},'publication_inventory')
    check({k:before[k] for k in expected_files}==publication['output_hashes'],'manifest_output_hashes')
    check(sum(p.stat().st_size for p in out.iterdir())<=3_950_000,'publication_aggregate_cap')
    freeze=json.loads((out/'freeze.json').read_text()); meta=json.loads((out/'metadata.json').read_text())
    check(freeze['schema']==SCHEMA and freeze['resource_revision']==REV and freeze['observation_cutoff_ns']==END,'freeze_schema_cutoff')
    check(freeze['inputs_and_actual_dependencies_sha256']==publication['input_hashes'],'freeze_input_hash_equality')
    check(freeze['level_validation_cache']['enabled'] is False and freeze['grid']['level_validation_cache']['enabled'] is False,'freeze_disabled_cache')
    check(freeze['grid']['candidate_count']==7200 and freeze['grid']['horizon_count']==28800 and freeze['grid']['horizons']==list(HORIZONS) and freeze['grid']['wall_seconds']==1200,'freeze_grid')
    for copied,suffix in [('source.py','/scripts/analyze_delayed_taker_quotes.py'),('tests.py','/tests/test_analyze_delayed_taker_quotes.py'),('method.md','/research/delayed-taker-fixed-quantity-plan.md'),('metadata.json','/metadata/normalized.json')]:
        matches=[v for k,v in publication['input_hashes'].items() if k.endswith(suffix)]
        check(matches==[before[copied]],'copied_source_input_hash')
    check(before['metadata.json']==META,'metadata_fixed_hash')
    for suffix,digest in [('/frames.jsonl.gz',RAW),('/20260930T0252Z/manifest.json',MANIFEST)]:
        check([v for k,v in publication['input_hashes'].items() if k.endswith(suffix)]==[digest],'recorded_capture_input_identity')
    for venue in ('rh_lighter','hyperliquid'):
        for asset in ASSETS:
            expected=F(0) if venue=='rh_lighter' else F('4.5' if asset in ('BTC','ETH') else '.9')
            check(F(meta['markets'][venue][asset]['taker_fee_bps'])==expected,'metadata_public_fees')
    candidates=rows(out/'candidates.csv.gz',C_FIELDS,7200); outcomes=rows(out/'outcomes.csv.gz',O_FIELDS,28800)
    identities=[]
    for offset in range(0,3000,5):
        for asset in ASSETS:
            for budget in BUDGETS:
                if budget!=1000 and offset%30:continue
                for long in ('rh_lighter','hyperliquid'):identities.append((START+offset*NS,offset//600,asset,budget,long))
    by={};groups=defaultdict(list);strata=defaultdict(list); omap={}
    for ident,(c,expected) in enumerate(zip(candidates,identities)):
        anchor,stratum,asset,budget,long=expected
        check((int(c['id']),int(c['anchor_ns']),int(c['stratum']),c['asset'],int(c['budget']),c['long_venue'])==(ident,anchor,stratum,asset,budget,long),'candidate_exact_grid_identity')
        by[ident]=c
        check(c['status']=='entry_quote_complete' or c['status'].startswith(('anchor_','entry_')) and c['status']!='entry_pending','candidate_terminal_status')
        if c['quantity']:
            q=F(c['quantity']);check(q>=0,'quantity_nonnegative')
            for venue in ('rh_lighter','hyperliquid'):
                step=F(meta['markets'][venue][asset]['size_step']);check((q/step).denominator==1,'quantity_common_grid')
        if c['anchor_long_buy_notional']:
            clock(c,'anchor_',anchor)
            check(truth(c['anchor_notional_exceeds_budget'])==(F(c['anchor_long_buy_notional'])>budget),'anchor_depth_budget_flag')
        if c['status']=='entry_quote_complete':
            entry=int(c['entry_ns']);check(anchor+NS//2<=entry<=min(anchor+2*NS,END),'entry_window')
            baseline={k.removeprefix('anchor_'):v for k,v in c.items() if k.startswith('anchor_')}
            clock(c,'',entry,baseline,anchor+NS//2)
            check(F(c['quantity'])>0,'entry_positive_quantity')
            for venue in ('rh_lighter','hyperliquid'):
                rule=meta['markets'][venue][asset];q=F(c['quantity'])
                check(q>=F(rule.get('min_qty') or rule['size_step']) and (rule.get('max_qty') is None or q<=F(rule['max_qty'])),'entry_quantity_order_rules')
            le,se=F(c['entry_long_buy']),F(c['entry_short_sell'])
            check(le>0 and se>0,'entry_positive_notionals')
            for venue,value in ((long,le),('hyperliquid' if long=='rh_lighter' else 'rh_lighter',se)):
                rule=meta['markets'][venue][asset]
                check(value>=F(rule['min_notional']) and (rule.get('max_quote') is None or value<=F(rule['max_quote'])),'entry_notional_order_rules')
            lr,sr=(F(0),F('4.5' if asset in ('BTC','ETH') else '.9')/10000) if long=='rh_lighter' else (F('4.5' if asset in ('BTC','ETH') else '.9')/10000,F(0))
            same_fraction(c['entry_long_fee'],le*lr,'candidate_long_own_fee');same_fraction(c['entry_short_fee'],se*sr,'candidate_short_own_fee')
            same_fraction(c['entry_drift_from_anchor_walk'],le-F(c['anchor_long_buy_notional']),'entry_anchor_drift')
            check(truth(c['entry_notional_exceeds_anchor_budget'])==(le>budget),'entry_budget_flag')
            if c['instant_adjusted_ex_funding']:same_fraction(c['instant_deficit_to_010'],F(1,10)-F(c['instant_adjusted_ex_funding']),'instant_deficit_identity')
            else:check(c['instant_deficit_to_010']=='','missing_instant_deficit_blank')
        else:
            check(all(c[k]=='' for k in ('entry_ns','entry_long_buy','entry_short_sell','entry_long_fee','entry_short_fee','instant_adjusted_ex_funding','instant_deficit_to_010','rh_source_ns','hl_source_ns')),'censored_candidate_economics_blank')
    check(Counter(int(c['stratum']) for c in candidates)==Counter({i:1440 for i in range(5)}),'candidate_strata_denominator')
    for n,o in enumerate(outcomes):
        ident,horizon=int(o['candidate_id']),int(o['horizon']);check((ident,horizon)==(n//4,HORIZONS[n%4]),'outcome_exact_identity_order');c=by[ident];omap[ident,horizon]=o
        check(truth(o['funding_unknown']),'all_funding_unknown');check(o['status']=='quote_complete' or o['status'].startswith(('anchor_','entry_','exit_')) and 'pending' not in o['status'],'outcome_terminal_status')
        key=(c['asset'],c['long_venue'],int(c['budget']),horizon);groups[key].append(o);strata[(*key,int(c['stratum']))].append(o)
        if o['status']=='quote_complete':
            check(c['status']=='entry_quote_complete','completed_exit_shared_entry')
            entry=int(c['entry_ns']);exit=int(o['exit_ns']);due=entry+horizon*NS+NS//2
            check(due<=exit<=min(entry+horizon*NS+2*NS,END),'exit_window')
            clock(o,'',exit,c,due)
            le,se,lx,sx=map(F,(c['entry_long_buy'],c['entry_short_sell'],o['exit_long_sell'],o['exit_short_buy']))
            check(lx>0 and sx>0,'exit_positive_notionals')
            for venue,value in ((c['long_venue'],lx),('hyperliquid' if c['long_venue']=='rh_lighter' else 'rh_lighter',sx)):
                rule=meta['markets'][venue][c['asset']]
                check(value>=F(rule['min_notional']) and (rule.get('max_quote') is None or value<=F(rule['max_quote'])),'exit_notional_order_rules')
            rate=F('4.5' if c['asset'] in ('BTC','ETH') else '.9')/10000
            lr,sr=(F(0),rate) if c['long_venue']=='rh_lighter' else (rate,F(0))
            fees=(le*lr,se*sr,lx*lr,sx*sr);gross=se-le+lx-sx;fee_net=gross-sum(fees);stress=max(le,se)*F(5,10000);capital=(le+se)*F(5,100)*F(exit-entry,NS*365*86400);adjusted=fee_net-stress-capital
            expected=dict(zip(('entry_long_fee','entry_short_fee','exit_long_fee','exit_short_fee'),fees));expected.update(gross=gross,fee_only_net=fee_net,stress=stress,capital=capital,adjusted_quote_net_ex_funding=adjusted)
            for k,v in expected.items():same_fraction(o[k],v,'four_fill_'+k)
            check(o['entry_long_fee']==c['entry_long_fee'] and o['entry_short_fee']==c['entry_short_fee'],'shared_entry_fees_exact')
            check(truth(o['utc_hour_boundary_crossed'])==(entry//(3600*NS)!=exit//(3600*NS)),'hour_crossing_flag')
            check(truth(o['funding_boundary_tie'])==(entry%(3600*NS)==0 or exit%(3600*NS)==0),'funding_boundary_tie_flag')
            if c['instant_adjusted_ex_funding']:same_fraction(o['improvement_from_instant'],adjusted-F(c['instant_adjusted_ex_funding']),'instant_improvement_identity')
            else:check(o['improvement_from_instant']=='','missing_instant_improvement_blank')
        else:
            check(all(o[k]=='' for k in O_FIELDS if k not in ('candidate_id','horizon','status','funding_unknown')),'censored_outcome_economics_clocks_blank')
            if c['status']!='entry_quote_complete':check(o['status']==c['status'],'initial_failure_all_horizons')
    summary=json.loads(load_gz(out/'summary.json.gz'))
    check(summary['schema']==SCHEMA and summary['resource_revision']==REV and summary['status']=='complete_quote_diagnostic','summary_schema')
    check(summary['candidates']==7200 and summary['horizon_rows']==28800 and summary['candidate_statuses']==dict(Counter(c['status'] for c in candidates)),'summary_candidate_denominators')
    check(summary['funding_inclusive_net'] is None and summary['summed_portfolio_net'] is None and summary['actual_fills_observed'] is False and summary['private_ack_observed'] is False and summary['executable_profit_claim'] is False,'honest_quote_semantics')
    check(summary['level_validation_cache']['enabled'] is False and summary['level_validation_cache']['entries']==0,'actual_disabled_cache')
    terminal=summary['terminal_event'];check(terminal['raw_sha_verified'] is True and terminal['truncated'] is False and terminal['raw_gzip_sha256']==RAW and terminal['manifest_sha256']==MANIFEST and terminal['counts']['decoded_records']==124019 and terminal['started_ns']==START and terminal['stopped_ns']>=END and terminal['reason']=='duration_limit','recorded_verified_terminal')
    for field,suffix in [('adapter_sha256','/scripts/rh_maker_events.py'),('book_decoder_sha256','/scripts/maker_book_archive.py')]:check([v for k,v in publication['input_hashes'].items() if k.endswith(suffix)]==[terminal[field]],'terminal_recorded_source_hash')
    for name,expected in [('groups',groups),('stratum_groups',strata)]:
        actual=summary[name];check(len(actual)==len(expected),'summary_group_cardinality');check(len({tuple(g['key']) for g in actual})==len(actual),'summary_unique_group_keys')
        for g in actual:check(tuple(g['key']) in expected,'summary_expected_group_key');verify_stats(g,stats(expected[tuple(g['key'])]))
        check(sum(g['original'] for g in actual)==28800,'summary_group_denominator_conservation')
    contrasts=summary['shared_entry_control_contrasts'];check(len(contrasts)==96,'paired_contrast_cardinality');seen=set()
    for contrast in contrasts:
        key=tuple(contrast['key']);check(key not in seen and key in groups and key[3]!=10,'paired_unique_key');seen.add(key)
        pairs=[(omap[int(c['id']),10],omap[int(c['id']),key[3]]) for c in candidates if (c['asset'],c['long_venue'],int(c['budget']))==key[:3]]
        both=[(a,b) for a,b in pairs if a['status']==b['status']=='quote_complete'];deltas=[F(b['adjusted_quote_net_ex_funding'])-F(a['adjusted_quote_net_ex_funding']) for a,b in both]
        expected=dict(original=len(pairs),both_quote_complete=len(both),control_only_complete=sum(a['status']=='quote_complete' and b['status']!='quote_complete' for a,b in pairs),diagnostic_only_complete=sum(a['status']!='quote_complete' and b['status']=='quote_complete' for a,b in pairs))
        for k,v in expected.items():check(contrast[k]==v,'paired_'+k)
        median=contrast['median_quote_difference_ex_funding'];check((median is None and not deltas) or (median is not None and deltas and F(median)==statistics.median(deltas)),'paired_exact_median')
    check(before=={p.name:sha(p) for p in out.iterdir()},'published_hashes_unchanged_after')
    result=dict(status='passed',verification_scope='completed derived outputs only; no raw access or strategy invocation',path=str(out),candidates=7200,outcomes=28800,checks=dict(sorted(checks.items())),candidate_statuses=summary['candidate_statuses'],outcome_statuses=dict(Counter(o['status'] for o in outcomes)),input_hashes_currently_recomputed=False,limits=['Exported references support endpoint causality; first eligible selection/full book walks and anchor quantity floor are not reconstructable without raw books.','Instant opposite-walk cashflows are not exported; checked deficit and improvement identities only.','Input hashes/terminal are checked as recorded provenance; raw inputs deliberately not opened.'])
    text=json.dumps(result,sort_keys=True,indent=2)+'\n';check(len(text.encode())<50000,'verification_report_under_50k');print(text,end='')
if __name__=='__main__':main(sys.argv[1])
