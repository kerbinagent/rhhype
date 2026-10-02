#!/usr/bin/env python3
"""Run the frozen flow preflight with the corrected ordinary-feed adapter."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import single_venue_flow_recovery as study
from scripts import single_venue_ordinary_events as ordinary

PLAN = ROOT / 'reports/experiment-storage/single-venue-flow-recovery-ordinary-feed-fix-v1.json'
OUT = ROOT / 'reports/single-venue-research/ordinary-feed-fix-v1'


def run(batch):
    previous = study.events, study.OUT
    try:
        study.events, study.OUT = ordinary, OUT
        return study.run(batch, plan_path=PLAN)
    finally:
        study.events, study.OUT = previous


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=int, choices=(1, 2), required=True)
    run(parser.parse_args().batch)
