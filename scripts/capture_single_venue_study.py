"""Two public market data feeds; no wallet, authentication or trading requests."""
import asyncio
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
import scripts.core_passive_lit_capture as capture

def both_trade_feeds(venue,markets):
    return [{'type':'subscribe','channel':f'{feed}/{market}'}
            for market in markets.values() for feed in ('order_book','trade')]

def main():
    capture.PLAN=ROOT/'reports/experiment-storage/single-venue-research-v1.json'
    capture.OUT=ROOT/'reports/single-venue-capture'
    capture.HARD_BYTES=4325376
    capture.subscriptions=both_trade_feeds
    asyncio.run(capture.main())

if __name__=='__main__':main()
