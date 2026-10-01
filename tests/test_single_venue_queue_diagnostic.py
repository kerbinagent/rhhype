import unittest
from decimal import Decimal as D
from scripts.single_venue_queue_diagnostic import diagnose,imbalance,NS

def book(t,bid=99,ask=100,bq=9,aq=1,**kw):
    e=dict(type='book',asset='BTC',venue='lighter',received_ns=int(t*NS),source_ns=int(t*NS),
           bids=[[bid,bq]],asks=[[ask,aq]],valid=True,clock_valid=True,generation=1)
    e.update(kw);return e
META={'lighter':{'BTC':dict(qty_step='0.01',min_qty='0.01',min_notional='1')}}
def run(events):
    events=events+[dict(type='end',received_ns=600*NS)]
    return next(r for r in diagnose(events,META,0,['BTC']) if r['venue']=='lighter' and r['bucket']=='high')

class QueueDiagnosticTest(unittest.TestCase):
    def test_signed_long_short_values_and_delays(self):
        self.assertEqual(imbalance(book(3)),D('.8'))
        long=run([book(3),book(3.3,bid=90,ask=91),book(3.4),book(13.7,bid=99,ask=100),book(13.8,bid=100,ask=101)])
        self.assertEqual(long['counts']['matched'],1)
        self.assertEqual(D(long['signed_delayed_quote_bps']['mean']),0)
        self.assertGreater(D(long['signed_delayed_midpoint_bps']['mean']),0)
        short=run([book(3,bq=1,aq=9),book(3.4,bq=1,aq=9),book(13.8,bid=98,ask=99,bq=1,aq=9)])
        self.assertEqual(short['counts']['matched'],1)
        self.assertEqual(D(short['signed_delayed_quote_bps']['mean']),0)
        self.assertGreater(D(short['signed_delayed_midpoint_bps']['mean']),0)
    def test_first_eligible_bad_book_is_not_retried(self):
        row=run([book(3),book(3.4,valid=False),book(3.5),book(13.9,bid=101,ask=102)])
        self.assertEqual(row['counts']['missing_first_eligible'],1)
        self.assertEqual(row['signed_delayed_quote_bps']['n'],0)
    def test_overlapping_pending_and_invalidation(self):
        row=run([book(3),book(3.4),book(4),book(4.4),
                 dict(type='invalidate',asset='BTC',venue='lighter',received_ns=5*NS)])
        self.assertEqual(row['counts']['admitted'],2)
        self.assertEqual(row['counts']['invalidated'],2)
    def test_generation_and_notional_cap(self):
        row=run([book(3),book(3.4,generation=2)])
        self.assertEqual(row['counts']['generation_changed'],1)
        row=run([book(3),book(3.4,bid=102,ask=103)])
        self.assertEqual(row['counts']['entry_quote_above_cap'],1)

if __name__=='__main__':unittest.main()
