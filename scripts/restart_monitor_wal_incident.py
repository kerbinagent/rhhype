"""Resume the existing paper ledger with smaller checkpoint batches."""
import datetime
import fcntl
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/monitor-wal-incident'
DATA = ROOT / 'data/paper-monitor-10s'

def main():
    assert not (OUT / 'process.json').exists()
    assert sum(p.stat().st_size for p in OUT.iterdir()) < 2 * 1024 * 1024 - 65536
    with (DATA / 'paper.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        db = sqlite3.connect(f'file:{DATA}/paper.sqlite3?mode=ro', uri=True)
        payload = db.execute('SELECT payload FROM engine_state').fetchone()[0]
        db.close()
        assert payload.encode() == gzip.decompress((OUT / 'pre-state.json.gz').read_bytes())
        assert (DATA / 'paper_config.json').read_bytes() == (OUT / 'pre-config.json').read_bytes()
        command = [str(ROOT / '.venv/bin/python'), 'scripts/monitor.py', '--no-tui',
                   '--holding-seconds', '10', '--take-profit-usd', '0.10',
                   '--shadow-strategies', '--report-seconds', '0.5']
        fcntl.flock(lock, fcntl.LOCK_UN)
        with (OUT / 'startup.log').open('xb') as log:
            proc = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                    stdout=log, stderr=subprocess.STDOUT,
                                    start_new_session=True)
    result = dict(pid=proc.pid, command=command,
                  launched_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  pre_state_sha256=hashlib.sha256(payload.encode()).hexdigest(),
                  paper_only=True, existing_database_preserved=True,
                  change='Checkpoint interval2s to0.5s; all economic settings unchanged')
    (OUT / 'process.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
