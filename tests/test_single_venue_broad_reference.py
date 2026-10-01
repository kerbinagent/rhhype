import unittest
from scripts.single_venue_broad_reference import collect_snapshots


def book(asset, venue, t, price, source=None):
    return dict(type='book', asset=asset, venue=venue, received_ns=t,
                source_ns=t if source is None else source, valid=True, clock_valid=True,
                bids=[[str(price), '1']], asks=[[str(price + 2), '1']])


class ReferenceTests(unittest.TestCase):
    def test_assets_with_shared_receipts_keep_distinct_pairs(self):
        t=1_000_000_000
        stream=[book('BTC','lighter',t,100), book('LIT','lighter',t,10),
                book('BTC','rh_lighter',t+1,102),book('LIT','rh_lighter',t+1,12)]
        wanted={('BTC','rh_lighter',t+1),('LIT','rh_lighter',t+1)}
        snapshots,end=collect_snapshots(stream,wanted)
        self.assertIsNone(end)
        self.assertEqual(snapshots['BTC','rh_lighter',t+1]['mids']['lighter'],'101')
        self.assertEqual(snapshots['LIT','rh_lighter',t+1]['mids']['lighter'],'11')
        self.assertTrue(all(x['pair_fresh'] for x in snapshots.values()))

    def test_invalidation_is_asset_specific_and_future_books_do_not_backfill(self):
        t=1_000_000_000
        stream=[book('BTC','lighter',t,100),book('LIT','lighter',t,10),
                dict(type='invalidate',asset='BTC',venue='lighter',received_ns=t+1),
                book('BTC','rh_lighter',t+2,102),book('LIT','rh_lighter',t+2,12),
                book('BTC','lighter',t+3,103)]
        snapshots,_=collect_snapshots(stream,{('BTC','rh_lighter',t+2),('LIT','rh_lighter',t+2)})
        self.assertFalse(snapshots['BTC','rh_lighter',t+2]['pair_fresh'])
        self.assertNotIn('lighter',snapshots['BTC','rh_lighter',t+2]['mids'])
        self.assertTrue(snapshots['LIT','rh_lighter',t+2]['pair_fresh'])

    def test_stale_crossvenue_pair_is_retained_as_unmatched(self):
        t=1_000_000_000
        stream=[book('BTC','lighter',t,100),book('BTC','rh_lighter',t+300_000_000,102),
                dict(type='end',received_ns=t+400_000_000)]
        snapshots,end=collect_snapshots(stream,{('BTC','rh_lighter',t+300_000_000)})
        self.assertFalse(next(iter(snapshots.values()))['pair_fresh'])
        self.assertEqual(end['type'],'end')


if __name__=='__main__':unittest.main()
