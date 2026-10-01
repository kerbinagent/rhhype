"""Hash-verified tables for executable-filter batches and common-window screening."""
import csv,datetime,gzip,hashlib,io,json,sys
from decimal import Decimal as D
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/single-venue-research'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main(family):
    assert family in ('relative','depth')
    kind='relative'
    stem='single-venue-news'
    batch=ROOT/'reports'/stem
    terminal=json.loads((batch/'terminal.json').read_bytes())
    assert terminal['state']=='finished' and terminal['event_coverage_valid']
    assert terminal['all_windows_normal'] if kind=='shock' else terminal['normal_endpoint']
    plan=ROOT/'reports/experiment-storage'/(stem+'-v1.json');protocol=json.loads(plan.read_bytes())
    windows=(1,2,3) if kind=='shock' else (1,)
    assets=('LIT',) if kind=='shock' else tuple(protocol['assets'])
    evidence=[];rows=[]
    for index in windows:
        capture=(batch/f'window-{index}'/'capture') if kind=='shock' else batch/'capture'
        manifest=json.loads((capture/'manifest.json').read_bytes())
        assert manifest['end_reason']=='duration_limit' and not manifest['truncated']
        assert sha(capture/'frames.jsonl.gz')==manifest['frames_sha256']
        assert datetime.datetime.fromisoformat(protocol['recorded_utc'])<datetime.datetime.fromisoformat(manifest['started_utc'])
        for asset in assets:
            name=f'{stem}-{index}-lit' if kind=='shock' else f'{stem}-{family}-{asset.lower()}'
            directory=OUT/name;summary=json.loads(gzip.decompress((directory/'summary.json.gz').read_bytes()))
            audit=json.loads((directory/'independent-audit.json').read_bytes())
            assert audit['status']=='passed' and audit['sample']==name
            assert audit['summary_sha256']==sha(directory/'summary.json.gz')
            assert audit['trace_sha256']==sha(directory/'trace.jsonl.gz')==summary['trace_sha256']
            assert not summary['error'] and summary['complete_capture_verified'] and summary['asset']==asset
            assert summary['manifest_sha256']==sha(capture/'manifest.json') and summary['plan_sha256']==sha(plan)
            evidence.append(dict(window=index,asset=asset,sample=name,started_utc=manifest['started_utc'],ended_utc=manifest['ended_utc'],
                manifest_sha256=sha(capture/'manifest.json'),summary_sha256=audit['summary_sha256'],audit_sha256=sha(directory/'independent-audit.json'),feature_counts=summary['feature_counts']))
            for arm,r in summary['arms'].items():
                rule,venue=arm.split(':');episodes=r['episodes']
                net=sum((D(e['cash_after_capital']) for e in episodes),D(0))
                stress=sum((D(e['stressed_net']) for e in episodes),D(0));change=D(r['cash'])-600
                if r['complete']:assert not r['unknown'] and not r['position'] and not r['pending'] and abs(change-net)<D('1e-20')
                rows.append(dict(window=index,asset=asset,rule=rule,venue=venue,collateral='USDC' if venue=='lighter' else 'USDG',
                    attempts=r['attempts'],closed=r['closed'],zero_fill_entries=r['counts'].get('entry_no_fill',0),
                    winning_closes=sum(D(e['cash_after_capital'])>0 for e in episodes),
                    stressed_winning_closes=sum(D(e['stressed_net'])>0 for e in episodes),
                    long_closes=sum(e['side']==1 for e in episodes),short_closes=sum(e['side']==-1 for e in episodes),
                    closed_entry_notional=str(sum((D(e['entry_value']) for e in episodes),D(0))),
                    closed_cash_after_capital=str(net),closed_stressed_cash=str(stress),realized_cash_change=str(change),
                    complete=r['complete'],unknown=r['unknown'],position_open=r['position'] is not None,pending_order=r['pending'] is not None))
    aggregates=[]
    for asset,rule,venue in sorted({(r['asset'],r['rule'],r['venue']) for r in rows}):
        members=[r for r in rows if (r['asset'],r['rule'],r['venue'])==(asset,rule,venue)]
        total=dict(asset=asset,rule=rule,venue=venue,windows=list(windows),all_flat_known=all(r['complete'] for r in members))
        for key in ('attempts','closed','zero_fill_entries','winning_closes','stressed_winning_closes','long_closes','short_closes'):
            total[key]=sum(r[key] for r in members)
        for key in ('closed_entry_notional','closed_cash_after_capital','closed_stressed_cash','realized_cash_change'):
            total[key]=str(sum((D(r[key]) for r in members),D(0)))
        aggregates.append(total)
    result=dict(schema=stem+'-'+family+'-comparison-v1',recorded_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        source_sha256=sha(Path(__file__)),evidence=evidence,rows=rows,aggregates=aggregates,
        limits='Conditional public-book paper executions, no private acknowledgments or fills. Independent asset/rule/venue ledgers cannot be summed. Aggregates combine only the same asset/rule/venue across fixed windows. Unknown/open obligations prevent a total profit claim. Zero signals/fills provide no profitability evidence. Cross-asset screening has multiple comparisons and correlated events; any positive arm requires fresh validation. USDC and USDG are separate native collateral. Reference filters condition on parity, not an executable hedge or established fair value.')
    payload=gzip.compress((json.dumps(result,indent=2)+'\n').encode(),mtime=0);assert len(payload)<=16384
    target=OUT/(stem+'-'+family+'-comparison.json.gz');assert not target.exists();target.write_bytes(payload)
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    data=stream.getvalue().encode();assert len(data)<=32768
    target=OUT/(stem+'-'+family+'-comparison.csv');assert not target.exists();target.write_bytes(data)
    print(json.dumps(aggregates,indent=2))

if __name__=='__main__':main(*sys.argv[1:])
