"""Configure the sealed one-market adapter before the pinned diagnostic."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from scripts.core_spot_passive_skew500 import configure
from scripts.spot_basis_horizon_diagnostic import main

if __name__ == '__main__':
    configure()
    main()
