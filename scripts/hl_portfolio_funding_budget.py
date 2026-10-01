"""Existing HYPE/BTC funding archive under an optimistic portfolio-capital model."""
import hashlib,json
from decimal import Decimal as D
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'reports/experiment-storage/hl-portfolio-funding-budget-allocation-v1.json'
OUT=ROOT/'reports/hl-portfolio-funding-budget'

def main():
    p=PLAN.read_bytes();plan=json.loads(p)
    for pin in plan['input_pins']:
        assert hashlib.sha256((ROOT/pin['path']).read_bytes()).hexdigest()==pin['sha256']
    results=[]
    for asset in ['HYPE','BTC']:
        rows=[]
        for part in ['00','01']:
            rows+=json.loads((ROOT/f'data/raw/hyperliquid/20260929T034903Z/history/{asset}/funding_{part}.json').read_bytes())
        assert all(r['coin']==asset and 0<=r['time']%3600000<=1000 and D(r['fundingRate']).is_finite()for r in rows)
        pairs=[(r['time']//3600000*3600000,D(r['fundingRate']))for r in rows]
        assert [t for t,_ in pairs]==list(range(1787976000000,1790650800001,3600000))
        for i,j in plan['blocks']:
            lo=1788220800000+i*86400000;hi=1788220800000+j*86400000
            rates=[v for t,v in pairs if lo<t<hi]
            assert len(rates)==(j-i)*24-1
            funding=sum(rates,D(0))*10000;capital=D('.05')*10000*(j-i)/365
            result={'asset':asset,'start_day':i+1,'end_day':j,'events':len(rates),
                    'funding_bps':str(funding),'capital_bps':str(capital),'trading_fee_bps':'23','stress_bps':'5',
                    'residual_before_borrow_basis_spread_bps':str(funding-capital-28),
                    'negative_hours':sum(v<0 for v in rates)}
            results.append(result)
    out={'actual_pnl':None,'cashflow_not_computed':True,'development_not_validation':True,
         'account_eligibility_and_margin_feasibility_unknown':True,'borrow_cost_optimistically_zero':True,
         'capital_one_times_spot_principal':True,'full_period_overlaps_weeks':True,'results':results}
    b=(json.dumps(out,indent=2)+'\n').encode();assert len(b)<=16384
    OUT.mkdir(exist_ok=True);assert not any(OUT.iterdir())
    with(OUT/'summary.json').open('xb')as f:f.write(b)
    with(OUT/'terminal.json').open('x')as f:json.dump({'status':'completed_offline','requests':0,'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'plan_sha256':hashlib.sha256(p).hexdigest(),'summary_sha256':hashlib.sha256(b).hexdigest()},f)
    for r in results:print(r['asset'],r['start_day'],r['end_day'],r['funding_bps'],r['residual_before_borrow_basis_spread_bps'])

if __name__=='__main__':main()
