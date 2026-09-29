"""Rate-gated Hyperliquid REST refresh for books needed by paper execution.

The public l2Book WebSocket currently sends snapshots roughly every five seconds.
This service requests fresh books only for due paper intents, due latency probes,
and held exposure. The shared legacy Client gate enforces the venue's REST budget.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict

import aiohttp


def _targets(engine, now):
    """Return priority by market key: exit 0, entry 1, probe 2, held 3."""
    targets = {}
    for position in engine.positions.values():
        for leg in position['legs']:
            if leg['venue'] != 'hyperliquid':
                continue
            market_key = leg['key']
            intent = leg.get('intent')
            if intent and intent['due'] <= now <= intent['expires']:
                priority = 0 if intent['kind'] == 'exit' else 1
                targets[market_key] = min(priority, targets.get(market_key, 4))
            elif leg.get('remaining', 0) > 0:
                targets[market_key] = min(3, targets.get(market_key, 4))
    for probe in engine.probes.values():
        if probe['due'] > now:
            continue
        signal = probe['signal']
        for market_key in (signal['buy'], signal['sell']):
            if (market_key.startswith('hyperliquid:') and
                    market_key not in probe.get('after', {})):
                targets[market_key] = min(2, targets.get(market_key, 4))
    return targets


def _market_for_key(engine, market_key):
    market = engine.market_meta.get(market_key)
    if market is not None:
        return market
    # A held position can outlive discovery of its original pair.
    for position in engine.positions.values():
        for leg in position['legs']:
            if leg['key'] == market_key:
                return {'venue': leg['venue'], 'market': leg['market']}
    return None


def _prune_history(history, live, now):
    active = sorted(((k, t) for k, t in history.items() if k in live),
                    key=lambda item: item[1], reverse=True)[:1024]
    remaining = 1024-len(active)
    recent = sorted(((k, t) for k, t in history.items()
                     if k not in live and now-t < 60),
                    key=lambda item: item[1], reverse=True)[:remaining]
    return defaultdict(float, active+recent)


async def run_hl_refresh(engine, client, on_book, stop: asyncio.Event, *,
                         interval=0.05, min_key_interval=0.5, max_concurrent=3):
    """Keep selected HL books fresh while preserving stream reconnect semantics.

    `client` is the monitor's shared legacy.Client, including its per-venue REST
    gate. A REST response is tagged with the still-current stream generation;
    disconnects, rebuilds and newer stream books cause the response to be dropped.
    """
    if interval <= 0 or min_key_interval <= 0 or max_concurrent < 1:
        raise ValueError('refresh intervals and concurrency must be positive')
    last_request = defaultdict(float)
    inflight = set()
    tasks = set()
    # Urgent entries/exits get three of six turns; probes and held exposure
    # retain scheduled opportunities even during a sustained entry burst.
    slots = (0, 1, 0, 2, 0, 3)
    turn = 0

    async def refresh(market_key, market, generation, started):
        try:
            engine.stats['target_refresh_requests'] += 1
            result = await client.book(market)
            current = engine.books.get(market_key)
            if not current or not current.get('valid') or current.get('generation') != generation:
                engine.stats['target_refresh_skipped_generation'] += 1
                return
            received = result['received']
            engine_time = result.get('engine_time')
            current_time = current.get('engine_time')
            if (received < started or received <= current['received'] or
                    (engine_time is not None and current_time is not None and
                     engine_time < current_time)):
                engine.stats['target_refresh_skipped_old'] += 1
                return
            bids, asks = result['levels']
            on_book({'venue': 'hyperliquid', 'market': market['market'],
                     'bids': bids, 'asks': asks, 'received': received,
                     'engine_time': engine_time,
                     'sequence': f"rest:{engine_time}" if engine_time is not None else None,
                     'generation': generation, 'valid': True,
                     'source': 'targeted_rest'})
            engine.stats['target_refresh_successes'] += 1
        except asyncio.CancelledError:
            raise
        except (aiohttp.ClientError, OSError, RuntimeError, KeyError, TypeError, ValueError,
                asyncio.TimeoutError) as exc:
            # A failed targeted request must not poison a healthy stream book.
            engine.stats['target_refresh_errors'] += 1
            engine.stats[f'target_refresh_error_{type(exc).__name__}'] += 1
        finally:
            inflight.discard(market_key)

    try:
        while not stop.is_set():
            now = time.time()
            targets = _targets(engine, now)
            if len(last_request) > 512:
                # Discovery can change the market universe for days. Keep
                # recent/active keys and a hard bound on scheduling history.
                last_request = _prune_history(last_request, set(targets) | inflight, now)
            while len(tasks) < max_concurrent:
                ready = defaultdict(list)
                for market_key, priority in targets.items():
                    if market_key in inflight or now-last_request[market_key] < min_key_interval:
                        continue
                    current = engine.books.get(market_key)
                    market = _market_for_key(engine, market_key)
                    if (not market or market.get('venue') != 'hyperliquid' or
                            not current or not current.get('valid') or
                            current.get('generation') is None):
                        continue
                    ready[priority].append(market_key)
                if not ready:
                    break
                desired = slots[turn % len(slots)]
                turn += 1
                priority = desired if ready.get(desired) else min(ready)
                market_key = min(ready[priority], key=lambda k: (last_request[k], k))
                current = engine.books[market_key]
                last_request[market_key] = now
                inflight.add(market_key)
                task = asyncio.create_task(refresh(market_key, _market_for_key(engine, market_key),
                                                   current['generation'], now))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
