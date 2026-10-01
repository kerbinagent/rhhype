"""Audited batch tables; source/control space belongs to the frozen batch budget."""
import csv,datetime,gzip,hashlib,io,json
from decimal import Decimal as D
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/single-venue-research'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def decoded(p):return json.loads(gzip.decompress(p.read_bytes()))

def main():
    batch=ROOT/'reports/single-venue-depth-batch'
    terminal=json.loads((batch/'terminal.json').read_bytes())
    assert terminal['state']=='finished' and terminal['all_windows_normal']
    evidence=[];rows=[]
    for kind,windows in (('depth',(1,2,3)),('clock_control',(2,3))):
        plan=ROOT/'reports/experiment-storage'/('single-venue-depth-batch-v1.json' if kind=='depth' else 'single-venue-clock-control-v1.json')
        protocol=json.loads(plan.read_bytes())
        for index in windows:
            capture=batch/f'window-{index}'/'capture'
            manifest=json.loads((capture/'manifest.json').read_bytes())
            assert manifest['end_reason']=='duration_limit' and not manifest['truncated']
            assert sha(capture/'frames.jsonl.gz')==manifest['frames_sha256']
            assert datetime.datetime.fromisoformat(protocol['recorded_utc'])<datetime.datetime.fromisoformat(manifest['started_utc'])
            name=f'single-venue-depth-batch-{index}-lit' if kind=='depth' else f'single-venue-clock-control-{index}-lit'
            directory=OUT/name;summary=decoded(directory/'summary.json.gz')
            audit=json.loads((directory/'independent-audit.json').read_bytes())
            assert audit['status']=='passed' and audit['sample']==name
            assert audit['summary_sha256']==sha(directory/'summary.json.gz')
            assert audit['trace_sha256']==sha(directory/'trace.jsonl.gz')==summary['trace_sha256']
            assert not summary['error'] and summary['complete_capture_verified']
            assert summary['manifest_sha256']==sha(capture/'manifest.json') and summary['plan_sha256']==sha(plan)
            evidence.append(dict(kind=kind,window=index,sample=name,started_utc=manifest['started_utc'],ended_utc=manifest['ended_utc'],
                manifest_sha256=sha(capture/'manifest.json'),summary_sha256=audit['summary_sha256'],audit_sha256=sha(directory/'independent-audit.json')))
            for arm,r in summary['arms'].items():
                rule,venue=arm.split(':');net=sum((D(e['cash_after_capital']) for e in r['episodes']),D(0))
                stressed=sum((D(e['stressed_net']) for e in r['episodes']),D(0))
                change=D(r['cash'])-600
                if r['complete']:assert not r['unknown'] and not r['position'] and not r['pending'] and abs(change-net)<D('1e-20')
                rows.append(dict(kind=kind,window=index,rule=rule,venue=venue,collateral='USDC' if venue=='lighter' else 'USDG',
                    attempts=r['attempts'],closed=r['closed'],zero_fill_entries=r['counts'].get('entry_no_fill',0),
                    winning_closes=sum(D(e['cash_after_capital'])>0 for e in r['episodes']),
                    long_closes=sum(e['side']==1 for e in r['episodes']),short_closes=sum(e['side']==-1 for e in r['episodes']),
                    closed_entry_notional=str(sum((D(e['entry_value']) for e in r['episodes']),D(0))),
                    closed_cash_after_capital=str(net),closed_stressed_cash=str(stressed),realized_cash_change=str(change),
                    complete=r['complete'],unknown=r['unknown'],position_open=r['position'] is not None,pending_order=r['pending'] is not None))
    aggregates=[]
    for group,kind,windows in (('depth_all_windows','depth',(1,2,3)),('depth_control_windows','depth',(2,3)),('clock_control_windows','clock_control',(2,3))):
        selected=[r for r in rows if r['kind']==kind and r['window'] in windows]
        for rule,venue in sorted({(r['rule'],r['venue']) for r in selected}):
            members=[r for r in selected if r['rule']==rule and r['venue']==venue]
            total=dict(group=group,rule=rule,venue=venue,windows=list(windows),all_flat_known=all(r['complete'] for r in members))
            for key in ('attempts','closed','zero_fill_entries','winning_closes','long_closes','short_closes'):
                total[key]=sum(r[key] for r in members)
            for key in ('closed_entry_notional','closed_cash_after_capital','closed_stressed_cash','realized_cash_change'):
                total[key]=str(sum((D(r[key]) for r in members),D(0)))
            aggregates.append(total)
    result=dict(schema='single-venue-depth-batch-comparison-v1',recorded_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        source_sha256=sha(Path(__file__)),evidence=evidence,rows=rows,aggregates=aggregates,
        limits='Conditional public-book paper executions; no private fills. Every rule/venue/window is an independent ledger. Aggregates only combine the same rule/venue across stated windows; no pooled venue/direction profit or independent win-rate claim. Clock controls apply to windows2/3 only, with different times and fills; no automatic subtraction or causal claim. Any unresolved position means closed cash is not total outcome.')
    blob=(json.dumps(result,indent=2)+'\n').encode();assert len(blob)<=32768
    target=OUT/'depth-batch-comparison.json';assert not target.exists();target.write_bytes(blob)
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    data=stream.getvalue().encode();assert len(data)<=8192
    target=OUT/'depth-batch-comparison.csv';assert not target.exists();target.write_bytes(data)
    print(json.dumps(aggregates,indent=2))

if __name__=='__main__':main()
