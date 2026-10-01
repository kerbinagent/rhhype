"""Follow-up schema diagnostic: same public taker order/version/source millisecond."""
import gzip,json
from pathlib import Path
from scripts import single_venue_trade_groups as base

def simultaneous(row,trade):
    strict=base_identity(row,trade)
    stamp=trade.get('timestamp')
    if strict is None or isinstance(stamp,bool) or not isinstance(stamp,int):return None
    return strict[:3]+(str(stamp),)+strict[4:]

base_identity=base.identity

def main():
    old=base.ROOT/'reports/single-venue-research/public-trade-groups.json'
    prior=json.loads(old.read_bytes());timing=json.loads(base.TIMING.read_bytes())
    assert prior['timing_sha256']==base.sha(base.TIMING)
    base.identity=simultaneous;windows=[]
    for w in timing['windows']:
        index=w['window'];source=base.ROOT/f'reports/single-venue-depth-batch/window-{index}/capture'
        mp=source/'manifest.json';rp=source/'frames.jsonl.gz';manifest=json.loads(mp.read_bytes())
        assert base.sha(mp)==w['manifest_sha256'] and base.sha(rp)==manifest['frames_sha256']
        assert rp.stat().st_size<=8388608
        with gzip.open(rp,'rb') as handle:
            raw=handle.read(128*1024*1024+1);assert len(raw)<=128*1024*1024
        lines=raw.splitlines();assert len(lines)==manifest['payload_records']<=100000
        result=base.collect((json.loads(line) for line in lines),w['shocks'])
        for r in result.values():r.pop('shock_group_details')
        assert base.sha(rp)==manifest['frames_sha256']
        windows.append(dict(window=index,manifest_sha256=base.sha(mp),raw_sha256=manifest['frames_sha256'],venues=result))
    report=dict(schema='public-trade-groups-simultaneous-v2',retrospective=True,source_sha256=base.sha(Path(__file__)),
        grouping_source_sha256=base.sha(Path(base.__file__)),strict_report_sha256=base.sha(old),windows=windows,
        reason='Strict transaction-hash grouping yielded only single prints. Window2 schema inspection found repeated taker orderIDs with identical versions and source milliseconds but distinct tx_hash values. This follow-up drops transaction hash from grouping and retains exact source timestamp. Strict result retained.',
        method='Same venue/market/generation/aggressor orderID/order version/source millisecond. No account fields used. Aggregates only; no new cash or active capture analysis.',
        limits='Same observed order identity and timestamp is a narrower observable than a latent parent metaorder. Does not establish completion, residual size, exact presweep depth, or independent events. Distinct tx_hash semantics not established; these groups are exploratory.')
    blob=(json.dumps(report,indent=2)+'\n').encode();assert len(blob)<=5000
    target=base.ROOT/'reports/single-venue-research/public-trade-groups-simultaneous.json';assert not target.exists();target.write_bytes(blob)
    print(json.dumps(windows,indent=2))

if __name__=='__main__':main()
