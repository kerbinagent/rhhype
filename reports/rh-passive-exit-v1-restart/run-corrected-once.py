"""One bounded corrected replay of an already completed, verified capture."""
from datetime import datetime, timezone
import json
from pathlib import Path
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts import watch_passive_replay as watcher
from scripts import replay_passive_retirement_corrected as correction

settings = watcher.Settings(capture=correction.DEFAULT_CAPTURE,
    protocol=correction.DEFAULT_PROTOCOL, out=correction.DEFAULT_OUT,
    state_dir=ROOT / 'reports/rh-passive-exit-v1-restart/corrected-supervisor')
settings = watcher.preflight(settings)
verified = watcher.validate_capture(settings, watcher._digest(settings.protocol))
correction.verify_correction(correction.DEFAULT_FREEZE, settings.protocol, settings.capture)
settings.state_dir.mkdir(parents=True, exist_ok=False)
command = [sys.executable, str(ROOT / 'scripts/replay_passive_retirement_corrected.py'),
           'replay', '--capture', str(settings.capture), '--protocol', str(settings.protocol),
           '--correction-freeze', str(correction.DEFAULT_FREEZE), '--out', str(settings.out)]
stopped = False


def stop(*_):
    global stopped
    stopped = True


def status(state, **details):
    record = {'schema': 'rh-passive-corrected-replay-supervisor-v1', 'state': state,
        'updated_utc': datetime.now(timezone.utc).isoformat(),
        'command': command, 'implementation_variant': correction.VARIANT,
        'maximum_replay_seconds': settings.replay_seconds,
        'maximum_log_bytes': watcher.MAX_LOG_BYTES,
        'launch_source_sha256': watcher._digest(Path(__file__)),
        'bounded_runner_source_sha256': watcher._digest(ROOT / 'scripts/watch_passive_replay.py'),
        **verified, **details}
    body = (json.dumps(record, indent=2) + '\n').encode()
    assert len(body) <= watcher.MAX_STATUS_BYTES
    temporary = settings.state_dir / 'status.json.tmp'
    temporary.write_bytes(body)
    temporary.replace(settings.state_dir / 'status.json')


def corrected_popen(original_command, **kwargs):
    assert original_command == watcher.command(settings)
    return subprocess.Popen(command, **kwargs)


for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, stop)
status('replay_running', replay_attempts=1)
try:
    reason, details = watcher.run_replay(settings, lambda: stopped, popen=corrected_popen)
    status(reason, **details)
except BaseException as exc:
    status('supervisor_error', error=f'{type(exc).__name__}: {str(exc)[:500]}')
    raise
if reason != 'replay_finished':
    raise SystemExit(2 if reason == 'replay_incomplete' else 1)
