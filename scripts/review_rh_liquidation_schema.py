"""Classify archived RH liquidation arrays; never reconstruct books or economics."""
import argparse
import gzip
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOCATION = ROOT / 'reports/experiment-storage/rh-liquidation-schema-review-allocation-v1.json'
OUT = ROOT / 'reports/rh-liquidation-schema-review.json'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def scan(spec, limits):
    directory = ROOT / ('data/raw/maker-capture/20260929T' + spec['name'])
    mp = directory / 'manifest.json'
    manifest = json.loads(mp.read_bytes())
    require(digest(mp) == spec['manifest_sha256'], 'manifest changed')
    markets = {str(v): k for k, v in manifest['selected_markets']['rh_lighter'].items()}
    started = datetime.fromisoformat(manifest['started_utc'])
    delta = started - datetime(1970, 1, 1, tzinfo=started.tzinfo)
    start_ns = (delta.days * 86400 + delta.seconds) * 1000000000 + delta.microseconds * 1000
    counts = Counter()
    groups = {}
    seen = {}
    records = expanded = 0
    last_receipt = None
    raw = directory / 'frames.jsonl.gz'
    with gzip.open(raw, 'rb') as f:
        while True:
            line = f.readline(limits['line_bytes'] + 1)
            if not line:
                break
            require(len(line) <= limits['line_bytes'] and line.endswith(b'\n'), 'line bound')
            expanded += len(line)
            records += 1
            require(expanded <= limits['decoded_bytes_each'] and records <= spec['decoded_records'], 'decode bound')
            row = json.loads(line)
            require(isinstance(row, dict), 'record shape')
            receipt = row.get('receipt_utc_ns')
            require(type(receipt) is int and (last_receipt is None or receipt >= last_receipt), 'receipt order')
            last_receipt = receipt
            if row.get('kind') != 'frame' or row.get('venue') != 'rh_lighter' or row.get('channel') != 'trade':
                continue
            market = str(row.get('market'))
            require(market in markets, 'unknown RH market')
            p = row.get('payload')
            require(isinstance(p, dict), 'payload shape')
            stage = p.get('type')
            require(stage in ('subscribed/trade', 'update/trade'), 'unknown trade stage')
            ordinary, liquidations = p.get('trades'), p.get('liquidation_trades')
            require(isinstance(ordinary, list) and isinstance(liquidations, list), 'trade arrays')
            counts[stage + ':frames'] += 1
            counts[stage + ':ordinary_rows'] += len(ordinary)
            counts[stage + ':liquidation_rows'] += len(liquidations)
            for trade in liquidations:
                require(isinstance(trade, dict), 'liquidation shape')
                tid, timestamp = trade.get('trade_id'), trade.get('timestamp')
                require(type(tid) is int and type(timestamp) is int, 'liquidation id/time')
                require(str(trade.get('market_id')) == market, 'liquidation market')
                kind = trade.get('type')
                require(isinstance(kind, str) and len(kind) <= 40, 'liquidation kind')
                identity = row.get('generation'), market, tid
                fingerprint = json.dumps(trade, sort_keys=True, separators=(',', ':'))
                require(len(fingerprint) <= 8192, 'liquidation record bound')
                duplicate = identity in seen
                require(not duplicate or seen[identity] == fingerprint, 'conflicting liquidation identity')
                seen[identity] = fingerprint
                require(len(seen) <= limits['liquidation_ids'], 'identity bound')
                key = markets[market], stage, kind
                g = groups.setdefault(key, Counter())
                g['rows'] += 1
                g['duplicate_global_identity'] += duplicate
                g['source_before_capture_start'] += timestamp * 1000000 < start_ns
                g['source_after_receipt'] += timestamp * 1000000 > receipt
                for field in ('ask_id', 'bid_id'):
                    value = trade.get(field)
                    g[field + ('_zero' if value == 0 else '_nonzero' if type(value) is int and value > 0 else '_other')] += 1
    require(records == spec['decoded_records'], 'terminal record count')
    require(sum(g['rows'] for g in groups.values()) == spec['expected_ignored_liquidation_rows'], 'prior ignored count')
    return {'archive': spec['name'], 'records': records, 'decoded_bytes': expanded,
            'gzip_eof': True, 'counts': dict(counts), 'unique_liquidation_ids': len(seen),
            'groups': [dict(asset=k[0], message_stage=k[1], trade_type=k[2], **v) for k, v in sorted(groups.items())]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    if not args.run:
        print('Dry plan: classify only RH liquidation subscription/update arrays in two frozen archives.')
        return
    require(not OUT.exists(), 'output already exists')
    allocation_bytes = ALLOCATION.read_bytes()
    a = json.loads(allocation_bytes)
    require(digest(Path(__file__)) == a['script_sha256'], 'script changed')
    paths = [ROOT / ('data/raw/maker-capture/20260929T' + s['name']) / 'frames.jsonl.gz' for s in a['archives']]
    for p, spec in zip(paths, a['archives']):
        require(p.stat().st_size == spec['compressed_bytes'] and digest(p) == spec['raw_sha256'], 'raw admission')
    result = {'status': 'complete_classification_only', 'script_sha256': a['script_sha256'],
              'economic_calculations': False, 'maker_eligibility_inferred': False,
              'archives': [scan(s, a['bounds']) for s in a['archives']]}
    for p, spec in zip(paths, a['archives']):
        require(digest(p) == spec['raw_sha256'], 'raw changed before publication')
        mp = p.parent / 'manifest.json'
        require(digest(mp) == spec['manifest_sha256'], 'manifest changed before publication')
    require(ALLOCATION.read_bytes() == allocation_bytes and digest(Path(__file__)) == a['script_sha256'], 'freeze changed')
    b = (json.dumps(result, indent=2) + '\n').encode()
    require(len(b) <= a['bounds']['output_bytes'], 'output bound')
    with OUT.open('xb') as f:
        f.write(b)
    print(b.decode())


if __name__ == '__main__':
    main()
