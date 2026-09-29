import gzip
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from analyze_contingent import analyze, exposure, load_database, main, render_markdown


def leg(side, quantity, entry_time, exits, *, fee=0):
    return {'side':side,'venue':'hyperliquid' if side=='long' else 'rh_lighter',
            'quantity':quantity,'entry_time':entry_time,'remaining':quantity-sum(q for _,q in exits),
            'entry_result':'filled' if quantity else 'rejected',
            'entry_fee':fee/2,'exit_fee':fee/2,'fees_usd':fee,
            'exit_fills':[{'timestamp':t,'quantity':q,'fee':fee/2 if i==0 else 0}
                          for i,(t,q) in enumerate(exits)]}


def closed(ident, cohort_id, policy, *, net=-1.5):
    return {'id':ident,'cohort_id':cohort_id,'trial_policy':policy,'status':'CLOSED',
            'opened_at':1,'closed_at':10,'settled_at':11,
            'legs':[leg('long',10,0,[(10,10)],fee=.5),
                    leg('short',10,0,[(10,10)],fee=.5)],
            'price_pnl':0,'fees_usd':1,'other_costs_usd':.5,
            'capital_costs_usd':0,'funding_usd':0,'net_pnl_usd':net}


def aborted(ident, cohort_id, policy):
    return {'id':ident,'cohort_id':cohort_id,'trial_policy':policy,'status':'ABORTED',
            'closed_at':1,'legs':[leg('long',0,None,[]),leg('short',0,None,[])]}


def state(rows, *, status='stopped', counts=None, control_positions=None, treatment_positions=None):
    counts=counts or {'selected':len(rows),'terminal_cohorts':len(rows)}
    def engine(policy,positions,closed_count,aborted_count):
        return {'positions':positions or {},'cohort_rows':rows if policy=='control' else [],
                'cohort_counts':counts if policy=='control' else {},
                'cohort_sums':{},'ledgers':{'convergence':{
                    'entry_attempts':closed_count+aborted_count,
                    'closed_trades':closed_count,'estimated_trades':0,
                    'aborted_trades':aborted_count,'closed_pnl_exact':-1.5*closed_count,
                    'closed_pnl_estimated':0,'fees_usd':closed_count,
                    'other_costs_usd':.5*closed_count,'capital_costs_usd':0,'funding_usd':0}}}
    return {'study_status':status,'saved_at':20,'checkpoint_id':'fixed',
            'trial':{'control':engine('control',control_positions,1,0),
                     'treatment':engine('treatment',treatment_positions,0,1)}}


class ExposureTests(unittest.TestCase):
    def test_partial_exits_and_same_timestamp_changes(self):
        position={'status':'CLOSED','opened_at':2,
                  'legs':[leg('long',10,0,[(5,4),(8,6)]),
                          leg('short',10,2,[(5,4),(10,6)])]}
        result=exposure(position,10,20)
        self.assertEqual(result['coverage'],'complete')
        self.assertAlmostEqual(result['equivalent_seconds'],3.2)
        self.assertAlmostEqual(result['wall_seconds'],4)
        self.assertAlmostEqual(result['peak_fraction'],1)
        self.assertAlmostEqual(result['entry_phase_equivalent_seconds'],2)
        self.assertAlmostEqual(result['exit_phase_equivalent_seconds'],1.2)

    def test_open_is_observed_to_freeze_and_truncated_is_censored(self):
        position={'status':'EXITING','opened_at':1,
                  'legs':[leg('long',10,0,[]),leg('short',0,None,[])]}
        result=exposure(position,10,5)
        self.assertEqual(result['coverage'],'observed_to_freeze')
        self.assertIsNone(result['equivalent_seconds'])
        self.assertEqual(result['observed_to_freeze_equivalent_seconds'],5)
        position['funding_history_truncated']=True
        self.assertIsNone(exposure(position,10,5)['equivalent_seconds'])

    def test_negative_inventory_rejected(self):
        position={'status':'CLOSED','legs':[leg('long',10,0,[(1,11)]),
                                            leg('short',0,None,[])]}
        with self.assertRaisesRegex(ValueError,'negative or excess inventory'):
            exposure(position,10,2)


class AnalyzerTests(unittest.TestCase):
    def test_aborted_treatment_is_known_zero_but_not_a_profitable_fill(self):
        row={'cohort_id':'c1','selected_at':0,'original_quantity':10,
             'control_position_id':'a','treatment_position_id':'b',
             'control_result':{'status':'closed','net_usd':-1.5},
             'treatment_result':{'status':'aborted','net_usd':0}}
        result=analyze(state([row]),{'c1':row},
                       {'a':closed('a','c1','simultaneous'),
                        'b':aborted('b','c1','hl_first')})
        self.assertEqual(result['pairs']['both_exact_known'],1)
        self.assertAlmostEqual(result['pairs']['treatment_minus_control_usd'],1.5)
        self.assertEqual(result['pairs'].get('both_filled_exact',0),0)
        self.assertEqual(result['pairs']['foregone_control_matches'],1)
        self.assertEqual(result['policies']['treatment']['cohort_outcomes']['aborted'],1)
        self.assertTrue(result['coverage']['all_terminal_trades_retained'])

    def test_missing_trade_and_unmapped_cohort_cannot_be_zeroed(self):
        row={'cohort_id':'c1','selected_at':0,'original_quantity':10,
             'control_position_id':'a','treatment_position_id':'lost',
             'control_result':None,'treatment_result':None}
        checkpoint=state([row],counts={'selected':2,'terminal_cohorts':1})
        result=analyze(checkpoint,{'c1':row},{'a':closed('a','c1','simultaneous')})
        self.assertFalse(result['coverage']['all_original_candidates_mapped'])
        self.assertFalse(result['coverage']['paired_measures_complete'])
        self.assertEqual(result['coverage']['missing_trade_count'],1)
        self.assertEqual(result['pairs']['not_both_resolved'],1)
        self.assertEqual(result['pairs'].get('foregone_control_matches',0),0)
        self.assertNotIn('both_exact_known',result['pairs'])

    def test_both_filled_pair_keeps_candidate_and_peer_send_clocks_distinct(self):
        row={'cohort_id':'c1','selected_at':0,'original_quantity':10,
             'control_position_id':'a','treatment_position_id':'b',
             'treatment_result':{'status':'closed','net_usd':-1.5,
                 'exposure_metric_status':'complete','unmatched_equivalent_seconds':2,
                 'one_leg_clock_seconds':2}}
        treatment=closed('b','c1','hl_first')
        treatment['legs']=[leg('long',10,1,[(10,10)],fee=.5),
                           leg('short',10,3,[(10,10)],fee=.5)]
        treatment['opened_at']=3
        treatment['contingent']={'peer_sent_at':2,'first_fill_time':1}
        checkpoint=state([row])
        ledger=checkpoint['trial']['treatment']['ledgers']['convergence']
        ledger.update(closed_trades=1,aborted_trades=0,closed_pnl_exact=-1.5,
                      fees_usd=1,other_costs_usd=.5)
        result=analyze(checkpoint,{'c1':row},
                       {'a':closed('a','c1','simultaneous'),'b':treatment})
        self.assertEqual(result['pairs']['both_filled_exact'],1)
        self.assertEqual(result['pairs']['both_filled_treatment_minus_control_usd'],0)
        self.assertIn('difference: 0.0000 USD',render_markdown(result))
        timing=result['policies']['treatment']['timing']
        self.assertEqual(timing['equivalent_seconds'],2)
        clocks=result['policies']['treatment']['latency_seconds']
        self.assertEqual(clocks['candidate_to_hl_fill']['mean'],1)
        self.assertEqual(clocks['candidate_to_peer_fill']['mean'],3)
        self.assertEqual(clocks['peer_send_to_peer_fill']['mean'],1)
        row['treatment_result']['unmatched_equivalent_seconds']=3
        with self.assertRaisesRegex(ValueError,'exposure mismatch'):
            analyze(checkpoint,{'c1':row},
                    {'a':closed('a','c1','simultaneous'),'b':treatment})

    def test_active_restored_position_supersedes_old_transition(self):
        row={'cohort_id':'c1','selected_at':0,'original_quantity':10,
             'control_position_id':'a','treatment_position_id':None,
             'treatment_result':{'status':'abstained','net_usd':0}}
        active={'id':'a','cohort_id':'c1','trial_policy':'simultaneous',
                'status':'EXITING','opened_at':1,
                'legs':[leg('long',10,0,[]),leg('short',0,None,[])]}
        checkpoint=state([row],control_positions={'a':active})
        checkpoint['trial']['control']['ledgers']['convergence'].update(
            closed_trades=0,closed_pnl_exact=0,fees_usd=0,other_costs_usd=0)
        old=dict(active,status='ENTRY_PENDING')
        result=analyze(checkpoint,{'c1':row},{'a':old})
        self.assertEqual(result['policies']['control']['cohort_outcomes']['open_exposure'],1)
        self.assertEqual(result['policies']['control']['timing']['observed_to_freeze_equivalent_seconds'],20)
        self.assertNotIn('both_exact_known',result['pairs'])

    def test_component_or_policy_mismatch_fails(self):
        row={'cohort_id':'c1','selected_at':0,'original_quantity':10,
             'control_position_id':'a','treatment_position_id':None,
             'treatment_result':{'status':'abstained','net_usd':0}}
        trade=closed('a','c1','simultaneous',net=-.5)
        with self.assertRaisesRegex(ValueError,'component P&L'):
            analyze(state([row]),{'c1':row},{'a':trade})
        trade['net_pnl_usd']=-1.5
        trade['trial_policy']='hl_first'
        with self.assertRaisesRegex(ValueError,'identity mismatch'):
            analyze(state([row]),{'c1':row},{'a':trade})
        trade['trial_policy']='simultaneous'
        trade['price_pnl']=float('nan')
        with self.assertRaisesRegex(ValueError,'not finite'):
            analyze(state([row]),{'c1':row},{'a':trade})

    def test_entry_failure_class_is_separate_from_both_filled(self):
        row={'cohort_id':'c1','selected_at':0,'original_quantity':10,
             'control_position_id':'a','treatment_position_id':'b'}
        failed=closed('a','c1','simultaneous',net=-1)
        failed['legs']=[leg('long',10,0,[(10,10)],fee=.5),leg('short',0,None,[])]
        failed.update(exit_reason='entry_failure',fees_usd=.5)
        checkpoint=state([row])
        checkpoint['trial']['control']['ledgers']['convergence'].update(
            closed_pnl_exact=-1,fees_usd=.5)
        result=analyze(checkpoint,{'c1':row},
                       {'a':failed,'b':aborted('b','c1','hl_first')})
        self.assertEqual(result['policies']['control']['trade_class_outcomes']
                         ['entry_failed:closed']['count'],1)
        self.assertEqual(result['policies']['treatment']['trade_class_outcomes']
                         ['zero_abort:aborted']['count'],1)
        self.assertEqual(result['pairs']['both_filled_treatment_minus_control_usd'],None)
        report=render_markdown(result)
        self.assertIn('entry_failed:closed',report)
        self.assertIn('difference: N/A USD',report)

    def test_ro_loader_requires_stopped_checkpoint_and_preserves_mapping(self):
        row={'cohort_id':'c1','selected_at':0,'original_quantity':10,
             'control_position_id':'a','treatment_position_id':None,
             'control_result':None,'treatment_result':{'status':'abstained','net_usd':0}}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'trial.sqlite'
            db=sqlite3.connect(path)
            db.executescript('CREATE TABLE engine_state(id INTEGER PRIMARY KEY,payload TEXT);'
                             'CREATE TABLE trades(id TEXT PRIMARY KEY,payload TEXT);'
                             'CREATE TABLE evidence(key TEXT,kind TEXT,payload BLOB);')
            checkpoint=state([],status='running',counts={'selected':1})
            db.execute('INSERT INTO engine_state VALUES(1,?)',(json.dumps(checkpoint),))
            db.execute('INSERT INTO evidence VALUES(?,?,?)',
                       ('c1:candidate','candidate_cohort',gzip.compress(json.dumps(row).encode())))
            db.commit()
            with self.assertRaisesRegex(ValueError,'stopped'):
                load_database(path)
            checkpoint['study_status']='duration_elapsed'
            db.execute('UPDATE engine_state SET payload=? WHERE id=1',(json.dumps(checkpoint),))
            db.commit();db.close()
            loaded,mapping,trades,digest=load_database(path)
            self.assertEqual(mapping['c1']['control_position_id'],'a')
            self.assertEqual(trades,{})
            self.assertEqual(len(digest),64)
            self.assertEqual(loaded['study_status'],'duration_elapsed')
            out=Path(folder)/'report'
            main(['--db',str(path),'--out',str(out)])
            summary=json.loads((out/'analysis.json').read_text())
            self.assertFalse(summary['coverage']['paired_measures_complete'])
            self.assertIn('missing referenced trades=1',(out/'REPORT.md').read_text())
            self.assertIn('treatment minus control: N/A USD',(out/'REPORT.md').read_text())
            bundle=out/'evidence.json.gz'
            self.assertLess(bundle.stat().st_size,8*1024*1024)
            replay=Path(folder)/'replay'
            main(['--bundle',str(bundle),'--out',str(replay)])
            replayed=json.loads((replay/'analysis.json').read_text())
            self.assertEqual(summary['evidence_bundle']['sha256'],
                             replayed['evidence_bundle']['sha256'])
            self.assertEqual(summary['coverage'],replayed['coverage'])
            self.assertEqual((out/'analysis.json').read_bytes(),
                             (replay/'analysis.json').read_bytes())


if __name__=='__main__':
    unittest.main()
