import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from analyze_horizon import analyze, render_markdown


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'analyze_horizon.py'
NAMES = ('historical_median', 'persistence', 'horizon_delta', 'conditional_linear')


def row(route, start, actual, forecasts=None):
    return {'model_version': 2, 'route': route, 'anchor_time': start,
            'outcome_time': start + 13, 'anchor_closing_bps': actual - 2,
            'outcome_closing_bps': actual, 'scored': forecasts is not None,
            'frozen_predictions_bps': forecasts}


def fixture():
    return {'status': 'stopped', 'updated_at': 1500, 'model': {
        'model_version': 2, 'max_export_rows': 4, 'pending_anchors': 0,
        'counts': {'observations': 15, 'anchors': 6, 'matched_anchors': 5,
                   'scored_anchors': 4, 'warmup_anchors': 2,
                   'censored_anchors': 1, 'mature_export_dropped': 1},
        'censored': {'outcome_missing': 1},
        'models': {
            'historical_median': {'count': 4, 'mean_error_bps': 1,
                                  'mean_absolute_error_bps': 9, 'root_mean_squared_error_bps': 10},
            'persistence': {'count': 4, 'mean_error_bps': 2,
                            'mean_absolute_error_bps': 7, 'root_mean_squared_error_bps': 8},
            'horizon_delta': {'count': 4, 'mean_error_bps': 1,
                              'mean_absolute_error_bps': 4, 'root_mean_squared_error_bps': 5},
            'conditional_linear': {'count': 4, 'mean_error_bps': 0,
                                   'mean_absolute_error_bps': 2, 'root_mean_squared_error_bps': 3},
        },
        'mature_rows': [
            row('BTC|A|B', 1000, 10, dict(zip(NAMES, (0, 9, 8, 10)))),
            row('BTC|A|B', 1013, 20, dict(zip(NAMES, (10, 17, 19, 19)))),
            row('BTC|B|A', 1301, 30, dict(zip(NAMES, (20, 25, 28, 31)))),
            row('BTC|B|A', 1314, 40),
        ],
    }}


class AnalyzeHorizonTests(unittest.TestCase):
    def test_all_run_ranking_and_retained_pairing_are_separate(self):
        result = analyze(fixture())
        self.assertEqual(result['all_run']['descriptive_ranking'],
                         ['conditional_linear', 'horizon_delta', 'persistence', 'historical_median'])
        self.assertEqual(result['all_run']['models']['conditional_linear']['mean_absolute_error_bps'], 2)
        retained = result['retained_rows']['models']
        self.assertAlmostEqual(retained['persistence']['mean_absolute_error_bps'], 3)
        self.assertAlmostEqual(retained['conditional_linear']['mean_absolute_error_bps'], 2/3)
        self.assertAlmostEqual(retained['conditional_linear']['paired_mae_improvement_vs_persistence_bps'], 7/3)
        self.assertEqual(retained['persistence']['p50_absolute_error_bps'], 3)
        self.assertAlmostEqual(retained['persistence']['p90_absolute_error_bps'], 4.6)
        self.assertEqual(result['retained_rows']['by_directed_route']['BTC|A|B']['scored_count'], 2)
        self.assertEqual(result['retained_rows']['by_anchor_5min_utc']['900']['scored_count'], 2)
        self.assertEqual(result['retained_rows']['by_anchor_5min_utc']['1200']['scored_count'], 1)

    def test_truncation_and_censoring_are_explicit(self):
        result = analyze(fixture())
        self.assertTrue(result['export']['truncated'])
        self.assertEqual(result['export']['mature_rows_missing_from_export'], 1)
        self.assertEqual(result['export']['scored_rows_missing_from_export'], 1)
        self.assertEqual(result['coverage_all_run']['censored_by_reason']['outcome_missing'], 1)
        markdown = render_markdown(result)
        self.assertIn('Export truncated: `True`', markdown)
        self.assertIn('not independent trials', result['interpretation'])

    def test_rejects_running_wrong_version_and_mismatched_frozen_forecast(self):
        snapshot = fixture()
        snapshot['status'] = 'running'
        with self.assertRaisesRegex(ValueError, 'stopped'):
            analyze(snapshot)
        snapshot['status'] = 'stopped'
        snapshot['model']['model_version'] = 1
        with self.assertRaisesRegex(ValueError, 'version 2'):
            analyze(snapshot)
        snapshot['model']['model_version'] = 2
        del snapshot['model']['mature_rows'][0]['frozen_predictions_bps']['conditional_linear']
        with self.assertRaisesRegex(ValueError, 'all frozen forecasts'):
            analyze(snapshot)

    def test_unequal_global_counts_suppress_ranking(self):
        snapshot = fixture()
        snapshot['model']['models']['historical_median']['count'] = 3
        result = analyze(snapshot)
        self.assertIsNone(result['all_run']['descriptive_ranking'])
        self.assertIsNone(result['all_run']['paired_mae_improvement_vs_persistence_bps']['conditional_linear'])

    def test_cli_writes_bounded_json_and_markdown(self):
        with TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            source = temporary/'horizon_snapshot.json'
            out = temporary/'report'
            source.write_text(json.dumps(fixture()))
            run = subprocess.run([sys.executable, str(SCRIPT), str(source), '--out', str(out)],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            saved = json.loads((out/'analysis.json').read_text())
            self.assertEqual(saved['input_model_version'], 2)
            self.assertIn('Five-minute anchor-time blocks', (out/'report.md').read_text())
            self.assertLess((out/'analysis.json').stat().st_size, 100_000)


if __name__ == '__main__':
    unittest.main()
