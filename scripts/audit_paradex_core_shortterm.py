"""Offline independent accounting and fill-evidence checks; run only after endpoint."""
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'reports/paradex-core-shortterm'
TOL = D('0.00000001')


def dec(value):
    return D(str(value))


def close(a, b):
    assert abs(dec(a)-dec(b)) <= TOL, (str(a), str(b))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    s = json.loads((OUT/'summary.json').read_text())
    assert s['counters']['runtime_completed'] == 1 and s['error'] is None
    assert digest(OUT/'events.jsonl.gz') == s['raw_sha256']
    assert digest(OUT/'unresolved.json.gz') == s['unresolved_sha256']
    assert digest(ROOT/'scripts/paradex_core_shortterm.py') == s['source_sha256']
    assert digest(ROOT/'reports/experiment-storage/paradex-core-shortterm-allocation-v1.json') == s['plan_sha256']
    for m in s['metadata']:
        assert digest(OUT/f"{m['venue']}-metadata.json.gz") == m['sha256']
    rows = [json.loads(x) for x in gzip.decompress((OUT/'events.jsonl.gz').read_bytes()).splitlines()]
    assert len(rows) == s['records']
    candidate_books = defaultdict(list)
    for row in rows:
        if row['kind']=='candidate_book':
            b=row['book']; k=f"{b['venue']}:{b['market']}"
            for label in row['branches']:candidate_books[(label,k)].append(b)
    pending = json.loads(gzip.decompress((OUT/'unresolved.json.gz').read_bytes()))
    funding_rows=defaultdict(list)
    for row in rows:
        if row['kind']=='funding_index':funding_rows[row['asset']].append(row['data'])
    positions = defaultdict(list)
    fills = defaultdict(list)
    admissions = Counter()
    counts = Counter(r['kind'] for r in rows)
    for r in rows:
        if r['kind'] == 'terminal_position':
            positions[r['branch']].append(r['data'])
        elif r['kind'] == 'fill':
            fills[(r['branch'], r['data']['position_id'], r['data']['leg'])].append(r)
        elif r['kind'] == 'admission':
            admissions[r['branch']] += 1
            signal = r['signal']
            t = signal['timestamp']
            prior = [(at, v) for at, v in r['history'] if t-122 <= at <= t-2]
            assert len(prior) >= 90 and prior[-1][0]-prior[0][0] >= 89
            values = sorted(v for _, v in prior)
            median = values[len(values)//2] if len(values)%2 else sum(values[len(values)//2-1:len(values)//2+1])/2
            close(median, signal['historical_basis_bps'])
            assert signal['net_edge_usd'] > 0 and signal['favorable_excursion_bps'] >= 5
            f=signal['funding_reference'];assert f['received']<=t and 0<=t-f['created']<=7
    reports = []
    audited_fills = 0
    for branch in s['branches']:
        label = branch['branch']
        assert admissions[label] == branch['attempts']
        all_positions = positions[label] + pending[label]
        assert len(all_positions) == branch['attempts']
        assert len({p['id'] for p in all_positions}) == len(all_positions)
        cash = stress = capital = D(0)
        wins = stressed_wins = minimum_cases = 0
        closed = []
        wallet_changes = defaultdict(D)
        for p in all_positions:
            total_pnl = total_fees = D(0)
            below_min = False
            for leg in p['legs']:
                events = fills[(label, p['id'], leg['key'])]
                entry_q = entry_value = entry_fees = exit_q = exit_value = exit_fees = pnl = D(0)
                for r in events:
                    f = r['data'];book = f['book'];intent = f['intent'];q = dec(f['fill_quantity']);value = dec(f['fill_value'])
                    assert book['valid'] and book['generation'] == intent['generation']
                    assert book['engine_time'] >= intent['due'] and intent['due'] <= book['received'] <= intent['expires']
                    assert 0 <= book['received']-book['engine_time'] <= 2
                    assert abs((intent['due']-intent['created'])-.4) < .000001
                    eligible=[b for b in candidate_books[(label,leg['key'])] if b.get('valid') and b.get('generation')==intent['generation'] and intent['due']<=b['received']<=intent['expires'] and b.get('engine_time') is not None and intent['due']<=b['engine_time']<=b['received'] and b['received']-b['engine_time']<=2 and b['bids'] and b['asks'] and b['bids'][0][0]<b['asks'][0][0]]
                    assert eligible and eligible[0]['received']==book['received']
                    for field in ('sequence','generation','bids','asks','engine_time'):assert eligible[0][field]==book[field]
                    is_entry = intent['kind'] == 'entry'
                    buy = (leg['side'] == 'long') if is_entry else (leg['side'] == 'short')
                    remaining = q;rebuilt = D(0)
                    for price, size in f['available_side_before_fill']:
                        taken = min(remaining, dec(size))
                        if taken > 0:
                            if is_entry:
                                assert price <= intent['price_limit'] if buy else price >= intent['price_limit']
                            rebuilt += taken*dec(price);remaining -= taken
                        if remaining == 0:break
                    close(remaining, 0);close(rebuilt, value)
                    close(q/dec(leg['step']), round(q/dec(leg['step'])))
                    fee = value*dec(f['fill_fee_bps'])/10000
                    assert fee == 0
                    if is_entry:
                        entry_q += q;entry_value += value;entry_fees += fee
                        assert q >= dec(leg['min_qty']) and value >= dec(leg['min_notional'])
                        assert value <= dec(label.split('-')[0])+TOL
                    else:
                        exit_q += q;exit_value += value;exit_fees += fee
                        pnl += (value-dec(leg['entry_vwap'])*q)*(1 if leg['side']=='long' else -1)
                        if q < dec(leg['min_qty']) or value < dec(leg['min_notional']):below_min = True
                    audited_fills += 1
                close(entry_q, leg['quantity']);close(entry_value, leg['entry_value'])
                close(entry_q-exit_q, leg['remaining']);close(exit_value, leg['exit_value'])
                close(entry_fees+exit_fees, leg['fees_usd']);close(pnl, leg['price_pnl'])
                assert len([r for r in events if r['data']['intent']['kind']=='exit']) == len(leg['exit_fills'])
                total_pnl += pnl;total_fees += entry_fees+exit_fees
                wallet_changes[leg['venue']] += pnl-entry_fees-exit_fees
            if p.get('capital_costs_usd') is not None:
                wallet_changes[p['legs'][0]['venue']] -= dec(p['capital_costs_usd'])+dec(p['other_costs_usd'])
            if p['status'] in ('CLOSED', 'CLOSED_ESTIMATED'):
                assert p['status']=='CLOSED_ESTIMATED' and p['funding']['estimated']
                expected_events=sorted((l['side'],l['entry_time'],f['timestamp'],f['quantity']) for l in p['legs'] if l['venue']=='paradex' for f in l['exit_fills'])
                actual_events=sorted((e['side'],e['entry']['timestamp'],e['exit']['timestamp'],e['quantity']) for e in p['funding']['events'])
                assert expected_events==actual_events
                recalculated_funding=D(0)
                for event in p['funding']['events']:
                    index=[]
                    for end in ('entry','exit'):
                        point=event[end];t=point['timestamp'];history=funding_rows[p['asset']]
                        a=[x for x in history if x['created']<=t][-1];b=[x for x in history if x['created']>=t][0]
                        assert a['received']<=p['settled_at'] and b['received']<=p['settled_at']
                        assert a==point['before'] and b==point['after'] and 0<=b['created']-a['created']<=6
                        val=dec(a['index']) if a['created']==b['created'] else dec(a['index'])+(dec(b['index'])-dec(a['index']))*(dec(t)-dec(a['created']))/(dec(b['created'])-dec(a['created']))
                        close(val,point['index']);index.append(val)
                    amount=-dec(event['quantity'])*(1 if event['side']=='long' else -1)*(index[1]-index[0])
                    close(amount,event['cashflow_usd']);recalculated_funding+=amount
                    wallet_changes['paradex']+=amount
                close(recalculated_funding,p['funding_usd'])
                capital_expected=sum((dec(l['exit_time'])-dec(l['entry_time']))*dec(l['entry_value'])*D('.05')/D(365*86400) for l in p['legs'] if l['entry_time'] is not None)
                close(capital_expected,p['capital_costs_usd'])
                for leg in p['legs']:
                    if leg['venue']=='lighter' and leg['quantity']:
                        assert all(int(leg['entry_time']//3600)==int(f['timestamp']//3600) for f in leg['exit_fills'])
                close(total_pnl, p['price_pnl']);close(total_fees, p['fees_usd'])
                trade_cash = total_pnl-total_fees+recalculated_funding
                trade_stress = trade_cash-dec(p['capital_costs_usd'])-D('.0005')*max(dec(l['entry_value']) for l in p['legs'])
                cash += trade_cash;stress += trade_stress;capital += dec(p['capital_costs_usd'])
                wins += trade_cash > 0;stressed_wins += trade_stress > 0;minimum_cases += below_min
                closed.append(p)
        ledger = branch['ledger']['standard']
        for venue, balance in ledger['wallets'].items():
            close(dec(ledger['initial_capital'])/2+wallet_changes[venue], balance)
        close(cash, branch['cash_pnl']);close(stress, branch['after_capital_and_stress'])
        assert len(closed)==branch['closed'] and wins==branch['cash_wins'] and stressed_wins==branch['stressed_wins']
        assert minimum_cases==branch['below_public_exit_minimum_cases']
        reports.append({'branch':label,'closed':len(closed),'cash_pnl':str(cash),'cash_wins':wins,'capital_charge':str(capital),'after_capital_and_stress':str(stress),'stressed_wins':stressed_wins,'below_public_exit_minimum_cases':minimum_cases,'pending_positions':len(pending[label]),'wallet_identity':'passed'})
    assert audited_fills == counts['fill']
    report = {'status':'passed','audit_source_sha256':digest(Path(__file__)),'raw_sha256':s['raw_sha256'],'record_counts':dict(counts),'audited_fills':audited_fills,'checks':'Source/plan/raw/metadata hashes; past-only reference; all recorded fills reconstructed from depth; lot grid, entry minima and cap; 400ms delay and advanced source clock; terminal leg and branch accounting; independent linear index interpolation and funding wallet allocation (estimated); per-venue wallet identities. First eligible book checked against all retained normalized callbacks during pending intents. Full wire stream and idle books are not retained; completeness depends on frozen callback capture.','branches':reports}
    data = (json.dumps(report,indent=2)+'\n').encode()
    assert len(data)<=8192
    with (OUT/'audit.json').open('xb') as f:f.write(data)
    print(data.decode())


if __name__ == '__main__':
    main()
