"""Reference-midpoint accounting identity for all earlier matched closes."""
import gzip,json,hashlib,sys
from decimal import Decimal as D
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
PLAN=ROOT/'reports/experiment-storage/single-venue-reference-accounting-v1.json'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    plan=json.loads(PLAN.read_bytes())
    for pin in plan['pins']:assert sha(ROOT/pin['path'])==pin['sha256'],pin['path']
    contexts=json.loads(gzip.decompress((ROOT/plan['contexts']).read_bytes()))
    rows=[]
    for sample in contexts['samples']:
        for row in sample['rows']:
            asset,arm=row['asset'],row['arm']
            name='single-venue-depth-'+asset.lower() if sample['sample']=='original' else 'single-venue-depth-incomplete-prefix-lit'
            summary=json.loads(gzip.decompress((ROOT/'reports/single-venue-research'/name/'summary.json.gz').read_bytes()))
            matches=[e for e in summary['arms'][arm]['episodes'] if e['entry_ns']==row['entry_ns'] and e['exit_ns']==row['exit_ns']]
            assert len(matches)==1;ep=matches[0]
            result=dict(sample=sample['sample'],asset=asset,arm=arm,entry_ns=row['entry_ns'],
                exit_ns=row['exit_ns'],status=row['status'],net=ep['cash_after_capital'])
            if row['status']!='matched':rows.append(result);continue
            if ep['exit_attempts']!=1:
                result['status']='multiple_exit_callbacks_no_simple_decomposition';rows.append(result);continue
            other='rh_lighter' if arm.endswith(':lighter') else 'lighter'
            half_tick=D(summary['end']['metadata']['markets'][other][asset]['price_tick'])/2
            def exact_mid(key):
                observed=D(str(row[key]['mids'][other]));value=observed.quantize(half_tick)
                assert value%half_tick==0 and abs(value-observed)<D('1e-8')
                return value
            en,ex=exact_mid('entry_pair'),exact_mid('exit_pair')
            reference=D(ep['side'])*D(ep['quantity'])*(ex-en)
            residual=D(ep['gross'])-reference
            charges=D(ep['entry_fee'])+D(ep['exit_fee'])+D(ep['capital'])
            assert reference+residual-charges==D(ep['cash_after_capital'])
            assert reference+residual-charges-D(ep['stress'])==D(ep['stressed_net'])
            result.update(reference_entry_mid=str(en),reference_exit_mid=str(ex),
                reference_midpoint_counterfactual_gross=str(reference),actual_gross=str(ep['gross']),
                execution_relative_residual=str(residual),fees_and_capital=str(charges),stress_net=ep['stressed_net'])
            rows.append(result)
    assert len(rows)==18
    result=dict(plan_sha256=sha(PLAN),scope=plan['scope'],rows=rows)
    blob=gzip.compress((json.dumps(result,separators=(',',':'))+'\n').encode(),mtime=0);assert len(blob)<=4096
    out=ROOT/'reports/single-venue-research/depth-reference-accounting.json.gz';assert not out.exists();out.write_bytes(blob)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
