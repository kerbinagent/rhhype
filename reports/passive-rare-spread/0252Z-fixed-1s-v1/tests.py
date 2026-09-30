import unittest
from fractions import Fraction
from scripts.analyze_passive_rare_spread import (Anchors,ASSETS,SIZES,NS,AGE,Excursions,common_step,decimal,score,verify_terminal,epoch_ns,ROOT,INPUT,EXPECTED_SHA)

def metadata():
    r={'size_step':'.01','price_tick':'1','price_tick_semantics':'fixed','min_qty':'.01','min_notional':'1','max_quote':'100000','max_qty':None,'maker_fee_bps':'2'}
    h={'size_step':'.01','price_tick_semantics':'hl_perp','sz_decimals':2,'min_qty':None,'min_notional':'1','max_quote':None,'max_qty':None,'taker_fee_bps':'3'}
    return {'rh_lighter':{a:dict(r) for a in ASSETS},'hyperliquid':{a:dict(h) for a in ASSETS}}

def book(venue,receipt,source=None,bid=100,ask=110,size=100,generation='g',asset='BTC'):
    return {'type':'book','venue':venue,'asset':asset,'generation':generation,'received_ns':receipt,'source_ns':source if source is not None else receipt,
            'bids':[(bid,size)],'asks':[(ask,size)]}

class Tests(unittest.TestCase):
    def test_decimal_integer_and_lcm(self):
        self.assertEqual(decimal(Fraction(100)),'100')
        self.assertEqual(decimal(Fraction(-10)),'-10')
        self.assertEqual(decimal(Fraction(1,1000000)),'0.000001')
        self.assertEqual(decimal(Fraction(1,10)),'0.1')
        self.assertEqual(common_step('.02','.03'),Fraction(6,100))
    def test_ask_sizing_own_fees_stress_and_full_depth(self):
        m=metadata();r,h=m['rh_lighter']['BTC'],m['hyperliquid']['BTC'];t=10*NS
        rh=book('rh_lighter',t);hl=book('hyperliquid',t,bid=102,ask=103)
        v=score(t,rh,hl,r,h,100)
        self.assertTrue(v['valid']);self.assertEqual(v['quantity'],'0.9')
        self.assertEqual(Fraction(v['rh_fee']),Fraction('189')*Fraction('.0002'))
        self.assertEqual(Fraction(v['hl_fee']),Fraction('184.5')*Fraction('.0003'))
        self.assertEqual(Fraction(v['stress']),Fraction('91.8')*Fraction('.0005'))
        self.assertEqual(Fraction(v['net']),Fraction('9')-Fraction('.9')-Fraction('.0378')-Fraction('.05535')-Fraction('.1')-Fraction('.0459'))
        hl['asks']=[(103,.89)]
        self.assertEqual(score(t,rh,hl,r,h,100)['reason'],'insufficient_hl_depth')
        hl['asks']=[(103,.5),(104,.4)]
        self.assertEqual(Fraction(score(t,rh,hl,r,h,100)['hl_buy']),Fraction('93.1'))
    def test_minimum_grid_and_cross(self):
        m=metadata();r,h=m['rh_lighter']['BTC'],m['hyperliquid']['BTC'];t=10*NS
        rh=book('rh_lighter',t);hl=book('hyperliquid',t,bid=102,ask=103)
        r['min_qty']='1';self.assertEqual(score(t,rh,hl,r,h,100)['reason'],'quantity_below_or_outside_bounds')
        r['min_qty']='.01';r['min_notional']='95';self.assertEqual(score(t,rh,hl,r,h,100)['reason'],'rh_notional_bounds')
        r['min_notional']='1';rh['bids']=[(100.5,100)];self.assertEqual(score(t,rh,hl,r,h,100)['reason'],'quote_off_grid')
        rh['bids']=[(110,100)];self.assertEqual(score(t,rh,hl,r,h,100)['reason'],'crossed_book')
    def test_clock_boundaries(self):
        m=metadata();r,h=m['rh_lighter']['BTC'],m['hyperliquid']['BTC'];t=10*NS
        rh=book('rh_lighter',t-AGE);hl=book('hyperliquid',t,bid=102,ask=103)
        self.assertTrue(score(t,rh,hl,r,h,100)['valid'])
        rh['source_ns']-=1;self.assertEqual(score(t,rh,hl,r,h,100)['reason'],'stale_source_or_receipt')
        rh=book('rh_lighter',t,source=t+1);self.assertEqual(score(t,rh,hl,r,h,100)['reason'],'invalid_clock')
    def test_future_cannot_repair_anchor_and_ties_all_applied(self):
        t=10*NS;engine=Anchors(t,metadata(),count=2)
        events=[book('rh_lighter',t),book('hyperliquid',t,bid=102,ask=103),
                book('rh_lighter',t,bid=101,ask=110),book('rh_lighter',t+NS+1),{'type':'end','received_ns':t+2*NS}]
        batches=list(engine.traverse(events))
        self.assertEqual(batches[0][0][0]['rh_bid'],'101')
        engine=Anchors(t,metadata(),count=1)
        first=list(engine.traverse([book('rh_lighter',t+1),book('hyperliquid',t+1),{'type':'end','received_ns':t+NS}]))[0][0][0]
        self.assertFalse(first['valid']);self.assertEqual(first['reason'],'missing_rh')
    def test_generation_and_scope_clearing(self):
        e=Anchors(10*NS,metadata(),count=1);e.apply(book('rh_lighter',10*NS));e.apply(book('hyperliquid',10*NS))
        e.apply({'type':'invalidate','venue':'rh_lighter','asset':'BTC','generation':'g','scope':'trade'})
        self.assertIn(('rh_lighter','BTC'),e.books)
        e.apply({'type':'control','venue':'rh_lighter','generation':'g2','control':'connection_open'})
        self.assertNotIn(('rh_lighter','BTC'),e.books)
        e.apply({'type':'invalidate','venue':'hyperliquid','asset':'BTC','generation':'g','scope':'book'})
        self.assertNotIn(('hyperliquid','BTC'),e.books)
    def test_excursion_rearm_gaps_and_left_censor(self):
        e=Excursions();e.update({'valid':False},0);r={'valid':True,'positive':True};e.update(r,1)
        self.assertTrue(r['left_censored']);e.update({'valid':False},2);e.update({'valid':True,'positive':True},3)
        self.assertEqual(len(e.items),1);self.assertEqual(e.items[0]['missing_anchors'],1)
        e.update({'valid':True,'positive':False},4);r={'valid':True,'positive':True};e.update(r,600)
        self.assertFalse(r['left_censored']);self.assertEqual(r['excursion'],2);self.assertEqual(e.items[1]['stratum'],1)
    def test_terminal_identity_gate(self):
        source=INPUT;manifest={'started_utc':'2026-09-30T02:52:57.958514+00:00','ended_utc':'2026-09-30T03:42:58.061557+00:00'}
        hashes={str(source/'manifest.json'):'manifest',str(ROOT/'scripts/rh_maker_events.py'):'adapter',str(ROOT/'scripts/maker_book_archive.py'):'decoder'}
        end={'raw_sha_verified':True,'truncated':False,'reason':'duration_limit','raw_gzip_sha256':EXPECTED_SHA,'manifest_sha256':'manifest',
             'adapter_sha256':'adapter','book_decoder_sha256':'decoder','counts':{'decoded_records':124019},
             'started_ns':epoch_ns(manifest['started_utc']),'stopped_ns':epoch_ns(manifest['ended_utc'])}
        verify_terminal(end,manifest,hashes,source)
        for change in ({'truncated':True},{'raw_gzip_sha256':'wrong'},{'manifest_sha256':'wrong'}, {'counts':{}}, {'stopped_ns':end['started_ns']+2999*NS}):
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'terminal_identity'):verify_terminal(end|change,manifest,hashes,source)
    def test_full_missing_denominator_all_strata_and_terminal(self):
        t=10*NS;e=Anchors(t,metadata());batches=list(e.traverse([{'type':'end','received_ns':t+3000*NS}]))
        rows=[r for batch,_ in batches for r in batch]
        self.assertEqual(len(rows),48000);self.assertEqual(rows[-1]['k'],2999)
        self.assertEqual([sum(r['k']//600==s for r in rows) for s in range(5)],[9600]*5)
        self.assertFalse(any(r['valid'] for r in rows))
        with self.assertRaisesRegex(ValueError,'missing_verified_terminal'):list(Anchors(t,metadata(),1).traverse([]))

if __name__=='__main__':unittest.main()
