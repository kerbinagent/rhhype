"""Fixed public eth_call screen of distinct-pool USDC/WETH cycles. No transactions."""
import datetime as dt
import gzip
import hashlib
import itertools
import json
import sys
import time
import urllib.error
import urllib.request
from decimal import Decimal as D
from pathlib import Path
from Crypto.Hash import keccak

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'reports/experiment-storage/base-atomic-cycle-screen-allocation-v1.json'
OUT = ROOT / 'reports/base-atomic-cycle-screen'
USDC = '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913'
WETH = '0x4200000000000000000000000000000000000006'
FACTORY = '0x33128a8fC17869897dcE68Ed026d694621f6FDfD'
QUOTER = '0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a'
TIERS = (100, 500, 3000)


def sel(signature):
    k = keccak.new(digest_bits=256)
    k.update(signature.encode())
    return '0x' + k.hexdigest()[:8]


def word(n):
    return int(n).to_bytes(32, 'big').hex()


def address(a):
    return a[2:].lower().zfill(64)


def quote_data(a, b, amount):
    assert a != b and a in TIERS and b in TIERS
    path = bytes.fromhex(USDC[2:]) + a.to_bytes(3, 'big') + bytes.fromhex(WETH[2:]) + b.to_bytes(3, 'big') + bytes.fromhex(USDC[2:])
    return sel('quoteExactInput(bytes,uint256)') + word(64) + word(amount) + word(len(path)) + path.hex().ljust(192, '0')


def decode_quote(data):
    raw = bytes.fromhex(data[2:])
    assert len(raw) >= 320 and len(raw) % 32 == 0, 'quote ABI length'
    words = [int.from_bytes(raw[i:i+32], 'big') for i in range(0, len(raw), 32)]
    for offset in words[1:3]:
        assert offset % 32 == 0 and offset >= 128 and offset + 96 <= len(raw)
        assert words[offset//32] == 2, 'expected two pools'
    assert words[0] > 0 and words[3] > 0
    return words[0], words[3]


def selftest():
    data = quote_data(100, 500, 100_000_000)
    assert data[:10] == '0xcdca1753'
    raw = bytes.fromhex(data[10:])
    assert len(raw) == 192 and int.from_bytes(raw[:32], 'big') == 64
    assert int.from_bytes(raw[32:64], 'big') == 100_000_000
    assert int.from_bytes(raw[64:96], 'big') == 66
    assert raw[96:116].hex() == USDC[2:].lower()
    assert raw[119:139].hex() == WETH[2:].lower()
    assert raw[142:162].hex() == USDC[2:].lower()
    synthetic = '0x' + ''.join(word(n) for n in [100_100_000, 128, 224, 123456, 2, 1, 2, 2, 0, 0])
    assert decode_quote(synthetic) == (100_100_000, 123456)
    assert D(decode_quote(synthetic)[0]-100_000_000)/10**6 == D('.1')
    try:
        quote_data(500, 500, 100_000_000)
    except AssertionError:
        pass
    else:
        raise AssertionError('same-pool cycle accepted')
    print('ABI and distinct-pool synthetic checks passed')


def main():
    plan_bytes = PLAN.read_bytes()
    p = json.loads(plan_bytes)
    OUT.mkdir(exist_ok=True)
    assert not any(OUT.iterdir()), 'single run only'
    (OUT/'claim.json').write_text(json.dumps({'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'plan_sha256': hashlib.sha256(plan_bytes).hexdigest(), 'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}, indent=2))
    trace, rows, rounds = [], [], []
    terminal = {'status': 'failed_no_retry', 'requests': 0}

    def rpc(method, params):
        assert method in ('eth_chainId', 'eth_getBlockByNumber', 'eth_call', 'eth_getCode')
        assert terminal['requests'] < p['max_requests']
        terminal['requests'] += 1
        payload = {'jsonrpc': '2.0', 'id': terminal['requests'], 'method': method, 'params': params}
        record = {'request': payload, 'sent_utc': dt.datetime.now(dt.timezone.utc).isoformat()}
        time.sleep(.3)
        try:
            req = urllib.request.Request(p['rpc_url'], data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', 'User-Agent': 'rhhype-public-research/1.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                raw = response.read(2_097_153)
                assert len(raw) <= 2_097_152, 'response cap'
            obj = json.loads(raw)
            record['raw_response_sha256'] = hashlib.sha256(raw).hexdigest()
            if method == 'eth_getBlockByNumber' and isinstance(obj.get('result'), dict):
                record['block_projection'] = {k: obj['result'][k] for k in ('number', 'hash', 'parentHash', 'timestamp', 'stateRoot')}
                record['transaction_hashes_not_retained'] = True
            else:
                record['response'] = obj
            assert obj.get('id') == payload['id'] and 'error' not in obj and obj.get('result') is not None, str(obj.get('error'))
            return obj['result']
        except Exception as exc:
            record['error'] = type(exc).__name__ + ': ' + str(exc)[:500]
            raise
        finally:
            record['received_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
            trace.append(record)
            packed = gzip.compress(json.dumps(trace).encode(), mtime=0)
            assert len(packed) <= 65536, 'trace storage cap'
            (OUT/'trace.json.gz').write_bytes(packed)

    def call(to, data, block):
        return rpc('eth_call', [{'to': to, 'data': data}, block])

    try:
        assert int(rpc('eth_chainId', []), 16) == 8453
        head = rpc('eth_getBlockByNumber', ['latest', False])
        assert 0 <= time.time()-int(head['timestamp'], 16) <= 60
        tag = head['number']
        for contract in (USDC, WETH, FACTORY, QUOTER):
            assert len(rpc('eth_getCode', [contract, tag])) > 2, 'no deployed code'
        assert int(call(USDC, sel('decimals()'), tag), 16) == 6
        assert int(call(WETH, sel('decimals()'), tag), 16) == 18
        pools = {}
        for tier in TIERS:
            result = call(FACTORY, sel('getPool(address,address,uint24)')+address(USDC)+address(WETH)+word(tier), tag)
            assert len(result) == 66
            pool = '0x' + result[-40:]
            pools[str(tier)] = {'address': pool, 'exists': int(pool, 16) != 0}
            if int(pool, 16):
                tokens = [call(pool, sel(f'token{i}()'), tag)[-40:].lower() for i in (0, 1)]
                assert set(tokens) == {USDC[2:].lower(), WETH[2:].lower()}
                assert int(call(pool, sel('fee()'), tag), 16) == tier
        start = time.monotonic()
        for round_i in range(3):
            while time.monotonic() < start + round_i*60:
                time.sleep(min(1, start+round_i*60-time.monotonic()))
            head = rpc('eth_getBlockByNumber', ['latest', False])
            tag = head['number']
            assert 0 <= time.time()-int(head['timestamp'], 16) <= 60, 'stale head'
            round_rows = []
            for a, b in itertools.permutations(TIERS, 2):
                for dollars in (100, 1000):
                    row = {'round': round_i, 'block': tag, 'block_hash': head['hash'], 'first_fee': a, 'second_fee': b, 'input_usdc': dollars, 'actual_pnl': None, 'after_gas_profit': None}
                    try:
                        assert pools[str(a)]['exists'] and pools[str(b)]['exists'], 'missing pool'
                        assert pools[str(a)]['address'] != pools[str(b)]['address'], 'identical pool'
                        amount, gas = decode_quote(call(QUOTER, quote_data(a, b, dollars*10**6), tag))
                        row.update(status='quote_only', output_usdc=str(D(amount)/10**6), surplus_after_pool_fees_before_gas_usdc=str(D(amount)/10**6-D(dollars)), quoter_gas_estimate=gas)
                    except Exception as exc:
                        row.update(status='unknown', error=type(exc).__name__+': '+str(exc)[:500])
                    round_rows.append(row)
            check = rpc('eth_getBlockByNumber', [tag, False])
            valid = check['hash'] == head['hash']
            for row in round_rows:
                row['block_hash_recheck_passed'] = valid
                if not valid:
                    row['status'] = 'unknown_reorg'
            rounds.append({'round': round_i, 'block': tag, 'block_hash_recheck_passed': valid})
            rows.extend(round_rows)
        terminal['status'] = 'completed_fixed_screen'
    except Exception as exc:
        terminal['error'] = type(exc).__name__+': '+str(exc)[:500]
    summary = {'actual_pnl': None, 'gas_not_subtracted': True, 'scope': 'Pool-fee-inclusive same-block eth_call quotes, no execution. Positive pre-gas quotes require separate gas and inclusion investigation. Negative pre-gas quotes already fail a necessary condition.', 'pools': locals().get('pools', {}), 'rounds': rounds, 'rows': rows}
    data = (json.dumps(summary, indent=2)+'\n').encode()
    assert len(data) <= 49152
    (OUT/'summary.json').write_bytes(data)
    terminal['summary_sha256'] = hashlib.sha256(data).hexdigest()
    terminal['ended_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    (OUT/'terminal.json').write_text(json.dumps(terminal, indent=2)+'\n')
    print(json.dumps(terminal))


if __name__ == '__main__':
    if len(sys.argv) == 2 and sys.argv[1] == 'selftest':
        selftest()
    elif len(sys.argv) == 2 and sys.argv[1] == 'run':
        main()
    else:
        print('Use selftest or run explicitly')
