"""Synthetic contracts for causal, fixed-cohort cross-asset OFI evaluation.

No retained market tables or archives are opened by these tests.
"""
import copy
from decimal import Decimal as D
import unittest

import numpy as np

from scripts import peer_cross_asset_ofi as q


NS = 10**9
VENUES = ('lighter', 'rh_lighter')
TARGETS = ('ETH', 'SOL', 'HYPE', 'XRP', 'SUI', 'NEAR', 'ZEC', 'VVV', 'LIT')
CHUNKS = tuple(f'chunk-{i:06d}' for i in (1, 2, 3, 7, 8, 9))
TRAIN = CHUNKS[:3]
APPLY = CHUNKS[3:]
CELLS = {f'{asset}:{venue}' for asset in TARGETS for venue in VENUES}
NOTIONALS = ('100', '1000', '10000')


def feature(values, when, generation):
    values = [float(x) for x in values]
    amount = D(str(values[5])) * D(100)
    return dict(values=values, depth_start='100', ofi=str(amount),
        unchanged_price_ofi='0', price_changing_ofi=str(amount),
        zero_flow=False, zero_ofi=amount == 0, all_prices_unchanged=False,
        start_received_ns=when-NS, start_source_ns=when-NS,
        end_received_ns=when, end_source_ns=when, generation=generation)


def set_ofi(row, value):
    f = row['features']; f['values'][5] = float(value)
    amount = D(str(value)) * D(f['depth_start'])
    f.update(ofi=str(amount), unchanged_price_ofi='0',
        price_changing_ofi=str(amount), zero_ofi=amount == 0)


def install_quotes(row, label=1, fee_bps=0):
    row.update(label_status='complete', label=float(label), profiles=[],
        decision_costs={}, policies={})
    for size in NOTIONALS:
        n = D(size); fee = n * D(str(fee_bps))/10000
        row['decision_costs'][size] = dict(failure=None, quantity=str(n/100),
            mid='100', spread_cash='0', estimated_fee_cash=str(fee),
            estimated_capital_cash='0')
        for side in (1, -1):
            gross = n * D(str(label)) * side / 10000
            net = gross-fee
            row['profiles'].append(dict(target=size, direction=side,
                quantity=str(n/100), status='complete', gross_cash=str(gross),
                fee_cash=str(fee), capital_cash='0', net_cash=str(net),
                net_bps=str(net/n*10000), entry_value=str(n),
                exit_value=str(n+gross*side),
                stressed_cash={str(bp):str(net-n*bp/10000) for bp in (1, 2, 5)}))


def tables(seed=193):
    """Full-rank features, with a genuinely independent BTC OFI innovation."""
    rng = np.random.default_rng(seed); out=[]
    for chunk in CHUNKS:
        number = int(chunk[-6:]); start=(number*3600+100)*NS
        rows=[]
        for slot in range(28):
            when=start+(30+20*slot)*NS
            for venue in VENUES:
                btc=None
                for asset in ('BTC',)+TARGETS:
                    ret, imbalance, first, total, trade = (
                        rng.uniform(-4, 4), rng.uniform(-.5, .5),
                        rng.uniform(-1, 1), rng.uniform(1, 3), rng.uniform(-1, 1))
                    current=imbalance*total
                    flow=current-first+rng.normal()
                    if asset == 'BTC' and chunk in APPLY:
                        flow=1+slot/100
                    values=[ret, imbalance, first, current, trade, flow]
                    generation=f'{chunk}:{venue}:{asset}'
                    row=dict(chunk=chunk, slot=slot, asset=asset, venue=venue,
                        decision_ns=when, generation=generation,
                        feature_failure=None, features=feature(values,when,generation))
                    if asset == 'BTC':btc=values
                    y=.5*ret+20*btc[5]
                    install_quotes(row,y)
                    rows.append(row)
        out.append(dict(chunk=chunk, scheduled_anchors=560, anchors=rows,
            feature_counts={}))
    return out


def find(chunks, chunk, asset='ETH', venue='lighter', slot=0):
    return next(row for table in chunks if table['chunk']==chunk
        for row in table['anchors'] if (row['asset'],row['venue'],row['slot'])
        == (asset,venue,slot))


def quoted_profile(row, size='100', side=1):
    return next(p for p in row['profiles'] if (p['target'],p['direction'])==(size,side))


class OutcomeTripwire(dict):
    """Reading a future field is an observable failure, even when it is null."""
    forbidden=frozenset(('label','label_status','profiles','policies','entry','exit'))
    def __getitem__(self,key):
        if key in self.forbidden:raise AssertionError('future field read: '+key)
        return super().__getitem__(key)
    def get(self,key,*args):
        if key in self.forbidden:raise AssertionError('future field read: '+key)
        return super().get(key,*args)
    def __contains__(self,key):
        if key in self.forbidden:raise AssertionError('future field read: '+key)
        return super().__contains__(key)


def poison_outcomes(chunks):
    for table in chunks:
        table['anchors']=[OutcomeTripwire(row) for row in table['anchors']]


def fixed_models(data,pre):
    """Stored synthetic coefficients give known +4/-4 bp candidate/reference."""
    models=q.fit_models(data,pre)
    for cell in models['cells'].values():
        for name,width,intercept in (('M0',6,-4),('M1',11,-4),('M2',12,4)):
            cell['models'][name]['coefficients']=[intercept]+[0.]*width
    return models


def fixed_forecast_fixture():
    data=tables();pre=q.feature_preflight(data);models=fixed_models(data,pre)
    for chunk in data[3:]:
        for row in chunk['anchors']:install_quotes(row,1)
    return data,pre,models


def economic_block(result, chunk=APPLY[0], venue='lighter', size='100'):
    return next(r for r in result['economics']['rows']
        if (r['chunk'],r['venue'],r['native_notional'])==(chunk,venue,size))


class CrossAssetOFITest(unittest.TestCase):
    def test_exact_six_calendars_and_same_venue_identity_joins(self):
        data=tables(); indexed=q.validate_tables(data)
        self.assertEqual(set(indexed),set(CHUNKS))
        self.assertTrue(all(len(rows)==560 for rows in indexed.values()))
        target=find(data,TRAIN[0]); leader=find(data,TRAIN[0],'BTC')
        vector,why=q.feature_vector(target,leader)
        self.assertIsNone(why)
        self.assertEqual(vector,target['features']['values']+leader['features']['values'])
        for changes in ({'venue':'rh_lighter'}, {'chunk':TRAIN[1]}, {'slot':1},
                        {'decision_ns':target['decision_ns']+1}):
            with self.subTest(join=changes):
                wrong=dict(leader,**changes)
                self.assertIsNone(q.feature_vector(target,wrong)[0])
        for mutation in ('missing','duplicate','wrong_time','wrong_chunk'):
            with self.subTest(calendar=mutation):
                bad=copy.deepcopy(data)
                if mutation=='missing':bad[0]['anchors'].pop()
                elif mutation=='duplicate':bad[0]['anchors'][-1]=copy.deepcopy(bad[0]['anchors'][0])
                elif mutation=='wrong_time':bad[0]['anchors'][0]['decision_ns']+=1
                else:bad[-1]['chunk']='chunk-000010'
                with self.assertRaises(ValueError):q.validate_tables(bad)
        records=[dict(chunk=name,path='synthetic/'+name+'.json.gz',bytes=1,
            role='fit' if name in TRAIN else 'application',
            started_ns=(int(name[-6:])*3600+100)*NS,
            ended_ns=(int(name[-6:])*3600+700)*NS) for name in CHUNKS]
        inventory=dict(schema='peer-shared-ofi-input-inventory-v1',tables=records,
            table_gzip_cap_bytes=q.CAPS['table_gzip_bytes'],
            table_decoded_cap_bytes=q.CAPS['table_decoded_bytes'],
            rows_per_table=560,rows_per_cell=28,total_table_bytes=6,
            producer_protocol={'path':q.PRODUCER_PROTOCOL_PATH},
            producer_source={'path':q.PRODUCER_PATH},
            scientific_parent_protocol={'path':q.SHARED_PROTOCOL_PATH},
            scientific_source={'path':q.SHARED_PATH})
        self.assertEqual(q.verify_inventory_metadata(inventory,records),records)
        wrong=copy.deepcopy(inventory);wrong['tables'][3]['role']='fit'
        with self.assertRaises(ValueError):q.verify_inventory_metadata(wrong,wrong['tables'])
        for table,record in zip(data,records):q.validate_table_clock(table,record)
        poison_outcomes(data)
        q.validate_table_clock(data[3],records[3])
        data[3]['anchors'][0]['decision_ns']+=1
        with self.assertRaises(ValueError):q.validate_table_clock(data[3],records[3])

    def test_feature_clocks_own_generation_and_observed_flow_identity(self):
        data=tables(); target=find(data,TRAIN[0]); leader=find(data,TRAIN[0],'BTC')
        when=target['decision_ns']
        for key,boundary in (('start_received_ns',when-NS),('start_source_ns',when-NS),
                             ('end_received_ns',when),('end_source_ns',when)):
            with self.subTest(clock=key):
                good=copy.deepcopy(target)
                if 'received' in key:
                    good['features'][key]=boundary-250_000_000
                    good['features'][key.replace('received','source')]=boundary-250_000_000
                else:good['features'][key]=boundary-250_000_000
                self.assertIsNotNone(q.feature_vector(good,leader)[0])
                good['features'][key]-=1
                self.assertIsNone(q.feature_vector(good,leader)[0])
        changes=(('end_source_ns',when+1),('generation','different-own-generation'),
                 ('depth_start','0'),('ofi','NaN'),('price_changing_ofi','0'))
        for key,value in changes:
            with self.subTest(invalid=key):
                bad=copy.deepcopy(target);bad['features'][key]=value
                self.assertIsNone(q.feature_vector(bad,leader)[0])
        unchanged=copy.deepcopy(target)
        f=unchanged['features'];value=f['values'][3]-f['values'][2]
        set_ofi(unchanged,value)
        f.update(all_prices_unchanged=True,unchanged_price_ofi=f['ofi'],price_changing_ofi='0')
        self.assertIsNotNone(q.feature_vector(unchanged,leader)[0])
        set_ofi(unchanged,value+1)
        self.assertIsNone(q.feature_vector(unchanged,leader)[0])

    def test_feature_preflight_never_reads_outcomes_and_one_cell_blocks_cohort(self):
        good=tables();poison_outcomes(good)
        pre=q.feature_preflight(good)
        self.assertEqual(pre['status'],'passed')
        self.assertEqual(set(pre['cells']),CELLS)
        self.assertEqual(pre['application_mask'],{c:list(range(28)) for c in APPLY})
        bad=tables()
        for chunk in TRAIN:
            for slot in range(7):find(bad,chunk,slot=slot)['feature_failure']='synthetic_gap'
        poison_outcomes(bad)
        pre=q.feature_preflight(bad)
        self.assertEqual(pre['status'],'insufficient_feature_support')
        result=q.analyze(bad)
        self.assertEqual(result['classification'],'insufficient_feature_support')
        self.assertIsNone(result['models']);self.assertIsNone(result['evaluation'])

    def test_funding_is_causal_and_future_fields_cannot_select_application_mask(self):
        data=tables()
        for row in data[3]['anchors']:
            if row['slot']==0:row['feature_failure']='synthetic_gap'
        poison_outcomes(data)
        pre=q.feature_preflight(data)
        self.assertEqual(pre['status'],'passed')
        self.assertEqual(pre['application_mask'][APPLY[0]],list(range(1,28)))
        funded=tables()
        for row in funded[3]['anchors']:
            when=(7*3600+3550+20*row['slot'])*NS
            row['decision_ns']=when
            f=row['features'];f.update(start_received_ns=when-NS,start_source_ns=when-NS,
                end_received_ns=when,end_source_ns=when)
        poison_outcomes(funded)
        pre=q.feature_preflight(funded)
        self.assertNotIn(2,pre['application_mask'][APPLY[0]])
        self.assertIn(1,pre['application_mask'][APPLY[0]])
        self.assertIn(3,pre['application_mask'][APPLY[0]])

    def test_training_labels_reapply_cell_chunk_counts_and_nonzero_variance(self):
        for kind in ('chunk_count','total_count','zero_variance'):
            with self.subTest(fit=kind):
                data=tables();pre=q.feature_preflight(data)
                self.assertEqual(pre['status'],'passed')
                if kind=='zero_variance':
                    for chunk in TRAIN:
                        for slot in range(28):find(data,chunk,slot=slot)['label']=1.
                else:
                    sizes=(9,0,0) if kind=='chunk_count' else (7,7,6)
                    for chunk,count in zip(TRAIN,sizes):
                        for slot in range(count):
                            row=find(data,chunk,slot=slot)
                            row.update(label=None,label_status='missing_first_eligible')
                fit=q.fit_models(data,pre)
                self.assertEqual(fit['status'],'insufficient_training_support')
                cell=fit['cells']['ETH:lighter']
                if kind=='zero_variance':self.assertEqual(cell['variance'],0)
                elif kind=='chunk_count':
                    self.assertEqual(cell['training_labels'],75)
                    self.assertEqual(cell['training_counts'][TRAIN[0]],19)
                else:
                    self.assertEqual(cell['training_labels'],64)
                    self.assertEqual(cell['training_counts'],dict(zip(TRAIN,(21,21,22))))

    def test_missing_training_labels_can_destroy_rank_without_failing_counts(self):
        data=tables()
        for chunk in TRAIN:
            for venue in VENUES:
                for slot in range(28):
                    row=find(data,chunk,'BTC',venue,slot)
                    x=row['features']['values']
                    set_ofi(row,x[3]-x[2]+(1 if slot==0 else 0))
        pre=q.feature_preflight(data)
        self.assertEqual(pre['status'],'passed')
        for chunk in TRAIN:find(data,chunk,slot=0).update(label=None,label_status='missing_first_eligible')
        fit=q.fit_models(data,pre)
        self.assertEqual(fit['status'],'insufficient_training_support')
        cell=fit['cells']['ETH:lighter']
        self.assertEqual(cell['training_labels'],81)
        self.assertEqual(cell['training_counts'],dict.fromkeys(TRAIN,27))
        self.assertEqual(cell['models']['M1']['status'],'available')
        self.assertEqual(cell['models']['M2']['status'],'rank_deficient')

    def test_rank_gate_keeps_fixed_columns_and_rejects_near_endpoint_identity(self):
        for kind in ('constant','exact','near'):
            with self.subTest(rank=kind):
                data=tables()
                for chunk in TRAIN:
                    for venue in VENUES:
                        for slot in range(28):
                            row=find(data,chunk,'BTC',venue,slot)
                            x=row['features']['values']
                            if kind=='constant':x[4]=.25
                            else:set_ofi(row,x[3]-x[2]+(1e-9*x[0] if kind=='near' else 0))
                poison_outcomes(data)
                pre=q.feature_preflight(data)
                self.assertEqual(pre['status'],'insufficient_feature_support')
                self.assertNotEqual(pre['cells']['ETH:lighter']['models']['M2']['status'],'available')
                self.assertEqual(pre['cells']['ETH:lighter']['models']['M2']['design_columns'],13)
        data=tables();row=find(data,TRAIN[0]);btc=find(data,TRAIN[0],'BTC')
        for value in (float('nan'),float('inf'),True):
            with self.subTest(number=value):
                bad=copy.deepcopy(row);bad['features']['values'][0]=value
                self.assertIsNone(q.feature_vector(bad,btc)[0])

    def test_real_nested_ols_uses_training_only_and_recovers_consistent_forecast(self):
        data=tables()
        for chunk in data[3:]:chunk['anchors']=[OutcomeTripwire(row) for row in chunk['anchors']]
        pre=q.feature_preflight(data);models=q.fit_models(data,pre)
        self.assertEqual(models['status'],'available')
        self.assertEqual(set(models['cells']),CELLS)
        for cell in models['cells'].values():
            self.assertEqual(len(cell['training_ids']),84)
            self.assertEqual(cell['training_counts'],dict.fromkeys(TRAIN,28))
            self.assertEqual([cell['models'][m]['design_columns'] for m in ('M0','M1','M2')],[7,12,13])
            self.assertEqual([cell['models'][m]['columns'] for m in ('M0','M1','M2')],
                [list(range(6)),list(range(11)),list(range(12))])
        frozen=copy.deepcopy(models)
        for chunk in data[3:]:
            # Only after fitting succeeds are application outcomes made readable.
            chunk['anchors']=[dict.copy(row) for row in chunk['anchors']]
            for row in chunk['anchors']:
                # Application covariates can be far outside training support.
                row['features']['values'][0]+=1000
                asset,venue,slot=row['asset'],row['venue'],row['slot']
                btc=find(data,chunk['chunk'],'BTC',venue,slot)
                install_quotes(row,.5*row['features']['values'][0]+20*btc['features']['values'][5])
        changed_pre=q.feature_preflight(data);refit=q.fit_models(data,changed_pre)
        for key in CELLS:
            self.assertEqual(refit['cells'][key],models['cells'][key])
        row=find(data,APPLY[0]);btc=find(data,APPLY[0],'BTC')
        vector,_=q.feature_vector(row,btc)
        self.assertAlmostEqual(q.predict(models['cells']['ETH:lighter'],vector,'M2'),row['label'],places=8)
        self.assertEqual(models,frozen)
        result=q.evaluate(data,changed_pre,refit)
        for block in result['forecast']['chunks']:
            self.assertTrue(block['primary_available'])
            self.assertLess(block['normalized_mse']['M2'],1e-18)
            self.assertGreater(block['M2_vs_M1_improvement'],0)
        self.assertFalse(result['validation_claim']);self.assertFalse(result['strategy_promotion'])
        self.assertFalse(result['realized_fill_claim'])

    def test_later_missing_label_does_not_trim_mask_or_primary_forecast_loss(self):
        data,pre,models=fixed_forecast_fixture();mask=copy.deepcopy(pre['application_mask'])
        row=find(data,APPLY[0]);row.update(label=None,label_status='unresolved_at_end')
        result=q.evaluate(data,pre,models)
        self.assertEqual(result['application_mask'],mask)
        self.assertEqual(len(result['audit_rows']),3*18*28)
        block=result['forecast']['chunks'][0]
        self.assertEqual(block['mask_rows'],28)
        self.assertFalse(block['primary_available'])
        self.assertIsNone(block['M2_vs_M1_improvement'])
        cell=block['cells']['ETH:lighter']
        self.assertEqual(cell['complete_labels'],27)
        self.assertEqual(cell['missing_labels'],{'unresolved_at_end':1})
        self.assertIsNotNone(cell['conditional_available_normalized_mse']['M2'])
        self.assertIsNone(cell['normalized_mse']['M2'])
        self.assertIsNone(result['forecast']['equal_chunk_M2_vs_M1_improvement'])
        self.assertEqual(result['classification'],'inconclusive_missing_application_evidence')
        tampered=copy.deepcopy(pre);tampered['application_mask'][APPLY[0]].pop()
        with self.assertRaises(ValueError):q.evaluate(data,tampered,models)
        row['features']['values'][0]+=1
        with self.assertRaises(ValueError):q.evaluate(data,pre,models)

    def test_missing_reference_candidate_and_exact_side_size_profiles_block_cash(self):
        for kind in ('reference','candidate','wrong_size','wrong_side','duplicate','bad_cash'):
            with self.subTest(profile=kind):
                data,pre,models=fixed_forecast_fixture();row=find(data,APPLY[0])
                side=-1 if kind=='reference' else 1
                profile=quoted_profile(row,side=side)
                if kind in ('reference','candidate'):profile['status']='unresolved_at_end'
                elif kind=='wrong_size':row['profiles'].remove(profile)
                elif kind=='wrong_side':
                    row['profiles']=[p for p in row['profiles'] if p['direction']!=1]
                elif kind=='duplicate':row['profiles'].append(copy.deepcopy(profile))
                else:profile['net_cash']='1000'
                if kind in ('duplicate','bad_cash'):
                    with self.assertRaises(ValueError):q.evaluate(data,pre,models)
                    continue
                result=q.evaluate(data,pre,models);block=economic_block(result)
                unknown='M1' if kind=='reference' else 'M2'
                self.assertEqual(block['cells']['ETH:lighter'][unknown]['admitted_unknown'],1)
                self.assertEqual(block['cells']['ETH:lighter'][unknown]['mask_rows'],28)
                self.assertFalse(block['primary_available'])
                self.assertIsNone(block['M2_minus_M1_mean_conditional_net_cash'])
                self.assertEqual(result['classification'],'inconclusive_missing_application_evidence')
                # Wrong/missing100-long cannot borrow1000-long or100-short.
                if kind=='wrong_size':self.assertTrue(economic_block(result,size='1000')['primary_available'])

    def test_known_no_action_is_zero_and_simultaneous_targets_are_one_admission_slot(self):
        data,pre,models=fixed_forecast_fixture();row=find(data,APPLY[0])
        for cost in row['decision_costs'].values():cost['spread_cash']='1000000'
        row['profiles']=[]
        result=q.evaluate(data,pre,models);block=economic_block(result)
        cell=block['cells']['ETH:lighter']
        self.assertEqual(cell['M2']['known_no_action'],1)
        self.assertEqual(cell['M2']['admitted_unknown'],0)
        self.assertEqual(cell['M2']['all_mask_mean_conditional_net_cash'],D('.01')*27/28)
        self.assertTrue(block['primary_available'])
        self.assertEqual(result['classification'],'supports_later_untouched_replication_proposal')
        masked=tables()
        for chunk in masked[3:]:
            for candidate in chunk['anchors']:install_quotes(candidate,1)
        find(masked,APPLY[0])['feature_failure']='known_decision_gap'
        # All18cells abstain on the common feature-mask failure. Future fields
        # on this original calendar must remain unread, even on other assets.
        masked[3]['anchors']=[OutcomeTripwire(r) if r['slot']==0 else r
            for r in masked[3]['anchors']]
        pre=q.feature_preflight(masked);models=fixed_models(masked,pre)
        result=q.evaluate(masked,pre,models);block=economic_block(result)
        self.assertEqual(block['mask_rows'],27)
        self.assertEqual(block['all_mask_equal_target_mean_conditional_net_cash']['M2'],D('.01'))
        self.assertAlmostEqual(block['all_calendar_equal_target_mean_conditional_net_cash']['M2'],
            D('.01')*27/28,delta=D('1e-27'))
        for cell in block['cells'].values():
            self.assertEqual(cell['M2']['original_calendar_rows'],28)
            self.assertEqual(cell['M2']['known_no_action_off_mask'],1)
            self.assertEqual(cell['M2']['known_no_action_on_mask'],0)
        self.assertEqual(result['classification'],'supports_later_untouched_replication_proposal')
        sparse,pre,models=fixed_forecast_fixture()
        for chunk in sparse[3:]:
            for row in chunk['anchors']:
                if row['slot']!=0:
                    for cost in row['decision_costs'].values():cost['spread_cash']='1000000'
        result=q.evaluate(sparse,pre,models)
        self.assertEqual(len(result['economics']['rows']),18)
        for block in result['economics']['rows']:
            self.assertEqual(block['distinct_M2_admitted_slots'],1)
            self.assertEqual(sum(c['M2']['admitted'] for c in block['cells'].values()),9)
            self.assertGreater(block['all_mask_equal_target_mean_conditional_net_cash']['M2'],0)
            self.assertFalse(block['support_pass']);self.assertFalse(block['positive_cash_pass'])
        self.assertFalse(result['economics']['passes']);self.assertFalse(result['strategy_promotion'])

    def test_native_collateral_ledgers_and_equal_target_weights_are_kept_separate(self):
        data,pre,models=fixed_forecast_fixture()
        for chunk in data[3:]:
            for row in chunk['anchors']:
                if row['venue']=='rh_lighter':install_quotes(row,1,fee_bps='1.05')
                elif row['asset']=='ETH':install_quotes(row,9)
        result=q.evaluate(data,pre,models)
        self.assertTrue(result['forecast']['passes'])
        self.assertEqual(len(result['economics']['rows']),18)
        self.assertEqual(len(result['economics']['aggregates']),6)
        for block in result['economics']['rows']:
            n=D(block['native_notional'])
            self.assertEqual(set(block['cells']),{a+':'+block['venue'] for a in TARGETS})
            if block['venue']=='lighter':
                self.assertEqual(block['collateral'],'USDC')
                self.assertEqual(block['all_mask_equal_target_mean_conditional_net_cash']['M2'],n*D('0.0001')*17/9)
                self.assertTrue(block['positive_cash_pass'])
            else:
                self.assertEqual(block['collateral'],'USDG')
                self.assertEqual(block['all_mask_equal_target_mean_conditional_net_cash']['M2'],-n*D('0.000005'))
                self.assertFalse(block['positive_cash_pass'])
            self.assertEqual(block['mask_rows'],28)
        self.assertFalse(result['economics']['passes'])
        self.assertEqual(result['classification'],'park_this_linear_version')


if __name__=='__main__':
    unittest.main()
