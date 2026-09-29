"""The independent audit must detect corrupted financial records."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from paper_loss_audit import audit, read_sample


class LossAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sample = read_sample(Path(__file__).resolve().parents[1] / 'data/evidence/short-horizon-loss-audit.json.gz')

    def test_frozen_accounting_reconciles(self):
        result = audit(self.sample)
        self.assertTrue(result['accounting_checks_pass'])
        self.assertEqual(result['closed_retained'], 978)
        self.assertEqual(sum(p['wins'] for p in result['portfolios'].values()), 0)

    def test_detects_incorrect_trade_pnl(self):
        sample = copy.deepcopy(self.sample)
        trade = next(p for p in sample['trades'] if p['status'] == 'CLOSED')
        trade['net_pnl_usd'] += 1
        self.assertFalse(audit(sample)['accounting_checks_pass'])

    def test_detects_incorrect_fill_fee_and_wallet(self):
        sample = copy.deepcopy(self.sample)
        trade = next(p for p in sample['trades'] if p['status'] == 'CLOSED')
        leg = next(l for l in trade['legs'] if l['entry_value'])
        leg['entry_fee_bps'] += 1
        ledger = sample['engine']['ledgers'][trade['strategy']]
        venue = next(iter(ledger['wallets']))
        ledger['wallets'][venue] += 2
        result = audit(sample)
        self.assertFalse(result['accounting_checks_pass'])
        self.assertGreater(result['independent_max_absolute_errors']['entry_fee_usd'], 0.01)
        self.assertGreater(result['independent_max_absolute_errors']['wallet_usd'], 1.99)
