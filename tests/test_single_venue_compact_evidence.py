import unittest
from unittest.mock import patch
from scripts import single_venue_strategy as strategy
from scripts import single_venue_compact_evidence as compact
from scripts import audit_single_venue_study as auditor
from tests.test_single_venue_strategy import TestOneVenue, book, META

class TestCompact(unittest.TestCase):
    def test_identical_economics_and_raw_audit_with_hash_only_books(self):
        # Reuse the independent raw test, including deliberate fill corruption.
        with patch.object(strategy,'snapshot',compact.compact_snapshot),patch.object(auditor,'match_book',compact.match_compact):
            TestOneVenue('test_full_raw_audit_accepts_cash_and_rejects_corrupted_fill').test_full_raw_audit_accepts_cash_and_rejects_corrupted_fill()
        events=[]
        for j in range(1500):
            t=j/10
            events += [book(t,venue='rh_lighter',bid=100.19 if t>=130 else 99.99,ask=100.21 if t>=130 else 100.01),book(t+.001)]
        events.append(dict(type='end',received_ns=150*10**9))
        def run():
            trace=[];s=strategy.Study({v:{'LIT':META} for v in ('lighter','rh_lighter')},0,trace.append)
            for e in events:s.process(e)
            return s.summary()
        expected=run()
        with patch.object(strategy,'snapshot',compact.compact_snapshot):self.assertEqual(run(),expected)

    def test_changed_raw_depth_rejected(self):
        b=book(1);w=compact.compact_snapshot(b);b['bids']=[(99.98,100)]
        with self.assertRaises(AssertionError):compact.match_compact(w,b)

if __name__=='__main__':unittest.main()
