"""Five paired public ETH books: displayed execution-cost diagnostic only."""
import concurrent.futures as cf
import datetime as dt
import gzip
import hashlib
import json
import time
import urllib.parse
import urllib.request
from decimal import Decimal as D, ROUND_DOWN
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'reports/experiment-storage/core-eth-quote-cost-allocation-v1.json'
OUT = ROOT / 'reports/core-eth-quote-cost'


def sha(b):
    return hashlib.sha256(b).hexdigest()


def verify_retired(plan):
    for study in plan['completed_studies_frozen']:
        prefix = study['directory'] + '/'
        expected = {p for p in study['pins'] if p.startswith(prefix)}
        actual = {str(p.relative_to(ROOT)) for p in (ROOT / study['directory']).iterdir()}
        assert expected == actual, 'Completed artifact set changed'
        total = 0
        for path, pin in study['pins'].items():
            b = (ROOT / path).read_bytes()
            assert len(b) == pin['bytes'] and sha(b) == pin['sha256']
            total += len(b)
        assert total <= study['new_reservation_bytes']


def put(plan, name, b, category):
    verify_retired(plan)
    pattern = {'raw': '*.json.gz', 'output': 'summary.json', 'control': '*claim.json'}[category]
    used = sum(p.stat().st_size for p in OUT.glob(pattern))
    if category == 'control':
        used += PLAN.stat().st_size
    assert used + len(b) <= plan['categories_bytes'][category]
    with (OUT / name).open('xb') as f:
        f.write(b)


def fetch(market):
    params = urllib.parse.urlencode({'market_id': market, 'limit': 10})
    row = {'market_id': market, 'start_utc': dt.datetime.now(dt.timezone.utc).isoformat()}
    start = time.monotonic()
    try:
        url = 'https://mainnet.zklighter.elliot.ai/api/v1/orderBookOrders?' + params
        request = urllib.request.Request(url, headers={'User-Agent': 'rhhype-public-research/1.0'})
        with urllib.request.urlopen(request, timeout=5) as response:
            b = response.read(32769)
            assert response.status == 200 and len(b) <= 32768
        row['body'] = json.loads(b)
        row['body_sha256'] = sha(b)
    except Exception as exc:
        row['error'] = str(exc)[:160]
    row['received_mono'] = time.monotonic()
    row['rtt_seconds'] = row['received_mono']-start
    row['received_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    return row


def levels(row):
    assert 'error' not in row, row.get('error')
    b = row['body']
    assert b['code'] == 200
    result = {}
    for side in ('bids', 'asks'):
        pairs = [(D(x['price']), D(x['remaining_base_amount'])) for x in b[side]]
        assert all(p.is_finite() and q.is_finite() and p > 0 and q >= 0 for p, q in pairs)
        pairs = [(p, q) for p, q in pairs if q > 0]
        assert pairs and pairs == sorted(pairs, reverse=side == 'bids', key=lambda x: x[0])
        result[side] = pairs
    assert result['bids'][0][0] < result['asks'][0][0]
    return result


def walk(book, qty):
    remaining, cash = qty, D(0)
    for price, available in book:
        take = min(remaining, available)
        cash += take * price
        remaining -= take
        if remaining == 0:
            return cash
    raise ValueError('Insufficient captured depth')


def analyze(plan, rows, index):
    out = []
    try:
        assert all(r['rtt_seconds'] <= plan['max_rtt_seconds'] for r in rows.values()), 'RTT gate'
        skew = abs(rows['spot']['received_mono']-rows['perp']['received_mono'])
        assert skew <= plan['max_receipt_skew_seconds'], 'Receipt skew gate'
        spot, perp = levels(rows['spot']), levels(rows['perp'])
        timing_error = None
    except Exception as exc:
        timing_error = str(exc)[:160]
    for size in plan['sizes']:
        r = {'round': index, 'target_usdc': size, 'status': 'rejected'}
        try:
            assert timing_error is None, timing_error
            qty = (D(size) / spot['asks'][0][0]).quantize(D('.0001'), rounding=ROUND_DOWN)
            assert qty >= D('.005')
            sa, sb = walk(spot['asks'], qty), walk(spot['bids'], qty)
            pa, pb = walk(perp['asks'], qty), walk(perp['bids'], qty)
            mid_notional = qty * (spot['asks'][0][0]+spot['bids'][0][0])/2
            # Crossing at both legs and both sides on these same snapshots.
            spread_cost = sa-sb+pa-pb
            assert spread_cost >= 0
            r.update(status='displayed_quote_only', quantity_eth=str(qty),
                     spot_buy_usdc=str(sa), open_basis_usdc=str(pb-sa),
                     closing_liability_usdc=str(pa-sb),
                     immediate_roundtrip_cost_usdc=str(spread_cost),
                     immediate_roundtrip_cost_bps=str(spread_cost/mid_notional*10000),
                     receipt_skew_seconds=round(skew, 6))
        except Exception as exc:
            r['reason'] = str(exc)[:160]
        out.append(r)
    return out


def main():
    p = PLAN.read_bytes()
    plan = json.loads(p)
    assert plan['requests_max'] == 10 and plan['rounds'] == 5 and plan['retries'] == 0
    assert Path(__file__).stat().st_size <= 8192
    verify_retired(plan)
    OUT.mkdir(exist_ok=True)
    assert not any(OUT.iterdir()), 'No retries or overwrites'
    claim = {'plan_sha256': sha(p), 'source_sha256': sha(Path(__file__).read_bytes()),
             'started_utc': dt.datetime.now(dt.timezone.utc).isoformat()}
    put(plan, 'claim.json', (json.dumps(claim)+'\n').encode(), 'control')
    start, results, requests = time.monotonic(), [], 0
    terminal = {'status': 'failed_no_retry'}
    try:
        with cf.ThreadPoolExecutor(max_workers=2) as pool:
            for i in range(5):
                time.sleep(max(0, start+i*30-time.monotonic()))
                futures = {name: pool.submit(fetch, market) for name, market in plan['markets'].items()}
                requests += 2
                rows = {name: f.result() for name, f in futures.items()}
                packed = gzip.compress((json.dumps(rows)+'\n').encode(), mtime=0)
                put(plan, str(i)+'.json.gz', packed, 'raw')
                results.extend(analyze(plan, rows, i))
                print(json.dumps({'round': i, 'rows': results[-4:]}), flush=True)
        summary = {'actual_pnl': None, 'actual_fills': False,
                   'underlying_book_timestamps_verified': False,
                   'standard_fee_scenario_bps': 0, 'requests': requests,
                   'future_exit_funding_and_debit_costs_unknown': True,
                   'all_outcomes': results, 'plan_sha256': sha(p)}
        b = (json.dumps(summary)+'\n').encode()
        put(plan, 'summary.json', b, 'output')
        terminal.update(status='completed', summary_sha256=sha(b))
    except Exception as exc:
        terminal['error'] = str(exc)[:160]
    terminal['requests'] = requests
    put(plan, 'terminal-claim.json', (json.dumps(terminal)+'\n').encode(), 'control')
    print(json.dumps(terminal), flush=True)


if __name__ == '__main__':
    main()
