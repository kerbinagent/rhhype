"""Observed execution groups, never private owner identity or latent metaorders."""
import gzip,hashlib,json
from collections import Counter
from decimal import Decimal as D
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TIMING=ROOT/'reports/single-venue-research/depth-batch-timing.json'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def identity(row,trade):
    if not isinstance(trade.get('is_maker_ask'),bool):return None
    side='bid' if trade['is_maker_ask'] else 'ask'
    ident=trade.get(side+'_id_str',trade.get(side+'_id'))
    version=trade.get(side+'_order_version');tx=trade.get('tx_hash')
    if ident is None or version is None or not tx:return None
    return (row['venue'],str(trade['market_id']),row['generation'],str(tx),side,str(ident),str(version))

def collect(records,shocks):
    groups={};seen=set();trade_groups={};counts=Counter()
    for row in records:
        payload=row.get('payload') or {}
        if row.get('kind')!='frame' or payload.get('type')!='update/trade':continue
        counts[row['venue']+':update_batches']+=1
        for trade in payload.get('trades',[]):
            if trade.get('type')!='trade':continue
            tid=str(trade.get('trade_id_str',trade.get('trade_id')))
            unique=(row['venue'],str(trade['market_id']),row['generation'],tid)
            if unique in seen:counts[row['venue']+':duplicate_prints']+=1;continue
            seen.add(unique);counts[row['venue']+':unique_prints']+=1
            key=identity(row,trade)
            if key is None:counts[row['venue']+':missing_group_identity']+=1;continue
            group=groups.setdefault(key,dict(venue=row['venue'],prints=0,prices=set(),qty=D(0),
                first_receipt=row['receipt_utc_ns'],last_receipt=row['receipt_utc_ns'],shocks=0))
            group['prints']+=1;group['prices'].add(D(trade['price']));group['qty']+=D(trade['size'])
            group['last_receipt']=max(group['last_receipt'],row['receipt_utc_ns'])
            short=(row['venue'],tid)
            if short in trade_groups:assert trade_groups[short]==key,'ambiguous shock trade identity'
            trade_groups[short]=key
    for shock in shocks:
        key=trade_groups.get((shock['venue'],str(shock['trade_id'])))
        if key is None:counts[shock['venue']+':unmatched_shock_prints']+=1
        else:groups[key]['shocks']+=1
    report={}
    for venue in ('lighter','rh_lighter'):
        gs=[g for g in groups.values() if g['venue']==venue];hit=[g for g in gs if g['shocks']]
        report[venue]=dict(counts={k.split(':',1)[1]:v for k,v in counts.items() if k.startswith(venue+':')},
            observed_groups=len(gs),multi_print_groups=sum(g['prints']>1 for g in gs),
            multi_price_groups=sum(len(g['prices'])>1 for g in gs),
            max_prints_per_group=max((g['prints'] for g in gs),default=0),
            groups_spanning_receipt_frames=sum(g['first_receipt']!=g['last_receipt'] for g in gs),
            detected_shock_prints=sum(g['shocks'] for g in hit),detected_shock_groups=len(hit),
            shock_groups_at_multiple_prices=sum(len(g['prices'])>1 for g in hit),
            max_shock_prints_per_group=max((g['shocks'] for g in hit),default=0),
            shock_group_details=[dict(prints=g['prints'],detector_shock_prints=g['shocks'],
                distinct_execution_prices=len(g['prices']),total_observed_quantity=str(g['qty']),
                receipt_span_ms=(g['last_receipt']-g['first_receipt'])/1e6) for g in hit])
    return report

def main():
    timing=json.loads(TIMING.read_bytes());windows=[]
    for window in timing['windows']:
        index=window['window'];source=ROOT/f'reports/single-venue-depth-batch/window-{index}/capture'
        mp=source/'manifest.json';rp=source/'frames.jsonl.gz';manifest=json.loads(mp.read_bytes())
        assert sha(mp)==window['manifest_sha256'] and sha(rp)==manifest['frames_sha256']
        assert manifest['end_reason']=='duration_limit' and not manifest['truncated']
        def records():
            decoded=count=0
            with gzip.open(rp,'rb') as handle:
                while True:
                    line=handle.readline(8*1024*1024+1)
                    if not line:break
                    assert len(line)<=8*1024*1024 and line.endswith(b'\n')
                    decoded+=len(line);count+=1
                    assert decoded<=128*1024*1024 and count<=100000
                    yield json.loads(line)
            assert count==manifest['payload_records']
        result=collect(records(),window['shocks'])
        assert sha(mp)==window['manifest_sha256'] and sha(rp)==manifest['frames_sha256']
        windows.append(dict(window=index,manifest_sha256=sha(mp),raw_sha256=sha(rp),venues=result))
    report=dict(schema='single-venue-public-trade-grouping-v1',retrospective=True,source_sha256=sha(Path(__file__)),
        timing_sha256=sha(TIMING),windows=windows,
        method='Deduplicate ordinary update/trade prints by venue,market,generation,tradeID; exclude subscribed backlog. Group only matching venue,market,generation,transaction hash,aggressor orderID and order version. is_maker_ask implies buyer is aggressor; otherwise seller. No account identifiers used or output.',
        limits='Observed public execution groups are not latent parent metaorders, whole-order completion, or proof of independent shocks. More than one execution price is observed multi-price execution, not exact reconstruction of unobserved pre-order depth or residual. This raw-schema diagnostic does not certify adapter-valid tradable events or change prior strategy/cash results; no new PnL test or active capture inspection.')
    blob=(json.dumps(report,indent=2)+'\n').encode();assert len(blob)<=16384
    target=ROOT/'reports/single-venue-research/public-trade-groups.json';assert not target.exists();target.write_bytes(blob)
    print(json.dumps({w['window']:{v:{k:r[k] for k in ('observed_groups','multi_price_groups','detected_shock_prints','detected_shock_groups','shock_groups_at_multiple_prices')} for v,r in w['venues'].items()} for w in windows},indent=2))

if __name__=='__main__':main()
