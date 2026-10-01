"""Fresh ten-crypto window using unchanged relative-gap, lead-lag and flow rules."""
import datetime,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts import single_venue_depth as study
from scripts import single_venue_depth_events as events
from scripts.single_venue_strategy import Study,PARAMS

PLAN=ROOT/'reports/experiment-storage/single-venue-broad-relative-v1.json'
OUT=ROOT/'reports/single-venue-broad-relative'
PREDECESSOR=ROOT/'reports/single-venue-broad/terminal.json'
ASSETS=('BTC','ETH','SOL','HYPE','XRP','SUI','NEAR','ZEC','VVV','LIT')
SELECTED={
 'rh_lighter':dict(zip(ASSETS,('1','0','3','2','6','9','7','4','8','5'))),
 'lighter':dict(zip(ASSETS,('1','0','2','24','7','16','10','90','69','120'))),
}
RAW_BYTES=67108864
HARD_BYTES=RAW_BYTES+262144
METADATA_BYTES=131072
DECODED_BYTES=1073741824
RECORDS=1000000
TRADE_IDS=500000

def broad_events(*args,**kwargs):
    return events.iter_events(*args,**kwargs,max_decoded_bytes=DECODED_BYTES,
        max_records=RECORDS,max_ids=TRADE_IDS)

def configure():
    study.Study=Study;study.PARAMS=PARAMS
    study.PLAN=PLAN;study.ASSETS=ASSETS
    study.NAMES={a:'single-venue-broad-relative-'+a.lower() for a in ASSETS}
    study.capture.PLAN=PLAN;study.capture.OUT=OUT/'capture'
    study.capture.SELECTED=SELECTED;study.capture.HARD_BYTES=HARD_BYTES
    study.capture.METADATA_MAX_BYTES=METADATA_BYTES
    events.HARD_BYTES=HARD_BYTES;events.METADATA_MAX_BYTES=METADATA_BYTES
    events.MAX_DECODED_BYTES=DECODED_BYTES;events.MAX_RECORDS=RECORDS;events.MAX_TRADE_IDS=TRADE_IDS
    study.iter_events=broad_events

def verify():
    configure();p=study.verify()
    assert p['selected']==SELECTED and p['assets']==list(ASSETS)
    assert p['duration_seconds']==600 and p['capture_hard_bytes']==HARD_BYTES
    assert p['categories_bytes']['raw']==RAW_BYTES
    assert p['adapter_bounds']==dict(decoded_bytes=DECODED_BYTES,records=RECORDS,trade_ids=TRADE_IDS)
    return p

def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def write(path,value):path.write_text(json.dumps(value,indent=2)+'\n')
def require_predecessor():
    assert json.loads(PREDECESSOR.read_bytes())['state']=='finished'

def supervise():
    verify();require_predecessor()
    state=dict(state='collecting',started_utc=utc(),economic_evaluation=False,plan_sha256=study.sha(PLAN))
    write(OUT/'status.json',state)
    try:
        run=subprocess.run([sys.executable,str(Path(__file__).resolve()),'capture'],
            cwd=ROOT,stdin=subprocess.DEVNULL,timeout=720,check=False)
        path=OUT/'capture/terminal.json'
        terminal=json.loads(path.read_bytes()) if path.exists() else None
        normal=bool(run.returncode==0 and terminal and terminal.get('end_reason')=='duration_limit')
        state.update(returncode=run.returncode,normal_endpoint=normal,terminal=terminal)
    except subprocess.TimeoutExpired:
        state.update(normal_endpoint=False,error='720second_process_timeout_no_retry')
    state.update(state='finished',ended_utc=utc())
    write(OUT/'terminal.json',state);write(OUT/'status.json',state)

def launch():
    verify();require_predecessor();OUT.mkdir(exist_ok=False)
    command=[sys.executable,str(Path(__file__).resolve()),'supervise']
    with (OUT/'stdout.txt').open('xb') as log:
        child=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,
            stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
    record=dict(pid=child.pid,command=command,launched_utc=utc(),seconds=600,
        per_process_timeout_seconds=720,public_read_only=True,plan_sha256=study.sha(PLAN))
    write(OUT/'process.json',record);print(json.dumps(record))

def audit(asset,digest):
    assert asset in ASSETS
    from scripts import audit_single_venue_study as cash
    from scripts import single_venue_compact_evidence as compact
    cash.PLAN=PLAN;cash.inputs=study.multi_inputs;cash.match_book=compact.match_compact
    cash.audit(study.NAMES[asset],digest)

def main(action,*args):
    verify()
    if action=='launch':launch()
    elif action=='supervise':supervise()
    elif action=='capture':require_predecessor();study.main('capture')
    else:
        terminal=json.loads((OUT/'terminal.json').read_bytes())
        assert terminal['state']=='finished' and terminal['normal_endpoint']
        if action=='replay':study.main('replay',*args)
        elif action=='audit':audit(*args)
        else:raise ValueError(action)

if __name__=='__main__':main(*sys.argv[1:])
