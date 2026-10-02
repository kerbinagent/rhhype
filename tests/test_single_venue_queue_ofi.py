"""Synthetic OFI, causality, frozen fits and native conditional quote contracts."""
import copy,gzip,json,tempfile,unittest
from contextlib import nullcontext
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch
import numpy as np
from scripts import single_venue_queue_ofi as q

def metadata(assets=('BTC',),fee='2',max_quote='50000'):
    return {v:{a:dict(price_tick='0.01',qty_step='0.001',min_qty='0.001',min_notional='1',
        max_quote=max_quote,max_qty=None,maximum_base_quantity_unknown=True,taker_fee_bps=fee)
        for a in assets} for v in q.VENUES}
def book(t,venue='lighter',bid='100',ask='100.01',bq='500',aq='500',source=None,snapshot=False):
    return dict(type='book',asset='BTC',venue=venue,received_ns=t,source_ns=t if source is None else source,
        generation='g',valid=True,clock_valid=True,bids=[[bid,bq]],asks=[[ask,aq]],book_snapshot=snapshot)
def trade(t,buy=True,qty='1',source=None):
    return dict(type='trade',asset='BTC',venue='lighter',received_ns=t,source_ns=t if source is None else source,
        generation='g',buy_aggressor=buy,qty=qty)
def invalid(t,scope='trade'):
    return dict(type='invalidate',asset='BTC',venue='lighter',received_ns=t,source_ns=None,
        generation='g',scope=scope,reason='synthetic')
def feature(values=None):
    return dict(values=[0.,0.,0.,0.,0.,0.] if values is None else values)
def fitted_chunks(seed=7,constant=False,dependent=False):
    rng=np.random.default_rng(seed);chunks=[]
    for name in q.FIT:
        rows=[]
        for asset in q.ASSETS:
            for venue in q.VENUES:
                X=rng.normal(size=(28,6))
                if constant:X[:,1]=.5
                if dependent:X[:,5]=X[:,3]-X[:,2]
                for slot,x in enumerate(X):
                    rows.append(dict(chunk=name,slot=slot,asset=asset,venue=venue,feature_failure=None,
                        features=feature(x.tolist()),label_status='complete',label=float(2*x[5]-x[0]),profiles=[],policies={}))
        chunks.append(dict(chunk=name,scheduled_anchors=560,anchors=rows))
    return chunks
def evaluation_chunks():
    chunks=[]
    for name in q.EVALUATION:
        rows=[]
        for asset in q.ASSETS:
            for venue in q.VENUES:
                for slot in range(28):
                    profiles=[];policies={}
                    for target in q.PARAMS['notionals']:
                        for side,net in ((1,'2'),(-1,'-1')):
                            profiles.append(dict(target=target,direction=side,status='complete',gross_cash=net,fee_cash='0',capital_cash='0',net_cash=net,net_bps=net,
                                stressed_cash={str(bp):str(D(net)-D(bp)) for bp in (1,2,5)}))
                        for model,direction in (('baseline',-1),('augmented',1)):
                            policies[model+':'+target]=dict(predicted_y=float(direction),direction=direction,admitted=True,status='admitted')
                    rows.append(dict(chunk=name,slot=slot,asset=asset,venue=venue,feature_failure=None,features=feature(),
                        label_status='complete',label=1.,profiles=profiles,policies=policies))
        chunks.append(dict(chunk=name,scheduled_anchors=560,anchors=rows))
    return chunks

class QueueOFITest(unittest.TestCase):
    def test_ofi_exact_telescoping_snapshot_gap_and_hook_restoration(self):
        old=(D(100),D(10),D(101),D(9));new=(D(100),D(14),D(101),D(6))
        self.assertEqual(q.ofi(old,new),D(7))
        self.assertEqual(q.ofi(new,(D(101),D(8),D(102),D(4))),D(14))
        features=q.QueueFeatures(metadata())
        for e in (book(0,bq='10',aq='10',snapshot=True),trade(0),
                  book(q.NS//2,bq='12',aq='9'),book(q.NS,bq='14',aq='6')):features.process(e)
        result,why=features.at('BTC','lighter',q.NS)
        self.assertIsNone(why);self.assertEqual(result['ofi'],'8')
        self.assertAlmostEqual(result['values'][5],result['values'][3]-result['values'][2])
        self.assertTrue(result['all_prices_unchanged'])
        features.process(book(q.NS+1,snapshot=True));self.assertEqual(len(features.state(('BTC','lighter'))['books']),1)
        self.assertEqual(features.at('BTC','lighter',q.NS+2)[1],'missing_start_book')
        features.process(book(2*q.NS));self.assertEqual(len(features.state(('BTC','lighter'))['books']),1)
        features.process(invalid(2*q.NS+1,'book'));self.assertFalse(features.state(('BTC','lighter'))['books'])
        original=(q.ordinary._common,q.ordinary._trade,q.ordinary.MAX_DECODED_BYTES,q.inventory.capture.HARD_BYTES)
        rawrow=dict(venue='lighter',generation='g',receipt_utc_ns=1790944200000000000,channel='order_book',payload={'type':'subscribed/order_book'})
        with self.assertRaisesRegex(RuntimeError,'fixture'):
            with q.adapter_configuration():
                self.assertTrue(q.ordinary._common(rawrow)['book_snapshot'])
                rawrow['payload']['type']='update/order_book';self.assertFalse(q.ordinary._common(rawrow)['book_snapshot'])
                printrow=dict(rawrow,channel='trade',payload={})
                raw=dict(type='trade',market_id=1,is_maker_ask=True,trade_id=1,price='100',size='0.123456789123456789',timestamp=1790944200000)
                self.assertEqual(q.ordinary._trade(printrow,raw,'1','BTC',None)['qty'],'0.123456789123456789')
                raise RuntimeError('fixture')
        self.assertEqual((q.ordinary._common,q.ordinary._trade,q.ordinary.MAX_DECODED_BYTES,q.inventory.capture.HARD_BYTES),original)

    def test_calendar_equal_receipt_causality_and_unknown_stale_trade_windows(self):
        study=q.Study(metadata(),0,'synthetic',assets=('BTC',))
        for e in (book(28*q.NS,snapshot=True),trade(28*q.NS+500000000),book(29*q.NS),book(29*q.NS+500000000)):
            study.process_group([e])
        study.process_group([book(30*q.NS,bq='510'),trade(30*q.NS,buy=False,qty='3')])
        row=study.rows[0];self.assertEqual(row['decision_ns'],30*q.NS);self.assertIsNone(row['feature_failure'])
        self.assertEqual(row['features']['values'][4],-1.)
        self.assertEqual(row['features']['end_received_ns'],30*q.NS)
        frozen=copy.deepcopy(row['features'])
        study.process_group([book(30*q.NS+100000000,bq='520')]);self.assertEqual(row['features'],frozen)
        study.process_group([invalid(30*q.NS+200000000)])
        self.assertTrue(study.pending[('BTC','lighter')]);self.assertIsNone(study.features.state(('BTC','lighter'))['trade_since'])
        study.process_group([book(30*q.NS+400000000)]);self.assertEqual(row['label_status'],'pending_exit')
        study.process_group([dict(type='end',received_ns=600*q.NS)])
        result=study.result();self.assertEqual(result['scheduled_anchors'],56)
        self.assertEqual(len(result['anchors']),56);self.assertEqual(row['label_status'],'unresolved_at_end')
        f=q.QueueFeatures(metadata())
        for e in (book(0,snapshot=True),book(q.NS//2),book(q.NS),trade(q.NS//2)):
            f.process(e)
        self.assertEqual(f.at('BTC','lighter',q.NS)[1],'unknown_trade_history')
        f=q.QueueFeatures(metadata())
        for e in (book(0,snapshot=True),trade(0),book(q.NS//2),book(q.NS),trade(q.NS,source=q.NS-500000001)):f.process(e)
        self.assertEqual(f.at('BTC','lighter',q.NS)[1],'stale_trade_window')
        f=q.QueueFeatures(metadata())
        for e in (book(0,snapshot=True),trade(0),book(q.NS//2),book(q.NS)):f.process(e)
        self.assertTrue(f.at('BTC','lighter',q.NS)[0]['zero_flow'])
        allcells=q.Study(metadata(q.ASSETS),0,'synthetic')
        allcells.process_group([dict(type='end',received_ns=600*q.NS)])
        self.assertEqual(len(allcells.result()['anchors']),560)

    def test_multisize_actual_fees_capital_native_limits_and_first_eligible_final(self):
        m=metadata(max_quote='2000');study=q.Study(m,0,'synthetic',assets=('BTC',));decision=30*q.NS
        for venue in q.VENUES:study.books[('BTC',venue)]=book(decision,venue=venue)
        with patch.object(study.features,'at',return_value=(feature(),None)):study.anchor(decision)
        row=study.rows[0]
        self.assertEqual(len(row['profiles']),6)
        self.assertTrue(all(p['status']=='maximum_quote_reject' for p in row['profiles'] if p['target']=='10000'))
        entry=decision+400000000;exit_time=entry+10400000000
        study.process(book(entry,bid='100.99',ask='101'))
        study.process(book(exit_time,bid='103',ask='103.01'))
        self.assertEqual(row['label_status'],'complete')
        profile=q.profile_for(row,'100',1);self.assertEqual(profile['status'],'complete')
        en,ex=D(profile['entry_value']),D(profile['exit_value'])
        self.assertEqual(D(profile['fee_cash']),(en+ex)*D('2')/10000)
        capital=D(100)*D('.05')*D('10.4')/31536000
        self.assertEqual(D(profile['capital_cash']),capital)
        self.assertEqual(D(profile['net_cash']),ex-en-(en+ex)*D('2')/10000-capital)
        self.assertEqual(D(profile['stressed_cash']['5']),D(profile['net_cash'])-en*D(5)/10000)
        self.assertTrue(profile['maximum_base_quantity_unknown'])
        for failure_book,expected in ((book(entry,bq='.001',aq='.001'),'insufficient_depth'),
                                     (book(entry+2000000001),'missing_first_eligible'),
                                     (book(entry+1000000000,source=entry+700000000),'missing_first_eligible')):
            one=q.Study(metadata(),0,'synthetic',assets=('BTC',));one.books[('BTC','lighter')]=book(decision)
            with patch.object(one.features,'at',return_value=(feature(),None)):one.anchor(decision)
            r=one.rows[0];one.process(failure_book);one.process(book(entry+2100000000))
            self.assertEqual(q.profile_for(r,'100',1)['status'],expected)
        one=q.Study(metadata(),0,'synthetic',assets=('BTC',));one.books[('BTC','lighter')]=book(decision)
        with patch.object(one.features,'at',return_value=(feature(),None)):one.anchor(decision)
        bad=book(entry);bad['asks'].append(['100.019','1']);one.process(bad)
        self.assertEqual(one.rows[0]['label_status'],'endpoint_native_book_failure')
        one=q.Study(metadata(),0,'synthetic',assets=('BTC',));one.books[('BTC','lighter')]=book(decision)
        with patch.object(one.features,'at',return_value=(feature(),None)):one.anchor(decision)
        one.process(book(decision+1,snapshot=True));self.assertEqual(one.rows[0]['label_status'],'snapshot_reset')
        self.assertTrue(q.funding_crosses(3600*q.NS-q.PARAMS['maximum_profile_span_ns']))
        self.assertFalse(q.funding_crosses(3600*q.NS-q.PARAMS['maximum_profile_span_ns']-1))
        limit=metadata()['lighter']['BTC'];limit['max_qty']='.5'
        ps,cost=q.decision_profiles(book(decision),limit)
        self.assertTrue(all(p['status']=='maximum_quantity_reject' for p in ps));self.assertTrue(cost['100']['failure'])

    def test_ols_fit_only_normalization_rank_failures_and_frozen_predictions(self):
        chunks=fitted_chunks(constant=True);model=q.fit_models(chunks);cell=model['cells']['BTC:lighter']
        expected=np.array([r['features']['values'] for c in chunks for r in c['anchors'] if r['asset']=='BTC' and r['venue']=='lighter'])
        np.testing.assert_allclose(cell['means'],expected.mean(axis=0));np.testing.assert_allclose(cell['scales'],expected.std(axis=0))
        self.assertEqual(cell['constant_columns'],[1]);self.assertEqual(cell['models']['augmented']['status'],'available')
        self.assertEqual(len(cell['training_ids']),84)
        frozen=copy.deepcopy(cell);prediction=q.predict(cell,[100,500,200,300,400,600],'augmented')
        self.assertAlmostEqual(prediction,1100.,places=8);self.assertEqual(cell,frozen)
        dependent=q.fit_models(fitted_chunks(dependent=True))['cells']['BTC:lighter']
        self.assertEqual(dependent['models']['baseline']['status'],'available')
        self.assertEqual(dependent['models']['augmented']['status'],'rank_deficient')
        near=fitted_chunks();rng=np.random.default_rng(10)
        for c in near:
            for r in c['anchors']:
                x=r['features']['values'];x[5]=x[3]-x[2]+1e-9*rng.normal()
        ill=q.fit_models(near)['cells']['BTC:lighter']['models']['augmented']
        self.assertEqual(ill['status'],'condition_number_exceeded');self.assertGreater(ill['condition'],1e8)
        too_few=[dict(c,anchors=c['anchors'][:1]) for c in chunks]
        self.assertEqual(q.fit_models(too_few)['cells']['BTC:lighter']['models']['baseline']['status'],'insufficient_training_labels')
        with self.assertRaisesRegex(ValueError,'fit_chunk_identity'):q.fit_models([dict(c,chunk=n) for c,n in zip(chunks,q.EVALUATION)])

    def test_all_policy_denominators_and_baseline_unknown_prevent_advancement(self):
        chunks=evaluation_chunks();models={'cells':{a+':'+v:dict(models={m:dict(status='available') for m in ('baseline','augmented')}) for a in q.ASSETS for v in q.VENUES}}
        summary=q.evaluation_summary(chunks,models)
        self.assertEqual(len(summary['rows']),60)
        selected=next(r for r in summary['rows'] if (r['asset'],r['venue'],r['target'])==('BTC','lighter','100'))
        self.assertEqual(selected['decision'],'exploratory_followup_candidate');self.assertEqual(selected['pooled']['augmented']['scheduled'],84)
        row=chunks[0]['anchors'][0];q.profile_for(row,'100',-1)['status']='unresolved_at_end'
        selected=next(r for r in q.evaluation_summary(chunks,models)['rows'] if (r['asset'],r['venue'],r['target'])==('BTC','lighter','100'))
        self.assertEqual(selected['decision'],'park_or_insufficient_coverage')
        self.assertIsNone(selected['chunks'][0]['all_calendar_cash_delta']);self.assertEqual(selected['chunks'][0]['policies']['baseline']['admitted_unknown'],1)
        row['policies']['baseline:100']['admitted']=False;row['policies']['baseline:100']['status']='nonpositive_predicted_cash'
        observation=q.policy_observation(row,'baseline','100');self.assertEqual(observation['cash'],D(0));self.assertFalse(observation['admitted'])

    def test_one_pipeline_publishes_model_before_eval_and_refuses_bounded_overwrite(self):
        fit=fitted_chunks();evaluation=evaluation_chunks();plan=dict(output_root='reports/single-venue-research/queue-ofi-v1',store_root='synthetic-store',source_pins=[])
        validation={};records={1:dict(inputs=[dict(chunk=c['chunk']) for c in fit]),2:dict(inputs=[dict(chunk=c['chunk']) for c in evaluation])}
        store=type('Store',(),{'locked':lambda self:nullcontext()})()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);protocol=root/'plan.json';protocol.write_text('{}');calls=[]
            def stream(record,models=None):
                calls.append(record['chunk'])
                if models is None:return next(c for c in fit if c['chunk']==record['chunk'])
                out=root/plan['output_root'];published=json.loads((out/'model-sha.json').read_bytes())
                self.assertEqual(published['model_sha256'],q.digest(out/'model.json'))
                return next(c for c in evaluation if c['chunk']==record['chunk'])
            with patch.object(q,'ROOT',root),patch.object(q,'PLAN',protocol),patch.object(q,'verify',return_value=(plan,validation)),patch.object(q.rolling,'Store',return_value=store),patch.object(q.inventory,'check_inputs',side_effect=lambda s,p,b:records[b]),patch.object(q,'stream_chunk',side_effect=stream),patch.object(q,'fit_models',wraps=q.fit_models) as fitted:
                q.run();self.assertEqual(calls,list(q.FIT+q.EVALUATION));self.assertEqual(fitted.call_count,1)
                out=root/plan['output_root'];self.assertLessEqual((out/'model.json').stat().st_size,q.CAPS['model'])
                self.assertTrue(json.loads((out/'terminal.json').read_bytes())['success'])
                self.assertEqual(len(json.loads(gzip.decompress((out/'summary.json.gz').read_bytes()))['rows']),60)
                with self.assertRaises(FileExistsError):q.run()
                bounded=root/'bounded.json'
                with self.assertRaisesRegex(ValueError,'output_byte_cap'):q.publish(bounded,{'value':'large'},3)
                with self.assertRaisesRegex(ValueError,'decoded_output_byte_cap'):q.publish(bounded,{'value':'x'*1000},1000,compressed=True,decoded_cap=100)
                self.assertFalse(bounded.exists());q.publish(bounded,{},20)
                with self.assertRaises(FileExistsError):q.publish(bounded,{},20)
        frozen=dict(status='frozen',schema='single-venue-queue-ofi-v1',parameters=q.PARAMS,output_caps=q.CAPS,
            fit_chunks=list(q.FIT),evaluation_chunks=list(q.EVALUATION),features={'baseline':list(q.FEATURES[:5])},
            output_root='reports/single-venue-research/queue-ofi-v1',store_root='data/rolling/market-research-v1',pin_owner='inventory_context_v1',
            runtime_requirements={'python':'3.13.9','numpy':'2.5.3'},source_pins=[])
        with patch.object(q.rolling,'read_json',return_value=frozen),patch.object(q,'source_pins') as pins:
            with self.assertRaisesRegex(ValueError,'unique_own'):q.verify()
            frozen['source_pins']=[dict(path='scripts/single_venue_queue_ofi.py',sha256='x')]*2+[dict(path='tests/test_single_venue_queue_ofi.py',sha256='x')]
            with self.assertRaisesRegex(ValueError,'unique_own'):q.verify()
            frozen['status']='draft_not_runnable'
            with self.assertRaisesRegex(ValueError,'not_frozen'):q.verify()
            pins.assert_not_called()

if __name__=='__main__':unittest.main()
