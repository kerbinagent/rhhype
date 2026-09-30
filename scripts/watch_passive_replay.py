#!/usr/bin/env python3
"""Wait for one approved public capture and run its frozen replay once.

Dry plan by default. This supervisor never starts a capture or changes a policy.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.analyze_rh_passive_exit import verify_protocol

MAX_WAIT_SECONDS = 3600
MAX_REPLAY_SECONDS = 3600
MAX_LOG_BYTES = 1_000_000
MAX_STATUS_BYTES = 16_000
MAX_JSON_BYTES = 1_000_000
RAW_CAP = 384_000_000
DEFAULT_CAPTURE = ROOT / 'data/raw/rh-passive-exit-v1/20260930T0252Z'
DEFAULT_PROTOCOL = ROOT / 'reports/rh-passive-exit-v1-restart/protocol.json'
DEFAULT_OUT = ROOT / 'data/derived/rh-passive-exit-v1-restart'
DEFAULT_STATE = ROOT / 'reports/rh-passive-exit-v1-restart/supervisor'


@dataclass(frozen=True)
class Settings:
    capture: Path = DEFAULT_CAPTURE
    protocol: Path = DEFAULT_PROTOCOL
    out: Path = DEFAULT_OUT
    state_dir: Path = DEFAULT_STATE
    wait_seconds: float = MAX_WAIT_SECONDS
    replay_seconds: float = MAX_REPLAY_SECONDS
    poll_seconds: float = 1.0


def _digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _json_bytes(path):
    with Path(path).open('rb') as stream:
        body = stream.read(MAX_JSON_BYTES + 1)
    if len(body) > MAX_JSON_BYTES:
        raise ValueError('JSON exceeds 1 MB bound')
    return body


def _object(path):
    value = json.loads(_json_bytes(path))
    if not isinstance(value, dict):
        raise ValueError('JSON object required')
    return value


def _under(path, base):
    path = Path(path).absolute()
    if path.is_symlink() or not path.resolve().is_relative_to(base.resolve()):
        raise ValueError(f'path must be inside {base}: {path}')
    # Reject symlinks in parents as well, including dangling output links.
    if any(part.is_symlink() for part in (path, *path.parents) if part != ROOT.parent):
        raise ValueError(f'symlink path rejected: {path}')
    return path.resolve()


def preflight(settings):
    """Validate paths and bounds without creating files or replaying anything."""
    capture = _under(settings.capture, ROOT / 'data/raw')
    protocol = _under(settings.protocol, ROOT / 'reports')
    out = _under(settings.out, ROOT / 'data/derived')
    state = _under(settings.state_dir, ROOT / 'reports')
    if not capture.is_dir() or not protocol.is_file():
        raise ValueError('existing capture directory and protocol file required')
    if protocol.name != 'protocol.json':
        raise ValueError('protocol.json required')
    if out.exists() or state.exists():
        raise ValueError('output and supervisor state directories must both be new')
    if state == protocol.parent or protocol.is_relative_to(state):
        raise ValueError('supervisor state must not contain the protocol')
    for value, maximum, name in ((settings.wait_seconds, MAX_WAIT_SECONDS, 'wait'),
                                  (settings.replay_seconds, MAX_REPLAY_SECONDS, 'replay'),
                                  (settings.poll_seconds, 5, 'poll')):
        if isinstance(value, bool) or not math.isfinite(value) or not 0 < value <= maximum:
            raise ValueError(f'invalid {name} seconds; maximum is {maximum}')
    _object(protocol)
    return Settings(capture, protocol, out, state, settings.wait_seconds,
                    settings.replay_seconds, settings.poll_seconds)


def command(settings):
    return [sys.executable, str(ROOT / 'scripts/analyze_rh_passive_exit.py'),
            'replay', '--capture', str(settings.capture), '--protocol',
            str(settings.protocol), '--out', str(settings.out)]


def _status(settings, state, **details):
    value = {'schema': 'rh-passive-replay-supervisor-v1', 'state': state,
             'updated_utc': datetime.now(timezone.utc).isoformat(),
             'capture': str(settings.capture), 'protocol': str(settings.protocol),
             'out': str(settings.out), 'replay_attempts': 0, **details}
    body = json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode() + b'\n'
    if len(body) > MAX_STATUS_BYTES:
        raise ValueError('supervisor status exceeds bound')
    temporary = settings.state_dir / 'status.json.tmp'
    with temporary.open('wb') as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, settings.state_dir / 'status.json')


def validate_capture(settings, protocol_hash, *, verifier=verify_protocol):
    """Fail closed on a finalized capture; keep the existing verifier authoritative."""
    manifest_path = settings.capture / 'manifest.json'
    if manifest_path.is_symlink():
        raise ValueError('symlink manifest rejected')
    manifest = _object(manifest_path)
    if manifest.get('end_reason') != 'duration_limit' or manifest.get('truncated') is not False:
        raise ValueError('complete duration_limit capture required')
    if manifest.get('read_only') is not True or type(manifest.get('configured_seconds')) is not int:
        raise ValueError('read-only 3000-second capture required')
    if manifest['configured_seconds'] != 3000:
        raise ValueError('read-only 3000-second capture required')
    if _digest(settings.protocol) != protocol_hash:
        raise ValueError('protocol changed while waiting')
    _, verified, start, _, end = verifier(settings.protocol, settings.capture)
    if verified != manifest or end < start + 3000 * 1_000_000_000:
        raise ValueError('capture did not complete its frozen timeline')
    frames = settings.capture / 'frames.jsonl.gz'
    claimed = manifest.get('frames_sha256')
    if (not isinstance(claimed, str) or len(claimed) != 64
            or any(c not in '0123456789abcdef' for c in claimed)):
        raise ValueError('valid raw SHA-256 required')
    total, entries = 0, 0
    for path in settings.capture.rglob('*'):
        entries += 1
        if entries > 256 or path.is_symlink():
            raise ValueError('capture archive has too many entries or a symlink')
        if path.is_file():
            total += path.stat().st_size
            if total > RAW_CAP:
                raise ValueError('capture archive exceeds raw byte cap')
    if not frames.is_file() or _digest(frames) != claimed:
        raise ValueError('raw archive hash mismatch')
    return {'protocol_sha256': protocol_hash, 'manifest_sha256': _digest(manifest_path),
            'frames_sha256': claimed, 'archive_bytes': total}


def terminate_group(process, *, killpg=os.killpg):
    """Only the replay's new session is signaled, never the capture or supervisor."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        if sig == signal.SIGTERM:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
    process.wait(timeout=3)


def run_replay(settings, stopped, *, popen=subprocess.Popen, monotonic=time.monotonic,
               selector_factory=selectors.DefaultSelector, killpg=os.killpg):
    """Drain stdout even after the log cap; regularly check stop and deadline."""
    process = popen(command(settings), cwd=ROOT, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, start_new_session=True, bufsize=0)
    written = discarded = 0
    reason = None
    deadline = monotonic() + settings.replay_seconds
    try:
        os.set_blocking(process.stdout.fileno(), False)
        with selector_factory() as selector, (settings.state_dir / 'replay.log').open('xb') as log:
            selector.register(process.stdout, selectors.EVENT_READ)
            eof = False
            while True:
                if stopped():
                    reason = 'stopped'
                    break
                if monotonic() >= deadline:
                    reason = 'replay_timeout'
                    break
                for key, _ in selector.select(timeout=0.2):
                    try:
                        block = os.read(key.fileobj.fileno(), 65_536)
                    except BlockingIOError:
                        continue
                    if not block:
                        selector.unregister(key.fileobj)
                        eof = True
                        continue
                    keep = min(len(block), MAX_LOG_BYTES - written)
                    if keep:
                        log.write(block[:keep])
                        log.flush()
                    written += keep
                    discarded += len(block) - keep
                code = process.poll()
                if code is not None and eof:
                    reason = ('replay_finished' if code == 0 else
                              'replay_incomplete' if code == 2 else 'replay_failed')
                    break
        if reason in ('stopped', 'replay_timeout'):
            terminate_group(process, killpg=killpg)
        return reason, {'replay_attempts': 1, 'replay_pid': process.pid,
                        'replay_exit_code': process.poll(), 'log_bytes': written,
                        'discarded_log_bytes': discarded,
                        'analysis_path': str(settings.out / 'analysis.json')}
    except BaseException:
        terminate_group(process, killpg=killpg)
        raise
    finally:
        process.stdout.close()


def supervise(settings, stopped=lambda: False, *, monotonic=time.monotonic,
              sleep=time.sleep, validator=validate_capture, runner=run_replay):
    settings = preflight(settings)
    # Exclusive state ownership also prevents competing watchers with the same plan.
    settings.state_dir.mkdir(parents=True, exist_ok=False)
    details = {'protocol_sha256': _digest(settings.protocol), 'replay_attempts': 0}
    _status(settings, 'waiting_for_manifest', **details)
    deadline = monotonic() + settings.wait_seconds
    try:
        previous_manifest = None
        while True:
            if stopped():
                _status(settings, 'stopped', **details)
                return 130
            remaining = deadline - monotonic()
            if remaining <= 0:
                _status(settings, 'wait_timeout', **details)
                return 3
            manifest_path = settings.capture / 'manifest.json'
            if manifest_path.is_symlink():
                raise ValueError('symlink manifest rejected')
            try:
                body = _json_bytes(manifest_path)
            except FileNotFoundError:
                previous_manifest = None
            else:
                fingerprint = (len(body), hashlib.sha256(body).hexdigest())
                # The capture writes this file directly. Require unchanged bytes
                # on two reads separated by a poll before parsing or verifying.
                if fingerprint == previous_manifest:
                    break
                previous_manifest = fingerprint
            sleep(min(settings.poll_seconds, remaining))
        if stopped():
            _status(settings, 'stopped', **details)
            return 130
        if monotonic() >= deadline:
            _status(settings, 'wait_timeout', **details)
            return 3
        details.update(validator(settings, details['protocol_sha256']))
        # The analyzer also independently refuses any existing output directory.
        if settings.out.exists() or settings.out.is_symlink():
            raise ValueError('output must still be a new directory')
        if stopped():
            _status(settings, 'stopped', **details)
            return 130
        details['replay_attempts'] = 1
        _status(settings, 'replaying', **details)
        reason, replay_details = runner(settings, stopped)
        details.update(replay_details)
        _status(settings, reason, **details)
        return {'replay_finished': 0, 'replay_incomplete': 2, 'stopped': 130,
                'replay_timeout': 4}.get(reason, 1)
    except Exception as exc:
        _status(settings, 'rejected_or_failed', **details,
                error_type=type(exc).__name__, error=str(exc)[:2000])
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, default=DEFAULT_CAPTURE)
    parser.add_argument('--protocol', type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--state-dir', type=Path, default=DEFAULT_STATE)
    parser.add_argument('--wait-seconds', type=float, default=MAX_WAIT_SECONDS)
    parser.add_argument('--replay-seconds', type=float, default=MAX_REPLAY_SECONDS)
    parser.add_argument('--poll-seconds', type=float, default=1)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args(argv)
    settings = Settings(args.capture, args.protocol, args.out, args.state_dir,
                        args.wait_seconds, args.replay_seconds, args.poll_seconds)
    try:
        settings = preflight(settings)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    if not args.run:
        print(json.dumps({'mode': 'dry_plan', 'command': command(settings),
                          'wait_seconds': settings.wait_seconds,
                          'replay_seconds': settings.replay_seconds,
                          'max_log_bytes': MAX_LOG_BYTES,
                          'status_path': str(settings.state_dir / 'status.json')}, indent=2))
        return 0
    stop = [False]
    def request_stop(signum, frame):
        stop[0] = True
    prior = {sig: signal.signal(sig, request_stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        return supervise(settings, lambda: stop[0])
    finally:
        for sig, handler in prior.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    raise SystemExit(main())
