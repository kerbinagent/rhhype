"""Broader native spot/perp universe; all trading rules match frozen limits engine."""
import asyncio
from pathlib import Path
import core_spot_perp_limits as base
ROOT=Path(__file__).resolve().parents[1]
base.PLAN=ROOT/'reports/experiment-storage/core-spot-perp-alts-v1.json'
base.OUT=ROOT/'reports/core-spot-perp-alts'
base.ASSETS=['SKY','UNI','AAVE','LINK','LDO']
if __name__=='__main__':asyncio.run(base.run())
