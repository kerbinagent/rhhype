"""Explicit transport correction after public RPC 429 before any quotes."""
import hashlib
import json
import time
from pathlib import Path
import base_atomic_cycle_screen as screen

ROOT = Path(__file__).resolve().parents[1]
screen.PLAN = ROOT/'reports/experiment-storage/base-atomic-cycle-slow-transport-allocation-v1.json'
screen.OUT = ROOT/'reports/base-atomic-cycle-slow-transport'
plan = json.loads(screen.PLAN.read_text())
for pin in plan['source_pins']:
    assert hashlib.sha256((ROOT/pin['path']).read_bytes()).hexdigest() == pin['sha256']
original_sleep = time.sleep


def slow_sleep(seconds):
    original_sleep(max(5, seconds))


if __name__ == '__main__':
    screen.time.sleep = slow_sleep
    screen.main()
