"""Frozen linear-box displayed price bound, no actual margin or execution claim."""
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
PLAN = ROOT / 'reports/experiment-storage/deribit-linear-box-quotes-allocation-v1.json'
OUT = ROOT / 'reports/deribit-linear-box-quotes'


def fetch(name):
    start = time.monotonic()
    row = {'instrument_name': name}
    try:
        url = 'https://www.deribit.com/api/v2/public/get_order_book?' + urllib.parse.urlencode(dict(instrument_name=name, depth=10))
        req = urllib.request.Request(url, headers={'User-Agent': 'rhhype-public-research/1.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            raw = response.read(65537)
            assert response.status == 200 and len(raw) <= 65536
        row.update(body=json.loads(raw, parse_float=str), raw_sha256=hashlib.sha256(raw).hexdigest())
    except Exception as exc:
        row['error'] = type(exc).__name__ + ':' + str(exc)[:160]
    row.update(received_mono=time.monotonic(), received_ms=int(time.time() * 1000))
    row['rtt_seconds'] = row['received_mono'] - start
    return row


def cash_fee(levels, q, index):
    remaining, cash, fee = q, D(0), D(0)
    for price, amount in levels:
        take = min(remaining, amount)
        cash += price * take
        fee += min(D('.0003') * index, D('.125') * price) * take
        remaining -= take
        if remaining == 0:
            return cash, fee
    raise ValueError('insufficient displayed depth')


def analyze(selection, rows, round_index):
    checked, errors = [], []
    for leg in selection['legs']:
        m = leg['instrument']
        row = rows[m['instrument_name']]
        try:
            assert 'error' not in row, row.get('error')
            assert row['rtt_seconds'] <= 2, 'RTT exceeds2s'
            body = row['body']
            assert body.get('testnet') is False and 'error' not in body
            b = body['result']
            assert b['instrument_name'] == m['instrument_name'] and b['state'] == 'open'
            age = row['received_ms'] - b['timestamp']
            assert -1000 <= age <= 5000, 'book timestamp age gate'
            index = D(b['index_price'])
            assert index.is_finite() and index > 0
            books = {}
            for side in ['bids', 'asks']:
                levels = [(D(p), D(q)) for p, q in b[side]]
                assert levels and all(p.is_finite() and q.is_finite() and p > 0 and q > 0 for p, q in levels), 'empty/invalid levels'
                assert levels == sorted(levels, key=lambda v: v[0], reverse=side == 'bids'), 'unsorted book'
                books[side] = levels
            assert books['bids'][0][0] < books['asks'][0][0], 'crossed book'
            checked.append((leg, books['asks' if leg['side'] == 'buy' else 'bids'], index, age))
        except Exception as exc:
            errors.append(m['instrument_name'] + ':' + type(exc).__name__ + ':' + str(exc)[:130])
    arrivals = [r['received_mono'] for r in rows.values()]
    if max(arrivals) - min(arrivals) > 1:
        errors.append('cross-instrument receipt skew exceeds1s')
    step = max(D(str(l['instrument']['min_trade_amount'])) for l in selection['legs'])
    width = D(selection['face_per_base_unit'])
    results = []
    for budget in [100, 250, 500, 1000]:
        q = (D(budget) / (width * D('1.1')) / step).to_integral_value(rounding=ROUND_DOWN) * step
        row = dict(asset=selection['asset'], round=round_index, cash_budget=budget,
                   quantity=str(q), status='unknown', errors=errors.copy(), actual_pnl=None)
        try:
            assert q >= step, 'below minimum quantity'
            assert not errors, 'one or more quote gates failed'
            debit, fee, detail = D(0), D(0), []
            for leg, levels, index, age in checked:
                cash, cost = cash_fee(levels, q, index)
                debit += cash if leg['side'] == 'buy' else -cash
                fee += cost
                detail.append(dict(instrument_name=leg['instrument']['instrument_name'], side=leg['side'],
                                   premium_usdc=str(cash), entry_fee_usdc=str(cost), book_age_ms=age))
            assert debit > 0, 'nonpositive net debit needs separate financing model'
            face = width * q
            remaining_seconds = D(selection['expiry'] - max(r['received_ms'] for r in rows.values())) / 1000
            assert remaining_seconds > 0
            minimum_capital = debit + fee
            capital = minimum_capital * D('.05') * remaining_seconds / D(31536000)
            stress = face * D('.0005')
            gross = face - debit
            row.update(status='displayed_conditional_bound', face_usdc=str(face), debit_usdc=str(debit),
                       entry_fee_usdc=str(fee), gross_before_all_costs_usdc=str(gross),
                       after_entry_fee_usdc=str(gross - fee), minimum_capital_charge_usdc=str(capital),
                       stress_usdc=str(stress), optimistic_residual_usdc=str(gross - fee - capital - stress),
                       cash_budget_covers_net_debit_and_fees=minimum_capital <= budget,
                       remaining_seconds=str(remaining_seconds), legs=detail)
        except Exception as exc:
            row['errors'].append(type(exc).__name__ + ':' + str(exc)[:160])
        results.append(row)
    return results


def self_check():
    lo, hi = D(2400), D(3000)
    for s in [D(0), lo, D(2700), hi, D(100000)]:
        assert max(s-lo, 0)-max(s-hi, 0)+max(hi-s, 0)-max(lo-s, 0) == hi-lo
    assert cash_fee([(D(1), D(2)), (D(3), D(5))], D(3), D(1000)) == (D(5), D('.55'))
    try:
        cash_fee([(D(1), D(2))], D(3), D(1000))
    except ValueError:
        pass
    else:
        raise AssertionError('missing depth accepted')


def main():
    self_check()
    p = PLAN.read_bytes()
    plan = json.loads(p)
    for pin in plan['input_pins']:
        assert hashlib.sha256((ROOT / pin['path']).read_bytes()).hexdigest() == pin['sha256']
    selections = [r['selection'] for r in json.loads((ROOT / plan['selection_file']).read_bytes())['outcomes']]
    OUT.mkdir(exist_ok=True)
    assert not any(OUT.iterdir())
    with (OUT / 'claim.json').open('x') as f:
        json.dump(dict(started_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                       plan_sha256=hashlib.sha256(p).hexdigest(), source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()), f)
    start, retained, outcomes, provenance = time.monotonic(), 0, [], []
    names = [l['instrument']['instrument_name'] for s in selections for l in s['legs']]
    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        for i in range(3):
            time.sleep(max(0, start + i * 30 - time.monotonic()))
            assert time.monotonic() - start - i * 30 <= 2, 'missed fixed round'
            futures = {name: pool.submit(fetch, name) for name in names}
            rows = {name: future.result() for name, future in futures.items()}
            raw = (json.dumps(rows) + '\n').encode()
            packed = gzip.compress(raw, mtime=0)
            assert retained + len(packed) <= 32768
            with (OUT / (str(i) + '.json.gz')).open('xb') as f:
                f.write(packed)
            retained += len(packed)
            provenance.append(dict(round=i, raw_sha256=hashlib.sha256(raw).hexdigest(), gzip_bytes=len(packed)))
            for s in selections:
                outcomes.extend(analyze(s, {l['instrument']['instrument_name']: rows[l['instrument']['instrument_name']] for l in s['legs']}, i))
            print('round', i, 'complete', flush=True)
    result = dict(actual_pnl=None, fills_observed=False, four_leg_fees_no_combo_discount=True,
                  delivery_fee_assumed_zero_for_optimistic_bound=True, extra_margin_assumed_zero=True,
                  capital_feasibility_unknown=True, outcomes=outcomes, provenance=provenance)
    b = (json.dumps(result, indent=2) + '\n').encode()
    assert len(b) <= 49152
    with (OUT / 'summary.json').open('xb') as f:
        f.write(b)
    terminal = dict(status='completed', requests=24, raw_bytes=retained,
                    unknown_rows=sum(r['status'] == 'unknown' for r in outcomes), summary_sha256=hashlib.sha256(b).hexdigest())
    with (OUT / 'terminal.json').open('x') as f:
        json.dump(terminal, f)
    print(json.dumps(terminal))


if __name__ == '__main__':
    main()
