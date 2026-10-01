"""Three fixed LIT windows comparing executable-quote fade filters."""
import datetime,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts import single_venue_depth as study
from scripts import single_venue_depth_events as events
from scripts.single_venue_executable_strategy import ExecutableStudy
from scripts.single_venue_strategy import PARAMS
EXECUTION_PARAMS=dict(PARAMS,admission_start_seconds=3,admission_stop_seconds=570)
PLAN=ROOT/'reports/experiment-storage/single-venue-executable-shock-v1.json'
OUT=ROOT/'reports/single-venue-executable-shock'
SELECTED={'rh_lighter':{'LIT':'5'},'lighter':{'LIT':'120'}}
WINDOWS=(1,2,3)
RAW_BYTES=8388608
HARD_BYTES=RAW_BYTES+131072

def configure(index):
    assert index in WINDOWS
    study.Study=ExecutableStudy;study.PARAMS=EXECUTION_PARAMS
    study.PLAN=PLAN;study.ASSETS=('LIT',);study.NAMES={'LIT':f'single-venue-executable-shock-{index}-lit'}
    study.capture.PLAN=PLAN;study.capture.OUT=OUT/f'window-{index}'/'capture'
    study.capture.SELECTED=SELECTED;study.capture.HARD_BYTES=HARD_BYTES
    events.HARD_BYTES=HARD_BYTES

def verify(index):
    configure(index);p=study.verify()
    assert p['selected']==SELECTED and p['duration_seconds']==600 and p['windows']==list(WINDOWS)
    assert p['capture_hard_bytes']==HARD_BYTES and p['categories_bytes']['raw']==RAW_BYTES
    return p

def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def write(path,value):path.write_text(json.dumps(value,indent=2)+'\n')

def supervise():
    verify(1);results=[]
    state=dict(started_utc=utc(),planned_windows=list(WINDOWS),state='collecting',
        economic_evaluation=False,plan_sha256=study.sha(PLAN))
    for index in WINDOWS:
        state.update(current_window=index,completed_windows=len(results));write(OUT/'status.json',state)
        command=[sys.executable,str(Path(__file__).resolve()),'capture',str(index)]
        try:
            run=subprocess.run(command,cwd=ROOT,stdin=subprocess.DEVNULL,timeout=720,check=False)
            terminal_path=OUT/f'window-{index}'/'capture'/'terminal.json'
            terminal=json.loads(terminal_path.read_bytes()) if terminal_path.exists() else None
            normal=bool(run.returncode==0 and terminal and terminal.get('end_reason')=='duration_limit')
            result=dict(window=index,returncode=run.returncode,normal_endpoint=normal,terminal=terminal)
        except subprocess.TimeoutExpired:
            result=dict(window=index,normal_endpoint=False,error='720second_process_timeout_no_retry')
        results.append(result)
        if not result['normal_endpoint']:break
    state.update(state='finished',ended_utc=utc(),results=results,
        attempted_windows=len(results),completed_windows=sum(r['normal_endpoint'] for r in results),
        all_windows_normal=len(results)==3 and all(r['normal_endpoint'] for r in results))
    write(OUT/'terminal.json',state);write(OUT/'status.json',state)

def launch():
    verify(1);OUT.mkdir(exist_ok=False)
    command=[sys.executable,str(Path(__file__).resolve()),'supervise']
    with (OUT/'stdout.txt').open('xb') as log:
        child=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
            start_new_session=True,close_fds=True)
    record=dict(pid=child.pid,command=command,launched_utc=utc(),fixed_windows=3,
        seconds_per_window=600,per_process_timeout_seconds=720,public_read_only=True,plan_sha256=study.sha(PLAN))
    write(OUT/'process.json',record);print(json.dumps(record))

def main(action,*args):
    if action=='launch':launch()
    elif action=='supervise':supervise()
    else:
        index=int(args[0]);verify(index)
        if action=='capture':study.main('capture')
        else:
            terminal=json.loads((OUT/'terminal.json').read_bytes())
            assert terminal['state']=='finished'
            assert any(r['window']==index and r['normal_endpoint'] for r in terminal['results'])
            if action=='replay':study.main('replay',args[1])
            elif action=='audit':
                from scripts.audit_single_venue_executable import run_audit
                run_audit(index,args[1])
            else:raise ValueError(action)

if __name__=='__main__':main(*sys.argv[1:])
