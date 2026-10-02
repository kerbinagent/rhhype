"""Synthetic publication successor contracts; never inspect research tables."""
import copy,gzip,json,tempfile,unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch
from scripts import single_venue_queue_ofi_publication_fix as fix
base=fix.base

def synthetic_table(chunk='chunk-000001',started=1000000000):
    rows=[]
    for asset in base.ASSETS:
        for venue in base.VENUES:
            for slot in range(28):
                rows.append(dict(chunk=chunk,asset=asset,venue=venue,slot=slot,
                    decision_ns=started+(30+20*slot)*base.NS,features=None,
                    feature_failure='synthetic_missing',label_status='feature_unavailable',label=None,profiles=[],policies={}))
    return dict(chunk=chunk,scheduled_anchors=560,anchors=rows,adapter={'manifest_sha256':'manifest','raw_gzip_sha256':'raw'})
def fixture(root,table=None):
    table=synthetic_table() if table is None else table
    path=root/'saved.json.gz';packed=gzip.compress(base.encode(table),mtime=0);path.write_bytes(packed)
    saved=dict(chunk='chunk-000001',path='saved.json.gz',bytes=len(packed),sha256=base.digest(path),decoded_bytes_cap=16777216)
    record=dict(chunk='chunk-000001',started_ns=1000000000,manifest_sha256='manifest',raw_sha256='raw')
    return saved,record,packed

class PublicationFixTest(unittest.TestCase):
    def test_configuration_restores_every_global_after_run_or_parent_error(self):
        original={key:getattr(base,key) for key in ('PLAN','CAPS','verify','stream_chunk')}
        def failed_run():
            self.assertEqual(base.PLAN,fix.PLAN);self.assertEqual(base.CAPS['gzip_per_chunk'],524288)
            self.assertIs(base.verify,fix.verify);self.assertIs(base.stream_chunk,fix.stream_chunk)
            with fix.parent_configuration():
                self.assertEqual(base.PLAN,fix.PARENT_PLAN);self.assertEqual(base.CAPS['gzip_per_chunk'],262144)
                self.assertIs(base.verify,fix.ORIGINAL_VERIFY)
            self.assertIs(base.verify,fix.verify)
            raise RuntimeError('fixture')
        with patch.object(base,'run',side_effect=failed_run):
            with self.assertRaisesRegex(RuntimeError,'fixture'):fix.run()
        self.assertEqual({key:getattr(base,key) for key in original},original)
        with patch.object(base,'digest',return_value=fix.PARENT_SHA),patch.object(fix,'ORIGINAL_VERIFY',side_effect=RuntimeError('parent')):
            with self.assertRaisesRegex(RuntimeError,'parent'):fix.verify()
        self.assertEqual({key:getattr(base,key) for key in original},original)

    def test_exact_parent_and_unique_direct_pins_reject_changes_or_omission(self):
        parent=dict(parameters=copy.deepcopy(base.PARAMS),source_pins=[dict(path='scripts/single_venue_queue_ofi.py',sha256='parent-source')],output_root='old')
        successor=dict(status='frozen',schema='single-venue-queue-ofi-publication-fix-v1',
            parent_plan=str(fix.PARENT_PLAN.relative_to(fix.ROOT)),parent_plan_sha256=fix.PARENT_SHA,
            output_root=fix.OUTPUT_ROOT,output_caps=fix.CAPS,saved_fit_chunk=fix.SAVED,
            source_pins=[dict(path='scripts/single_venue_queue_ofi_publication_fix.py',sha256='new-source'),
                         dict(path='tests/test_single_venue_queue_ofi_publication_fix.py',sha256='new-test')])
        with patch.object(base,'digest',return_value='changed'),patch.object(fix,'ORIGINAL_VERIFY') as original:
            with self.assertRaisesRegex(ValueError,'parent_protocol_changed'):fix.verify()
            original.assert_not_called()
        with patch.object(base,'digest',side_effect=FileNotFoundError('parent')):
            with self.assertRaises(FileNotFoundError):fix.verify()
        with patch.object(base,'digest',return_value=fix.PARENT_SHA),patch.object(fix,'ORIGINAL_VERIFY',return_value=(parent,{'validation':'same'})),patch.object(base.rolling,'read_json',return_value=successor),patch.object(base,'source_pins') as pins,patch.object(fix,'saved_identity'):
            merged,validation=fix.verify();self.assertEqual(merged['parameters'],base.PARAMS)
            self.assertEqual(merged['output_root'],fix.OUTPUT_ROOT);self.assertEqual(merged['output_caps'],fix.CAPS)
            self.assertEqual(len(merged['source_pins']),3);self.assertEqual(validation,{'validation':'same'})
            self.assertEqual(parent['output_root'],'old')
            successor['source_pins']=successor['source_pins'][:1]
            with self.assertRaisesRegex(ValueError,'unique_publication'):fix.verify()
            successor['source_pins']*=2
            with self.assertRaisesRegex(ValueError,'unique_publication'):fix.verify()
            successor['status']='draft_not_runnable'
            with self.assertRaisesRegex(ValueError,'not_frozen'):fix.verify()
            successor['status']='frozen';successor['parameters']={**base.PARAMS,'hold_ns':1}
            with self.assertRaisesRegex(ValueError,'scientific_field'):fix.verify()
            self.assertEqual(pins.call_count,1)

    def test_saved_gzip_hash_bounds_calendar_and_exact_byte_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);saved,record,packed=fixture(root)
            with patch.object(fix,'ROOT',root):
                result=fix.reuse_fit_chunk(record,saved)
                self.assertEqual(gzip.compress(base.encode(result),mtime=0),packed)
                self.assertEqual(len(result['anchors']),560)
                (root/saved['path']).write_bytes(packed[:-1]+b'x')
                with self.assertRaisesRegex(ValueError,'hash_or_size'):fix.reuse_fit_chunk(record,saved)
                (root/saved['path']).write_bytes(packed)
                with self.assertRaisesRegex(ValueError,'decoded_byte_cap'):fix.reuse_fit_chunk(record,{**saved,'decoded_bytes_cap':100})
                with self.assertRaisesRegex(ValueError,'capture_identity'):fix.reuse_fit_chunk({**record,'raw_sha256':'changed'},saved)
                table=synthetic_table();table['anchors'][0]['decision_ns']+=1
                bad,_,_=fixture(root,table)
                with self.assertRaisesRegex(ValueError,'calendar_timestamp'):fix.reuse_fit_chunk(record,bad)
                table=synthetic_table();table['anchors'][0]=table['anchors'][1]
                bad,_,_=fixture(root,table)
                with self.assertRaisesRegex(ValueError,'calendar_denominator'):fix.reuse_fit_chunk(record,bad)

    def test_unchanged_pipeline_reuses_first_bytes_and_inherits_model_barrier(self):
        original={key:getattr(base,key) for key in ('PLAN','CAPS','verify','stream_chunk')}
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);saved,first,packed=fixture(root)
            plan_path=root/'successor.json';plan_path.write_text('{}')
            parent_path=root/'parent.json';parent_path.write_text('{}')
            plan=dict(output_root='new-output',store_root='synthetic-store',source_pins=[])
            records={1:dict(inputs=[first]+[dict(first,chunk=n) for n in base.FIT[1:]]),
                     2:dict(inputs=[dict(first,chunk=n) for n in base.EVALUATION])}
            store=type('Store',(),{'locked':lambda self:nullcontext()})();calls=[]
            original_reuse=fix.reuse_fit_chunk
            def remaining(record,models=None):
                calls.append(record['chunk'])
                if record['chunk'] in base.EVALUATION:
                    self.assertIsNotNone(models)
                    out=root/plan['output_root'];manifest=json.loads((out/'model-sha.json').read_bytes())
                    self.assertEqual(manifest['model_sha256'],base.digest(out/'model.json'))
                    self.assertEqual(models['plan_sha256'],base.digest(plan_path))
                else:self.assertIsNone(models)
                return synthetic_table(record['chunk'])
            with patch.object(base,'ROOT',root),patch.object(fix,'ROOT',root),patch.object(fix,'PLAN',plan_path),patch.object(fix,'PARENT_PLAN',parent_path),patch.object(fix,'SAVED',saved),patch.object(fix,'verify',return_value=(plan,{})),patch.object(fix,'ORIGINAL_STREAM',side_effect=remaining),patch.object(fix,'reuse_fit_chunk',side_effect=lambda r:original_reuse(r,saved)),patch.object(base.rolling,'Store',return_value=store),patch.object(base.inventory,'check_inputs',side_effect=lambda s,p,b:records[b]),patch.object(base,'fit_models',return_value={'cells':{}}) as fitted,patch.object(base,'evaluation_summary',return_value={'rows':[]}):
                fix.run();self.assertEqual(calls,list(base.FIT[1:]+base.EVALUATION));self.assertEqual(fitted.call_count,1)
                out=root/plan['output_root'];self.assertEqual((out/'chunk-000001.json.gz').read_bytes(),packed)
                for name in ('started.json','model.json','provenance.json','terminal.json'):
                    self.assertEqual(json.loads((out/name).read_bytes())['plan_sha256'],base.digest(plan_path))
                self.assertTrue(json.loads((out/'terminal.json').read_bytes())['success'])
                with self.assertRaises(FileExistsError):fix.run()
        self.assertEqual({key:getattr(base,key) for key in original},original)

if __name__=='__main__':unittest.main()
