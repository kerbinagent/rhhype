#!/usr/bin/env python3
"""Plot remaining cost budget in stopped, conditional two-maker quote screens."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ('BTC', 'ETH', 'NVDA', 'XAG')
SIZES = (100, 250, 500, 1000)


def render(source: Path, out: Path) -> dict:
    if source.stat().st_size > 16_000_000:
        raise ValueError('input exceeds 16 MB bound')
    groups = defaultdict(list)
    with source.open(newline='') as stream:
        for count, row in enumerate(csv.DictReader(stream), 1):
            if count > 10_000:
                raise ValueError('row cap exceeded')
            if row['stage'] != 'static' or row['side'] != 'buy_rh':
                continue
            for venue in ('hl', 'core'):
                notional = max(float(row[f'{venue}_rh_entry']),
                               float(row[f'{venue}_hedge_entry']))
                if notional <= 0:
                    raise ValueError('nonpositive original notional')
                # Negative means the target is missed before additional cost.
                value = (float(row[f'{venue}_fee_only']) - .10) / notional * 10_000
                groups[(venue, row['asset'], int(row['budget_usd']))].append(value)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.colors import TwoSlopeNorm

    expected = {(v, a, s) for v in ('hl', 'core') for a in ASSETS for s in SIZES}
    if set(groups) != expected or any(not values for values in groups.values()):
        raise ValueError('incomplete group inventory')
    rows = [dict(hedge_venue=v, asset=a, budget_usd=s, observations=len(groups[(v, a, s)]),
                 median_headroom_bps=median(groups[(v, a, s)]))
            for v, a, s in sorted(expected)]
    if not all(np.isfinite(r['median_headroom_bps']) for r in rows):
        raise ValueError('nonfinite headroom')
    low = min(-1, min(r['median_headroom_bps'] for r in rows))
    high = max(1, max(r['median_headroom_bps'] for r in rows))
    norm = TwoSlopeNorm(vmin=low, vcenter=0, vmax=high)
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 5.8))
    for ax, venue, title in zip(axes, ('hl', 'core'), ('Hyperliquid hedge', 'Lighter Core hedge')):
        values = np.array([[median(groups[(venue, a, s)]) for s in SIZES] for a in ASSETS])
        plot = ax.imshow(values, cmap='RdYlGn', norm=norm, aspect='auto')
        ax.set_title(title, fontsize=13, pad=12)
        ax.set_xticks(range(4), [f'${size:,}' for size in SIZES])
        ax.set_yticks(range(4), ASSETS)
        ax.set_xlabel('RH order budget')
        for i in range(4):
            for j in range(4):
                rgba = plot.cmap(norm(values[i, j]))
                brightness = .2126*rgba[0] + .7152*rgba[1] + .0722*rgba[2]
                ax.text(j, i, f'{values[i, j]:+.2f}', ha='center', va='center',
                        color='black' if brightness > .55 else 'white', fontsize=12)
    fig.suptitle('Additional cost budget left after a $0.10 target', fontsize=16, y=.97)
    fig.text(.5, .89, 'Median basis points per original leg notional; negative values already miss the target',
             ha='center', fontsize=10)
    fig.subplots_adjust(left=.07, right=.84, bottom=.24, top=.79, wspace=.25)
    color_ax = fig.add_axes([.88, .28, .022, .49])
    fig.colorbar(plot, cax=color_ax, label='Basis points')
    fig.text(.07, .13, 'Conditional unchanged-book screen: both RH maker fills assumed. No group covers an additional 5 bp.',
             fontsize=10)
    fig.text(.07, .075, 'Stopped 29 Sep 2026 samples; Standard fees; USDG/USDC parity.\n'
             'No observed maker fills, delayed hedge execution, conversion, or portfolio return.', fontsize=9)
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out/'cost-headroom.svg', metadata={'Date': None})
    fig.savefig(out/'cost-headroom.png', dpi=160)
    plt.close(fig)
    result = {'classification': 'conditional static quote screen, not fills or expected profit',
              'source': str(source), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'target_usd': .10, 'headroom_unit': 'bps of max original entry leg notional', 'groups': rows}
    (out/'cost-headroom.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'reports/passive-hedge-venues/matched-rows.csv')
    parser.add_argument('--out', type=Path, default=ROOT/'reports/passive-hedge-venues')
    args = parser.parse_args()
    result = render(args.source, args.out)
    print(json.dumps({'groups': len(result['groups']), 'out': str(args.out)}))
