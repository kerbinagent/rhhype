"""Past-capture basis forecasts at fixed horizons; no fills or execution P&L."""
from collections import deque
from decimal import Decimal as D
from pathlib import Path
from statistics import mean, median
import datetime
import gzip
import hashlib
import json
import math
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from scripts.core_spot_passive_events_v2 import iter_events
from scripts.audit_core_spot_passive_skew500 import fresh

PLAN = ROOT / 'reports/experiment-storage/spot-basis-horizon-diagnostic-v1.json'
OUT = ROOT / 'reports/spot-basis-horizon-diagnostic'
NS = 10**9

def metrics(rows):
    if not rows:
        return {'n': 0}
    errors = [r['future_bps'] - r['reference_bps'] for r in rows]
    changes = [r['future_bps'] - r['basis_bps'] for r in rows]
    mse = mean(x*x for x in errors)
    no_change_mse = mean(x*x for x in changes)
    return dict(n=len(rows), median_forecast_rmse_bps=math.sqrt(mse),
                no_change_rmse_bps=math.sqrt(no_change_mse),
                mse_skill_vs_no_change=1-mse/no_change_mse if no_change_mse else None,
                mean_predicted_long_spot_short_perp_gain_bps=mean(r['basis_bps']-r['reference_bps'] for r in rows),
                mean_realized_basis_contraction_bps=-mean(changes),
                positive_contraction_count=sum(x < 0 for x in changes))

def main():
    plan = json.loads(PLAN.read_bytes())
    for pin in plan['source_pins']:
        assert hashlib.sha256((ROOT / pin['path']).read_bytes()).hexdigest() == pin['sha256']
    source = ROOT / plan['source_capture']
    manifest = json.loads((source / 'manifest.json').read_bytes())
    start = int(datetime.datetime.fromisoformat(manifest['started_utc']).timestamp()*NS)
    origins = [dict(grid_seconds=x, target_ns=start+x*NS,
                    principal=x in plan['principal_origin_grid_seconds'], horizons={})
               for x in plan['origin_grid_seconds']]
    books, history, last, generation, ended = {}, deque(maxlen=125), None, 0, None
    for e in iter_events(source, expected_manifest_sha256=plan['source_manifest_sha256'], max_raw_bytes=3407872):
        if e['type'] == 'end':
            ended = e
            continue
        if e['type'] == 'invalidate':
            books.clear(); history.clear(); last = None; generation += 1
            continue
        if e['type'] != 'book':
            continue
        asset, kind = e['asset'].rsplit('_', 1)
        assert asset == 'LIT'
        now = e['received_ns']
        books[kind] = e
        if not fresh(books, now):
            continue
        mid = {k: (D(v['bids'][0][0])+D(v['asks'][0][0]))/2 for k,v in books.items()}
        basis = (mid['perp']/mid['spot']-1)*10000
        if last is None or now-last >= NS:
            history.append((now, basis)); last = now
        refs = [(t,v) for t,v in history if now-122*NS <= t <= now-2*NS]
        for origin in origins:
            if 'origin_status' not in origin and now >= origin['target_ns']:
                if now-origin['target_ns'] > 250_000_000:
                    origin['origin_status'] = 'missing_fresh_pair_in_250ms'
                elif len(refs) < 60 or refs[-1][0]-refs[0][0] < 89*NS:
                    origin['origin_status'] = 'insufficient_reference'
                else:
                    origin.update(origin_status='matched', origin_ns=now, generation=generation,
                                  basis_bps=float(basis), reference_bps=float(median(v for t,v in refs)),
                                  reference_count=len(refs), reference_span_ns=refs[-1][0]-refs[0][0])
            if origin.get('origin_status') != 'matched':
                continue
            for horizon in plan['horizons_seconds']:
                if str(horizon) in origin['horizons']:
                    continue
                target = origin['origin_ns']+horizon*NS
                if now < target:
                    continue
                if generation != origin['generation']:
                    row = dict(status='invalidation_crossing')
                elif now-target > 250_000_000:
                    row = dict(status='missing_fresh_pair_in_250ms')
                else:
                    row = dict(status='matched', future_ns=now, future_bps=float(basis),
                               basis_bps=origin['basis_bps'], reference_bps=origin['reference_bps'])
                origin['horizons'][str(horizon)] = row
    assert ended
    for origin in origins:
        origin.setdefault('origin_status', 'capture_ended_before_match')
        for horizon in plan['horizons_seconds']:
            origin['horizons'].setdefault(str(horizon), dict(status='origin_missing' if origin['origin_status'] != 'matched' else 'capture_ended_before_match'))
    summary = {}
    for horizon in plan['horizons_seconds']:
        pairs = [(o,o['horizons'][str(horizon)]) for o in origins if o['horizons'][str(horizon)]['status']=='matched']
        summary[str(horizon)] = dict(
            all_10s_grid=metrics([r for o,r in pairs]),
            principal_60s_grid=metrics([r for o,r in pairs if o['principal']]),
            positive_excursion_10s_grid=metrics([r for o,r in pairs if r['basis_bps'] > r['reference_bps']]),
            missing_grid_origins=len(origins)-len(pairs))
    result = dict(scope=plan['scope'], source_manifest_sha256=plan['source_manifest_sha256'],
                  plan_sha256=hashlib.sha256(PLAN.read_bytes()).hexdigest(),
                  summary=summary, origins=origins)
    data = gzip.compress((json.dumps(result, separators=(',',':'))+'\n').encode(),mtime=0)
    assert len(data) <= plan['output_cap_bytes']
    OUT.mkdir(exist_ok=False)
    (OUT/'diagnostic.json.gz').write_bytes(data)
    print(json.dumps(summary, indent=2))

if __name__ == '__main__':
    main()
