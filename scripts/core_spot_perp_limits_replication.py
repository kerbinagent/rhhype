"""One unchanged prospective replication; only output and frozen plan paths differ."""
import asyncio
from pathlib import Path
import core_spot_perp_limits as base
ROOT=Path(__file__).resolve().parents[1]
base.PLAN=ROOT/'reports/experiment-storage/core-spot-perp-limits-replication-v1.json'
base.OUT=ROOT/'reports/core-spot-perp-limits-replication'
if __name__=='__main__':asyncio.run(base.run())
