"""Separate transport correction; original DNS-failed screen remains intact."""
from pathlib import Path
import core_native_funding_screen as screen

screen.PLAN = screen.ROOT / 'reports/experiment-storage/core-native-funding-network-allocation-v1.json'
screen.OUT = screen.ROOT / 'reports/core-native-funding-network-correction'

if __name__ == '__main__':
    screen.main()
