import sys
from pathlib import Path
import unittest
import copy
import json
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from paper_engine import EngineConfig
from paper_contingent import PairedTrial, unmatched_exposure
from paper_store import PaperStore
from contingent_observer import checkpoint, select_pairs


def pair():
    hl = {'venue':'hyperliquid','market':'BTC','asset':'BTC','fee_bps':4.5,
          'step':'.01','min_qty':.01,'min_notional':10,'collateral':'USDC'}
    other = dict(hl,venue='rh_lighter',market=1,fee_bps=0,
                 published_fee_floor_bps=0)
    return {'asset':'BTC','hl':hl,'other':other,'metadata_timestamp':1000}


def book(venue, market, t, bid, ask, size=100, source=None, generation=1):
    return {'venue':venue,'market':market,'bids':[(bid,size)],'asks':[(ask,size)],
            'received':t,'engine_time':t if source is None else source,
            'valid':True,'generation':generation,'sequence':str(t)}


def cohort():
    config=EngineConfig(capital_rate=0,latency_probes_ms=())
    trial=PairedTrial([pair()],config,now=1000)
    hl=book('hyperliquid','BTC',1000,99.99,100)
    other=book('rh_lighter',1,1000,102,102.01)
    trial.receive(hl);trial.receive(other)
    p=pair()
    signal=trial.control._signal(p,p['hl'],p['other'],hl,other,'convergence',1000)
    assert signal is not None
    trial.control._maybe_enter(p,trial.control.pair_id(p),signal,'convergence',1000)
    return trial,signal


class ContingentTests(unittest.TestCase):
    def test_same_cohort_peer_waits_for_full_hl_fill_then_normal_delay(self):
        trial,signal=cohort()
        control=next(iter(trial.control.positions.values()))
        treated=next(iter(trial.treatment.positions.values()))
        self.assertEqual(control['cohort_id'],treated['cohort_id'])
        self.assertEqual(treated['signal']['quantity'],signal['quantity'])
        peer=next(l for l in treated['legs'] if l['venue']!='hyperliquid')
        self.assertIsNone(peer['intent'])
        trial.receive(book('rh_lighter',1,1000.6,102,102.01))
        self.assertIsNone(peer['entry_result'])
        trial.receive(book('hyperliquid','BTC',1000.8,99.99,100))
        self.assertEqual(treated['contingent']['phase'],'peer_pending')
        self.assertAlmostEqual(peer['intent']['due'],1001.2)
        self.assertAlmostEqual(peer['intent']['price_limit'],
                               control['legs'][1]['intent']['price_limit'] if control['legs'][1]['intent'] else
                               treated['contingent']['peer_original_intent']['price_limit'])
        trial.receive(book('rh_lighter',1,1001.1,102,102.01))
        self.assertIsNone(peer['entry_result'])
        trial.receive(book('rh_lighter',1,1001.3,102,102.01))
        self.assertEqual(treated['status'],'OPEN')
        self.assertAlmostEqual(peer['quantity'],signal['quantity'])

    def test_hl_partial_flattens_actual_fill_and_never_sends_peer(self):
        trial,signal=cohort()
        treated=next(iter(trial.treatment.positions.values()))
        trial.receive(book('hyperliquid','BTC',1000.8,99.99,100,size=4))
        hl=next(l for l in treated['legs'] if l['venue']=='hyperliquid')
        peer=next(l for l in treated['legs'] if l['venue']!='hyperliquid')
        self.assertEqual(treated['status'],'EXITING')
        self.assertEqual(treated['exit_reason'],'entry_failure')
        self.assertEqual(peer['entry_result'],'not_sent_hl_first')
        self.assertEqual(hl['quantity'],4)
        self.assertEqual(hl['intent']['kind'],'exit')
        self.assertEqual(hl['intent']['quantity'],4)
        self.assertEqual(trial.treatment.contingent_counts['peer_sent'],0)

    def test_hl_price_limit_rejects_with_zero_treatment_trade(self):
        trial,_=cohort()
        trial.receive(book('rh_lighter',1,1000.6,102,102.01))
        trial.receive(book('hyperliquid','BTC',1000.8,100.2,100.3))
        self.assertEqual(trial.treatment.contingent_counts['hl_zero'],1)
        self.assertEqual(trial.treatment.ledgers['convergence']['fees_usd'],0)
        self.assertEqual(len(trial.treatment.positions),0)
        self.assertEqual(trial.control.stats['hedge_failures'],1)

    def test_peer_partial_or_generation_change_flattens_all_filled_legs(self):
        for generation,size in ((1,4),(2,100)):
            with self.subTest(generation=generation):
                trial,_=cohort()
                trial.receive(book('hyperliquid','BTC',1000.8,99.99,100))
                treated=next(iter(trial.treatment.positions.values()))
                trial.receive(book('rh_lighter',1,1001.3,102,102.01,
                                   size=size,generation=generation))
                self.assertEqual(treated['status'],'EXITING')
                self.assertEqual(treated['exit_reason'],'entry_failure')
                hl=next(l for l in treated['legs'] if l['venue']=='hyperliquid')
                self.assertEqual(hl['intent']['kind'],'exit')
                if generation==1:
                    peer=next(l for l in treated['legs'] if l['venue']!='hyperliquid')
                    self.assertEqual(peer['entry_result'],'partial')
                    self.assertEqual(peer['intent']['kind'],'exit')

    def test_missing_other_book_waits_then_flattens_hl(self):
        trial,_=cohort()
        trial.receive(book('rh_lighter',1,1000.1,102,102.01))
        trial.receive(book('hyperliquid','BTC',1002.3,99.99,100))
        treated=next(iter(trial.treatment.positions.values()))
        self.assertEqual(treated['contingent']['phase'],'awaiting_peer_book')
        trial.treatment.tick(1004.4)
        self.assertEqual(treated['status'],'EXITING')
        self.assertEqual(treated['exit_reason'],'entry_failure')

    def test_export_restore_keeps_contingent_phase_and_candidate_id(self):
        trial,_=cohort()
        state=trial.export_state()
        restored=PairedTrial([pair()],EngineConfig(capital_rate=0,latency_probes_ms=()),
                             control_state=state['control'],treatment_state=state['treatment'],now=1000.5)
        treated=next(iter(restored.treatment.positions.values()))
        control=next(iter(restored.control.positions.values()))
        self.assertEqual(treated['cohort_id'],control['cohort_id'])
        self.assertEqual(treated['contingent']['phase'],'hl_pending')
        self.assertEqual(restored.control.cohort_counts['selected'],1)
        self.assertEqual(set(restored.control.ledgers),{'convergence'})
        active=next(iter(restored.control.cohorts.values()))
        self.assertIs(active,restored.control.cohort_rows[-1])

    def test_checkpoint_precommit_failure_restores_rows_and_drained_events(self):
        trial,_=cohort()
        class Failing:
            def checkpoint(self,*args):raise RuntimeError('precommit')
            def load_state(self):return None
        before=len(trial.control.transitions)
        with self.assertRaisesRegex(RuntimeError,'precommit'):
            checkpoint(Failing(),trial,'running',{},time.time())
        self.assertEqual(len(trial.control.transitions),before)
        row=next(iter(trial.control.cohorts.values()))
        self.assertIs(row,trial.control.cohort_rows[-1])

    def test_checkpoint_postcommit_failure_does_not_requeue(self):
        trial,_=cohort()
        class DurableFailure:
            state=None
            def checkpoint(self,state,*args):
                self.state=copy.deepcopy(state)
                raise RuntimeError('postcommit')
            def load_state(self):return self.state
        with self.assertRaisesRegex(RuntimeError,'committed but maintenance failed'):
            checkpoint(DurableFailure(),trial,'running',{},time.time())
        self.assertEqual(trial.control.transitions,[])
        self.assertEqual(trial.treatment.transitions,[])

    def test_bounded_state_fits_store_checkpoint_limit(self):
        trial,_=cohort()
        original=trial.control.cohort_rows[-1]
        for i in range(500):
            row=copy.deepcopy(original)
            row['cohort_id']=f'bounded-{i}'
            trial.control.cohort_rows.append(row)
        for engine in (trial.control,trial.treatment):
            for i in range(200):
                engine.episode_history.append({'route':f'BTC|route-{i}',
                    'asset':'BTC','strategy':'convergence','reason':'observed_end',
                    'first':1000+i,'last':1001+i,'samples':2,'peak':1.23})
        encoded=json.dumps(trial.export_state(),allow_nan=False).encode()
        self.assertLess(len(encoded),PaperStore.STATE_LIMIT*.75)

    def test_selected_universe_excludes_non_frozen_assets(self):
        p=pair()
        p['hl']['volume']=2_000_000;p['other']['volume']=2_000_000
        p['other']['published_fee_floor_bps']=0
        chosen=select_pairs([p,dict(p,asset='SHEIN')])
        self.assertEqual(len(chosen),1)
        self.assertEqual(chosen[0]['asset'],'BTC')

    def test_exposure_is_original_quantity_normalized_and_missing_is_unknown(self):
        position={'status':'CLOSED','signal':{'quantity':10},'legs':[
            {'venue':'hyperliquid','quantity':10,'entry_time':1000,
             'exit_fills':[{'timestamp':1002,'quantity':10}]},
            {'venue':'rh_lighter','quantity':10,'entry_time':1001,
             'exit_fills':[{'timestamp':1002,'quantity':10}]}]}
        metric=unmatched_exposure(position)
        self.assertEqual(metric['one_leg_clock_seconds'],1)
        self.assertEqual(metric['unmatched_equivalent_seconds'],1)
        position['funding_history_truncated']=True
        self.assertIsNone(unmatched_exposure(position)['unmatched_equivalent_seconds'])
        position.pop('funding_history_truncated')
        position['legs'][1]['exit_fills'][0]['quantity']=-1
        self.assertEqual(unmatched_exposure(position)['exposure_metric_status'],
                         'invalid_exit_fill')


if __name__=='__main__':
    unittest.main()
