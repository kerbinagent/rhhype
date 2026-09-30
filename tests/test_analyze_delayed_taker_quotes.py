import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import analyze_delayed_taker_quotes as model

T = 1790736777958514000
NS = model.NS


def metadata():
    result = {}
    for venue in model.MARKET_IDS:
        result[venue] = {}
        for asset in model.ASSETS:
            result[venue][asset] = dict(size_step='0.001', min_qty='0.001',
                min_notional='1', max_quote=None, max_qty=None,
                price_tick_semantics='decimal', price_tick='0.01',
                taker_fee_bps='0' if venue == 'rh_lighter' else '4.5')
    return result


def candidate(identity=0, anchor=T, budget=1000, asset='BTC', long='rh_lighter'):
    return dict(id=identity, anchor_ns=anchor, stratum=0, asset=asset, long_venue=long, budget=budget)


def book(venue, now, *, source=None, asset='BTC', bids=None, asks=None, generation='g', sequence=1):
    return dict(type='book', venue=venue, asset=asset, market=model.MARKET_IDS[venue][asset],
        received_ns=now, source_ns=now if source is None else source,
        generation=generation, sequence=sequence, valid=True,
        bids=bids or [[99, 100]], asks=asks or [[100,100]])


def pair(now, **kwargs):
    return [book(venue, now, **kwargs) for venue in model.MARKET_IDS]


def engine(*rows, end=T+400*NS, planned=()):
    return model.QuoteEngine(metadata(), candidates=rows or [candidate()], end_ns=end,planned_close_venues=planned)


def started_entry(*rows, now=T+NS//2, end=T+400*NS, planned=()):
    result=engine(*rows,end=end,planned=planned)
    result.batch(T,pair(T))
    result.batch(now,pair(now))
    return result


class TimelineTests(unittest.TestCase):
    def test_exact_grid_denominators_and_full_tail(self):
        rows=list(model.grid())
        self.assertEqual(len(rows),7200)
        self.assertEqual(len({row['id'] for row in rows}),7200)
        self.assertEqual(sum(row['budget']==1000 for row in rows),4800)
        self.assertEqual(max(row['anchor_ns'] for row in rows if row['budget']==1000),T+2995*NS)
        self.assertEqual(max(row['anchor_ns'] for row in rows if row['budget']==100),T+2970*NS)
        result=model.QuoteEngine(metadata())
        result.finish()
        self.assertEqual(len(result.outcomes),28800)
        self.assertTrue(all(row['status']=='anchor_missing_book' for row in result.rows))
        self.assertTrue(all(row['status']=='anchor_missing_book' for row in result.outcomes.values()))

    def test_entry_due_batch_is_first_eligible_and_shared(self):
        result=started_entry()
        row=result.rows[0]
        self.assertEqual(row['entry_ns'],T+NS//2)
        self.assertEqual(row['quantity'],'10')
        result.batch(T+NS,pair(T+NS,asks=[[102,100]]))
        self.assertEqual(row['entry_ns'],T+NS//2)
        self.assertEqual(row['entry_long_buy'],'1000')
        self.assertEqual(len(result.outcomes),4)

    def test_equal_deadline_pair_is_evaluated_before_timeout(self):
        result=engine()
        result.batch(T,pair(T))
        result.batch(T+2*NS,pair(T+2*NS))
        self.assertEqual(result.rows[0]['entry_ns'],T+2*NS)
        self.assertEqual(result.rows[0]['status'],'entry_quote_complete')
        deadline=T+14*NS
        result.batch(deadline,pair(deadline))
        self.assertEqual(result.outcomes[0,10]['status'],'quote_complete')
        self.assertEqual(result.outcomes[0,10]['exit_ns'],deadline)

    def test_exit_due_and_cutoff_pair_before_eof(self):
        cutoff=T+11*NS
        result=started_entry(end=cutoff,planned=('rh_lighter',))
        result.batch(cutoff,pair(cutoff)+[dict(type='invalidate',venue='rh_lighter',
            asset='BTC',received_ns=cutoff,scope='book',reason='disconnect')])
        self.assertEqual(result.outcomes[0,10]['status'],'quote_complete')
        self.assertEqual(result.outcomes[0,10]['exit_ns'],cutoff)
        self.assertEqual(result.outcomes[0,30]['status'],'exit_eof')

    def test_all_tied_events_before_anchor_and_timer(self):
        result=engine()
        events=pair(T)
        events.append(book('rh_lighter',T,asks=[[101,100]]))
        result.batch(T,events)
        self.assertEqual(result.rows[0]['quantity'],'9.9')
        due=T+NS//2
        result.batch(due,pair(due)+[book('rh_lighter',due,asks=[[102,100]])])
        self.assertEqual(result.rows[0]['entry_long_buy'],'1009.8')

    def test_first_shallow_entry_fails_without_retry(self):
        result=engine()
        result.batch(T,pair(T))
        result.batch(T+NS//2,pair(T+NS//2,asks=[[100,1]]))
        result.batch(T+NS,pair(T+NS))
        self.assertEqual(result.rows[0]['status'],'entry_depth')
        self.assertTrue(all(row['status']=='entry_depth' for row in result.outcomes.values()))
        self.assertNotIn('entry_ns',result.rows[0])

    def test_first_shallow_exit_does_not_retry_or_change_q(self):
        result=started_entry()
        due=T+11*NS
        result.batch(due,pair(due,bids=[[99,1]]))
        result.batch(due+NS//2,pair(due+NS//2))
        self.assertEqual(result.outcomes[0,10]['status'],'exit_depth')
        self.assertNotIn('adjusted_quote_net_ex_funding',result.outcomes[0,10])
        self.assertEqual(result.rows[0]['quantity'],'10')
        result.batch(T+31*NS,pair(T+31*NS))
        self.assertEqual(result.outcomes[0,30]['status'],'quote_complete')
        self.assertEqual(result.rows[0]['entry_ns'],T+NS//2)

    def test_advancement_source_due_age_and_skew_not_backfilled(self):
        result=engine()
        result.batch(T,pair(T))
        due=T+NS//2
        result.batch(due,pair(due,source=T))
        self.assertNotIn('entry_ns',result.rows[0])
        result.batch(due+NS//10,[book('rh_lighter',due+NS//10)])
        self.assertNotIn('entry_ns',result.rows[0])
        result.batch(T+NS,[book('hyperliquid',T+NS)])
        self.assertEqual(result.rows[0]['entry_ns'],T+NS)
        other=engine()
        other.batch(T,[book('rh_lighter',T),book('hyperliquid',T,source=T-NS-1)])
        self.assertEqual(other.rows[0]['status'],'anchor_cross_venue_skew')
        stale=engine()
        stale.batch(T,pair(T,source=T-2*NS-1))
        self.assertEqual(stale.rows[0]['status'],'anchor_stale_source_or_receipt')

    def test_future_source_book_invalidates_without_fill(self):
        result=engine()
        result.batch(T,pair(T))
        due=T+NS//2
        result.batch(due,[book('rh_lighter',due,source=due+1),book('hyperliquid',due)])
        self.assertTrue(result.rows[0]['status'].startswith('entry_gap:'))
        self.assertNotIn('entry_ns',result.rows[0])

    def test_generation_source_regression_and_nonce_gap_censor_pending(self):
        for event in (book('rh_lighter',T+NS,generation='new'),
                      book('rh_lighter',T+NS,source=T),
                      dict(type='invalidate',venue='rh_lighter',asset='BTC',received_ns=T+NS,
                           scope='book',reason='nonce_gap')):
            with self.subTest(event=event):
                result=started_entry()
                result.batch(T+NS,[event])
                self.assertTrue(all(row['status'].startswith('exit_gap:') for row in result.outcomes.values()))
                result.batch(T+11*NS,pair(T+11*NS))
                self.assertTrue(result.outcomes[0,10]['status'].startswith('exit_gap:'))

    def test_trade_only_invalidation_preserves_endpoint_quotes(self):
        result=started_entry()
        result.batch(T+NS,[dict(type='invalidate',venue='rh_lighter',asset='BTC',
            received_ns=T+NS,scope='trade',reason='trade_gap')])
        result.batch(T+11*NS,pair(T+11*NS))
        self.assertEqual(result.outcomes[0,10]['status'],'quote_complete')

    def test_planned_shutdown_eof_preserves_real_gap_and_expired_deadline(self):
        cutoff=T+NS
        result=started_entry(end=cutoff)
        result.batch(cutoff+1,[dict(type='control',control='connection_close',
            venue='rh_lighter',received_ns=cutoff+1)])
        self.assertTrue(all(row['status']=='exit_eof' for row in result.outcomes.values()))
        real=started_entry(end=cutoff)
        real.batch(cutoff-1,[dict(type='control',control='connection_close',
            venue='rh_lighter',received_ns=cutoff-1)])
        real.batch(cutoff+1,[])
        self.assertTrue(all(row['status']=='exit_gap:connection_close' for row in real.outcomes.values()))
        expired=engine(end=T+3*NS)
        expired.batch(T,pair(T))
        expired.batch(T+3*NS+1,[])
        self.assertTrue(all(row['status']=='entry_missing' for row in expired.outcomes.values()))

    def test_genuine_cutoff_gap_not_suppressed_by_planned_close(self):
        cutoff=T+11*NS
        result=started_entry(end=cutoff,planned=('rh_lighter',))
        result.batch(cutoff,pair(cutoff)+[dict(type='invalidate',venue='rh_lighter',asset='BTC',
            received_ns=cutoff,scope='book',reason='nonce_gap'),
            dict(type='control',venue='rh_lighter',received_ns=cutoff,control='connection_close')])
        self.assertEqual(result.outcomes[0,10]['status'],'exit_gap:nonce_gap')
        self.assertTrue(all(row['status']=='exit_gap:nonce_gap' for row in result.outcomes.values()))

    def test_declared_planned_cutoff_close_only_yields_eof(self):
        cutoff=T+NS
        result=started_entry(end=cutoff,planned=('rh_lighter',))
        result.batch(cutoff,[dict(type='control',venue='rh_lighter',received_ns=cutoff,control='connection_close'),
            dict(type='invalidate',venue='rh_lighter',asset='BTC',received_ns=cutoff,scope='book',reason='disconnect')])
        self.assertTrue(all(row['status']=='exit_eof' for row in result.outcomes.values()))

    def test_generation_control_invalidates_other_asset_before_new_book(self):
        result=engine(candidate(asset='ETH'))
        result.batch(T,pair(T,asset='ETH'))
        result.batch(T+NS//2,pair(T+NS//2,asset='ETH'))
        result.batch(T+NS,[dict(type='control',control='connection_open',venue='rh_lighter',
            generation='new',received_ns=T+NS)])
        self.assertTrue(all(row['status']=='exit_gap:generation_change' for row in result.outcomes.values()))
        other=started_entry()
        other.batch(T+NS,[dict(type='control',control='generation_invalidated',
            venue='rh_lighter',received_ns=T+NS)])
        self.assertTrue(all(row['status']=='exit_gap:generation_invalidated' for row in other.outcomes.values()))

    def test_eager_metadata_validation_and_lazy_fraction_materialization(self):
        result=engine(candidate(anchor=T+NS))
        result.batch(T,pair(T))
        self.assertEqual(result.books['rh_lighter','BTC']['_levels'],{})
        result.batch(T+NS,pair(T+NS))
        self.assertIn('asks',result.books['rh_lighter','BTC']['_levels'])
        bad=started_entry()
        bad.batch(T+NS,[book('rh_lighter',T+NS,bids=[[99,100],[98.005,1]])])
        self.assertTrue(all(row['status']=='exit_gap:quote_off_grid' for row in bad.outcomes.values()))

    def test_entry_eof_and_initial_invalid_denominators(self):
        rows=[candidate(),candidate(1,budget=1000,asset='ETH')]
        result=engine(*rows,end=T+NS//4)
        result.batch(T,pair(T))
        result.finish()
        self.assertEqual(result.rows[0]['status'],'entry_eof')
        self.assertEqual(result.rows[1]['status'],'anchor_missing_book')
        self.assertEqual(len(result.outcomes),8)
        self.assertEqual(sum(row['status']=='entry_eof' for row in result.outcomes.values()),4)

    def test_no_refresh_during_hold_is_endpoint_quote_not_continuity(self):
        result=started_entry()
        # Fresh endpoints alone are sufficient unless an explicit intervening gap is recorded.
        result.batch(T+301*NS,pair(T+301*NS))
        self.assertEqual(result.outcomes[0,300]['status'],'quote_complete')
        self.assertEqual(result.outcomes[0,10]['status'],'exit_missing')
        self.assertEqual(result.outcomes[0,60]['status'],'exit_missing')


class EconomicsAndPublicationTests(unittest.TestCase):
    def test_four_own_fees_and_actual_capital(self):
        rh_long=model.economics(200,202,204,206,0,'4.5',12*NS)
        hl_long=model.economics(200,202,204,206,'4.5',0,12*NS)
        self.assertEqual(rh_long['gross'],'0')
        self.assertEqual(hl_long['gross'],'0')
        self.assertEqual(model.rational(rh_long['entry_short_fee'])+model.rational(rh_long['exit_short_fee']),model.rational('.1836'))
        self.assertEqual(model.rational(hl_long['entry_long_fee'])+model.rational(hl_long['exit_long_fee']),model.rational('.1818'))
        self.assertEqual(model.rational(rh_long['stress']),model.rational('.101'))
        expected=model.rational(402)*model.rational('.05')*12/(365*86400)
        self.assertEqual(model.rational(rh_long['capital']),expected)
        self.assertEqual(model.rational(rh_long['adjusted_quote_net_ex_funding']),-model.rational('.1836')-model.rational('.101')-expected)

    def test_anchor_depth_excess_and_delayed_drift_are_separate(self):
        result=engine(candidate(budget=200))
        result.batch(T,pair(T,asks=[[100,1],[102,100]]))
        row=result.rows[0]
        self.assertEqual(row['quantity'],'2')
        self.assertEqual(row['anchor_long_buy_notional'],'202')
        self.assertTrue(row['anchor_notional_exceeds_budget'])
        result.batch(T+NS//2,pair(T+NS//2,asks=[[101,1],[103,100]]))
        self.assertEqual(row['entry_long_buy'],'204')
        self.assertEqual(row['entry_drift_from_anchor_walk'],'2')
        self.assertTrue(row['entry_notional_exceeds_anchor_budget'])
        self.assertEqual(row['quantity'],'2')

    def test_direction_specific_anchor_q(self):
        rows=[candidate(budget=200),candidate(1,budget=200,long='hyperliquid')]
        result=engine(*rows)
        result.batch(T,[book('rh_lighter',T,asks=[[100,100]]),book('hyperliquid',T,asks=[[200,100]])])
        self.assertEqual([row['quantity'] for row in result.rows],['2','1'])

    def test_funding_boundary_never_gives_funding_inclusive_positive(self):
        hour=3600*NS;anchor=(T//hour+1)*hour-11*NS
        result=engine(candidate(anchor=anchor),end=anchor+400*NS)
        result.batch(anchor,pair(anchor))
        result.batch(anchor+NS//2,pair(anchor+NS//2))
        result.batch(anchor+11*NS,pair(anchor+11*NS,bids=[[101,100]],asks=[[102,100]]))
        row=result.outcomes[0,10]
        self.assertTrue(row['utc_hour_boundary_crossed'])
        self.assertTrue(row['funding_boundary_tie'])
        self.assertTrue(row['funding_unknown'])
        result.finish()
        summary=model.summarize(result)
        self.assertIsNone(summary['funding_inclusive_net'])
        self.assertIsNone(summary['summed_portfolio_net'])

    def test_missing_optional_instant_depth_does_not_reject_entry(self):
        result=engine()
        result.batch(T,pair(T))
        due=T+NS//2
        # RH bids are the optional immediate long liquidation, not either entry leg.
        result.batch(due,[book('rh_lighter',due,bids=[[99,1]]),book('hyperliquid',due)])
        self.assertEqual(result.rows[0]['status'],'entry_quote_complete')
        self.assertIsNone(result.rows[0]['instant_adjusted_ex_funding'])
        result.batch(T+11*NS,pair(T+11*NS))
        self.assertEqual(result.outcomes[0,10]['status'],'quote_complete')
        self.assertIsNone(result.outcomes[0,10]['improvement_from_instant'])

    def test_quantity_order_minimum_and_maximum_fail_without_retry(self):
        result=engine()
        result.markets['rh_lighter']['BTC']['max_quote']='1001'
        result.batch(T,pair(T))
        due=T+NS//2
        result.batch(due,pair(due,asks=[[101,100]]))
        self.assertEqual(result.rows[0]['status'],'entry_order_rule')
        result.batch(T+NS,pair(T+NS))
        self.assertEqual(result.rows[0]['status'],'entry_order_rule')

    def test_cap_checked_before_any_write_and_csv_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            output=model.BoundedOutput(directory,cap=5)
            with self.assertRaisesRegex(ValueError,'cap_before_write'):
                output.write('large','123456','summary')
            self.assertFalse((Path(directory)/'large').exists())
            output=model.BoundedOutput(directory)
            output.csv_gzip('rows.gz',['id','status'],[dict(id=1,status='entry_eof')],'candidates')
            self.assertIn('entry_eof',gzip.decompress((Path(directory)/'rows.gz').read_bytes()).decode())
            with self.assertRaisesRegex(ValueError,'already_exists'):
                output.write('rows.gz',b'x','candidates')

    def test_dry_default_never_verifies_or_opens_archive(self):
        with patch.object(model,'verify_inputs',side_effect=AssertionError('archive opened')):
            with patch('builtins.print') as printed:
                model.main([])
            self.assertEqual(json.loads(printed.call_args.args[0])['mode'],'dry_plan')

    def test_no_overwrite_dangling_symlink_and_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            parent=Path(directory)
            with patch.object(model,'OUTPUT_PARENT',parent):
                dangling=parent/'existing';dangling.symlink_to(parent/'missing')
                with self.assertRaisesRegex(ValueError,'new_output_child'):
                    model.run(dangling)
                (parent/'new.building').mkdir()
                with self.assertRaisesRegex(ValueError,'staging_already'):
                    model.run(parent/'new')

    def test_terminal_source_hash_mismatch_refused(self):
        with self.assertRaisesRegex(ValueError,'verified_terminal'):
            model.verify_terminal(dict(type='end',raw_sha_verified=True,truncated=False),{}, {})

    def test_complete_synthetic_terminal_then_mutated_count_and_hash(self):
        manifest={'ended_utc':'2026-09-30T03:42:58.061557+00:00'}
        hashes={str(model.INPUT/'manifest.json'):'a'*64,
            str(model.ROOT/'scripts/rh_maker_events.py'):'b'*64,
            str(model.ROOT/'scripts/maker_book_archive.py'):'c'*64}
        terminal=dict(type='end',raw_sha_verified=True,truncated=False,reason='duration_limit',
            raw_gzip_sha256=model.EXPECTED_RAW,manifest_sha256='a'*64,adapter_sha256='b'*64,
            book_decoder_sha256='c'*64,counts={'decoded_records':124019},started_ns=T,
            stopped_ns=model.epoch_ns(manifest['ended_utc']))
        model.verify_terminal(terminal,manifest,hashes)
        for changed in (dict(terminal,counts={'decoded_records':124018}),
                        dict(terminal,raw_gzip_sha256='d'*64),dict(terminal,truncated=True)):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(ValueError,'verified_terminal'):
                    model.verify_terminal(changed,manifest,hashes)

    def test_anchor_references_and_instant_deficit_retained_in_csv_fields(self):
        result=started_entry();row=result.rows[0]
        self.assertEqual(row['anchor_rh_source_ns'],T)
        self.assertEqual(row['rh_source_ns'],T+NS//2)
        self.assertEqual(model.rational(row['instant_deficit_to_010']),
            model.rational('.1')-model.rational(row['instant_adjusted_ex_funding']))
        self.assertIn('anchor_rh_source_ns',model.CANDIDATE_FIELDS)
        self.assertIn('anchor_hl_generation',model.CANDIDATE_FIELDS)

    def test_receipt_batch_traversal_requires_terminal_no_injected_publication(self):
        result=engine()
        with self.assertRaisesRegex(ValueError,'missing_terminal'):
            result.traverse(pair(T))
        result=engine(end=T+NS)
        result.traverse(pair(T)+pair(T+NS//2)+[dict(type='end')])
        self.assertEqual(result.rows[0]['entry_ns'],T+NS//2)
        self.assertEqual(result.outcomes[0,10]['status'],'exit_eof')


if __name__=='__main__':
    unittest.main()
