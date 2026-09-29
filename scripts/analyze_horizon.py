#!/usr/bin/env python3
"""Offline, descriptive analysis of a stopped v2 horizon observer snapshot.

Frozen anchor forecasts are scored against later executable quote bps. This
script does not refit forecasts, infer fills, or estimate trading profit.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics


MODELS = ('historical_median', 'persistence', 'horizon_delta', 'conditional_linear')
MAX_SOURCE_BYTES = 32_000_000
MAX_RETAINED_ROWS = 5000
MAX_GROUPS = 5000
MAX_MARKDOWN_GROUPS = 100
MAX_OUTPUT_BYTES = 20_000_000
BLOCK_SECONDS = 300
ANALYSIS_VERSION = 1


def _finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{label} must be finite')
    return float(value)


def _count(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f'{label} must be a nonnegative integer')
    return value


def _percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _scores(rows):
    """All models are evaluated on exactly the same frozen scored rows."""
    result = {}
    for model in MODELS:
        errors = [row['outcome'] - row['predictions'][model] for row in rows]
        absolute = [abs(error) for error in errors]
        persistence_absolute = [abs(row['outcome'] - row['predictions']['persistence']) for row in rows]
        result[model] = {
            'count': len(rows),
            'mean_error_bps': statistics.fmean(errors) if errors else None,
            'mean_absolute_error_bps': statistics.fmean(absolute) if absolute else None,
            'root_mean_squared_error_bps': math.sqrt(statistics.fmean(e * e for e in errors)) if errors else None,
            'p50_absolute_error_bps': _percentile(absolute, .5),
            'p90_absolute_error_bps': _percentile(absolute, .9),
            'paired_mae_improvement_vs_persistence_bps': (
                statistics.fmean(base - test for base, test in zip(persistence_absolute, absolute))
                if errors else None),
        }
    return result


def _validate(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get('status') != 'stopped':
        raise ValueError('input must be a stopped horizon observer snapshot')
    model = snapshot.get('model')
    if not isinstance(model, dict) or model.get('model_version') != 2:
        raise ValueError('input must contain horizon model version 2')
    rows = model.get('mature_rows')
    counts = model.get('counts')
    global_models = model.get('models')
    if not isinstance(rows, list) or len(rows) > MAX_RETAINED_ROWS:
        raise ValueError('missing or oversized mature_rows export')
    if not isinstance(counts, dict) or not isinstance(global_models, dict):
        raise ValueError('missing model counts or all-run model summaries')
    normalized = []
    seen = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or row.get('model_version') != 2:
            raise ValueError(f'mature_rows[{index}] has a different model version')
        route = row.get('route')
        if not isinstance(route, str) or not route or len(route) > 256:
            raise ValueError(f'mature_rows[{index}] has an invalid route')
        anchor_time = _finite(row.get('anchor_time'), f'mature_rows[{index}].anchor_time')
        outcome_time = _finite(row.get('outcome_time'), f'mature_rows[{index}].outcome_time')
        if anchor_time < 0 or outcome_time <= anchor_time or anchor_time > 253402300799:
            raise ValueError(f'mature_rows[{index}] has invalid chronology')
        identity = (route, anchor_time, outcome_time)
        if identity in seen:
            raise ValueError(f'mature_rows[{index}] duplicates an anchor')
        seen.add(identity)
        outcome = _finite(row.get('outcome_closing_bps'), f'mature_rows[{index}].outcome_closing_bps')
        _finite(row.get('anchor_closing_bps'), f'mature_rows[{index}].anchor_closing_bps')
        scored = row.get('scored')
        if not isinstance(scored, bool):
            raise ValueError(f'mature_rows[{index}].scored must be boolean')
        predictions = row.get('frozen_predictions_bps')
        if scored:
            if not isinstance(predictions, dict) or set(predictions) != set(MODELS):
                raise ValueError(f'mature_rows[{index}] lacks all frozen forecasts')
            predictions = {name: _finite(predictions[name], f'mature_rows[{index}].{name}')
                           for name in MODELS}
        elif predictions is not None:
            raise ValueError(f'mature_rows[{index}] is unscored but has forecasts')
        normalized.append({'route': route, 'anchor_time': anchor_time,
                           'outcome_time': outcome_time, 'outcome': outcome,
                           'scored': scored, 'predictions': predictions})
    for key in ('anchors', 'matched_anchors', 'scored_anchors', 'censored_anchors',
                'warmup_anchors', 'mature_export_dropped'):
        _count(counts.get(key, 0), f'counts.{key}')
    if counts.get('matched_anchors', 0) < len(rows):
        raise ValueError('retained mature rows exceed all-run matched anchors')
    if counts.get('scored_anchors', 0) < sum(row['scored'] for row in normalized):
        raise ValueError('retained scored rows exceed all-run scored anchors')
    for name in MODELS:
        entry = global_models.get(name)
        if not isinstance(entry, dict):
            raise ValueError(f'missing all-run summary for {name}')
        count = _count(entry.get('count'), f'models.{name}.count')
        if count:
            for field in ('mean_error_bps', 'mean_absolute_error_bps', 'root_mean_squared_error_bps'):
                _finite(entry.get(field), f'models.{name}.{field}')
    route_metrics = model.get('per_route', {})
    if not isinstance(route_metrics, dict) or len(route_metrics) > MAX_GROUPS:
        raise ValueError('missing or oversized per_route summary')
    return model, normalized


def analyze(snapshot):
    """Return bounded statistics; global and retained-row results stay distinct."""
    model, rows = _validate(snapshot)
    counts = model['counts']
    global_models = model['models']
    retained_scored = [row for row in rows if row['scored']]
    all_run_count = counts.get('scored_anchors', 0)
    equal_counts = all(global_models[name]['count'] == all_run_count for name in MODELS)
    ranking = None
    if equal_counts and all_run_count:
        ranking = sorted(MODELS, key=lambda name: (
            global_models[name]['mean_absolute_error_bps'],
            global_models[name]['root_mean_squared_error_bps'], MODELS.index(name)))
    by_route = defaultdict(list)
    by_block = defaultdict(list)
    for row in retained_scored:
        by_route[row['route']].append(row)
        by_block[int(row['anchor_time'] // BLOCK_SECONDS * BLOCK_SECONDS)].append(row)
    if len(by_route) > MAX_GROUPS or len(by_block) > MAX_GROUPS:
        raise ValueError('too many route or time-block groups')
    matched = counts.get('matched_anchors', 0)
    anchors = counts.get('anchors', 0)
    dropped = counts.get('mature_export_dropped', 0)
    coverage = {
        'observations': counts.get('observations', 0),
        'anchors': anchors,
        'matched_anchors': matched,
        'scored_anchors': all_run_count,
        'warmup_anchors': counts.get('warmup_anchors', 0),
        'censored_anchors': counts.get('censored_anchors', 0),
        'pending_anchors_at_stop': model.get('pending_anchors', 0),
        'matched_fraction_of_anchors': matched / anchors if anchors else None,
        'scored_fraction_of_matched': all_run_count / matched if matched else None,
        'censored_by_reason': model.get('censored', {}),
    }
    export = {
        'max_export_rows': model.get('max_export_rows'),
        'retained_mature_rows': len(rows),
        'retained_scored_rows': len(retained_scored),
        'all_run_mature_rows': matched,
        'all_run_scored_rows': all_run_count,
        'reported_dropped_rows': dropped,
        'mature_rows_missing_from_export': matched - len(rows),
        'scored_rows_missing_from_export': all_run_count - len(retained_scored),
        'truncated': bool(dropped or matched > len(rows)),
    }
    all_run_route_coverage = {}
    for route, metric in sorted(model.get('per_route', {}).items()):
        if not isinstance(route, str) or not isinstance(metric, dict):
            raise ValueError('invalid per_route summary')
        all_run_route_coverage[route] = {
            'matched_anchors': _count(metric.get('matched_anchors'), f'per_route.{route}.matched_anchors'),
            'scored_anchors': _count(metric.get('scored_anchors'), f'per_route.{route}.scored_anchors'),
        }
    return {
        'analysis_version': ANALYSIS_VERSION,
        'input_model_version': 2,
        'snapshot_updated_at': snapshot.get('updated_at'),
        'metric': '12–16 second forward executable closing-spread quote error, bps',
        'coverage_all_run': coverage,
        'export': export,
        'ranking_rule': 'All-run MAE ascending on equal scored counts; tie-break all-run RMSE, then fixed model order.',
        'all_run': {
            'models': {name: global_models[name] for name in MODELS},
            'equal_scored_counts': equal_counts,
            'descriptive_ranking': ranking,
            'paired_mae_improvement_vs_persistence_bps': {
                name: (global_models['persistence']['mean_absolute_error_bps'] -
                       global_models[name]['mean_absolute_error_bps'])
                if ranking else None for name in MODELS},
            'by_directed_route_coverage': all_run_route_coverage,
        },
        'retained_rows': {
            'scored_count': len(retained_scored),
            'models': _scores(retained_scored),
            'by_directed_route': {route: {'scored_count': len(group), 'models': _scores(group)}
                                  for route, group in sorted(by_route.items())},
            'by_anchor_5min_utc': {str(start): {'start_utc': datetime.fromtimestamp(start, timezone.utc).isoformat(),
                                               'scored_count': len(group), 'models': _scores(group)}
                                   for start, group in sorted(by_block.items())},
        },
        'interpretation': (
            'Forecasts were frozen at each anchor. Retained rows may omit older anchors; '
            'The snapshot has no per-block censor timestamps, so block coverage cannot be reconstructed. '
            'opposite directions and adjacent anchor outcomes can be correlated. '
            'These are quote-bps errors, not independent trials, fills, cash P&L, or trading profit.'),
    }


def _number(value):
    return '—' if value is None else f'{value:.3f}'


def render_markdown(report):
    coverage = report['coverage_all_run']
    export = report['export']
    all_run = report['all_run']
    retained = report['retained_rows']
    lines = [
        '# Horizon model v2: stopped snapshot analysis', '',
        f"Snapshot updated: `{report['snapshot_updated_at']}`. Metric: {report['metric']}.", '',
        '## Scored coverage and censoring', '',
        f"All-run anchors: {coverage['anchors']}; matched: {coverage['matched_anchors']}; "
        f"scored: {coverage['scored_anchors']}; warmup: {coverage['warmup_anchors']}; "
        f"censored: {coverage['censored_anchors']}; pending at stop: {coverage['pending_anchors_at_stop']}.", '',
        f"Censor reasons: `{json.dumps(coverage['censored_by_reason'], sort_keys=True)}`.", '',
        '## All-run model errors', '',
        'Primary descriptive ranking: all-run MAE on equal scored counts; tie-break RMSE, then fixed model order.', '',
        '| Model | Scored | MAE bps | RMSE bps | MAE gain vs persistence bps |',
        '|---|---:|---:|---:|---:|',
    ]
    for name in MODELS:
        metric = all_run['models'][name]
        gain = all_run['paired_mae_improvement_vs_persistence_bps'][name]
        lines.append(f"| {name} | {metric['count']} | {_number(metric['mean_absolute_error_bps'])} | "
                     f"{_number(metric['root_mean_squared_error_bps'])} | {_number(gain)} |")
    lines += ['', f"Ranking: `{all_run['descriptive_ranking']}`. "
              f"Equal model scored counts: `{all_run['equal_scored_counts']}`.", '',
              '## Retained-row analysis', '',
              f"Retained mature rows: {export['retained_mature_rows']} of {export['all_run_mature_rows']}; "
              f"retained scored: {export['retained_scored_rows']} of {export['all_run_scored_rows']}. "
              f"Export truncated: `{export['truncated']}`; reported dropped: {export['reported_dropped_rows']}.", '',
              'Percentiles and route/block results use retained scored rows only. '
              'Each model is scored on the same anchors; positive MAE gain means lower absolute error than persistence.', '',
              '| Model | p50 abs bps | p90 abs bps | Retained MAE bps | Paired MAE gain bps |',
              '|---|---:|---:|---:|---:|']
    for name in MODELS:
        metric = retained['models'][name]
        lines.append(f"| {name} | {_number(metric['p50_absolute_error_bps'])} | "
                     f"{_number(metric['p90_absolute_error_bps'])} | "
                     f"{_number(metric['mean_absolute_error_bps'])} | "
                     f"{_number(metric['paired_mae_improvement_vs_persistence_bps'])} |")
    for title, groups in (('Directed routes', retained['by_directed_route']),
                          ('Five-minute anchor-time blocks (UTC)', retained['by_anchor_5min_utc'])):
        lines += ['', f'## {title}', '',
                  '| Group | Scored | Persistence MAE | Conditional linear MAE | Conditional gain |',
                  '|---|---:|---:|---:|---:|']
        shown = list(groups.items())[:MAX_MARKDOWN_GROUPS]
        for key, entry in shown:
            base = entry['models']['persistence']
            test = entry['models']['conditional_linear']
            label = key.replace('|', '\\|')
            lines.append(f"| {label} | {entry['scored_count']} | "
                         f"{_number(base['mean_absolute_error_bps'])} | "
                         f"{_number(test['mean_absolute_error_bps'])} | "
                         f"{_number(test['paired_mae_improvement_vs_persistence_bps'])} |")
        if len(groups) > len(shown):
            lines += ['', f'{len(groups)-len(shown)} further groups are in analysis.json.']
    lines += ['', 'Opposite directions and adjacent 12–16 second outcomes can be correlated. '
              'No independent significance or cash-profit inference is made. '
              'Per-block censor coverage is unavailable from this snapshot.', '']
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path, help='Stopped v2 horizon_snapshot.json')
    parser.add_argument('--out', type=Path, required=True, help='Output directory for analysis.json and report.md')
    args = parser.parse_args(argv)
    if args.snapshot.stat().st_size > MAX_SOURCE_BYTES:
        parser.error('snapshot exceeds 32 MB input cap')
    try:
        snapshot = json.loads(args.snapshot.read_text())
        report = analyze(snapshot)
    except (ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    args.out.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(report, indent=2, allow_nan=False)+'\n'
    markdown_text = render_markdown(report)
    if len(json_text.encode()) > MAX_OUTPUT_BYTES or len(markdown_text.encode()) > MAX_OUTPUT_BYTES:
        parser.error('analysis exceeds 20 MB output cap')
    (args.out/'analysis.json').write_text(json_text)
    (args.out/'report.md').write_text(markdown_text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
