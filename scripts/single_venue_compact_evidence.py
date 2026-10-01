"""Logging-only supplement: hash retained raw depth instead of duplicating it.

No feature, order, size, delay, execution or accounting function is replaced.
The independent auditor retrieves and walks the exact original full raw book.
"""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
import scripts.single_venue_strategy as strategy
import scripts.run_single_venue_study as runner
import scripts.audit_single_venue_study as auditor

def levels_hash(book):
    return hashlib.sha256(json.dumps({k:book[k] for k in ('bids','asks')},
        separators=(',',':'),allow_nan=False).encode()).hexdigest()

def compact_snapshot(book):
    return {**{k:book[k] for k in ('venue','market','received_ns','source_ns','generation','sequence')},
            'levels_sha256':levels_hash(book)}

original_match=auditor.match_book
def match_compact(witness,book):
    if 'levels_sha256' in witness:
        assert witness['levels_sha256']==levels_hash(book)
        original_match({k:v for k,v in witness.items() if k!='levels_sha256'},book)
    else:
        original_match(witness,book)

original_inputs=runner.inputs
def compact_inputs(plan,name,manifest_hash=None):
    return original_inputs(plan,name.removesuffix('-compact'),manifest_hash)

def configure():
    strategy.snapshot=compact_snapshot
    runner.inputs=compact_inputs
    auditor.inputs=compact_inputs
    auditor.match_book=match_compact

def main(action,name,manifest_hash=None):
    supplement=ROOT/'reports/experiment-storage/single-venue-compact-evidence-v1.json'
    for pin in json.loads(supplement.read_bytes())['source_pins']:
        assert runner.sha(ROOT/pin['path'])==pin['sha256']
    configure()
    if action=='replay':runner.main(name,manifest_hash)
    elif action=='audit':auditor.audit(name,manifest_hash)
    else:raise ValueError('replay or audit required')

if __name__=='__main__':main(*sys.argv[1:])
