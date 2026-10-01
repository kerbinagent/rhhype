"""Three fixed public top-book observations of one preselected ETH box."""
import datetime as dt
import gzip
import hashlib
import json
import time
import urllib.error
import urllib.request
from decimal import Decimal as D, ROUND_DOWN
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT/'reports/experiment-storage/derive-box-quote-allocation-v1.json'
OUT = ROOT/'reports/derive-box-quote-screen'


def evaluate(obj, received, request_seconds, p):
    ticks = obj['result']['tickers']
    legs, times = [], []
    for name, side in p['legs']:
        r = ticks[name]
        vals = {k: D(str(r[k])) for k in ('a', 'b', 'A', 'B', 'I', 'M', 'minp', 'maxp')}
        assert all(x.is_finite() for x in vals.values())
        assert 0 < vals['b'] <= vals['a'] and vals['A'] > 0 and vals['B'] > 0
        assert vals['I'] > 0 and vals['M'] > 0
        price, available = (vals['a'], vals['A']) if side == 'buy' else (vals['b'], vals['B'])
        assert vals['minp'] <= price <= vals['maxp'], 'aggressive price outside venue bounds'
        assert D(p['spot_metadata'])/2 < vals['I'] < D(p['spot_metadata'])*2, 'unverified index scale'
        t = int(r['t'])/1000
        assert -.25 <= received-t <= 5, 'snapshot freshness'
        times.append(t)
        # Conservative cap sensitivity: use larger of trade premium and mark.
        fee = min(D('.0003')*vals['I'], D('.125')*max(price, vals['M']))
        legs.append({'instrument': name, 'side': side, 'price': str(price),
                     'available': str(available), 'index': str(vals['I']),
                     'mark': str(vals['M']), 'variable_fee_per_unit': str(fee), 'timestamp': t})
    assert max(times)-min(times) <= 1 and request_seconds <= 2, 'timing gate'
    debit = sum((D(x['price'])*(1 if x['side']=='buy' else -1) for x in legs), D(0))
    fees = sum((D(x['variable_fee_per_unit']) for x in legs), D(0))
    width = D(p['strike_high'])-D(p['strike_low'])
    denominator = debit+fees+D('.1')*width
    assert debit > 0 and denominator > 0, 'unexpected credit box'
    years = (D(p['expiry'])-D(str(received)))/D(31536000)
    assert years > 0
    rows = []
    for budget in (100, 250, 500, 1000):
        cash = D(budget)
        q = ((cash-2)/denominator).quantize(D('.01'), rounding=ROUND_DOWN)
        status = 'valid_quote_scenario'
        if q < D('.1') or q > 10000:
            status = 'outside_quantity_limits'
        elif any(q > D(x['available']) for x in legs):
            status = 'insufficient_top_depth'
        face, entry, fee = q*width, q*debit, D(2)+q*fees
        reserve = cash-entry-fee
        assert reserve >= face*D('.1')
        capital, stress = cash*D('.05')*years, cash*D('.0005')
        rows.append({'cash_budget': budget, 'primary': budget == 1000, 'status': status,
                     'quantity': str(q), 'fixed_payoff_usdc': str(face), 'entry_debit_usdc': str(entry),
                     'four_order_fee_scenario_usdc': str(fee), 'remaining_cash_usdc': str(reserve),
                     'capital_usdc': str(capital), 'stress_usdc': str(stress),
                     'gross_payoff_minus_debit_usdc': str(face-entry),
                     'scenario_residual_usdc': str(face-entry-fee-capital-stress) if status=='valid_quote_scenario' else None,
                     'native_rfq_fee_scenario_usdc': str(D('.5')+face*D('.005')*years),
                     'maximum_native_rfq_debit_before_unmeasured_costs': str(face-D('.5')-face*D('.005')*years-capital-stress),
                     'actual_pnl': None})
    return {'legs': legs, 'unit_debit': str(debit), 'years': str(years), 'rows': rows}


def main():
    pb = PLAN.read_bytes(); p = json.loads(pb)
    for pin in p['input_pins']:
        assert hashlib.sha256((ROOT/pin['path']).read_bytes()).hexdigest() == pin['sha256']
    assert p['rounds'] == 3 and p['interval_seconds'] == 30 and p['retries'] == 0
    OUT.mkdir(exist_ok=True); assert not any(OUT.iterdir())
    wall, mono = time.time(), time.monotonic()
    claim = {'plan_sha256': hashlib.sha256(pb).hexdigest(),
             'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 't0': wall}
    with (OUT/'claim.json').open('x') as f:json.dump(claim,f)
    rounds, packed_total = [], 0
    for i in range(3):
        delay = mono+30*i-time.monotonic()
        if delay > 0:time.sleep(delay)
        record = {'round': i, 'planned_utc': wall+30*i, 'status': 'failed_no_retry'}
        try:
            assert abs((time.time()-wall)-(time.monotonic()-mono)) <= .5, 'clock discontinuity'
            assert time.monotonic()-(mono+30*i) <= 1, 'late callback'
            req = urllib.request.Request(p['url'], data=json.dumps(p['body']).encode(),
                                         headers={'Content-Type': 'application/json', 'User-Agent': 'rhhype-public-research/1.0'})
            begin = time.monotonic()
            try:r = urllib.request.urlopen(req, timeout=5)
            except urllib.error.HTTPError as e:r=e
            with r:raw=r.read(1048577);code=r.status
            received, elapsed = time.time(), time.monotonic()-begin
            assert len(raw) <= 1048576
            z = gzip.compress(raw, mtime=0);assert packed_total+len(z)<=65536
            with (OUT/f'round{i}.json.gz').open('xb') as f:f.write(z)
            packed_total += len(z)
            record.update(http_status=code,received=received,request_seconds=elapsed,
                          raw_sha256=hashlib.sha256(raw).hexdigest(),gzip_bytes=len(z))
            assert code==200, f'HTTP {code}'
            record['analysis']=evaluate(json.loads(raw),received,elapsed,p)
            record['status']='evaluated'
        except Exception as e:
            record['error']=str(e)[:200]
            record['missing_cash_budgets']=[100,250,500,1000]
        rounds.append(record)
    result={'rounds':rounds,'expected_size_rows':12,'actual_pnl':None,'rfq_price_observed':False,
            'unknown_costs':['settlement_if_any','bridge_and_transfer','account_specific_fees','margin_and_legged_execution'],
            'not_a_complete_cost_or_execution_test':True}
    b=(json.dumps(result,indent=2)+'\n').encode();assert len(b)<=24576
    with (OUT/'summary.json').open('xb') as f:f.write(b)
    terminal={'status':'completed_fixed_window','summary_sha256':hashlib.sha256(b).hexdigest(),
              'valid_rounds':sum(x['status']=='evaluated' for x in rounds)}
    tb=(json.dumps(terminal)+'\n').encode()
    assert len(pb)+(OUT/'claim.json').stat().st_size+len(tb)<=16384
    assert Path(__file__).stat().st_size<=16384
    with (OUT/'terminal.json').open('xb') as f:f.write(tb)
    print(json.dumps(result));print(json.dumps(terminal))


if __name__=='__main__':main()
