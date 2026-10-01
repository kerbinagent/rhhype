"""Bounded offline evaluation after the separately frozen news capture terminates."""
import datetime,hashlib,json,subprocess,sys,time,gzip
from pathlib import Path
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts import single_venue_news as news
PLAN=ROOT/'reports/experiment-storage/single-venue-news-analysis-v1.json'
OUT=news.OUT
CAPTURE_PLAN_SHA='e9efab93a06e4e53fdb76b2f4b0e955f25f37a749c810062736a66f04ec90ffe'
TERMINAL_DEADLINE=news.EVENT+10*60
MAX_WAIT_SECONDS=14*3600
ANALYSIS_SECONDS=3600
def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(path,value):
    b=(json.dumps(value,indent=2)+'\n').encode();assert len(b)<=8192;path.write_bytes(b)
def verify():
    p=json.loads(PLAN.read_bytes());assert sha(news.PLAN)==CAPTURE_PLAN_SHA
    for pin in p['pins']:assert sha(ROOT/pin['path'])==pin['sha256']
    news.verify('relative');return p
def await_terminal(heartbeat,wall=time.time,mono=time.monotonic,sleep=time.sleep):
    deadline=mono()+MAX_WAIT_SECONDS;path=OUT/'terminal.json'
    while not path.exists():
        if wall()>TERMINAL_DEADLINE or mono()>=deadline:raise TimeoutError('capture_terminal_missing_no_retry')
        heartbeat();sleep(30)
    t=json.loads(path.read_bytes())
    assert t['state']=='finished' and t['normal_endpoint'] and t['event_coverage_valid'],'capture_incomplete_no_evaluation'
    assert t['plan_sha256']==CAPTURE_PLAN_SHA
    return t
def pin_capture(terminal):
    cap=OUT/'capture';manifest=json.loads((cap/'manifest.json').read_bytes())
    assert manifest['end_reason']=='duration_limit' and not manifest['truncated'] and news.coverage(manifest)
    digest=sha(cap/'manifest.json');raw=sha(cap/'frames.jsonl.gz')
    assert digest==terminal['terminal']['manifest_sha256'] and raw==manifest['frames_sha256']
    assert manifest['market_plan_sha256']==CAPTURE_PLAN_SHA
    path=OUT/'external-verification.json';assert not path.exists()
    write(path,dict(verified_utc=utc(),manifest_sha256=digest,raw_sha256=raw,raw_bytes=(cap/'frames.jsonl.gz').stat().st_size,
        terminal_sha256=sha(OUT/'terminal.json'),analysis_plan_sha256=sha(PLAN)))
    return digest
def commands(digest):
    for family in ('relative','depth'):
        yield ['scripts/single_venue_news.py','replay',family,digest]
        for asset in news.ASSETS:yield ['scripts/single_venue_news.py','audit',family,asset,digest]
        yield ['scripts/single_venue_news_readout.py',family]
def command(args,deadline,mono=time.monotonic):
    remaining=deadline-mono()
    if remaining<=0:raise TimeoutError('analysis_deadline_no_retry')
    run=subprocess.run(['nice','-n','19',sys.executable,*args],cwd=ROOT,stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=min(600,remaining),check=False)
    if run.returncode:raise RuntimeError('command_failed_no_retry '+repr(args)+' '+run.stderr[:1500].decode(errors='replace'))
def make_readout():
    rows=[]
    for family in ('relative','depth'):
        p=ROOT/'reports/single-venue-research'/('single-venue-news-'+family+'-comparison.json.gz')
        report=json.loads(gzip.decompress(p.read_bytes()))
        assert len(report['rows'])==(60 if family=='relative' else 40)
        rows.extend(dict(family=family,**r) for r in report['rows'])
    lines=['NEWS WINDOW: AUTOMATED PAPER READOUT',
        'All100asset/venue/rule rows are retained in the separate relative/depth comparison files. All20matching independent audits passed before these tables were generated.',
        'Conditional public-book IOC model; no private order acknowledgments or authenticated fills. Independent ledgers must not be summed. USDG/USDC collateral remains separate. A positive exploratory outcome is not a validated tradable edge.',
        'Each row below is an arm with an entry attempt or unresolved obligation. Cash is in that venue native collateral, after modeled fees/capital. Stress deducts5bpofentrynotional. Zero-entry arms provide no profitability evidence.']
    lines.append('Total arms='+str(len(rows))+';flat_known='+str(sum(r['complete'] for r in rows))+';arms_with_attempts='+str(sum(r['attempts']>0 for r in rows)))
    for r in rows:
        if r['attempts'] or not r['complete']:
            net=Decimal(r['closed_cash_after_capital']);stress=Decimal(r['closed_stressed_cash'])
            lines.append(f"{r['asset']}/{r['venue']}/{r['rule']}:attempts={r['attempts']},closed={r['closed']},cash={net:.6g},stress={stress:.6g},complete={r['complete']},unknown={bool(r['unknown'])}")
    text='\n'.join(lines)+'\n';assert len(text.encode())<=16384
    p=ROOT/'reports/single-venue-research/single-venue-news-readout.txt';assert not p.exists();p.write_text(text)
def supervise():
    verify();state=dict(state='waiting_for_capture_terminal',started_utc=utc(),plan_sha256=sha(PLAN),economic_evaluation=False)
    def heartbeat():state.update(heartbeat_utc=utc());write(OUT/'analysis-status.json',state)
    heartbeat()
    try:
        terminal=await_terminal(heartbeat);verify();digest=pin_capture(terminal)
        deadline=time.monotonic()+ANALYSIS_SECONDS
        state.update(state='evaluating_completed_capture',economic_evaluation=True,manifest_sha256=digest,completed_commands=0)
        for args in commands(digest):
            state.update(command=args);heartbeat();command(args,deadline)
            state['completed_commands']+=1;heartbeat()
        make_readout();state.update(state='finished',success=True)
    except Exception as exc:
        state.update(state='finished',success=False,error=type(exc).__name__+': '+str(exc)[:2500])
    state.update(ended_utc=utc());write(OUT/'analysis-terminal.json',state);write(OUT/'analysis-status.json',state)
def launch():
    verify();assert OUT.exists() and not (OUT/'analysis-process.json').exists()
    assert time.time()<TERMINAL_DEADLINE
    args=[sys.executable,str(Path(__file__).resolve()),'supervise']
    with (OUT/'analysis-stdout.txt').open('xb') as log:
        child=subprocess.Popen(args,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
    record=dict(pid=child.pid,command=args,launched_utc=utc(),plan_sha256=sha(PLAN),public_data_only=True,offline_after_capture=True,
        terminal_deadline_epoch=TERMINAL_DEADLINE,max_wait_seconds=MAX_WAIT_SECONDS,max_analysis_seconds=ANALYSIS_SECONDS,no_retry=True)
    write(OUT/'analysis-process.json',record);print(json.dumps(record))
if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('launch','supervise')
    globals()[sys.argv[1]]()
