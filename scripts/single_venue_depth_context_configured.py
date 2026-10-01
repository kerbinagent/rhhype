"""Configure the existing adapter for each pinned sample's selected markets."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts import single_venue_depth_context as context
from scripts import single_venue_depth_capture as capture

original=context.adapter.iter_events

def configured(directory,*,expected_manifest_sha256,max_raw_bytes):
    assert context.sha(directory/'manifest.json')==expected_manifest_sha256
    capture.SELECTED=json.loads((directory/'manifest.json').read_bytes())['selected_markets']
    return original(directory,expected_manifest_sha256=expected_manifest_sha256,max_raw_bytes=max_raw_bytes)

if __name__=='__main__':
    repair=json.loads((ROOT/'reports/experiment-storage/single-venue-depth-context-config-v1.json').read_bytes())
    for pin in repair['pins']:assert context.sha(ROOT/pin['path'])==pin['sha256']
    context.adapter.iter_events=configured
    context.main()
