"""One explicit, bounded exploratory ACK replay; dry by default."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts import watch_passive_replay as watcher
from scripts import replay_passive_ack_exploratory as exploratory

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--scenario', choices=('base', 'plus200'), required=True)
parser.add_argument('--run', action='store_true')
args = parser.parse_args()
settings = watcher.preflight(watcher.Settings(
    capture=exploratory.DEFAULT_CAPTURE, protocol=exploratory.DEFAULT_PROTOCOL,
    out=ROOT / f'data/derived/rh-passive-exit-v1-restart-ack-exploratory-{args.scenario}',
    state_dir=Path(__file__).resolve().parent / args.scenario))
verified = watcher.validate_capture(settings, watcher._digest(settings.protocol))
protocol, provenance = exploratory.verify_inputs(settings.capture, settings.protocol,
    exploratory.DEFAULT_STRICT, exploratory.DEFAULT_CORRECTED)
sources = exploratory.source_snapshot(protocol)
command = [sys.executable, str(ROOT / 'scripts/replay_passive_ack_exploratory.py'),
    '--replay', '--scenario', args.scenario, '--out', str(settings.out)]
if not args.run:
    print(json.dumps({'dry_plan': True, 'scenario': args.scenario, 'command': command,
        'dependency_count': len(sources), 'maximum_replay_seconds': settings.replay_seconds,
        'maximum_log_bytes': watcher.MAX_LOG_BYTES, 'archive_bytes': verified['archive_bytes']}))
    raise SystemExit(0)

settings.state_dir.mkdir(parents=True, exist_ok=False)
implementation = {'recorded_utc': datetime.now(timezone.utc).isoformat(),
    'classification': exploratory.CLASSIFICATION, 'prospective_freeze': False,
    'source_sha256': sources, 'scenario': exploratory.scenario_plan(args.scenario),
    'provenance': provenance}
implementation_path = settings.state_dir / 'implementation.json'
implementation_path.write_text(json.dumps(implementation, indent=2) + '\n')
stopped = False


def stop(*_):
    global stopped
    stopped = True


def status(state, **details):
    record = {'schema': 'rh-passive-ack-exploratory-supervisor-v1', 'state': state,
        'updated_utc': datetime.now(timezone.utc).isoformat(), 'command': command,
        'classification': exploratory.CLASSIFICATION, 'scenario': args.scenario,
        'maximum_replay_seconds': settings.replay_seconds,
        'maximum_log_bytes': watcher.MAX_LOG_BYTES,
        'launch_source_sha256': watcher._digest(Path(__file__)),
        'bounded_runner_source_sha256': watcher._digest(ROOT / 'scripts/watch_passive_replay.py'),
        'implementation_sha256': watcher._digest(implementation_path), **verified, **details}
    body = (json.dumps(record, indent=2) + '\n').encode()
    assert len(body) <= watcher.MAX_STATUS_BYTES
    temporary = settings.state_dir / 'status.json.tmp'
    temporary.write_bytes(body)
    temporary.replace(settings.state_dir / 'status.json')


def selected_popen(original_command, **kwargs):
    assert original_command == watcher.command(settings)
    return subprocess.Popen(command, **kwargs)


for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, stop)
status('replay_running', replay_attempts=1)
try:
    reason, details = watcher.run_replay(settings, lambda: stopped, popen=selected_popen)
    status(reason, **details)
except BaseException as exc:
    status('supervisor_error', error=f'{type(exc).__name__}: {str(exc)[:500]}')
    raise
if reason != 'replay_finished':
    raise SystemExit(2 if reason == 'replay_incomplete' else 1)
