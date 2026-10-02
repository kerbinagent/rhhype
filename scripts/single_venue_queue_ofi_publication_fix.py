#!/usr/bin/env python3
"""Publication-only successor: unchanged OFI analysis, larger immutable tables.

The first fit table is independently pinned and reused without interpreting or
changing its features or outcomes. Remaining chunks use the frozen original
stream. Every monkeypatch is scoped and restored, including on failure.
"""
from contextlib import contextmanager
import gzip,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts import single_venue_queue_ofi as base
PLAN=ROOT/'reports/experiment-storage/single-venue-queue-ofi-publication-fix-v1.json'
PARENT_PLAN=ROOT/'reports/experiment-storage/single-venue-queue-ofi-v1.json'
PARENT_SHA='27073af951c7d8fd08e24978314e662810d17e0b56645f894b710fbdf11ace70'
PARENT_CAPS=dict(base.CAPS)
CAPS={**PARENT_CAPS,'gzip_per_chunk':524288}
OUTPUT_ROOT='reports/single-venue-research/queue-ofi-publication-fix-v1'
SAVED=dict(chunk='chunk-000001',path='reports/single-venue-research/queue-ofi-v1/chunk-000001.json.gz',
    bytes=219661,sha256='2834825384d8abe5226ee00bda3c444673b88667d464ebc1da413f338ddbc78b',decoded_bytes_cap=16777216)
ORIGINAL_VERIFY=base.verify
ORIGINAL_STREAM=base.stream_chunk

@contextmanager
def parent_configuration():
    old={key:getattr(base,key) for key in ('PLAN','CAPS','verify','stream_chunk')}
    try:
        base.PLAN=PARENT_PLAN;base.CAPS=PARENT_CAPS;base.verify=ORIGINAL_VERIFY;base.stream_chunk=ORIGINAL_STREAM
        yield
    finally:
        for key,value in old.items():setattr(base,key,value)

def saved_identity(saved):
    path=ROOT/saved['path']
    if base.rolling.regular(path)!=saved['bytes'] or base.digest(path)!=saved['sha256']:
        raise ValueError('saved_fit_table_hash_or_size_changed')
    return path

def verify():
    # The exact parent contract and its own direct/transitive source verification
    # are always checked using the original verifier and original globals.
    if base.digest(PARENT_PLAN)!=PARENT_SHA:raise ValueError('frozen_parent_protocol_changed')
    with parent_configuration():parent,validation=ORIGINAL_VERIFY()
    successor=base.rolling.read_json(PLAN,CAPS['protocol'])
    if successor.get('status')!='frozen':raise ValueError('publication_protocol_not_frozen')
    if successor.get('schema')!='single-venue-queue-ofi-publication-fix-v1':raise ValueError('publication_schema_changed')
    if successor.get('parent_plan')!=str(PARENT_PLAN.relative_to(ROOT)) or successor.get('parent_plan_sha256')!=PARENT_SHA:
        raise ValueError('parent_protocol_identity_changed')
    if successor.get('output_root')!=OUTPUT_ROOT or successor.get('output_caps')!=CAPS:
        raise ValueError('publication_paths_or_caps_changed')
    if successor.get('saved_fit_chunk')!=SAVED:raise ValueError('saved_fit_identity_changed')
    # Optional restatements must agree; inherited scientific fields cannot change.
    scientific=('parameters','features','fit_chunks','evaluation_chunks','input_validation_plan',
        'input_validation_plan_sha256','store_root','pin_owner','runtime_requirements','calendar','label',
        'native_quote_profiles','costs','model','decision_policy','evaluation','advance_gate')
    for key in scientific:
        if key in successor and successor[key]!=parent[key]:raise ValueError('inherited_scientific_field_changed '+key)
    direct=successor.get('source_pins',[]);names=[pin['path'] for pin in direct]
    required={'scripts/single_venue_queue_ofi_publication_fix.py','tests/test_single_venue_queue_ofi_publication_fix.py'}
    if len(set(names))!=len(names) or not required.issubset(names):raise ValueError('unique_publication_source_and_test_pins_required')
    base.source_pins(direct);saved_identity(SAVED)
    merged=dict(parent);merged['output_root']=OUTPUT_ROOT;merged['output_caps']=dict(CAPS)
    pins={pin['path']:pin for pin in parent['source_pins']}
    for pin in direct:
        if pin['path'] in pins and pin!=pins[pin['path']]:raise ValueError('conflicting_inherited_source_pin')
        pins[pin['path']]=pin
    merged['source_pins']=list(pins.values())
    return merged,validation

def reuse_fit_chunk(record,saved=SAVED):
    if record['chunk']!=saved['chunk']:raise ValueError('saved_fit_chunk_record_changed')
    path=saved_identity(saved);packed=path.read_bytes()
    with gzip.open(path,'rb') as stream:body=stream.read(saved['decoded_bytes_cap']+1)
    if len(body)>saved['decoded_bytes_cap']:raise ValueError('saved_fit_decoded_byte_cap')
    table=json.loads(body)
    if table.get('chunk')!=record['chunk'] or table.get('scheduled_anchors')!=560 or len(table.get('anchors',[]))!=560:
        raise ValueError('saved_fit_chunk_calendar_changed')
    expected={(a,v,slot) for a in base.ASSETS for v in base.VENUES for slot in range(28)}
    actual=[]
    for row in table['anchors']:
        identity=(row.get('asset'),row.get('venue'),row.get('slot'));actual.append(identity)
        if identity not in expected or row.get('chunk')!=record['chunk']:
            raise ValueError('saved_fit_row_identity_changed')
        due=record['started_ns']+(base.PARAMS['anchor_start_seconds']+row['slot']*base.PARAMS['anchor_step_seconds'])*base.NS
        if row.get('decision_ns')!=due:raise ValueError('saved_fit_calendar_timestamp_changed')
    if len(set(actual))!=560 or set(actual)!=expected:raise ValueError('saved_fit_calendar_denominator_changed')
    adapter=table.get('adapter',{})
    if adapter.get('manifest_sha256')!=record['manifest_sha256'] or adapter.get('raw_gzip_sha256')!=record['raw_sha256']:
        raise ValueError('saved_fit_capture_identity_changed')
    # Reuse has no numerical transformation. The unchanged parent publisher must
    # recreate the exact immutable bytes, not merely equivalent JSON values.
    if gzip.compress(base.encode(table),mtime=0)!=packed:raise ValueError('saved_fit_byte_identity_not_reproducible')
    saved_identity(saved)
    return table

def stream_chunk(record,models=None):
    if record['chunk']==SAVED['chunk']:
        if models is not None:raise ValueError('saved_fit_cannot_be_evaluation')
        return reuse_fit_chunk(record)
    return ORIGINAL_STREAM(record,models=models)

@contextmanager
def execution_configuration():
    old={key:getattr(base,key) for key in ('PLAN','CAPS','verify','stream_chunk')}
    try:
        base.PLAN=PLAN;base.CAPS=CAPS;base.verify=verify;base.stream_chunk=stream_chunk
        yield
    finally:
        for key,value in old.items():setattr(base,key,value)
def run():
    with execution_configuration():base.run()
def main():
    if len(sys.argv)!=2 or sys.argv[1] not in ('verify','run'):
        raise SystemExit('usage: single_venue_queue_ofi_publication_fix.py verify|run')
    globals()[sys.argv[1]]()
if __name__=='__main__':main()
