"""Three fixed full-universe displayed-book cost rounds, never actual fills."""
import concurrent.futures as cf
import datetime as dt
import gzip
import hashlib
import json
import time
from decimal import Decimal as D, ROUND_DOWN
from pathlib import Path
from core_eth_quote_cost import fetch, levels, walk

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'reports/experiment-storage/core-native-quote-cost-allocation-v1.json'
OUT = ROOT / 'reports/core-native-quote-cost'


def analyze(market, pair, index):
    result = []
    for size in (100, 250, 500, 1000):
        row = {'asset': market['asset'], 'round': index, 'size_usdc': size, 'status': 'unknown'}
        try:
            assert all(p['rtt_seconds'] <= 2 for p in pair.values()), 'RTT exceeds2s'
            skew = abs(pair['spot']['received_mono'] - pair['perp']['received_mono'])
            assert skew <= .25, 'receipt skew exceeds250ms'
            spot, perp = levels(pair['spot']), levels(pair['perp'])
            q = (D(size) / spot['asks'][0][0]).quantize(D(1).scaleb(-market['decimals']), rounding=ROUND_DOWN)
            assert q >= D(market['min_base']), 'base minimum'
            sa, sb = walk(spot['asks'], q), walk(spot['bids'], q)
            pa, pb = walk(perp['asks'], q), walk(perp['bids'], q)
            assert min(sa, sb, pa, pb) >= D(market['min_quote']), 'quote minimum'
            cost = sa - sb + pa - pb
            assert cost >= 0
            row.update(status='displayed_quote_only', quantity=str(q), spot_buy_usdc=str(sa),
                       opening_basis_usdc=str(pb - sa), closing_liability_usdc=str(pa - sb),
                       immediate_roundtrip_cost_usdc=str(cost),
                       immediate_roundtrip_cost_bps=str(cost / sa * 10000),
                       receipt_skew_seconds=round(skew, 6))
        except Exception as exc:
            row['reason'] = type(exc).__name__ + ':' + str(exc)[:160]
        result.append(row)
    return result


def self_check():
    assert walk([(D(10), D(2)), (D(12), D(3))], D(3)) == 32
    try:
        walk([(D(10), D(2))], D(3))
    except ValueError:
        pass
    else:
        raise AssertionError('unavailable depth accepted')
    market = {'asset': 'TEST', 'decimals': 1, 'min_base': '1', 'min_quote': '1'}
    def book(bid, ask):
        return {'rtt_seconds': .1, 'received_mono': 1,
                'body': {'code': 200, 'bids': [{'price': str(bid), 'remaining_base_amount': '100'}],
                         'asks': [{'price': str(ask), 'remaining_base_amount': '100'}]}}
    pair = {'spot': book(99, 100), 'perp': book(101, 102)}
    r = analyze(market, pair, 0)[0]
    assert D(r['immediate_roundtrip_cost_usdc']) == 2
    pair['perp']['received_mono'] = 2
    assert all(r['status'] == 'unknown' for r in analyze(market, pair, 0))


def main():
    self_check()
    p = PLAN.read_bytes()
    plan = json.loads(p)
    for pin in plan['input_pins']:
        assert hashlib.sha256((ROOT / pin['path']).read_bytes()).hexdigest() == pin['sha256']
    OUT.mkdir(exist_ok=True)
    assert not any(OUT.iterdir())
    with (OUT / 'claim.json').open('x') as f:
        json.dump({'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                   'plan_sha256': hashlib.sha256(p).hexdigest(),
                   'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}, f)
    retained, outcomes, provenance = 0, [], []
    start = time.monotonic()
    with cf.ThreadPoolExecutor(max_workers=14) as pool:
        for index in range(3):
            time.sleep(max(0, start + index * 30 - time.monotonic()))
            late = time.monotonic() - (start + index * 30)
            assert late <= 2, 'missed fixed round'
            pending = {(m['asset'], k): pool.submit(fetch, m[k]) for m in plan['universe'] for k in ('spot', 'perp')}
            rows = {m['asset']: {k: pending[(m['asset'], k)].result() for k in ('spot', 'perp')}
                    for m in plan['universe']}
            b = (json.dumps(rows) + '\n').encode()
            packed = gzip.compress(b, mtime=0)
            assert retained + len(packed) <= 65536
            with (OUT / (str(index) + '.json.gz')).open('xb') as f:
                f.write(packed)
            retained += len(packed)
            provenance.append({'round': index, 'raw_sha256': hashlib.sha256(b).hexdigest(),
                               'gzip_bytes': len(packed), 'round_lateness_seconds': late})
            for market in plan['universe']:
                outcomes.extend(analyze(market, rows[market['asset']], index))
            print('round', index, 'complete', flush=True)
    result = {'actual_pnl': None, 'actual_fills': False, 'underlying_book_timestamps_verified': False,
              'standard_fee_scenario_bps': 0, 'future_exit_prices_unknown': True,
              'not_historical_execution_cost': True, 'all_outcomes': outcomes, 'provenance': provenance}
    b = (json.dumps(result, indent=2) + '\n').encode()
    assert len(b) <= 49152
    with (OUT / 'summary.json').open('xb') as f:
        f.write(b)
    terminal = {'status': 'completed', 'requests': 42, 'retained_raw_bytes': retained,
                'unknown_rows': sum(x['status'] == 'unknown' for x in outcomes),
                'summary_sha256': hashlib.sha256(b).hexdigest()}
    with (OUT / 'terminal.json').open('x') as f:
        json.dump(terminal, f)
    print(json.dumps(terminal))


if __name__ == '__main__':
    main()
