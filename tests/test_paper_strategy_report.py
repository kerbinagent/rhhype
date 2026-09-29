"""Shadow reporting uses cumulative ledgers and bounded trade diagnostics."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from paper_report import report, shadow_comparison


def ledger(closed=0,pnl=0,wins=0,fees=0):
    return {'initial_capital':20000,'wallets':{'hyperliquid':20000+pnl},
            'closed_pnl_exact':pnl,'closed_pnl_estimated':0,'closed_trades':closed,
            'estimated_trades':0,'closed_wins_exact':wins,'closed_wins_estimated':0,
            'fees_usd':fees}


def trade(ident,strategy,created,forecast=None,pnl=-1,reason='max_hold'):
    signal={'entry_policy':{'forecast_net_usd':forecast}} if forecast is not None else {}
    return {'id':ident,'strategy':strategy,'asset':'BTC','pair_id':'BTC|one|two',
            'status':'CLOSED','created_at':created,'opened_at':created+1,
            'closed_at':created+12,'exit_reason':reason,'net_pnl_usd':pnl,
            'signal':signal,'legs':[]}


class ShadowComparisonTests(unittest.TestCase):
    def setUp(self):
        self.engine={'shadow_started_at':1000,'positions':{},'ledgers':{
            'standard':ledger(500,-500,1,200),
            'shadow_baseline':ledger(12,-24,2,6),
            'cooldown':ledger(0),
            'convergence':ledger(3,-1.5,1,.8),
            'conservative':ledger(0)}}

    def test_matched_window_and_zero_trades(self):
        data=shadow_comparison(self.engine,[],1200,3)
        self.assertEqual(data['window'],{'started_at':1000,'checkpoint_at':1200,
                                          'seconds':200,'checkpoint_age_seconds':3,
                                          'status':'matched'})
        self.assertEqual(data['policies']['cooldown']['status'],'insufficient_trades')
        self.assertIsNone(data['policies']['cooldown']['cumulative_net_per_trade_usd'])
        self.assertNotIn('standard',data['policies'])
        self.assertIsNone(data['policies']['shadow_baseline']['open_position_mark_usd'])

    def test_cumulative_counts_come_from_ledger_not_retained_rows(self):
        rows=[trade('one','shadow_baseline',1100,pnl=-2),
              trade('old','shadow_baseline',900,pnl=100),
              trade('legacy','standard',1100,pnl=999)]
        data=shadow_comparison(self.engine,rows,1200,0)['policies']['shadow_baseline']
        self.assertEqual((data['cumulative_closed_trades'],data['cumulative_net_pnl_usd'],
                          data['cumulative_wins'],data['cumulative_fees_usd']),
                         (12,-24,2,6))
        self.assertEqual(data['cumulative_net_per_trade_usd'],-2)
        self.assertEqual(data['retained_closed_trades'],1)
        self.assertEqual(data['retained_exit_reasons'],{'max_hold':1})
        self.assertEqual(data['retained_mean_hold_seconds'],11)

    def test_forecast_vs_realized_only_uses_closed_policy_rows(self):
        rows=[trade('a','convergence',1100,forecast=.5,pnl=-1,reason='entry_failure'),
              trade('b','convergence',1110,forecast=1.5,pnl=2,reason='take_profit'),
              trade('c','convergence',1120,pnl=-2),
              trade('d','conservative',1120,forecast=100,pnl=50),
              trade('e','convergence',900,forecast=100,pnl=50)]
        data=shadow_comparison(self.engine,rows,1200,0)['policies']['convergence']
        self.assertEqual(data['retained_failed_hedges'],1)
        self.assertEqual(data['retained_exit_reasons'],{'entry_failure':1,'take_profit':1,'max_hold':1})
        self.assertEqual(data['retained_forecast_vs_realized'],{
            'count':2,'forecast_mean_usd':1,'realized_mean_usd':.5,
            'realized_minus_forecast_mean_usd':-.5})

    def test_report_reads_checkpoint_and_keeps_legacy_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'paper.sqlite3'
            db=sqlite3.connect(path)
            db.executescript('CREATE TABLE engine_state (id INTEGER, payload TEXT, updated REAL);'
                             'CREATE TABLE trades (payload TEXT, ts REAL);'
                             'CREATE TABLE top_signals (payload TEXT, score REAL);')
            state={'engine':self.engine | {'stats':{},'episode_history':[]}}
            db.execute('INSERT INTO engine_state VALUES (1,?,?)',(json.dumps(state),1200))
            db.execute('INSERT INTO trades VALUES (?,?)',
                       (json.dumps(trade('a','shadow_baseline',1100,pnl=-2)),1100))
            db.commit();db.close()
            data=report(path)
        self.assertIn('portfolios',data)
        self.assertIn('retained_trade_groups_not_lifetime_totals',data)
        shadow=data['shadow_comparison']['policies']['shadow_baseline']
        self.assertEqual(shadow['cumulative_closed_trades'],12)
        self.assertEqual(shadow['retained_closed_trades'],1)


if __name__=='__main__':unittest.main()
