"""Public linear-option catalogue and deterministic box selection, no quotes."""
import datetime as dt
import gzip
import hashlib
import json
import time
import urllib.parse
import urllib.request
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'reports/experiment-storage/deribit-linear-box-preflight-allocation-v1.json'
OUT = ROOT / 'reports/deribit-linear-box-preflight'


def choose(instruments, asset, spot, now):
    rows = [m for m in instruments if m['base_currency'] == asset and m['kind'] == 'option'
            and m['settlement_currency'] == 'USDC' and m['quote_currency'] == 'USDC'
            and m['instrument_type'] == 'linear' and m['is_active'] and m.get('state') == 'open'
            and now + 14 * 86400000 <= m['expiration_timestamp'] <= now + 45 * 86400000]
    expiries = sorted({m['expiration_timestamp'] for m in rows}, key=lambda t: (abs(t - now - 30 * 86400000), t))
    assert expiries, 'no eligible expiry'
    expiry = expiries[0]
    rows = [m for m in rows if m['expiration_timestamp'] == expiry]
    common = {D(str(m['strike'])) for m in rows if m['option_type'] == 'call'} & {D(str(m['strike'])) for m in rows if m['option_type'] == 'put'}
    lo = max(k for k in common if k <= spot * D('.9'))
    hi = min(k for k in common if k >= spot * D('1.1'))
    legs = []
    for kind, strike, side in [('call', lo, 'buy'), ('call', hi, 'sell'), ('put', hi, 'buy'), ('put', lo, 'sell')]:
        leg = [m for m in rows if m['option_type'] == kind and D(str(m['strike'])) == strike]
        assert len(leg) == 1
        legs.append({'side': side, 'instrument': leg[0]})
    assert len({m['instrument']['price_index'] for m in legs}) == 1
    assert all(D(str(m['instrument']['contract_size'])) == 1 for m in legs), 'nonunit contract multiplier'
    return {'asset': asset, 'index': str(spot), 'expiry': expiry, 'low_strike': str(lo), 'high_strike': str(hi),
            'face_per_base_unit': str(hi - lo), 'legs': legs}


def main():
    p = PLAN.read_bytes()
    plan = json.loads(p)
    OUT.mkdir(exist_ok=True)
    assert not any(OUT.iterdir())
    with (OUT / 'claim.json').open('x') as f:
        json.dump({'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                   'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   'plan_sha256': hashlib.sha256(p).hexdigest()}, f)
    data, provenance, errors, retained = {}, [], [], 0
    for name, endpoint, params in plan['requests']:
        try:
            time.sleep(2)
            url = 'https://www.deribit.com/api/v2/public/' + endpoint + '?' + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, headers={'User-Agent': 'rhhype-public-research/1.0'})
            with urllib.request.urlopen(req, timeout=15) as response:
                raw = response.read(4194305)
                assert response.status == 200 and len(raw) <= 4194304, 'response size'
            packed = gzip.compress(raw, mtime=0)
            assert retained + len(packed) <= 131072, 'raw budget'
            with (OUT / (name + '.json.gz')).open('xb') as f:
                f.write(packed)
            retained += len(packed)
            provenance.append({'name': name, 'url': url, 'raw_sha256': hashlib.sha256(raw).hexdigest(),
                               'received_utc': dt.datetime.now(dt.timezone.utc).isoformat()})
            obj = json.loads(raw)
            assert 'result' in obj and 'error' not in obj and obj.get('testnet') is False, 'response schema or environment'
            data[name] = obj['result']
        except Exception as exc:
            errors.append({'name': name, 'error': type(exc).__name__ + ':' + str(exc)[:200]})
    outcomes = []
    for asset in ['ETH', 'BTC']:
        row = {'asset': asset, 'status': 'unknown'}
        try:
            row.update(status='metadata_selected', selection=choose(data['instruments'], asset,
                       D(str(data[asset]['index_price'])), plan['selection_time_ms']))
        except Exception as exc:
            row['error'] = type(exc).__name__ + ':' + str(exc)[:200]
        outcomes.append(row)
    result = {'actual_pnl': None, 'quotes_observed': False, 'outcomes': outcomes,
              'catalogue_count': len(data.get('instruments', [])), 'provenance': provenance, 'errors': errors}
    b = (json.dumps(result, indent=2) + '\n').encode()
    assert len(b) <= 24576
    with (OUT / 'summary.json').open('xb') as f:
        f.write(b)
    with (OUT / 'terminal.json').open('x') as f:
        json.dump({'status': 'completed_preflight', 'requests': 3, 'raw_bytes': retained,
                   'unknown_assets': sum(r['status'] == 'unknown' for r in outcomes),
                   'summary_sha256': hashlib.sha256(b).hexdigest()}, f)
    for row in outcomes:
        selection = row.get('selection', {})
        print(row['asset'], row['status'], selection.get('expiry'), selection.get('low_strike'),
              selection.get('high_strike'), row.get('error'))
    print('catalogue_count', result['catalogue_count'], 'rawbytes', retained, 'errors', errors)


if __name__ == '__main__':
    main()
