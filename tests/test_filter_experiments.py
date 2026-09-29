"""Retrospective filters must not create fills or choose on holdout outcomes."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from filter_experiments import (dedupe_attempts, freeze, load, outcome,
                                select_on_train, split_chronological)


def trade(number, *, route='BTC|hyperliquid:BTC|lighter:1', edge=.5, net=-1,
          status='CLOSED', reason='max_hold', strategy='shadow_baseline'):
    stamp = 1000 + number
    return {'id':str(number),'asset':'BTC','pair_id':route,'strategy':strategy,
            'status':status,'created_at':stamp,'opened_at':stamp+.5,
            'closed_at':stamp+11,'settled_at':stamp+11.5,
            'exit_reason':reason,'net_pnl_usd':net,
            'price_pnl':net+.7,'fees_usd':.2,'other_costs_usd':.5,
            'capital_costs_usd':0,'funding_usd':0,
            'signal':{'route':route,'buy':'hyperliquid:BTC','sell':'lighter:1',
                      'net_edge_usd':edge,'opening_edge_usd':edge+.7,
                      'buy_value':999,'sell_value':1000,'buy_fee_bps':.9,
                      'sell_fee_bps':0,'skew_ms':100,'source_skew_ms':200},
            'legs':[{'venue':'hyperliquid','side':'long','entry_result':'filled'},
                    {'venue':'lighter','side':'short',
                     'entry_result':'rejected' if reason=='entry_failure' else 'filled'}]}


class FilterExperimentsTests(unittest.TestCase):
    def test_outcomes_keep_failed_hedges_and_aborts_separate(self):
        paired=trade(0,net=-1)
        failed=trade(1,net=-3,reason='entry_failure')
        aborted=trade(2,status='ABORTED',net=0,reason=None)
        result=outcome([paired,failed,aborted])
        self.assertEqual((result['attempts'],result['closed'],result['aborted']), (3,2,1))
        self.assertEqual((result['paired_closes'],result['failed_hedges']), (1,1))
        self.assertEqual(result['net_pnl_usd'],-4)
        self.assertAlmostEqual(result['price_pnl_usd'],-2.6)
        self.assertEqual(result['net_per_attempt_usd'],-4/3)

    def test_route_burst_deduplication_precedes_chronological_split(self):
        rows=[trade(0),trade(.2),trade(20),
              trade(25,route='ETH|hyperliquid:ETH|lighter:0')]
        # The 1020 entry closed at 1024, but its net result was unknown until 1026.
        rows[2]['closed_at']=1024
        rows[2]['settled_at']=1026
        kept=dedupe_attempts(rows,seconds=5)
        self.assertEqual([p['id'] for p in kept],['0','20','25'])
        train,test,cut,purged=split_chronological(kept,share=2/3)
        self.assertEqual([p['id'] for p in train],['0'])
        self.assertEqual([p['id'] for p in test],['25'])
        self.assertEqual(cut,1025)
        self.assertEqual(purged,1)

    def test_threshold_is_selected_only_from_train(self):
        # High edges look less bad in train, but are worse on the held-out rows.
        train=[trade(i,edge=1 if i<50 else .1,net=-.5 if i<50 else -2)
               for i in range(100)]
        holdout=[trade(100+i,edge=1 if i<20 else .1,
                       net=-10 if i<20 else -.1) for i in range(40)]
        choices=[('.1',lambda p:p['signal']['net_edge_usd']>=.1),
                 ('1',lambda p:p['signal']['net_edge_usd']>=1)]
        winner,_,minimum=select_on_train(train,'edge',choices)
        self.assertEqual(minimum,30)
        self.assertEqual(winner['threshold'],'1')
        self.assertEqual(outcome([p for p in holdout if choices[1][1](p)])['net_pnl_usd'],-200)

    def test_freeze_is_read_only_and_keeps_required_compact_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            db_path=root/'paper.sqlite3';markets=root/'markets.json';output=root/'sample.json.gz'
            db=sqlite3.connect(db_path)
            db.executescript('CREATE TABLE engine_state(id INTEGER,payload TEXT,updated REAL);'
                             'CREATE TABLE trades(id TEXT,payload TEXT,ts REAL);')
            engine={'engine':{'shadow_started_at':900,'ledgers':{'shadow_baseline':{'closed_trades':1}}}}
            db.execute('INSERT INTO engine_state VALUES(1,?,?)',(json.dumps(engine),1200))
            row=trade(0)
            row['legs'][0]['exit_fills']=[{'large_detail':'discard'}]
            db.execute('INSERT INTO trades VALUES(?,?,?)',('0',json.dumps(row),1000))
            db.commit();db.close()
            markets.write_text(json.dumps({'updated_at':1100,'pairs':[
                {'asset':'BTC','category':'crypto',
                 'hl':{'venue':'hyperliquid','market':'BTC'},
                 'other':{'venue':'lighter','market':1}}]}))
            metadata=freeze(db_path,markets,output)
            frozen=load(output)
            self.assertLess(metadata['bytes'],2_000_000)
            self.assertEqual(frozen['checkpoint_at'],1200)
            self.assertEqual(frozen['category_by_pair'][row['pair_id']],'crypto')
            self.assertNotIn('exit_fills',frozen['trades'][0]['legs'][0])
            self.assertEqual(frozen['trades'][0]['net_pnl_usd'],-1)
            self.assertEqual(frozen['trades'][0]['settled_at'],1011.5)
            check=sqlite3.connect(db_path)
            try:
                self.assertEqual(check.execute('SELECT COUNT(*) FROM trades').fetchone()[0],1)
            finally:
                check.close()


if __name__=='__main__':
    unittest.main()
