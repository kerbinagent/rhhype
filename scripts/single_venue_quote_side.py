"""Admitted shock anatomy: native bid/ask movement and reference quote edge."""
import gzip,json,hashlib
from pathlib import Path
from decimal import Decimal as D
ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'reports/experiment-storage/single-venue-quote-side-v1.json'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    plan=json.loads(PLAN.read_bytes())
    for pin in plan['pins']:assert sha(ROOT/pin['path'])==pin['sha256']
    groups={};signal_count=0
    for sample in plan['samples']:
        directory=ROOT/'reports/single-venue-research'/sample
        summary=json.loads(gzip.decompress((directory/'summary.json.gz').read_bytes()))
        asset=summary['asset'];markets=summary['end']['metadata']['markets']
        for row in map(json.loads,gzip.decompress((directory/'trace.jsonl.gz').read_bytes()).splitlines()):
            if row['kind']!='signal':continue
            signal_count+=1;s=row['signal'];venue=s['venue'];other='rh_lighter' if venue=='lighter' else 'lighter'
            key=(sample,asset,venue,s['print']['trade_id'],s['t'])
            if key in groups:
                assert groups[key]['signal']=={k:v for k,v in s.items() if k not in ('rule','direction')}
                groups[key]['admitted_rules'].append(s['rule']);continue
            tick=D(markets[venue][asset]['price_tick']);half_other=D(markets[other][asset]['price_tick'])/2
            def quotes(point):
                m=D(str(point['mids'][venue]));spread=D(str(point['spreads'][venue]))
                bid0=m*(1-spread/20000);ask0=m*(1+spread/20000)
                bid,ask=bid0.quantize(tick),ask0.quantize(tick)
                assert max(abs(bid-bid0),abs(ask-ask0))<D('1e-8') and bid<ask
                return bid,ask
            prebid,preask=quotes(s['pre']);bid,ask=quotes(s['decision'])
            ref=D(str(s['decision']['mids'][other])).quantize(half_other)
            assert ref%half_other==0 and abs(ref-D(str(s['decision']['mids'][other])))<D('1e-8')
            sign=1 if s['print']['buy_aggressor'] else -1;fade=-sign
            entry=ask if fade==1 else bid
            # This top-quote edge excludes depth,400ms latency and every exit cost.
            edge=D(fade)*(ref-entry)/entry*10000
            bid_move,ask_move=D(sign)*(bid-prebid),D(sign)*(ask-preask)
            total=bid_move+ask_move;assert total>0
            executable_move=ask_move if fade==1 else bid_move
            groups[key]=dict(signal={k:v for k,v in s.items() if k not in ('rule','direction')},
                sample=sample,asset=asset,venue=venue,trade_id=s['print']['trade_id'],signal_ns=s['t'],
                admitted_rules=[s['rule']],buy_aggressor=sign==1,pre_bid=str(prebid),pre_ask=str(preask),
                decision_bid=str(bid),decision_ask=str(ask),decision_reference_mid=str(ref),
                aligned_bid_change=str(bid_move),aligned_ask_change=str(ask_move),
                executable_side_share_of_sum=str(executable_move/total),
                fade_top_quote_reference_edge_bps=str(edge))
    rows=[{k:v for k,v in row.items() if k!='signal'} for row in groups.values()]
    result=dict(plan_sha256=sha(PLAN),scope=plan['scope'],admitted_signal_rows=signal_count,
        unique_admitted_opportunities=len(rows),rows=rows)
    blob=gzip.compress((json.dumps(result,separators=(',',':'))+'\n').encode(),mtime=0);assert len(blob)<=4096
    out=ROOT/'reports/single-venue-research/depth-quote-side.json.gz';assert not out.exists();out.write_bytes(blob)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
