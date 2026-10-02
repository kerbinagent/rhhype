#!/usr/bin/env python3
"""Offline metadata projection of one already captured, identified event."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import polymarket_no_basket_metadata as metadata

PLAN = ROOT / 'reports/experiment-storage/polymarket-no-basket-calendar-v1.json'
OUTPUT = ROOT / 'reports/polymarket-no-basket/calendar-review-v1.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan-sha256', required=True)
    args = parser.parse_args()
    raw_plan = PLAN.read_bytes()
    assert hashlib.sha256(raw_plan).hexdigest() == args.plan_sha256
    plan = json.loads(raw_plan)
    assert plan['status'] == 'frozen_offline_metadata_projection'
    own = Path(__file__).read_bytes()
    assert len(own) == plan['source_pin']['bytes']
    assert hashlib.sha256(own).hexdigest() == plan['source_pin']['sha256']
    metadata.verify(plan['original_plan_sha256'])
    assert not OUTPUT.exists()
    capture = plan['input']
    assert capture['path'] == 'reports/polymarket-no-basket/metadata-v1/response.body'
    with (ROOT / capture['path']).open('rb') as stream:
        raw = stream.read(capture['bytes'] + 1)
    assert len(raw) == capture['bytes'] == 26716
    assert hashlib.sha256(raw).hexdigest() == capture['sha256']
    obj = metadata.strict_json(raw)
    assert len(obj['events']) == 1
    event = obj['events'][0]
    expected = plan['identified_event']
    assert event['id'] == expected['id'] == '606422'
    assert event['slug'] == expected['slug']
    assert event['endDate'] == expected['end_utc'] == '2026-10-29T03:59:00Z'
    stamp = dt.datetime.fromisoformat(event['endDate'].replace('Z', '+00:00'))
    local = stamp.astimezone(ZoneInfo('America/New_York'))
    assert local.date().isoformat() == expected['meeting_local_date'] == '2026-10-28'
    assert stamp.date().isoformat() == expected['projection_end_utc_date'] == '2026-10-29'
    # Explicit successor selector: only the UTC date constant changes in memory.
    # Original source, captured response and v1 output remain untouched.
    metadata.DATE = expected['projection_end_utc_date']
    result = metadata.project(obj)
    result.update(schema='polymarket-no-basket-calendar-review-v1',
                  plan_sha256=args.plan_sha256,
                  original_result='inconclusive_frozen_utc_date_gate_failed',
                  input_sha256=capture['sha256'], network_requests=0,
                  calendar_basis='America/New_York meeting day',
                  end_local=local.isoformat(),
                  interpretation='Post-observation metadata calendar correction only; '
                  'original result unchanged. No economic fields inspected, no '
                  'eligibility or contract mapping inferred from the calendar match.')
    body = metadata.encoded(result)
    assert len(body) <= 131072
    with OUTPUT.open('xb') as stream:
        stream.write(body)
    print(json.dumps({'output': str(OUTPUT.relative_to(ROOT)), 'bytes': len(body),
                      'sha256': hashlib.sha256(body).hexdigest(),
                      'status': result['status'], 'network_requests': 0}))


if __name__ == '__main__':
    main()
