#!/usr/bin/env python3
"""Capture bounded paper audits on schedule; never edit strategy or send orders."""
import argparse
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
from pathlib import Path
import signal
import threading
import time

from paper_review import review

LOG = logging.getLogger('paper_review_loop')


def run_loop(source, out, interval, stop, *, clock=time.time, review_fn=review):
    state_path = Path(out) / 'review_state.json'
    due = float(json.loads(state_path.read_text())['next_due_at']) if state_path.exists() else clock()
    if not math.isfinite(due) or not math.isfinite(interval) or interval <= 0:
        raise ValueError('invalid review deadline or interval')
    while not stop.is_set():
        delay = due - clock()
        if delay > 0:
            stop.wait(min(60, delay))
            continue
        try:
            report = review_fn(source, out, now=clock(), interval_seconds=interval)
            due = report['next_due_at']
            LOG.info('checkpoint=%.3f next_due=%.3f', report['checkpoint_at'], due)
        except Exception:
            # Failed/stopped collectors cannot yield a new checkpoint. Retry
            # without advancing the ledger baseline or busy-looping on SQLite.
            LOG.exception('Review failed; preserving prior checkpoint')
            stop.wait(min(60, interval))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('data/paper-monitor'))
    parser.add_argument('--out', type=Path, default=Path('data/strategy-reviews'))
    parser.add_argument('--interval-seconds', type=float, default=1200)
    args = parser.parse_args()
    if not math.isfinite(args.interval_seconds) or args.interval_seconds <= 0:
        parser.error('interval must be positive and finite')
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / 'review_loop.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('A review loop already owns this output directory')
        lock.seek(0); lock.truncate(); lock.write(str(os.getpid())+'\n'); lock.flush()
        handler = RotatingFileHandler(args.out / 'review_loop.log', maxBytes=1_000_000, backupCount=1)
        logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(message)s')
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
        run_loop(args.source, args.out, args.interval_seconds, stop)


if __name__ == '__main__':
    main()
