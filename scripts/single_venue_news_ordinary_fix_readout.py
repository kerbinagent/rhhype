"""Bounded corrected news comparisons after twenty matching independent audits."""
import csv,datetime,gzip,io,json,sys
from decimal import Decimal as D
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts import single_venue_news_ordinary_fix as fix

def packed_json(path,cap,decoded_cap=2097152):
    assert not path.is_symlink() and path.stat().st_size<=cap
    with gzip.open(path,'rb') as f:data=f.read(decoded_cap+1)
    assert len(data)<=decoded_cap,'decoded_report_byte_cap'
    return json.loads(data)
def main(family):
    plan=fix.verify(family);pins=fix.require_pins(plan);stem=plan['output_stem'];rows=[];evidence=[]
    capture=fix.ROOT/plan['capture_root'];manifest=fix.read(capture/'manifest.json')
    original=fix.read(fix.news.PLAN)
    assert datetime.datetime.fromisoformat(original['recorded_utc'])<datetime.datetime.fromisoformat(manifest['started_utc'])
    rules=('gap_fade','leader_follow','local_shock_fade') if family=='relative' else ('depth_fade','depth_follow')
    expected={r+':'+v for r in rules for v in ('rh_lighter','lighter')}
    for asset in plan['assets']:
        name=stem+'-'+family+'-'+asset.lower();directory=fix.RESEARCH/name
        assert fix.tree_bytes(directory)<=fix.CAPS['per_directory']
        summary=packed_json(directory/'summary.json.gz',fix.CAPS['summary'])
        audit=fix.read(directory/'independent-audit.json',fix.CAPS['audit'])
        assert audit['status']=='passed' and audit['sample']==name
        assert audit['raw_capture_verified'] is True
        assert audit['summary_sha256']==fix.sha(directory/'summary.json.gz')
        assert audit['trace_sha256']==fix.sha(directory/'trace.jsonl.gz')==summary['trace_sha256']
        assert not summary['error'] and summary['complete_capture_verified'] and summary['asset']==asset
        assert summary['sample']==name and summary['source']==plan['capture_root']
        assert summary['manifest_sha256']==pins['manifest_sha256'] and summary['plan_sha256']==fix.sha(fix.PLAN)
        assert set(summary['arms'])==expected
        evidence.append(dict(asset=asset,sample=name,manifest_sha256=pins['manifest_sha256'],
            summary_sha256=audit['summary_sha256'],trace_sha256=audit['trace_sha256'],
            audit_sha256=fix.sha(directory/'independent-audit.json'),feature_counts=summary['feature_counts'],
            signal_checks_vacuous=audit['signal_checks_vacuous'],fill_checks_vacuous=audit['fill_checks_vacuous']))
        for arm,r in summary['arms'].items():
            rule,venue=arm.split(':');episodes=r['episodes']
            net=sum((D(e['cash_after_capital']) for e in episodes),D(0))
            stress=sum((D(e['stressed_net']) for e in episodes),D(0));change=D(r['cash'])-600
            if r['complete']:assert not r['unknown'] and not r['position'] and not r['pending'] and abs(change-net)<D('1e-20')
            rows.append(dict(window=1,asset=asset,rule=rule,venue=venue,collateral='USDC' if venue=='lighter' else 'USDG',
                attempts=r['attempts'],closed=r['closed'],zero_fill_entries=r['counts'].get('entry_no_fill',0),
                winning_closes=sum(D(e['cash_after_capital'])>0 for e in episodes),
                stressed_winning_closes=sum(D(e['stressed_net'])>0 for e in episodes),
                long_closes=sum(e['side']==1 for e in episodes),short_closes=sum(e['side']==-1 for e in episodes),
                closed_entry_notional=str(sum((D(e['entry_value']) for e in episodes),D(0))),
                closed_cash_after_capital=str(net),closed_stressed_cash=str(stress),realized_cash_change=str(change),
                complete=r['complete'],unknown=r['unknown'],position_open=r['position'] is not None,pending_order=r['pending'] is not None))
    assert len(rows)==(60 if family=='relative' else 40) and len(evidence)==10
    # Exactly one fixed window: each aggregate represents one independent arm.
    aggregates=[dict(asset=r['asset'],rule=r['rule'],venue=r['venue'],windows=[1],all_flat_known=r['complete'],
        **{k:r[k] for k in ('attempts','closed','zero_fill_entries','winning_closes','stressed_winning_closes',
        'long_closes','short_closes','closed_entry_notional','closed_cash_after_capital','closed_stressed_cash','realized_cash_change')}) for r in rows]
    result=dict(schema=stem+'-'+family+'-comparison-v1',recorded_utc=fix.utc(),source_sha256=fix.sha(Path(__file__)),
        analysis_plan_sha256=fix.sha(fix.PLAN),capture_plan_sha256=fix.CAPTURE_PLAN_SHA,
        manifest_sha256=pins['manifest_sha256'],raw_sha256=pins['raw_sha256'],evidence=evidence,rows=rows,aggregates=aggregates,
        limits='Conditional public-book IOC model, no private acknowledgments or fills. Independent asset/rule/venue ledgers cannot be summed. Unknown obligations prevent a total profit claim. Empty audits and zero entries provide no profitability evidence. USDG and USDC remain separate native collateral. One exploratory scheduled regime; any positive arm requires fresh validation.')
    packed=gzip.compress(fix.encode(result),mtime=0)
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    csv_bytes=stream.getvalue().encode()
    assert len(packed)<=fix.CAPS['comparison_gzip_per_family'] and len(csv_bytes)<=fix.CAPS['comparison_csv_per_family']
    targets=[fix.RESEARCH/(stem+'-'+family+'-comparison'+s) for s in ('.json.gz','.csv')]
    assert not any(p.exists() for p in targets)
    fix.verify(family);fix.require_pins(plan)
    fix.publish(targets[0],packed,fix.CAPS['comparison_gzip_per_family'])
    fix.publish(targets[1],csv_bytes,fix.CAPS['comparison_csv_per_family'])

def combined_readout(plan):
    pins=fix.require_pins(plan);rows=[];evidence=[]
    for family in ('relative','depth'):
        report=packed_json(fix.RESEARCH/(plan['output_stem']+'-'+family+'-comparison.json.gz'),fix.CAPS['comparison_gzip_per_family'])
        assert report['analysis_plan_sha256']==fix.sha(fix.PLAN) and report['capture_plan_sha256']==fix.CAPTURE_PLAN_SHA
        assert report['manifest_sha256']==pins['manifest_sha256'] and report['raw_sha256']==pins['raw_sha256']
        assert len(report['rows'])==(60 if family=='relative' else 40) and len(report['evidence'])==10
        rules=('gap_fade','leader_follow','local_shock_fade') if family=='relative' else ('depth_fade','depth_follow')
        assert {(r['asset'],r['rule'],r['venue']) for r in report['rows']}=={(a,r,v) for a in plan['assets'] for r in rules for v in ('rh_lighter','lighter')}
        assert {e['sample'] for e in report['evidence']}=={plan['output_stem']+'-'+family+'-'+a.lower() for a in plan['assets']}
        for e in report['evidence']:
            out=fix.RESEARCH/e['sample']
            for key,name in (('summary_sha256','summary.json.gz'),('trace_sha256','trace.jsonl.gz'),('audit_sha256','independent-audit.json')):
                assert e[key]==fix.sha(out/name)
            audit=fix.read(out/'independent-audit.json',fix.CAPS['audit'])
            assert audit['status']=='passed' and audit['sample']==e['sample'] and audit['raw_capture_verified']
            assert audit['summary_sha256']==e['summary_sha256'] and audit['trace_sha256']==e['trace_sha256']
            assert all(audit[k]==e[k] for k in ('signal_checks_vacuous','fill_checks_vacuous'))
        rows.extend(dict(family=family,**r) for r in report['rows']);evidence.extend(report['evidence'])
    assert len(rows)==100 and len(evidence)==20
    lines=['CORRECTED NEWS WINDOW: AUTOMATED PAPER READOUT',
        'All 100 independent asset/venue/rule rows remain in the two comparison files. All 20 matching independent audits passed.',
        'Conditional public-book IOC model; no private acknowledgments or authenticated fills. Independent ledgers must not be summed. USDG/USDC collateral remains separate.',
        'Cash is native collateral after modeled fees/capital. Stress deducts 5bp of entry notional. Empty audits are vacuous; zero-entry arms provide no profitability evidence. One exploratory regime is not durable profitability.',
        'Total arms=100; flat_known='+str(sum(r['complete'] for r in rows))+'; arms_with_attempts='+str(sum(r['attempts']>0 for r in rows)),
        'Vacuous signal audits='+str(sum(e['signal_checks_vacuous'] for e in evidence))+'; vacuous fill audits='+str(sum(e['fill_checks_vacuous'] for e in evidence))]
    for r in rows:
        if r['attempts'] or not r['complete']:
            lines.append(f"{r['family']}/{r['asset']}/{r['venue']}/{r['rule']}: attempts={r['attempts']}, closed={r['closed']}, cash={D(r['closed_cash_after_capital']):.6g}, stress={D(r['closed_stressed_cash']):.6g}, complete={r['complete']}, unknown={bool(r['unknown'])}")
    fix.publish(fix.RESEARCH/(plan['output_stem']+'-readout.txt'),('\n'.join(lines)+'\n').encode(),fix.CAPS['readout'])
if __name__=='__main__':main(*sys.argv[1:])
