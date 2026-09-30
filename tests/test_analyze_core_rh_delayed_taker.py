import copy
from collections import Counter
import datetime as dt
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import analyze_core_rh_delayed_taker as m
from scripts import audit_core_rh_delayed_taker as audit

T=m.EXPECTED[0]['start'];NS=m.NS


def iso(now):
    return (dt.datetime(1970,1,1,tzinfo=dt.timezone.utc)+dt.timedelta(microseconds=now//1000)).isoformat()


def make_fixture(directory):
    directory=Path(directory);specs=[];pins={}
    unit=directory/'unit.json';unit.write_bytes((m.ROOT/'reports/maker-equity-v2/unit-provenance.json').read_bytes())
    pins[str(unit)]=m.sha(unit)
    for original,plan_name in zip(m.EXPECTED,('maker-roundtrip-v1','maker-equity-v2')):
        spec=dict(original);path=directory/spec['name'];path.mkdir()
        spec['directory']=path
        plan=path/'market-plan.json';plan.write_bytes((m.ROOT/f'reports/{plan_name}/market-plan.json').read_bytes())
        pins[str(plan)]=m.sha(plan)
        selected={v:{a:m.IDS[v][a] for a in spec['assets']} for v in m.VENUES}
        selected['hyperliquid']={a:a if a in ('BTC','ETH') else 'xyz:NVDA' if a=='NVDA' else 'xyz:SILVER' for a in spec['assets']}
        rows=[dict(kind='connection_open',venue=v,generation=v+'-fixture',receipt_utc_ns=spec['start']) for v in selected]
        for k in range(841):
            now=spec['start']+k*NS//2
            for venue in m.VENUES:
                for asset in spec['assets']:
                    market=m.IDS[venue][asset]
                    body=dict(nonce=k+1,last_updated_at=now//1000,
                        bids=[dict(price='99',size='1000')],asks=[dict(price='100',size='1000')])
                    if k:body['begin_nonce']=k
                    rows.append(dict(kind='frame',venue=venue,generation=venue+'-fixture',
                        receipt_utc_ns=now,receipt_monotonic_ns=k+1,market=market,channel='order_book',
                        annotation=dict(channel='order_book',market=market,source_min_ns=now,source_max_ns=now,
                            quality='wire_ok' if k else 'wire_ok_snapshot'),
                        payload=dict(type='update/order_book' if k else 'subscribed/order_book',
                            channel='order_book:'+market,order_book=body)))
        encoded=[(json.dumps(row,separators=(',',':'))+'\n').encode() for row in rows]
        # Two concatenated members exercise actual gzip traversal without
        # creating expensive fake per-record gzip overhead in /tmp.
        midway=len(encoded)//2
        raw=gzip.compress(b''.join(encoded[:midway]),mtime=0)+gzip.compress(b''.join(encoded[midway:]),mtime=0)
        (path/'frames.jsonl.gz').write_bytes(raw)
        spec.update(bytes=len(raw),records=len(rows),raw_sha=hashlib.sha256(raw).hexdigest())
        manifest=dict(schema='maker-public-capture-v1',read_only=True,end_reason='duration_limit',
            truncated=False,errors=[],invalidations={},omitted_record_count_keys=0,
            omitted_invalidation_keys=0,dropped_complete_frame_on_cap=0,configured_seconds=420,
            configured_total_compressed_bytes=25_000_000,selected_markets=selected,
            payload_records=len(rows),compressed_payload_bytes=len(raw),started_utc=iso(spec['start']),
            ended_utc=iso(spec['start']+m.DURATION+NS//10),market_plan=str(plan),market_plan_sha256=pins[str(plan)],
            generations=[dict(venue=v,generation=v+'-fixture',opened_utc=iso(spec['start']),
                closed_utc=iso(spec['start']+m.DURATION+NS//20)) for v in selected],record_counts={})
        (path/'manifest.json').write_text(json.dumps(manifest))
        pins[str(path/'manifest.json')]=m.sha(path/'manifest.json');specs.append(spec)
    return dict(specs=specs,small_pins=pins,unit_path=unit)


def markets():
    return {v:{a:dict(size_step='.001',min_qty='.001',min_notional='1',price_tick='.01',
        max_quote=None,max_qty=None,taker_fee_bps='0') for a in m.ASSETS} for v in m.VENUES}


def row(identity=0,anchor=T):
    return dict(id=str(identity),archive='1939Z',asset='BTC',long_venue='rh_lighter',budget=1000,
        anchor_ns=anchor,stratum=0,status='not_evaluated_archive_abort',
        rule_spec_refs={v:f'1939Z:{v}:BTC' for v in m.VENUES})


def book(venue,now,**changes):
    result=dict(type='book',venue=venue,asset='BTC',receipt_ns=now,source_ns=now,
        generation='g',sequence=1,bids=[[99,1000]],asks=[[100,1000]],
        price_grid='known_pass',quantity_grid='known_pass')
    result.update(changes);return result


def pair(now,**changes):return [book(v,now,**changes) for v in m.VENUES]


def engine(*rows,end=T+420*NS):return m.QuoteEngine(markets(),list(rows) or [row()],end)


class Timeline(unittest.TestCase):
    def test_grid_and_empty_full_denominator(self):
        rows=list(m.grid());self.assertEqual(len(rows),1008)
        self.assertEqual(Counter(r['budget']==1000 for r in rows),{True:672,False:336})
        self.assertEqual(Counter(r['stratum'] for r in rows),{0:264,1:240,2:264,3:240})
        self.assertEqual(Counter(r['archive'] for r in rows),{'1939Z':504,'2022Z':504})
        for spec in m.EXPECTED:
            e=m.QuoteEngine(markets(),[r for r in rows if r['archive']==spec['name']],spec['start']+420*NS)
            e.finish()
        self.assertTrue(all(r['status']=='anchor_missing_book' and r['rule_spec_refs'] for r in rows))

    def test_due_deadline_and_cutoff_ties(self):
        for entry in (T+NS//2,T+2*NS):
            e=engine(end=entry+12*NS);e.batch(T,pair(T));e.batch(entry,pair(entry))
            e.batch(entry+12*NS,pair(entry+12*NS))
            r=e.rows[0];self.assertEqual(r['status'],'conditional_quote_complete')
            self.assertEqual(r['entry_ns'],entry);self.assertEqual(r['exit_ns'],entry+12*NS)
            self.assertEqual(r['quantity'],'10');self.assertTrue(r['legality_unknown'])

    def test_first_shallow_and_illegal_pairs_preserve_refs_no_retry(self):
        for change,status in ((dict(asks=[[100,1]]),'entry_depth'),
                              (dict(price_grid='known_fail'),'entry_known_rule_violation')):
            e=engine();e.batch(T,pair(T));e.batch(T+NS//2,pair(T+NS//2,**change));e.batch(T+NS,pair(T+NS))
            r=e.rows[0];self.assertEqual(r['status'],status)
            self.assertEqual(r['entry_selected_ns'],T+NS//2);self.assertTrue(r['entry_refs'])
            self.assertNotIn('entry_ns',r);self.assertNotIn('adjusted_quote_net_ex_funding',r)

    def test_each_known_rule_failure_is_terminal(self):
        for rule in ('quantity_grid','minimum_quantity','minimum_notional','maximum_quote'):
            e=engine();e.batch(T,pair(T))
            original=copy.deepcopy(e.markets)
            changed={}
            if rule=='quantity_grid':changed['quantity_grid']='known_fail'
            else:
                field={'minimum_quantity':'min_qty','minimum_notional':'min_notional','maximum_quote':'max_quote'}[rule]
                for venue in m.VENUES:e.markets[venue]['BTC'][field]='2000'
                if rule=='maximum_quote':
                    for venue in m.VENUES:e.markets[venue]['BTC'][field]='1'
            e.batch(T+NS//2,pair(T+NS//2,**changed));e.markets=original;e.batch(T+NS,pair(T+NS))
            self.assertEqual(e.rows[0]['status'],'entry_known_rule_violation')
            self.assertTrue(e.rows[0]['entry_refs']);self.assertNotIn('entry_ns',e.rows[0])

    def test_both_anchor_legs_required_and_fixed_q_price_drift(self):
        e=engine();e.batch(T,[book('rh_lighter',T),book('lighter',T,bids=[[99,1]])])
        self.assertEqual(e.rows[0]['status'],'anchor_depth');self.assertTrue(e.rows[0]['anchor_refs'])
        e=engine();e.batch(T,pair(T));e.batch(T+NS//2,pair(T+NS//2,asks=[[102,1000]]))
        self.assertEqual(e.rows[0]['quantity'],'10');self.assertEqual(e.rows[0]['entry_long_buy'],'1020')
        self.assertEqual(e.rows[0]['common_lot'],'0.001');self.assertEqual(e.rows[0]['anchor_long_best_ask'],'100')

    def test_two_second_freshness_advancement_skew_and_future(self):
        e=engine();e.batch(T,pair(T,source_ns=T-2*NS))
        self.assertEqual(e.rows[0]['status'],'entry_pending')
        e.batch(T+NS//2,pair(T+NS//2,source_ns=T));self.assertNotIn('entry_ns',e.rows[0])
        e.batch(T+2*NS,pair(T+2*NS));self.assertEqual(e.rows[0]['entry_ns'],T+2*NS)
        stale=engine();stale.batch(T,pair(T,source_ns=T-2*NS-1))
        self.assertEqual(stale.rows[0]['status'],'anchor_stale_source_or_receipt')
        skew=engine();skew.batch(T,[book('rh_lighter',T),book('lighter',T,source_ns=T-NS-1)])
        self.assertEqual(skew.rows[0]['status'],'anchor_cross_venue_skew')
        bad=engine();bad.batch(T,pair(T));bad.batch(T+NS//2,pair(T+NS//2,source_ns=T+NS//2+1))
        self.assertTrue(bad.rows[0]['status'].startswith('entry_gap:'))

    def test_dense_tie_gaps_recovery_and_later_anchor(self):
        e=engine(row(0),row(1,T+5*NS));e.record(T,pair(T));e.record(T+NS//2,pair(T+NS//2))
        now=T+NS
        for k in range(400):
            events=pair(now,sequence=k+2)
            if k==200:events.append(dict(type='invalidate',venue='rh_lighter',asset='BTC',reason='nonce_gap'))
            e.record(now,events)
        self.assertEqual(len(e.books),2);self.assertEqual(len(e.changed),1)
        e.record(T+5*NS,pair(T+5*NS,generation='new'));e.record(T+5500000000,pair(T+5500000000,generation='new'))
        e.record(T+16*NS,pair(T+16*NS,generation='new'));e.batch(T+16*NS,())
        self.assertEqual(e.rows[0]['status'],'exit_gap:nonce_gap')
        self.assertEqual(e.rows[1]['status'],'conditional_quote_complete')

    def test_genuine_gap_at_cutoff_is_not_eof(self):
        e=engine(end=T+11*NS);e.batch(T,pair(T));e.batch(T+NS//2,pair(T+NS//2))
        e.batch(T+11*NS,pair(T+11*NS)+[dict(type='invalidate',venue='rh_lighter',asset='BTC',reason='nonce_gap')])
        self.assertEqual(e.rows[0]['status'],'exit_gap:nonce_gap')

    def test_cost_identity_actual_elapsed_and_numeric_bound(self):
        a=m.economics(200,202,204,206,0,'4.5',12*NS)
        b=m.economics(200,202,204,206,'4.5',0,12*NS)
        self.assertEqual(a['gross'],'0');self.assertEqual(m.rat(a['entry_short_fee'])+m.rat(a['exit_short_fee']),m.rat('.1836'))
        self.assertEqual(m.rat(b['entry_long_fee'])+m.rat(b['exit_long_fee']),m.rat('.1818'))
        self.assertEqual(a['stress'],'0.101')
        self.assertEqual(m.rat(a['capital']),m.rat(402)*m.rat('.05')*12/(365*86400))
        with self.assertRaisesRegex(ValueError,'numeric_token_bound'):m.decimal('1000000000000.000000000000000001')
        for value in ('NaN','1e-19',True):
            with self.assertRaises(ValueError):m.decimal(value)

    def test_separate_timer_bounds(self):
        e=engine();e.timer_counts['stage']=2016
        with self.assertRaisesRegex(ValueError,'separate_timer'):e.schedule(T,'entry_due','0')


class RealPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(dir='/tmp');cls.path=Path(cls.tmp.name)
        cls.fixture=make_fixture(cls.path)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def preparation(self,name):
        path=self.path/(name+'-freeze.json')
        result=m.prepare(path,fixture_inputs=self.fixture)
        return path,result['sha256']

    def adapter(self):
        specs,pins,unit=m.context(self.fixture);manifests,meta,_=m.admit(specs,pins,unit)
        spec=specs[0];a=m.Adapter(manifests[spec['name']],meta[spec['name']],spec['start']+420*NS)
        with gzip.open(spec['directory']/'frames.jsonl.gz','rt') as handle:
            rows=[json.loads(next(handle)) for _ in range(7)]
        return a,rows[3]

    def test_actual_cli_prepare_and_full_publication(self):
        context=self.path/'context.json'
        serial=dict(unit_path=str(self.fixture['unit_path']),small_pins=self.fixture['small_pins'],
            specs=[{**s,'directory':str(s['directory'])} for s in self.fixture['specs']])
        context.write_text(json.dumps(serial))
        freeze=self.path/'cli-freeze.json';out=self.path/'cli-result'
        base=[sys.executable,'-B',str(m.ROOT/'scripts/analyze_core_rh_delayed_taker.py'),'--synthetic-fixture',str(context)]
        prepared=subprocess.run(base+['--prepare','--freeze',str(freeze)],capture_output=True,text=True,check=True)
        info=json.loads(prepared.stdout);self.assertEqual(info['raw_reads'],0)
        completed=subprocess.run(base+['--run','--freeze',str(freeze),'--freeze-sha256',info['sha256'],'--out',str(out)],
            capture_output=True,text=True,check=True)
        result=json.loads(completed.stdout);self.assertEqual(result['status'],'complete_quote_diagnostic')
        with gzip.open(out/'quotes.jsonl.gz','rt') as handle:rows=[json.loads(line) for line in handle]
        with gzip.open(out/'summary.json.gz','rt') as handle:summary=json.load(handle)
        manifest=json.loads((out/'manifest.json').read_text())
        self.assertEqual(len(rows),1008);self.assertEqual(summary['conditional_quote_complete'],992)
        self.assertEqual(summary['statuses']['exit_eof'],16)
        self.assertEqual(len(summary['groups']),32);self.assertEqual(len(summary['stratum_groups']),128)
        self.assertEqual(summary['fully_verified_executable_count'],0)
        self.assertTrue(all(t['verified'] and t['gzip_eof'] for t in summary['terminals'].values()))
        self.assertLess(result['new_physical_bytes']+m.EXTERNAL_RESERVE,600000)
        self.assertFalse((out/'fallback-roster.jsonl.gz').exists())
        audit.audit_rows(rows);audit.compare(summary,audit.summary_expectation(rows))
        for name,description in manifest['outputs'].items():
            self.assertEqual(m.sha(out/name),description['sha256'])
        self.assertEqual(manifest['external_freeze_path'],str(freeze))
        with self.assertRaisesRegex(ValueError,'new_output'):m.run(out,freeze_path=freeze,freeze_sha256=info['sha256'],fixture_inputs=self.fixture)

    def test_preparation_mutation_refusal_full_failure_and_no_raw_read(self):
        freeze,digest=self.preparation('mutation');plan=Path(self.fixture['specs'][0]['directory'])/'market-plan.json'
        original=plan.read_bytes();plan.write_bytes(original[:-1]+b' ')
        try:
            with patch.object(m.gzip,'open',side_effect=AssertionError('no raw decode')):
                with self.assertRaisesRegex(ValueError,'source_changed_since_preparation'):
                    m.run(self.path/'mutation-result',freeze_path=freeze,freeze_sha256=digest,fixture_inputs=self.fixture)
        finally:plan.write_bytes(original)
        self.check_failure(self.path/'mutation-result.building')

    def check_failure(self,stage):
        self.assertFalse((stage/'manifest.json').exists());self.assertFalse((stage/'quotes.jsonl.gz').exists())
        with gzip.open(stage/'failure-roster.jsonl.gz','rt') as handle:rows=[json.loads(line) for line in handle]
        self.assertEqual(len(rows),1008);self.assertTrue(all(r['economics'] is None for r in rows))
        return rows

    def test_output_cap_and_post_manifest_timeout_remove_completion(self):
        freeze,digest=self.preparation('cap')
        with patch.dict(m.LIMITS,rows=1):
            with self.assertRaises(m.OutputCapError):m.run(self.path/'cap-result',freeze_path=freeze,freeze_sha256=digest,fixture_inputs=self.fixture)
        self.check_failure(self.path/'cap-result.building')
        freeze,digest=self.preparation('timeout');out=self.path/'timeout-result'
        original=m.wall
        def final_timeout(started):
            if (out.with_name(out.name+'.building')/'manifest.json').exists():raise TimeoutError('forced_final_wall')
            original(started)
        with patch.object(m,'wall',side_effect=final_timeout):
            with self.assertRaisesRegex(TimeoutError,'forced_final_wall'):m.run(out,freeze_path=freeze,freeze_sha256=digest,fixture_inputs=self.fixture)
        self.check_failure(out.with_name(out.name+'.building'))

    def test_sigterm_handler_roster_restore_and_unread_archive(self):
        freeze,digest=self.preparation('signal');old=signal.getsignal(signal.SIGTERM)
        def terminate(*_args):signal.getsignal(signal.SIGTERM)(signal.SIGTERM,None)
        with patch.object(m,'traverse',side_effect=terminate):
            with self.assertRaisesRegex(TimeoutError,'supervised_sigterm'):
                m.run(self.path/'signal-result',freeze_path=freeze,freeze_sha256=digest,fixture_inputs=self.fixture)
        rows=self.check_failure(self.path/'signal-result.building')
        self.assertTrue(all(r['evaluation_status']=='not_evaluated_archive_abort' for r in rows))
        self.assertIs(signal.getsignal(signal.SIGTERM),old)

    def test_dangling_symlink_no_overwrite(self):
        freeze,digest=self.preparation('link');out=self.path/'link-result';out.symlink_to(self.path/'absent')
        with self.assertRaisesRegex(ValueError,'new_output'):m.run(out,freeze_path=freeze,freeze_sha256=digest,fixture_inputs=self.fixture)
        self.assertTrue(out.is_symlink())

    def test_prefloat_numeric_collision_against_retained_state_and_duplicate(self):
        a,snapshot=self.adapter();a.process(snapshot)
        update=copy.deepcopy(snapshot);now=T+NS//2
        update.update(receipt_utc_ns=now,annotation={**snapshot['annotation'],'source_min_ns':now,'source_max_ns':now,'quality':'wire_ok'})
        update['payload']['type']='update/order_book';body=update['payload']['order_book']
        body.update(nonce=2,begin_nonce=1,last_updated_at=now//1000)
        # JSON numeric literal must remain distinct before the pinned float decoder.
        numeric=json.loads('{"price":99.00000000000000001,"size":1000.0}',parse_float=m.finite_json_float)
        self.assertIsInstance(numeric['price'],Decimal)
        body['bids']=[numeric]
        self.assertEqual(a.process(update)[0]['reason'],'float_price_collision')
        self.assertFalse(a.registry);self.assertNotIn(('rh_lighter','1'),a.rebuilder.manager.states)
        b,snapshot=self.adapter();snapshot['payload']['order_book']['bids']*=2
        self.assertEqual(b.process(snapshot)[0]['reason'],'exact_duplicate_price')

    def test_same_price_delta_replacement_deletion_and_string_collision(self):
        for literal in ('99','99.00000000000000001'):
            a,snapshot=self.adapter();a.process(snapshot);update=copy.deepcopy(snapshot);now=T+NS//2
            update['receipt_utc_ns']=now;update['annotation'].update(quality='wire_ok',source_min_ns=now,source_max_ns=now)
            update['payload']['type']='update/order_book';body=update['payload']['order_book']
            body.update(nonce=2,begin_nonce=1,last_updated_at=now//1000,bids=[dict(price=literal,size='2000')])
            event=a.process(update)[0]
            if literal!='99':self.assertEqual(event['reason'],'float_price_collision');continue
            self.assertEqual(event['type'],'book');self.assertEqual(event['bids'][0][1],2000)
            # Delete the old bid and replace it by a distinct lower bid, keeping
            # a nonempty book while exercising transactional identity deletion.
            now+=NS//2;update['receipt_utc_ns']=now;update['annotation'].update(source_min_ns=now,source_max_ns=now)
            body.update(nonce=3,begin_nonce=2,last_updated_at=now//1000,
                        bids=[dict(price='99',size='0'),dict(price='98',size='1000')])
            self.assertEqual(a.process(update)[0]['bids'][0][0],98)
            self.assertNotIn(99.0,a.registry['rh_lighter','1','bids'])

    def test_planned_closure_eof_and_unexpected_close(self):
        for planned in (True,False):
            a,snapshot=self.adapter();a.process(snapshot)
            close=dict(kind='connection_close',venue='rh_lighter',generation='rh_lighter-fixture',
                       receipt_utc_ns=T+(420 if planned else 1)*NS)
            events=a.process(close)
            if planned:self.assertEqual(events,[])
            else:self.assertEqual(events[0]['type'],'invalidate')
            self.assertFalse(a.registry)

    def test_terminal_count_and_raw_hash_rejection_full_roster(self):
        spec=self.fixture['specs'][0];path=spec['directory'];rawpath=path/'frames.jsonl.gz';mpath=path/'manifest.json'
        original=rawpath.read_bytes();manifest_bytes=mpath.read_bytes();saved=dict(spec)
        oldpin=self.fixture['small_pins'][str(mpath)]
        try:
            lines=gzip.decompress(original).splitlines(keepends=True)
            changed=gzip.compress(b''.join(lines[:-1]),mtime=0);rawpath.write_bytes(changed)
            spec.update(bytes=len(changed),raw_sha=hashlib.sha256(changed).hexdigest())
            manifest=json.loads(manifest_bytes);manifest['compressed_payload_bytes']=len(changed)
            mpath.write_text(json.dumps(manifest));self.fixture['small_pins'][str(mpath)]=m.sha(mpath)
            freeze,digest=self.preparation('terminal-count')
            with self.assertRaisesRegex(ValueError,'terminal_record'):
                m.run(self.path/'terminal-result',freeze_path=freeze,freeze_sha256=digest,fixture_inputs=self.fixture)
            rows=self.check_failure(self.path/'terminal-result.building')
            self.assertEqual(sum(r['evaluation_status']=='not_evaluated_archive_abort' for r in rows),504)
            # Preserve exact approved sizes/inventory while changing content;
            # the predecode raw digest must reject it, not the decoder.
            freeze,digest=self.preparation('raw-content');altered=bytearray(changed);altered[-1]^=1;rawpath.write_bytes(altered)
            with self.assertRaisesRegex(ValueError,'raw_digest_before_decode'):
                m.run(self.path/'raw-content-result',freeze_path=freeze,freeze_sha256=digest,fixture_inputs=self.fixture)
            self.check_failure(self.path/'raw-content-result.building')
        finally:
            rawpath.write_bytes(original);mpath.write_bytes(manifest_bytes)
            spec.clear();spec.update(saved);self.fixture['small_pins'][str(mpath)]=oldpin

    def test_source_regression_requires_snapshot_and_scoped_trade_control(self):
        a,snapshot=self.adapter();a.process(snapshot)
        update=copy.deepcopy(snapshot);now=T+NS//2
        update.update(receipt_utc_ns=now)
        update['annotation'].update(quality='wire_ok',source_min_ns=T-NS,source_max_ns=T-NS)
        update['payload']['type']='update/order_book'
        update['payload']['order_book'].update(nonce=2,begin_nonce=1,last_updated_at=(T-NS)//1000)
        self.assertEqual(a.process(update)[0]['reason'],'source_regression')
        update['annotation'].update(source_min_ns=now,source_max_ns=now)
        update['payload']['order_book']['last_updated_at']=now//1000
        self.assertEqual(a.process(update)[0]['type'],'invalidate')
        self.assertFalse(a.registry)
        snapshot['receipt_utc_ns']=now;snapshot['annotation'].update(source_min_ns=now,source_max_ns=now)
        snapshot['payload']['order_book']['last_updated_at']=now//1000
        self.assertEqual(a.process(snapshot)[0]['type'],'book')
        control=dict(kind='generation_invalidated',venue='rh_lighter',generation='rh_lighter-fixture',
                     receipt_utc_ns=now,scope='trade',reason='trade_gap')
        self.assertEqual(a.process(control),[]);self.assertTrue(a.registry)
        control.update(scope='book',market='1',reason='specific_gap')
        self.assertEqual(a.process(control)[0]['reason'],'specific_gap');self.assertFalse(a.registry)

    def test_raw_numeric_bound_snapshot_zero_overflow_and_identity(self):
        for case,expected in (('zero','nonpositive_raw_book'),('overflow','raw_level_overflow')):
            a,snapshot=self.adapter()
            if case=='zero':snapshot['payload']['order_book']['bids'][0]['size']='0'
            else:snapshot['payload']['order_book']['bids']*=5001
            self.assertEqual(a.process(snapshot)[0]['reason'],expected)
        a,snapshot=self.adapter();snapshot['channel']='trade'
        with self.assertRaisesRegex(ValueError,'envelope_identity'):a.process(snapshot)
        a,snapshot=self.adapter();snapshot['annotation']['source_max_ns']=True
        with self.assertRaisesRegex(ValueError,'annotation_clock'):a.process(snapshot)
        a,snapshot=self.adapter();snapshot['payload']['order_book']['bids'][0]['price']=Decimal('1000000000000.000000000000000001')
        with self.assertRaisesRegex(ValueError,'numeric_token_bound'):a.process(snapshot)


if __name__=='__main__':unittest.main()
