"""Run both unchanged independent auditors against the full-trace retry."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts import audit_core_passive_fair_value as formula
from scripts import audit_core_passive_fair_references as raw
R=ROOT/'reports/core-passive-fair-retry'
if __name__=='__main__':
 formula.R=R;raw.R=R
 formula.run();raw.run()
