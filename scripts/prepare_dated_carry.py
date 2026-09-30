#!/usr/bin/env python3
"""Exactly two fresh public instrument requests; write price-independent launch config."""
import argparse
import asyncio
import gzip
import json
from pathlib import Path
import time

import aiohttp

try:
    from scripts import dated_carry_collector as collector
    from scripts import dated_carry_analysis as analysis
except ModuleNotFoundError:
    import dated_carry_collector as collector
    import dated_carry_analysis as analysis


async def prepare(args):
    t0_ns = collector.timestamp(args.t0_utc)
    if t0_ns % 10**9:
        raise ValueError('whole_second_t0_required')
    if t0_ns <= time.time_ns() + 30_000_000_000:
        raise ValueError('t0_must_allow_metadata_and_launch')
    root = collector.ROOT
    study = args.study_dir.resolve()
    store = collector.Store(study)
    pins = json.loads(collector.read(args.source_pins, 131072))
    for name, sha in pins.items():
        if collector.digest(collector.read(collector.relative_path(name), 1 << 20)) != sha:
            raise ValueError('source_pin_mismatch')
    store.external['source_control'] = sum((root / p).stat().st_size for p in pins
                                          if not (root / p).is_relative_to(study))
    store.write('metadata', 'fresh-request-claim.json', collector.body({
        'started_utc_ns': time.time_ns(), 'maximum_requests': 2, 'retries': False}))
    payloads = {}
    received = []
    async with aiohttp.ClientSession(trust_env=False, auto_decompress=False, cookie_jar=aiohttp.DummyCookieJar(),
                                     headers={'Accept-Encoding': 'identity'},
                                     timeout=aiohttp.ClientTimeout(total=20)) as session:
        if not hasattr(session, '_retry_connection'):
            raise ValueError('aiohttp_retry_control_unavailable')
        session._retry_connection = False
        for role, currency, kind in [('future', 'USDC', 'future'), ('spot', 'BTC', 'spot')]:
            provenance = {'role': role, 'started_utc_ns': time.time_ns(), 'status': 'failed',
                          'url': 'https://www.deribit.com/api/v2/public/get_instruments',
                          'params': {'currency': currency, 'kind': kind, 'expired': 'false', 'extended': 'true'}}
            try:
                async with session.get(provenance['url'], params=provenance['params'], allow_redirects=False) as response:
                    data = bytearray()
                    async for chunk in response.content.iter_chunked(8192):
                        if len(data) + len(chunk) > 1 << 20:
                            raise ValueError('metadata_response_cap')
                        data.extend(chunk)
                    provenance.update(http_status=response.status, received_utc_ns=time.time_ns(),
                                      received_monotonic_ns=time.monotonic_ns())
                    packed = gzip.compress(bytes(data), mtime=0)
                    store.write('metadata', f'fresh-{role}.json.gz', packed)
                    provenance.update(raw_bytes=len(data), sha256=collector.digest(packed), compressed_bytes=len(packed))
                    if response.status != 200:
                        raise ValueError('metadata_http_status')
                    payload = json.loads(data)
                    if not isinstance(payload, dict) or payload.get('error') or payload.get('jsonrpc') != '2.0':
                        raise ValueError('metadata_rpc_error')
                    payloads[role] = payload
                    received.append({'role': role, 'utc_ns': provenance['received_utc_ns'],
                                     'monotonic_ns': provenance['received_monotonic_ns']})
                    provenance['status'] = 'complete'
            except Exception as exc:
                provenance['error'] = f'{type(exc).__name__}: {str(exc)[:512]}'
                raise
            finally:
                store.write('metadata', f'fresh-{role}-provenance.json', collector.body(provenance))
    activation = t0_ns // 10**9
    markets = analysis.select_markets(payloads['future'], payloads['spot'], activation)
    metadata = {str(path.relative_to(root)): collector.digest(path.read_bytes())
                for path in sorted((study / 'metadata').iterdir()) if path.is_file()}
    config = {'schema': 'dated-carry-collector-config-v1', 't0_utc': args.t0_utc,
              'instruments': {role: market['instrument_name'] for role, market in markets.items()},
              'markets': markets, 'expiry_utc': markets['future']['expiration_timestamp'] // 1000,
              'fees': {'spot_taker': str(markets['spot']['taker_commission']),
                       'future_taker': str(markets['future']['taker_commission']), 'delivery_proxy': '0.00025'},
              'source_sha256': pins, 'metadata_sha256': metadata,
              'metadata_receipts': received,
              'private_execution_verified': False, 'all_in_headroom_usd': None}
    for name, sha in pins.items():
        if collector.digest(collector.read(collector.relative_path(name), 1 << 20)) != sha:
            raise ValueError('source_changed_during_metadata')
    path = store.write('source_control', 'config.json', collector.body(config))
    print(json.dumps({'config': str(path), 'sha256': collector.digest(path.read_bytes()),
                      'instruments': config['instruments'], 't0_utc': args.t0_utc}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fresh', action='store_true')
    parser.add_argument('--study-dir', type=Path)
    parser.add_argument('--source-pins', type=Path)
    parser.add_argument('--t0-utc')
    args = parser.parse_args()
    if not args.fresh:
        print('{"mode":"dry","network_performed":false}')
        return
    if not all((args.study_dir, args.source_pins, args.t0_utc)):
        parser.error('study-dir/source-pins/t0-utc required')
    asyncio.run(prepare(args))


if __name__ == '__main__':
    main()
