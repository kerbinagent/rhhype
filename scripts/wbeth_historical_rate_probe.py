"""Bounded public Ethereum historical WBETH exchange-rate probe; no transactions."""
import datetime as dt
import gzip
import hashlib
import json
import time
import urllib.request
from decimal import Decimal as D
from pathlib import Path
from Crypto.Hash import keccak

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'reports/experiment-storage/wbeth-historical-rate-probe-allocation-v1.json'
OUT = ROOT / 'reports/wbeth-historical-rate-probe'


def selector(name):
    k = keccak.new(digest_bits=256)
    k.update(name.encode())
    return '0x' + k.hexdigest()[:8]


def main():
    p = PLAN.read_bytes()
    plan = json.loads(p)
    OUT.mkdir(exist_ok=True)
    assert not any(OUT.iterdir())
    with (OUT/'claim.json').open('x') as f:
        json.dump(dict(started_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                       plan_sha256=hashlib.sha256(p).hexdigest(), source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),f)
    trace, blocks = [], {}
    terminal = {'status': 'failed_no_retry', 'requests': 0}
    result = {'actual_pnl': None, 'actual_redemption_or_secondary_price': None,
              'ethereum_rate_not_verified_on_bnb_chain': True}

    def rpc(method, params):
        assert method in ('eth_chainId', 'eth_getBlockByNumber', 'eth_call')
        assert terminal['requests'] < 52, 'request budget'
        terminal['requests'] += 1
        payload = {'jsonrpc': '2.0', 'id': terminal['requests'], 'method': method, 'params': params}
        time.sleep(.25)
        req = urllib.request.Request(plan['rpc_url'], data=json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json', 'User-Agent': 'rhhype-public-research/1.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read(524289)
            assert response.status == 200 and len(raw) <= 524288, 'RPC response size'
        obj = json.loads(raw)
        archive = {'request': payload, 'raw_response_sha256': hashlib.sha256(raw).hexdigest(),
                   'received_utc': dt.datetime.now(dt.timezone.utc).isoformat()}
        if method == 'eth_getBlockByNumber' and isinstance(obj.get('result'), dict):
            # Keep the block identity/time needed for deterministic bracketing.
            # Explicit projection avoids retaining unrelated transaction hashes.
            archive['block_projection'] = {k: obj['result'][k] for k in ('number', 'hash', 'parentHash', 'timestamp', 'stateRoot')}
            archive['transaction_hashes_not_retained'] = True
        else:
            archive['response'] = obj
        trace.append(archive)
        packed = gzip.compress((json.dumps(trace) + '\n').encode(), mtime=0)
        assert len(packed) <= 32768, 'trace budget'
        (OUT/'trace.json.gz').write_bytes(packed)
        assert obj.get('id') == payload['id'] and 'error' not in obj and obj.get('result') is not None, str(obj.get('error'))
        return obj['result']

    def block(number):
        if number not in blocks:
            b = rpc('eth_getBlockByNumber', [hex(number) if isinstance(number, int) else number, False])
            assert int(b['number'], 16) >= 0 and len(b['hash']) == 66
            blocks[number] = {'number': int(b['number'], 16), 'timestamp': int(b['timestamp'], 16), 'hash': b['hash']}
        return blocks[number]

    try:
        assert int(rpc('eth_chainId', []), 16) == 1, 'unexpected chain'
        latest = block('latest')
        assert -30 <= time.time() - latest['timestamp'] <= 300, 'stale/future chain head'
        lower_number = latest['number'] - 400000
        lower = block(lower_number)
        assert lower['timestamp'] < min(plan['target_timestamps']) < max(plan['target_timestamps']) < latest['timestamp']
        boundaries = []
        for target in plan['target_timestamps']:
            lo, hi = lower_number, latest['number']
            while hi - lo > 1:
                mid = (hi + lo) // 2
                if block(mid)['timestamp'] <= target:
                    lo = mid
                else:
                    hi = mid
            before, after = block(lo), block(hi)
            assert before['timestamp'] <= target < after['timestamp']
            assert after['timestamp'] - before['timestamp'] <= 60, 'large boundary block gap'
            boundaries.append({'target_timestamp': target, 'before': before, 'after': after})
        address = plan['contract']
        symbol_hex = rpc('eth_call', [{'to': address, 'data': selector('symbol()')}, hex(latest['number'])])
        symbol_bytes = bytes.fromhex(symbol_hex[2:])
        offset = int.from_bytes(symbol_bytes[:32], 'big')
        length = int.from_bytes(symbol_bytes[offset:offset+32], 'big')
        assert symbol_bytes[offset+32:offset+32+length].decode() == 'WBETH', 'wrong token symbol'
        decimals = int(rpc('eth_call', [{'to': address, 'data': selector('decimals()')}, hex(latest['number'])]),16)
        assert decimals == 18, 'unexpected token decimals'
        rates = []
        for boundary in boundaries:
            value = rpc('eth_call', [{'to': address, 'data': selector('exchangeRate()')}, hex(boundary['before']['number'])])
            assert len(value) == 66, 'unexpected rate ABI'
            rate = D(int(value,16)) / D(10**18)
            assert D('.5') < rate < D(5), 'implausible conversion scale'
            rates.append(rate)
        elapsed = D(plan['target_timestamps'][1] - plan['target_timestamps'][0])
        growth = rates[1]/rates[0]-1
        result.update(status='observed_onchain_rate_growth', boundaries=boundaries,
                      start_rate_eth_per_wbeth=str(rates[0]), end_rate_eth_per_wbeth=str(rates[1]),
                      token_unit_growth=str(growth), simple_annualized_growth=str(growth*31536000/elapsed),
                      exchange_rate_selector=selector('exchangeRate()'))
        terminal['status'] = 'completed'
    except Exception as exc:
        result['status'] = 'unknown'
        terminal['error'] = type(exc).__name__ + ':' + str(exc)[:320]
    b = (json.dumps(result,indent=2)+'\n').encode()
    assert len(b) <= 8192
    with (OUT/'summary.json').open('xb') as f:
        f.write(b)
    terminal['summary_sha256'] = hashlib.sha256(b).hexdigest()
    terminal['retained_projected_trace_bytes'] = (OUT/'trace.json.gz').stat().st_size if (OUT/'trace.json.gz').exists() else 0
    with (OUT/'terminal.json').open('x') as f:
        json.dump(terminal,f,indent=2)
    print(json.dumps(terminal))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
