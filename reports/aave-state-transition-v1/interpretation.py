"""Post-hoc arithmetic and nested ABI decoding of already admitted evidence."""
import hashlib
import json
from decimal import Decimal, getcontext
from pathlib import Path
from Crypto.Hash import keccak

BASE = Path(__file__).resolve().parent
getcontext().prec = 50


def load(name, digest):
    raw = (BASE/name).read_bytes()
    assert len(raw) < 16384 and hashlib.sha256(raw).hexdigest() == digest
    return json.loads(raw)


def selector(signature):
    return keccak.new(digest_bits=256, data=signature.encode()).digest()[:4]


def word(data, index):
    part = data[index*32:(index+1)*32]
    assert len(part) == 32
    return int.from_bytes(part, 'big')


def dynamic_bytes(data, offset):
    assert offset % 32 == 0 and offset+32 <= len(data)
    length = word(data[offset:], 0)
    end = offset+32+((length+31)//32)*32
    assert end <= len(data) and not any(data[offset+32+length:end])
    return data[offset+32:offset+32+length], end


def signed192(value):
    signed = value-2**256 if value >= 2**255 else value
    assert -2**191 <= signed < 2**191
    return signed


def main():
    projection = load('run-v1/projection.json', '76ddae0e183cdfb65b9e1413179fea839c17f675291305fc752a0ce723df3a47')
    request_raw = (BASE/'run-v1/raw/11.request.json').read_bytes()
    assert len(request_raw) < 8192
    request = json.loads(request_raw)
    call = request['request']['params'][0]['blockStateCalls'][0]['calls'][0]
    payload = bytes.fromhex(call['input'][2:])
    assert payload[:4] == selector('forward(address,bytes)')
    data = payload[4:]
    assert word(data, 0) < 2**160 and word(data, 1) == 64
    feed = '0x'+data[12:32].hex()
    inner, end = dynamic_bytes(data, 64)
    assert end == len(data)
    assert inner[:4] == selector('transmitSecondary(bytes32[3],bytes,bytes32[],bytes32[],bytes32)')
    args = inner[4:]
    assert word(args, 3) == 224
    report, end = dynamic_bytes(args, 224)
    for index in (4, 5):
        offset = word(args, index)
        assert offset == end and offset+32 <= len(args)
        count = word(args[offset:], 0)
        assert count <= 32
        end = offset+32+32*count
    assert end == len(args)
    assert word(report, 0) < 2**32 and word(report, 2) == 128
    signed192(word(report, 3))
    count = word(report[128:], 0)
    assert 0 < count <= 32 and len(report) == 160+count*32
    observations = [signed192(word(report, 5+i)) for i in range(count)]
    assert observations == sorted(observations)
    median = observations[count//2]
    before, after = projection['without_prefix'], projection['with_prefix']
    assert str(median) == projection['observed_prefix_answer_raw'] == after['collateral_price_raw']
    assert feed == projection['observed_prefix_answer_emitter']
    d = Decimal
    result = dict(schema='aave-state-transition-interpretation-v1', post_hoc=True,
        projection_sha256='76ddae0e183cdfb65b9e1413179fea839c17f675291305fc752a0ce723df3a47',
        prefix_request_sha256=hashlib.sha256(request_raw).hexdigest(),
        price_change_percent=str((d(after['collateral_price_raw'])/d(before['collateral_price_raw'])-1)*100),
        health_buffer_before_percent=str((d(before['health']['health_factor_wad'])/10**18-1)*100),
        health_shortfall_after_percent=str((1-d(after['health']['health_factor_wad'])/10**18)*100),
        forward_destination=feed, outer_selector='0x'+payload[:4].hex(), inner_selector='0x'+inner[:4].hex(),
        report_observations_timestamp=word(report, 0), report_observation_count=count,
        sorted_observations_raw=list(map(str,observations)), report_median_raw=str(median),
        source_signature_reference='https://docs.chain.link/data-feeds/svr-feeds/searcher-onboarding-ethereum',
        selector_and_abi_match_is_not_runtime_identity=True, historical_hint_observed=False,
        actual_auction_path_identified=False, economics=False)
    print(json.dumps(result,sort_keys=True,separators=(',',':')))


if __name__ == '__main__':
    main()
