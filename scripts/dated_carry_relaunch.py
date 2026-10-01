#!/usr/bin/env python3
"""Run the explicitly authorized fresh study inside the original 16 MiB allowance.

The retired run keeps a 1 MiB reservation. The fresh run has 15 MiB, enforced
by reducing only its sample category from 8 MiB to 7 MiB. Original source
files and the interrupted run's evidence remain unchanged.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

try:
    from scripts import dated_carry_collector as collector
    from scripts import dated_carry_endpoint as endpoint
    from scripts import prepare_dated_carry as metadata
except ModuleNotFoundError:
    import dated_carry_collector as collector
    import dated_carry_endpoint as endpoint
    import prepare_dated_carry as metadata


STUDY = collector.ROOT / 'reports/dated-carry/20261001-v2'
RETIRED = collector.ROOT / 'reports/dated-carry/20260930-v1'
RETIRED_FREEZE_SHA = 'f39389c3c10626e7499f96131586f5543b8c55b5cfabbc589442777da2f5e37a'
RETIRED_INDEX_SHA = '4b15af4f7c06ad9745b69da8a8f291efa4a385fe2239ec3d16b41a76d4599cb1'
RETIRED_CAP = 1 << 20
FRESH_CAP = 15 << 20
FRESH_SAMPLE_CAP = 7 << 20
BASE_STORE = collector.Store
REQUIRED_PINS = {
    'scripts/dated_carry_relaunch.py',
    'tests/test_dated_carry_relaunch.py',
    'research/dated-carry-relaunch-v2.md',
    'reports/experiment-storage/dated-carry-relaunch-allocation-v2.json',
}


def retired_usage():
    """Inspect accounting and trusted identity only, never quote contents."""
    frozen = collector.read(RETIRED / 'source_control/freeze.json', 131072)
    if collector.digest(frozen) != RETIRED_FREEZE_SHA:
        raise ValueError('retired_freeze_changed')
    index = collector.read(RETIRED / 'terminal/index.json', collector.INDEX_RESERVE)
    if collector.digest(index) != RETIRED_INDEX_SHA:
        raise ValueError('retired_last_index_changed')
    frozen_record = json.loads(frozen)
    external = collector.verify_pins(frozen_record, RETIRED.resolve())
    if external != frozen_record['external_bytes']:
        raise ValueError('retired_external_accounting_changed')
    usage = BASE_STORE(RETIRED, external_bytes=external).usage()
    if sum(usage.values()) > RETIRED_CAP:
        raise collector.BudgetExceeded('retired_run_exceeds_1_MiB_reservation')
    return usage


class FreshStore(BASE_STORE):
    def __init__(self, study_dir: Path, **kwargs):
        if Path(study_dir).resolve() != STUDY.resolve():
            raise ValueError('fresh_run_path_required')
        super().__init__(study_dir, **kwargs)

    def usage(self):
        retired_usage()
        usage = super().usage()
        if sum(usage.values()) > FRESH_CAP:
            raise collector.BudgetExceeded('fresh_run_exceeds_15_MiB_reservation')
        return usage


def install_budget():
    # This mutation is process-local; original source files and v1 freeze stay
    # unchanged. A direct v1 launcher cannot accept v2's different constants.
    retired_usage()
    collector.CAPS['samples'] = FRESH_SAMPLE_CAP
    if sum(collector.CAPS.values()) != FRESH_CAP:
        raise ValueError('fresh_category_caps_must_sum_to_15_MiB')
    collector.CONSTANTS['storage_envelope'] = {
        'retired_cap_bytes': RETIRED_CAP,
        'fresh_cap_bytes': FRESH_CAP,
        'combined_cap_bytes': RETIRED_CAP + FRESH_CAP,
        'retired_index_sha256': RETIRED_INDEX_SHA,
        'retired_freeze_sha256': RETIRED_FREEZE_SHA,
    }
    collector.Store = FreshStore


def check_pins(pins):
    if not REQUIRED_PINS <= pins.keys():
        raise ValueError('fresh_budget_wrapper_and_method_must_be_pinned')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('dry', 'metadata', 'freeze', 'launch', 'finalize'))
    parser.add_argument('--source-pins', type=Path)
    parser.add_argument('--t0-utc')
    parser.add_argument('--config-sha256')
    parser.add_argument('--freeze-sha256')
    args = parser.parse_args(argv)
    install_budget()
    config = STUDY / 'source_control/config.json'
    freeze = STUDY / 'source_control/freeze.json'
    if args.mode == 'dry':
        print(json.dumps({'network_performed': False, 'study_dir': str(STUDY),
                          'retired_usage': retired_usage(), 'constants': collector.CONSTANTS}))
        return 0
    if args.mode == 'metadata':
        if not args.source_pins or not args.t0_utc:
            parser.error('metadata requires source-pins and t0-utc')
        check_pins(json.loads(collector.read(args.source_pins, 131072)))
        asyncio.run(metadata.prepare(SimpleNamespace(study_dir=STUDY,
                     source_pins=args.source_pins, t0_utc=args.t0_utc)))
        return 0
    if not args.config_sha256:
        parser.error('config-sha256 required')
    check_pins(collector.load_config(config, args.config_sha256)['source_sha256'])
    if args.mode == 'freeze':
        collector.prepare(config, args.config_sha256, STUDY, freeze)
        print(json.dumps({'network_performed': False, 'freeze_sha256':
                          collector.digest(collector.read(freeze, 131072))}))
        return 0
    if not args.freeze_sha256:
        parser.error('freeze-sha256 required')
    return endpoint.main(['--' + args.mode, '--study-dir', str(STUDY),
                          '--config', str(config), '--config-sha256', args.config_sha256,
                          '--freeze', str(freeze), '--freeze-sha256', args.freeze_sha256])


if __name__ == '__main__':
    raise SystemExit(main())
