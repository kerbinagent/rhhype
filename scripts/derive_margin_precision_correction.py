"""Explicit API precision correction; original eight parameter errors retained."""
import datetime as dt
import gzip
import hashlib
import json
import time
import urllib.error
import urllib.request
from decimal import Decimal as D, ROUND_DOWN
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'reports/experiment-storage/derive-margin-precision-allocation-v1.json'
OUT=ROOT/'reports/derive-margin-precision-correction'


def main():
    pb=PLAN.read_bytes();p=json.loads(pb)
    for pin in p['input_pins']:
        assert hashlib.sha256((ROOT/pin['path']).read_bytes()).hexdigest()==pin['sha256']
    OUT.mkdir(exist_ok=True);assert not any(OUT.iterdir())
    with (OUT/'claim.json').open('x') as f:
        json.dump({'plan_sha256':hashlib.sha256(pb).hexdigest(),'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   'started_utc':dt.datetime.now(dt.timezone.utc).isoformat()},f)
    rows=[];size=0
    original=json.loads((ROOT/p['original_terminal']).read_bytes())
    source=[x for x in original['provenance'] if x['name'].startswith(('SM_','PM2_'))]
    assert len(source)==8
    for item in source:
        if rows:time.sleep(.5)
        body=item['body']
        for x in body['simulated_collaterals']:
            places=6 if x['asset_name']=='USDC' else 12
            x['amount']=format(D(x['amount']).quantize(D(1).scaleb(-places),rounding=ROUND_DOWN),'f')
        for x in body['simulated_position_changes']:x['amount']=format(D(x['amount']),'f')
        row={'name':item['name'],'body':body,'status':'failed_no_retry'}
        try:
            req=urllib.request.Request(item['url'],data=json.dumps(body).encode(),
                                       headers={'Content-Type':'application/json','User-Agent':'rhhype-public-research/1.0'})
            try:r=urllib.request.urlopen(req,timeout=15)
            except urllib.error.HTTPError as e:r=e
            with r:raw=r.read(65537);code=r.status
            assert len(raw)<=65536
            z=gzip.compress(raw,mtime=0);assert size+len(z)<=8192
            with (OUT/(item['name']+'.gz')).open('xb') as f:f.write(z)
            size+=len(z);obj=json.loads(raw)
            row.update(http_status=code,raw_sha256=hashlib.sha256(raw).hexdigest(),received_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                       result=obj.get('result'),error=obj.get('error'),status='simulation_returned' if 'result' in obj else 'api_error')
        except Exception as e:row['exception']=str(e)[:200]
        rows.append(row)
    result={'rows':rows,'expected_scenarios':8,'valid_response_scenarios':sum(x['status']=='simulation_returned' for x in rows),
            'actual_pnl':None,'present_margin_only':True}
    b=(json.dumps(result,indent=2)+'\n').encode();assert len(b)<=12000
    with (OUT/'summary.json').open('xb') as f:f.write(b)
    tb=(json.dumps({'status':'completed_fixed_correction','requests':8,'summary_sha256':hashlib.sha256(b).hexdigest()})+'\n').encode()
    assert len(pb)+len(tb)+(OUT/'claim.json').stat().st_size<=8192
    with (OUT/'terminal.json').open('xb') as f:f.write(tb)
    print(json.dumps(result))


if __name__=='__main__':main()
