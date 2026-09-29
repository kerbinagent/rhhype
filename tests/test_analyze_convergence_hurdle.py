import gzip
import json
import tempfile
import unittest
from pathlib import Path

from scripts.analyze_convergence_hurdle import INPUT, MAX_INPUT_BYTES, analyze, load_snapshot


class ConvergenceHurdleTest(unittest.TestCase):
    @staticmethod
    def fixture():
        row={'route':'A|buy|sell','status':'matched','censor_reason':None,
             'entry_buy_value':100,'entry_sell_value':101,
             'anchor_long_liquidation_value':99,
             'anchor_short_buyback_value':102,
             'buy_fee_bps':0,'sell_fee_bps':0,
             'anchor_time':1000,'outcome_time':1012,'quantity':1,
             'exit_long_value':99,'exit_short_buyback_value':102,
             'buy_entry_fee_usd':0,'sell_entry_fee_usd':0,
             'buy_exit_fee_usd':0,'sell_exit_fee_usd':0,
             'gross_capture_usd':-2,'total_four_fees_usd':0,
             'net_after_four_fees_usd':-2,
             'extra_cost_reserve_usd':.0505,'capital_elapsed_seconds':12,
             'capital_reserve_usd':0,'net_after_reserves_usd':-2.0505}
        censored=dict(row,status='censored',censor_reason='future_exit_depth')
        for key in ('exit_long_value','exit_short_buyback_value','gross_capture_usd',
                    'total_four_fees_usd','net_after_four_fees_usd','net_after_reserves_usd',
                    'buy_entry_fee_usd','sell_entry_fee_usd','buy_exit_fee_usd',
                    'sell_exit_fee_usd','extra_cost_reserve_usd','capital_elapsed_seconds',
                    'capital_reserve_usd','outcome_time'):
            censored.pop(key,None)
        snapshot={'status':'stopped','fixed_markout':{'finished':True,'extra_cost_bps':5,
                                    'margin_fraction':1,'capital_rate':0,
                                    'counts':{'anchors':2,'matched_anchors':1,
                                          'censored_anchors':1,'terminal_export_dropped':0},
                                    'terminal_rows':[row,censored]}}
        return snapshot

    def test_opening_edge_does_not_erase_closing_liability(self):
        snapshot=self.fixture()
        result=analyze(snapshot)
        self.assertEqual(result['opening_spread_positive_anchors'],2)
        self.assertEqual(result['distributions_usd']['instant_gross']['median'],-2)
        self.assertEqual(result['censor_reasons']['future_exit_depth'],1)
        self.assertEqual(result['oracle_on_observed_matched_only']['after_reserve_ge_target'],0)

    def test_stopped_snapshot_all_rows_conserved_and_oracle_limited(self):
        result=analyze(load_snapshot(INPUT))
        self.assertEqual(result['retained_all_anchor_count'],2134)
        self.assertEqual(result['oracle_on_observed_matched_only']['matched'],1595)
        self.assertEqual(sum(result['censor_reasons'].values()),539)
        self.assertEqual(result['oracle_on_observed_matched_only']['four_fee_ge_target'],1)
        self.assertEqual(result['oracle_on_observed_matched_only']['after_reserve_ge_target'],0)
        self.assertEqual(result['opening_screen_cohort']['matched']+
                         result['opening_screen_cohort']['censored'],
                         result['opening_screen_cohort']['anchors'])

    def test_decoded_gzip_bound_precedes_json_parse(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'oversized.json.gz'
            with gzip.open(path,'wb') as f:f.write(b'x'*1024)
            with self.assertRaisesRegex(ValueError,'decoded input bound'):
                load_snapshot(path,max_decoded_bytes=128)
            with path.open('wb') as f:f.truncate(MAX_INPUT_BYTES+1)
            with self.assertRaisesRegex(ValueError,'compressed input bound'):
                load_snapshot(path)

    def test_rejects_wrong_exit_fee_reserve_and_capital(self):
        for field,value,error in (
            ('buy_exit_fee_usd',.01,'buy_exit_fee_usd'),
            ('extra_cost_reserve_usd',.05,'reserve identity'),
            ('capital_reserve_usd',.01,'capital reserve identity'),
            ('net_after_reserves_usd',-2,'after-reserve identity'),
            ('quantity',float('nan'),'nonfinite'),
        ):
            with self.subTest(field=field):
                snapshot=self.fixture()
                snapshot['fixed_markout']['terminal_rows'][0][field]=value
                with self.assertRaisesRegex(ValueError,error):analyze(snapshot)


if __name__=='__main__':unittest.main()
