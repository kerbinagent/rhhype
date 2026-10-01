"""New frozen low-fee NVDA universe using the audited exact-input collector."""
from pathlib import Path
import rh_atomic_stock_cycle as screen

ROOT=Path(__file__).resolve().parents[1]
screen.PLAN=ROOT/'reports/experiment-storage/rh-nvda-low-fee-cycle-allocation-v1.json'
screen.OUT=ROOT/'reports/rh-nvda-low-fee-cycle'

if __name__=='__main__':
    screen.main()
