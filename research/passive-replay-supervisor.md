# Bounded passive replay supervisor

`scripts/watch_passive_replay.py` supervises one already authorized public capture
and one replay. It does not capture, refreeze the protocol, change strategy, or
start another experiment. The default command prints a plan and writes nothing.

The approved restart capture is `data/raw/rh-passive-exit-v1/20260930T0252Z`, with
`reports/rh-passive-exit-v1-restart/protocol.json` frozen before capture. The
detached capture was launched as PID 3045038 with a 3000-second duration, ending
around 2026-09-30 03:42:58 UTC. The supervisor never signals that PID.

The capture writes its manifest directly. The supervisor waits for matching
manifest size and SHA-256 on two reads separated by one polling interval before
validation. This stability wait shares the 3600-second manifest deadline and
responds to stop signals. Stable invalid JSON is rejected after that check.

Before replay, the supervisor requires a finalized `duration_limit` manifest,
an explicitly untruncated read-only capture, the configured 3000 seconds and
the full elapsed timeline. The existing `verify_protocol` checks all frozen
source hashes, metadata, universe, and timeline. The supervisor additionally
pins the protocol bytes across the wait, checks the archive SHA-256, and bounds
archive size and entry count. Malformed or invalid manifest objects fail closed.
No incomplete capture is retried automatically.

Capture, protocol, output, and supervisor paths must stay under the workspace's
`data/raw`, `reports`, `data/derived`, and `reports` directories respectively.
Symlink paths are rejected. Both output and supervisor state directories must
be new, so prior data is preserved. A second watcher with the same state directory
fails before replay. The analyzer independently refuses an existing output.

## Inspect and launch

Run from `/home/harry/projects/research/rhhype`:

```bash
.venv/bin/python scripts/watch_passive_replay.py
```

After reviewing that plan, detach the explicit run so chat interruption does not
interrupt the supervisor:

```bash
nohup .venv/bin/python scripts/watch_passive_replay.py --run </dev/null >/dev/null 2>&1 &
```

The PID printed by the shell belongs to the supervisor. To stop it gracefully,
send `SIGTERM` to that PID. It stops waiting or terminates only the replay's own
process group, with a three-second grace period and `SIGKILL` cleanup. Forced
`SIGKILL` of the supervisor cannot run its cleanup handler; use `SIGTERM`.

The maximum manifest wait is 3600 seconds, followed by at most 3600 seconds of
replay plus termination grace. `--wait-seconds` and `--replay-seconds` may reduce
those bounds. `--poll-seconds` ranges above zero through five seconds. The
supervisor launches the existing analyzer once:

```bash
.venv/bin/python scripts/analyze_rh_passive_exit.py replay \
  --capture data/raw/rh-passive-exit-v1/20260930T0252Z \
  --protocol reports/rh-passive-exit-v1-restart/protocol.json \
  --out data/derived/rh-passive-exit-v1-restart
```

## Inspect completion

`reports/rh-passive-exit-v1-restart/supervisor/status.json` is atomically replaced
and bounded to 16 KB. It records waiting, replaying, or a final state, archive and
protocol hashes, replay exit code, and the number of replay attempts. It is a
supervisor status, not an inference about executable fills or profitability.

`replay.log` in that directory contains at most 1 MB of merged replay stdout and
stderr. The supervisor continues draining and discarding excess output so the
child cannot block on a full pipe; discarded bytes are recorded in final status.
Replay evidence remains in the analyzer's bounded output files. A timeout or
stop preserves partial output and the log; the watcher never removes files.

Exit codes: 0 is `replay_finished`; 2 is `replay_incomplete`; 3 is `wait_timeout`;
4 is `replay_timeout`; 130 is `stopped`; 1 is rejection or replay failure.
An incomplete replay's unknown terminal inventory, excluded cohorts, and
errors remain in `analysis.json` and `REPORT.md`. The supervisor never assigns
unknown outcomes zero value or revises the result. Review those artifacts before
deciding on further work.

Offline verification:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_watch_passive_replay.py'
```

Tests use temporary captures, fake clocks, and fake processes. They do not start
a capture or run the research replay.
