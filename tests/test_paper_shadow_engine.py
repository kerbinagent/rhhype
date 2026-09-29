"""Shadow experiments preserve baseline accounting and actual delayed execution."""
import copy
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from paper_engine import PaperEngine, EngineConfig, SHADOW_POLICIES, scenario_fee, taker_delay
from tests.test_paper_engine import pair, book


class ShadowEngineTests(unittest.TestCase):
    def make(self):
        e=PaperEngine([pair()],EngineConfig(strategies=('standard',),holding_seconds=10,take_profit_usd=.10),now=1000)
        e.enable_shadows(1000)
        e.receive(book('hyperliquid','BTC',1000,99.99,100))
        e.receive(book('rh_lighter',1,1000,102,102.01))
        e.tick(1000)
        return e

    def test_enable_is_additive_and_restart_preserves_accounts_and_cooldown(self):
        e=self.make()
        original=copy.deepcopy(e.ledgers)
        e.enable_shadows(1001)
        self.assertEqual(original,e.ledgers)
        state=copy.deepcopy(e.export_state())
        restored=PaperEngine([pair()],e.config,state=state,now=1001)
        self.assertEqual(e.ledgers,restored.ledgers)
        self.assertEqual(restored.shadow_started_at,1000)
        self.assertEqual(restored.selector.routes,{})
        self.assertEqual(restored.selector.last_entries['cooldown'],e.selector.last_entries['cooldown'])
        self.assertEqual(set(restored.position_markets['hyperliquid:BTC']),set(restored.positions))

    def test_shadow_fees_and_delays_equal_standard(self):
        for m in (pair()['hl'],pair()['other']):
            for policy in SHADOW_POLICIES:
                self.assertEqual(scenario_fee(m,policy),scenario_fee(m,'standard'))
                self.assertEqual(taker_delay(m,policy,EngineConfig()),taker_delay(m,'standard',EngineConfig()))

    def test_baseline_matches_fresh_control_and_forecasts_wait(self):
        e=self.make()
        self.assertEqual({p['strategy'] for p in e.positions.values()}, {'standard','shadow_baseline','cooldown'})
        source=book('hyperliquid','BTC',1000.2,99.99,100,size=20)
        untouched=copy.deepcopy(source)
        e.receive(source)
        self.assertEqual(source,untouched)
        e.receive(book('rh_lighter',1,1000.5,102,102.01,size=20))
        for p in e.positions.values():self.assertEqual(p['status'],'OPEN')
        std=next(p for p in e.positions.values() if p['strategy']=='standard')
        shadow=next(p for p in e.positions.values() if p['strategy']=='shadow_baseline')
        self.assertEqual(std['legs'],shadow['legs'])
        self.assertEqual(e.ledgers['standard']['wallets'],e.ledgers['shadow_baseline']['wallets'])
        # Shared external books are independently available in each portfolio.
        self.assertGreater(std['legs'][0]['quantity'],0)
        self.assertGreater(shadow['legs'][0]['quantity'],0)

    def test_market_index_does_not_fill_unrelated_book_and_cleans_after_settlement(self):
        e=self.make()
        e.receive(book('hyperliquid','ETH',1000.3,99.99,100))
        self.assertTrue(all(p['legs'][0]['quantity']==0 for p in e.positions.values()))
        e.receive(book('hyperliquid','BTC',1000.3,99.99,100))
        e.receive(book('rh_lighter',1,1000.5,102,102.01))
        e.tick(1010.6)
        e.receive(book('hyperliquid','BTC',1010.9,99.99,100))
        e.receive(book('rh_lighter',1,1011.1,102,102.01))
        for ident in list(e.positions):
            e.settle_funding(ident,{'complete':True,'cashflow_usd':0,'events':[]},1011.2)
        self.assertFalse(e.positions)
        self.assertFalse(e.position_markets)

    def test_forecast_entry_records_prior_model_and_still_waits_for_fills(self):
        e=PaperEngine([pair()],EngineConfig(strategies=('standard',),holding_seconds=10,take_profit_usd=.10),now=1000)
        e.enable_shadows(1000)
        for index in range(41):
            now=1000+index*3
            long=book('hyperliquid','BTC',now,99.99,100)
            short=book('rh_lighter',1,now,100.2,100.21)
            signal=e._signal(pair(),pair()['hl'],pair()['other'],long,short,'standard',now)
            e.selector.observe(pair(),{'hyperliquid:BTC':long,'rh_lighter:1':short},now,signals=[signal])
        e.receive(book('hyperliquid','BTC',1121,99.99,100))
        e.receive(book('rh_lighter',1,1121,102,102.01))
        e.tick(1121)
        filtered=[p for p in e.positions.values() if p['strategy'] in ('convergence','conservative')]
        self.assertEqual(len(filtered),2)
        self.assertTrue(all(p['status']=='ENTRY_PENDING' for p in filtered))
        records=[item[1] for item in e.evidence if item[2]=='entry_model']
        self.assertEqual(len(records),2)
        for record in records:
            self.assertEqual(len(record['historical_closing_spreads']),41)
            self.assertTrue(all(row[0]<1121 for row in record['historical_closing_spreads']))
            self.assertGreater(record['signal']['entry_policy']['forecast_net_usd'],.5)

    def test_held_markets_bootstrap_before_unheld_without_mutating_metadata(self):
        from paper_monitor import all_markets
        e=self.make()
        e.receive(book('hyperliquid','BTC',1000.3,99.99,100))
        markets={f"{m['venue']}:{m['market']}":m for m in all_markets(e)}
        self.assertTrue(markets['hyperliquid:BTC']['risk_priority'])
        self.assertNotIn('risk_priority',markets['rh_lighter:1'])
        self.assertNotIn('risk_priority',e.market_meta['hyperliquid:BTC'])
