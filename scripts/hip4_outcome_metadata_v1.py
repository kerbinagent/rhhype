#!/usr/bin/env python3
"""One frozen anonymous HIP-4 outcomeMeta lookup plus offline question checks.

Default is dry and performs no HTTP. The projection is structural: membership
comes only from documented QuestionSpec fields, never from names, descriptions,
expiry text or update streams. A structural candidate is not proven active, its
quoteToken string is a label rather than an asset identity, and native precision
stays unavailable. The certificate helpers are offline math for a later,
separately frozen screen and claim no fill, fee, lot or timing result.
Review: reports/hip4-outcome-v1/source-review.md
"""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import gzip
import http.client
import multiprocessing
import os
from pathlib import Path
import re
import ssl
import sys
import time
import zlib

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import polymarket_no_basket_metadata as pm  # reviewed strict JSON and deadline

Refusal = pm.Refusal
digest, encoded, utc, bounded_read = pm.digest, pm.encoded, pm.utc, pm.bounded_read

PLAN = ROOT / 'reports/experiment-storage/hip4-outcome-metadata-v1.json'
SCHEMA = 'hip4-outcome-metadata-v1'
SOURCE = 'scripts/hip4_outcome_metadata_v1.py'
TEST = 'tests/test_hip4_outcome_metadata_v1.py'
HELPER = 'scripts/polymarket_no_basket_metadata.py'
PREVIOUS = 'reports/experiment-storage/hip4-outcome-research-allocation-v1.json'
OUT = 'reports/hip4-outcome-v1/metadata-v1'
HOST, TARGET = 'api.hyperliquid.xyz', '/info'
URL = 'https://api.hyperliquid.xyz/info'
BODY = b'{"type":"outcomeMeta"}'
BODY_CAP = 131072  # worst-case gzip of this many bytes still fits GZIP_CAP
GZIP_CAP = 163840
PROJECTION_CAP = 32768
CONTROL_CAP = 12288
REQUEST_SECONDS = 20
PROCESS_SECONDS = 60
TEXT_CAP = 512
MAX_MEMBERS = 101  # deployer docs: at most 100 named outcomes plus the fallback
QUESTION_FIELDS = ('question', 'name', 'description', 'fallbackOutcome',
                   'namedOutcomes', 'settledNamedOutcomes')
OPTIONAL_TEXT = ('quoteToken', 'venue', 'deployer', 'deployerFeeScale')
OUTCOME_KEYS = frozenset(('outcome', 'name', 'description', 'sideSpecs') + OPTIONAL_TEXT)
UNVERIFIED = {
    'active_state': 'listing and empty settledNamedOutcomes do not prove an unsettled, tradable question',
    'quote_asset_identity': 'quoteToken is a string label; HIP-1 names are not unique',
    'native_precision': 'no documented outcome size/price precision field',
}
REQUEST_PLAN = {
    'count': 1, 'method': 'POST', 'url': URL, 'body': BODY.decode('ascii'),
    'content_type': 'application/json', 'max_body_bytes': BODY_CAP,
    'max_raw_gzip_bytes': GZIP_CAP, 'request_deadline_seconds': REQUEST_SECONDS,
    'process_deadline_seconds': PROCESS_SECONDS, 'retry': False, 'redirects': False,
    'environment_proxies': False, 'pagination': False, 'fallbacks': [],
    'documented_rate_weight': 20,
}
OUTPUT_LIMITS = {'raw_gzip': GZIP_CAP, 'metadata_projection': PROJECTION_CAP,
                 'claim_terminal_and_supervisor_receipts': CONTROL_CAP}
ZERO, ONE = Decimal(0), Decimal(1)


def verify(plan_sha256):
    if not isinstance(plan_sha256, str) or not re.fullmatch('[0-9a-f]{64}', plan_sha256):
        raise Refusal('expected_plan_sha_required')
    if pm.BODY_CAP < BODY_CAP:
        raise Refusal('helper_body_cap_changed')
    try:
        raw = bounded_read(PLAN, 32768)
    except OSError:
        raise Refusal('plan_unreadable') from None
    if digest(raw) != plan_sha256:
        raise Refusal('plan_sha_mismatch')
    p = pm.strict_json(raw)
    if not isinstance(p, dict) or p.get('schema') != SCHEMA:
        raise Refusal('plan_schema')
    if p.get('status') != 'frozen_metadata_probe':
        raise Refusal('plan_not_frozen')
    if encoded(p.get('request_plan')) != encoded(REQUEST_PLAN):
        raise Refusal('request_plan_changed')
    if p.get('output_dir') != OUT or encoded(p.get('output_limits_bytes')) != encoded(OUTPUT_LIMITS):
        raise Refusal('output_plan_changed')
    if (ROOT / OUT).resolve() != ROOT.resolve() / OUT:
        raise Refusal('output_symlink')
    pins = p.get('source_pins')
    if not isinstance(pins, list) or len(pins) != 3:
        raise Refusal('missing_source_pins')
    seen = set()
    for pin in pins:
        path = pin.get('path') if isinstance(pin, dict) else None
        if path not in (SOURCE, TEST, HELPER) or path in seen:
            raise Refusal('invalid_source_pin')
        if (ROOT / path).resolve() != ROOT.resolve() / path:
            raise Refusal('symlinked_source_pin')
        seen.add(path)
        data = bounded_read(ROOT / path, 262144)
        if type(pin.get('bytes')) is not int or len(data) != pin['bytes'] or digest(data) != pin.get('sha256'):
            raise Refusal('source_pin_mismatch')
    if p.get('previous') != PREVIOUS or digest(bounded_read(ROOT / PREVIOUS, 262144)) != p.get('previous_sha256'):
        raise Refusal('previous_plan_sha_mismatch')
    return p


def uint(value):
    return type(value) is int and value >= 0


def clip(value, cut, label):
    if len(value) > TEXT_CAP:
        cut.append(label)
        return value[:TEXT_CAP]
    return value


def tally(values):
    counts = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def outcome_spec(raw):
    """Project one outcome entry as (spec, issues); missing fields stay missing."""
    if not isinstance(raw, dict) or not uint(raw.get('outcome')):
        return None, ['outcome_entry_invalid']
    spec, issues, cut = {'outcome': raw['outcome']}, [], []
    for key in ('name', 'description'):
        if isinstance(raw.get(key), str):
            spec[key] = clip(raw[key], cut, key)
        else:
            issues.append(f'{key}_missing_or_not_string')
    sides = raw.get('sideSpecs')
    if not isinstance(sides, list) or len(sides) != 2:
        issues.append('side_specs_not_two')
    else:
        names, tokens, extra = [], [], set()
        for side in sides:
            if not isinstance(side, dict) or not isinstance(side.get('name'), str):
                issues.append('side_name_invalid')
                names.append(None)
                tokens.append(None)
                continue
            names.append(clip(side['name'], cut, 'sideSpecs.name'))
            tokens.append(side['token'] if uint(side.get('token')) else None)
            if 'token' in side and not uint(side['token']):
                issues.append('side_token_not_uint')
            extra.update(k[:64] for k in side if k not in ('name', 'token'))
        spec['sideNames'] = names
        if any(t is not None for t in tokens):
            spec['sideTokens'] = tokens
        if extra:
            spec['unknownSideKeys'] = sorted(extra)
    for key in OPTIONAL_TEXT:
        if key in raw:
            if isinstance(raw[key], str):
                spec[key] = clip(raw[key], cut, key)
                if key == 'quoteToken' and key in cut:
                    issues.append('quote_label_truncated')  # never compare clipped labels
            else:
                issues.append(f'{key}_not_string')
    unknown = sorted(k[:64] for k in raw if k not in OUTCOME_KEYS)
    if unknown:
        spec['unknownKeys'] = unknown
    if cut:
        spec['truncated'] = cut
    return spec, issues


def label(spec):
    """Count-only label; never used for membership, expiry or candidacy."""
    text = spec.get('description', '')
    if text.startswith('class:'):
        return text.split('|', 1)[0][:64]
    name = spec.get('name', '')
    return name[:64] if name.startswith('template:') else 'other'


def question_record(raw):
    if not isinstance(raw, dict) or not uint(raw.get('question')):
        return None
    q, issues, cut = {'question': raw['question']}, [], []
    for key in ('name', 'description'):
        if isinstance(raw.get(key), str):
            q[key] = clip(raw[key], cut, key)
        else:
            issues.append(f'{key}_missing_or_not_string')
    if uint(raw.get('fallbackOutcome')):
        q['fallbackOutcome'] = raw['fallbackOutcome']
    else:
        issues.append('fallback_missing_or_invalid')
    for key in ('namedOutcomes', 'settledNamedOutcomes'):
        value = raw.get(key)
        if isinstance(value, list) and all(uint(v) for v in value):
            q[key] = list(value)
        else:
            issues.append(f'{key}_missing_or_invalid')
    extra = sorted(k[:64] for k in raw if k not in QUESTION_FIELDS)
    if extra:
        q['unknownKeys'] = extra
    if cut:
        q['truncated'] = cut
    q['issues'] = issues
    return q


def shape(value):
    if isinstance(value, list):
        return f'list[{len(value)}]'
    if type(value) is int or (isinstance(value, str) and len(value) <= 64):
        return value
    return type(value).__name__


def analyze(obj):
    """Structural projection and question candidacy from one parsed outcomeMeta object."""
    result = {'schema': 'hip4-outcome-metadata-projection-v1', 'issues': [],
              'precision_status': 'unavailable_no_documented_field', 'unverified': UNVERIFIED,
              'maximum_conclusion': 'structure at one instant; a structural candidate may '
                                    'only motivate a separately reviewed design'}
    if not isinstance(obj, dict) or not isinstance(obj.get('outcomes'), list):
        result.update(status='inconclusive_schema', issues=['outcomes_list_missing'])
        return result
    result['top_level_keys'] = sorted(k[:64] for k in obj)
    specs, spec_issues, duplicates, invalid = {}, {}, set(), 0
    for raw in obj['outcomes']:
        spec, issues = outcome_spec(raw)
        if spec is None:
            invalid += 1
        elif spec['outcome'] in specs:
            duplicates.add(spec['outcome'])
        else:
            specs[spec['outcome']], spec_issues[spec['outcome']] = spec, issues
    counts = {'outcome_entries': len(obj['outcomes']), 'invalid_outcome_entries': invalid,
              'unique_outcomes': len(specs), 'duplicate_outcome_ids': len(duplicates),
              'outcomes_with_issues': sum(1 for v in spec_issues.values() if v)}
    result['counts'] = counts
    result['labels'] = tally(label(s) for s in specs.values())
    for key in ('quoteToken', 'venue', 'deployerFeeScale'):
        result[f'{key}_counts'] = tally(s[key] for s in specs.values() if key in s)
    counts['outcomes_with_deployer'] = sum('deployer' in s for s in specs.values())
    side_tokens = sum('sideTokens' in s for s in specs.values())
    if side_tokens:
        counts['outcomes_with_side_tokens'] = side_tokens
        result['precision_status'] = 'unavailable_side_token_indices_unjoined'
    for key in ('deployers', 'feeScale'):
        if key in obj:
            result[f'{key}_shape'] = shape(obj[key])
    if 'questions' not in obj:
        result['status'] = 'inconclusive_membership_unavailable'
        return result
    if not isinstance(obj['questions'], list):
        result.update(status='inconclusive_schema', issues=['questions_not_list'])
        return result
    records, invalid_questions, owners = [], 0, {}
    for raw in obj['questions']:
        q = question_record(raw)
        if q is None:
            invalid_questions += 1
        else:
            records.append(q)
    id_counts = tally(q['question'] for q in records)
    for index, q in enumerate(records):
        if id_counts[q['question']] > 1:
            q['issues'].append('duplicate_question_id')  # every occurrence
        fallback = [q['fallbackOutcome']] if 'fallbackOutcome' in q else []
        for member in set(q.get('namedOutcomes', []) + fallback + q.get('settledNamedOutcomes', [])):
            owners.setdefault(member, set()).add(index)
    for q in records:
        issues, named = q['issues'], q.get('namedOutcomes')
        fallback, settled = q.get('fallbackOutcome'), q.get('settledNamedOutcomes')
        if named is not None:
            if not named:
                issues.append('no_named_outcomes')
            if len(set(named)) != len(named):
                issues.append('duplicate_named_outcomes')
            if fallback in named:
                issues.append('fallback_in_named')
        if settled:
            issues.append('settled_named_outcomes_present')
            if named is not None and not set(settled) <= set(named):
                issues.append('settled_not_in_named')
        members = sorted(set(named or []) | ({fallback} if fallback is not None else set()))
        if len(members) > MAX_MEMBERS:
            issues.append('exceeds_documented_member_bound')
        quotes, member_specs = set(), []
        for member in members:
            if member in duplicates:
                issues.append(f'member_listed_twice:{member}')
            if member not in specs:
                issues.append(f'member_not_listed:{member}')
                continue
            if spec_issues[member]:
                issues.append(f'member_spec_invalid:{member}')
            if len(owners[member]) > 1:
                issues.append(f'member_shared:{member}')
            if specs[member].get('quoteToken'):
                quotes.add(specs[member]['quoteToken'])
            else:
                issues.append(f'member_quote_missing:{member}')
            member_specs.append(specs[member])
        if len(quotes) > 1:
            issues.append('quote_label_mismatch')
        q.update(member_count=len(members), member_specs=member_specs,
                 structural_candidate=not issues and len(members) >= 2)
        if q['structural_candidate']:
            q['common_quote_label'] = quotes.pop()
    candidates = sum(q['structural_candidate'] for q in records)
    structured = sum(q['member_count'] >= 2 for q in records)
    counts.update(questions=len(obj['questions']), invalid_question_entries=invalid_questions,
                  structured_questions=structured, structural_candidates=candidates,
                  standalone_outcomes=sum(1 for o in specs if o not in owners))
    result['questions'] = records
    result['standalone_outcomes'] = sorted(o for o in specs if o not in owners)
    if candidates:
        result['status'] = 'structural_candidate'
    elif not obj['questions']:
        # Only a valid, empty questions list shows absence; malformed entries stay inconclusive.
        result['status'] = 'park_no_question_structure'
    else:
        result['status'] = 'inconclusive_no_structural_candidate'
    return result


def fit(projection):
    """Reduce detail deterministically to the cap; the raw gzip keeps everything."""
    for level in ('full', 'without_member_specs', 'question_summaries', 'counts_only'):
        if level == 'without_member_specs':
            for q in projection.get('questions', []):
                q.pop('member_specs', None)
        elif level == 'question_summaries':
            projection['questions'] = [
                {'question': q['question'],
                 'structural_candidate': q.get('structural_candidate', False),
                 'issue_count': len(q.get('issues', ()))} for q in projection.get('questions', [])]
        elif level == 'counts_only':
            projection.pop('questions', None)
            projection.pop('standalone_outcomes', None)
        projection['detail_level'] = level
        if len(encoded(projection)) <= PROJECTION_CAP:
            return projection
    raise Refusal('projection_byte_cap')


def top(value):
    """(price, size) -> Decimals with 0 <= price <= 1 and size > 0, or None."""
    if value is None:
        return None
    try:
        price, size = (Decimal(str(v)) for v in value)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('invalid_quote') from None
    if not (price.is_finite() and size.is_finite() and ZERO <= price <= ONE and size > ZERO):
        raise ValueError('invalid_quote')
    return price, size


def certificate(book):
    """Zero-cost static certificate for one complete fixed common-collateral question.

    book maps member -> tops 'yes_bid', 'yes_ask', 'no_bid', 'no_ask' as (price, size)
    or None. ell=max(0,bY,1-aN) and u=min(1,aY,1-bN). Under the documented merged
    book both sides are the same orders: one representation is chosen, never summed,
    and any mismatch between them makes the snapshot unusable (no result, no route).
    Valid only for authoritative membership, collateral and active state at one instant.
    """
    if len(book) < 2:
        raise ValueError('question_needs_two_members')
    rows, crossed, mirror = {}, [], []
    for member in sorted(book):
        t = {k: top(book[member].get(k)) for k in ('yes_bid', 'yes_ask', 'no_bid', 'no_ask')}
        sell = [(t['yes_bid'][0], 1, 'sell_yes', t['yes_bid'][1])] if t['yes_bid'] else []
        if t['no_ask']:
            sell.append((ONE - t['no_ask'][0], 0, 'buy_no_merge', t['no_ask'][1]))
        buy = [(t['yes_ask'][0], 0, 'buy_yes', t['yes_ask'][1])] if t['yes_ask'] else []
        if t['no_bid']:
            buy.append((ONE - t['no_bid'][0], 1, 'split_sell_no', t['no_bid'][1]))
        dispose, acquire = (max(sell) if sell else None), (min(buy) if buy else None)
        ell = max(ZERO, dispose[0]) if dispose else ZERO
        u = min(ONE, acquire[0]) if acquire else ONE
        if ell > u:
            crossed.append(member)
        for a, b in (('yes_bid', 'no_ask'), ('yes_ask', 'no_bid')):
            if t[a] and t[b] and (t[a][0] != ONE - t[b][0] or t[a][1] != t[b][1]):
                mirror.append(member)
        rows[member] = {'ell': ell, 'u': u, 'dispose': dispose, 'acquire': acquire}
    sum_ell = sum(r['ell'] for r in rows.values())
    sum_u = sum(r['u'] for r in rows.values())
    result = {'members': len(rows), 'sum_ell': str(sum_ell), 'sum_u': str(sum_u),
              'crossed': crossed, 'mirror_mismatch': sorted(set(mirror)), 'route': None}
    if crossed or mirror:
        result['status'] = 'inconsistent_snapshot'
    elif sum_ell <= ONE <= sum_u:
        result['status'] = 'certified_no_static_cycle'
    elif sum_u < ONE:
        result.update(status='candidate_inverse', route=inverse_route(rows))
    else:
        route = forward_route(rows)
        result.update(status='candidate_forward' if route['cash_closed']
                      else 'candidate_forward_residual', route=route)
    return result


def forward_route(rows):
    """Constructive sale of a synthetic full YES set; margin sum(max(bY,1-aN))-1.

    S holds members disposed through NO (1-aN). k=0: split+negate one member for one
    full YES set from 1 collateral, then sell every YES. k>=1: buy each chosen NO,
    negate each, merge k-1 full YES sets, then sell the remaining YES. Upfront capital
    is 1 for k=0 and sum of chosen aN otherwise. Missing disposal leaves residual YES.
    """
    chosen, sold, residual, margin, cap, outlay = [], [], [], -ONE, None, ZERO
    for member, row in sorted(rows.items()):
        if row['dispose'] is None:
            residual.append(member)
            continue
        value, _, kind, size = row['dispose']
        margin += value
        cap = size if cap is None else min(cap, size)
        if kind == 'buy_no_merge':
            chosen.append(member)
            outlay += ONE - value  # the NO ask
        else:
            sold.append(member)
    if chosen:
        legs = [['buy_no', m] for m in chosen] + [['negate', m] for m in chosen]
        legs += [['merge_question', None]] * (len(chosen) - 1)
    else:
        first = min(rows)
        legs, outlay = [['split', first], ['negate', first]], ONE
    legs += [['sell_yes', m] for m in sold]
    return {'type': 'forward', 'margin_per_unit': str(margin), 'unit_cap': str(cap),
            'legs': legs, 'residual_yes': residual, 'cash_closed': not residual,
            'collateral_before_proceeds': str(outlay)}


def inverse_route(rows):
    """Buy outside YES, split selected members, merge the full YES set once, sell selected NO."""
    cost, cap, bought, split, outlay = ZERO, None, [], [], ZERO
    for member, row in sorted(rows.items()):
        value, _, kind, size = row['acquire']
        cost += value
        cap = size if cap is None else min(cap, size)
        if kind == 'buy_yes':
            bought.append(['buy_yes', member])
            outlay += value
        else:
            split.append(member)
    legs = bought + [['split', m] for m in split] + [['merge_question', None]]
    legs += [['sell_no', m] for m in split]
    return {'type': 'inverse', 'margin_per_unit': str(ONE - cost), 'unit_cap': str(cap),
            'legs': legs, 'residual_yes': [], 'cash_closed': True,
            'collateral_before_merge': str(outlay + len(split))}


def write_once(path, data):
    temporary = path.with_name(path.name + '.pending')
    with temporary.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(temporary, path)  # Atomic and refuses overwrite.
    temporary.unlink()


def publish(path, value, cap, controls=False):
    data = encoded(value)
    if len(data) > cap:
        raise Refusal('publication_byte_cap')
    if controls:
        used = sum(p.stat().st_size for p in path.parent.glob('*.json') if p.name != 'metadata.json')
        if used + 2 * len(data) > CONTROL_CAP:
            raise Refusal('control_total_byte_cap')
    write_once(path, data)


def fetch(sink, receipt):
    """One HTTPS POST; HTTPSConnection ignores proxies and follows no redirects."""
    connection = None
    try:
        with pm.hard_deadline(REQUEST_SECONDS, 'request_deadline'):
            connection = http.client.HTTPSConnection(HOST, timeout=REQUEST_SECONDS,
                                                    context=ssl.create_default_context())
            receipt['request_attempted'] = True
            connection.request('POST', TARGET, body=BODY, headers={
                'Content-Type': 'application/json', 'Accept': 'application/json',
                'Accept-Encoding': 'identity', 'User-Agent': 'rhhype-public-metadata/1.0',
                'Connection': 'close',
            })
            response = connection.getresponse()
            receipt['http_status'] = response.status
            receipt['server_date'] = (response.getheader('Date') or '')[:64] or None
            length = response.getheader('Content-Length')
            if length is not None and (not re.fullmatch(r'[0-9]{1,12}', length) or
                                       int(length) > BODY_CAP):
                raise Refusal('declared_body_byte_cap_or_invalid_length')
            while len(sink) < BODY_CAP:
                chunk = response.read1(min(16384, BODY_CAP - len(sink)))
                if not chunk:
                    receipt['body_complete'] = True
                    break
                sink.extend(chunk)
            if length is not None and len(sink) == int(length):
                receipt['body_complete'] = True
            if not receipt['body_complete']:
                raise Refusal('body_cap_reached_without_complete_eof')
            if length is not None and len(sink) != int(length):
                raise Refusal('incomplete_body')
            if response.status != 200:
                raise Refusal('http_status_not_200')
            if (response.getheader('Content-Encoding') or 'identity').lower() != 'identity':
                raise Refusal('unsupported_content_encoding')
            media = (response.getheader('Content-Type') or '').split(';', 1)[0].strip().lower()
            if media != 'application/json':
                raise Refusal('unsupported_content_type')
    finally:
        if connection is not None:
            connection.close()


def keep_raw(out, sink, receipt):
    """Preserve every received byte, including partial bodies, only as gzip."""
    if not receipt['request_attempted']:
        return
    data = bytes(sink)
    receipt.update(body_bytes=len(data), body_sha256=digest(data))
    packed = gzip.compress(data, compresslevel=9, mtime=0)
    if len(packed) > GZIP_CAP:
        raise Refusal('raw_gzip_byte_cap')
    write_once(out / 'response.json.gz', packed)
    receipt['raw_gzip_bytes'] = len(packed)


def worker(plan_sha256, out):
    receipt = {'schema': 'hip4-outcome-metadata-terminal-v1', 'started_utc': utc(),
               'plan_sha256': plan_sha256, 'status': 'inconclusive', 'code': None,
               'transport_code': None, 'request_attempted': False, 'http_status': None,
               'server_date': None, 'body_complete': False, 'body_bytes': 0,
               'body_sha256': None, 'raw_gzip_bytes': 0, 'projection_published': False}
    sink = bytearray()
    try:
        verify(plan_sha256)
        try:
            fetch(sink, receipt)
        except Refusal as exc:
            receipt['transport_code'] = str(exc)
        except Exception:
            receipt['transport_code'] = 'transport_failure'
        keep_raw(out, sink, receipt)
        if receipt['transport_code']:
            raise Refusal(receipt['transport_code'])
        verify(plan_sha256)
        projection = analyze(pm.strict_json(bytes(sink)))
        projection.update(plan_sha256=plan_sha256, body_sha256=receipt['body_sha256'],
                          server_date=receipt['server_date'])
        projection = fit(projection)
        verify(plan_sha256)
        publish(out / 'metadata.json', projection, PROJECTION_CAP)
        receipt.update(projection_published=True, status=projection['status'])
    except Refusal as exc:
        receipt['code'] = str(exc)
    except Exception:
        receipt['code'] = 'internal_failure'
    finally:
        receipt['ended_utc'] = utc()
        try:
            verify(plan_sha256)
        except Exception:
            receipt.update(code='post_run_pin_check_failed', status='inconclusive')
        publish(out / 'terminal.json', receipt, 4096, controls=True)


def read_json(path, cap):
    try:
        return pm.strict_json(bounded_read(path, cap))
    except Exception:
        return None


def raw_matches(path, terminal):
    """Bounded gunzip of the retained raw; it must reproduce the terminal's body hash."""
    try:
        packed = bounded_read(path, GZIP_CAP)
        inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
        data = inflater.decompress(packed, BODY_CAP + 1)
    except Exception:
        return False
    return (inflater.eof and not inflater.unconsumed_tail and not inflater.unused_data and
            len(packed) == terminal.get('raw_gzip_bytes') and len(data) <= BODY_CAP and
            len(data) == terminal.get('body_bytes') and digest(data) == terminal.get('body_sha256'))


def conclusion_checks(out, plan_sha256, finished):
    """Every gate must pass before any projection status can be cited."""
    terminal = read_json(out / 'terminal.json', 4096)
    projection = read_json(out / 'metadata.json', PROJECTION_CAP)
    valid_terminal = (isinstance(terminal, dict) and
                      terminal.get('schema') == 'hip4-outcome-metadata-terminal-v1' and
                      terminal.get('plan_sha256') == plan_sha256)
    checks = {
        'worker_completed_exit_zero': finished,
        'terminal_valid': valid_terminal,
        'terminal_without_failure': valid_terminal and terminal.get('code') is None
                                    and terminal.get('transport_code') is None
                                    and terminal.get('request_attempted') is True
                                    and terminal.get('body_complete') is True
                                    and terminal.get('http_status') == 200
                                    and terminal.get('projection_published') is True,
        'projection_matches_terminal': valid_terminal and isinstance(projection, dict) and
                                       projection.get('plan_sha256') == plan_sha256 and
                                       projection.get('body_sha256') == terminal.get('body_sha256') and
                                       projection.get('status') == terminal.get('status'),
        'raw_matches_terminal': valid_terminal and raw_matches(out / 'response.json.gz', terminal),
        'no_pending_publication': not any(out.glob('*.pending')),
    }
    try:
        verify(plan_sha256)
        checks['final_plan_and_source_pins'] = True
    except Exception:
        checks['final_plan_and_source_pins'] = False
    attempts = (int(terminal.get('request_attempted') is True) if valid_terminal
                else 'unknown_0_or_1')
    return checks, attempts, terminal if valid_terminal else None


def supervise(process, deadline, out, plan_sha256):
    process.start()
    process.join(max(0, deadline - time.monotonic() - 0.5))
    timed_out = process.is_alive()
    if timed_out:
        process.kill()
        process.join(max(0, deadline - time.monotonic()))
    finished = not timed_out and process.exitcode == 0
    checks, attempts, terminal = conclusion_checks(out, plan_sha256, finished)
    eligible = all(checks.values())
    raw = out / 'response.json.gz'
    record = {'schema': 'hip4-outcome-metadata-supervisor-v1', 'plan_sha256': plan_sha256,
              'ended_utc': utc(),
              'status': 'process_deadline' if timed_out else
                        'worker_finished' if terminal else 'worker_failed_without_valid_terminal',
              'worker_exitcode': process.exitcode, 'request_attempts': attempts,
              'raw_gzip_bytes': raw.stat().st_size if raw.exists() else 0,
              'checks': checks, 'conclusion_eligible': eligible,
              'conclusion_status': terminal['status'] if eligible else 'inconclusive'}
    if record['raw_gzip_bytes'] > GZIP_CAP:
        raise Refusal('raw_gzip_byte_cap_breached')
    publish(out / 'supervisor.json', record, 2048, controls=True)
    return record


def run(plan_sha256):
    deadline = time.monotonic() + PROCESS_SECONDS
    with pm.hard_deadline(PROCESS_SECONDS, 'process_deadline_before_claim'):
        verify(plan_sha256)
    out = ROOT / OUT
    out.mkdir(parents=True, exist_ok=False)
    publish(out / 'claim.json', {
        'schema': 'hip4-outcome-metadata-claim-v1', 'started_utc': utc(),
        'plan_sha256': plan_sha256, 'source_sha256': digest(bounded_read(ROOT / SOURCE, 65536)),
        'request_count_max': 1, 'url': URL, 'body': BODY.decode('ascii'),
        'purpose': 'metadata_availability_only',
    }, 2048, controls=True)
    # Fork retains the already pinned code. The worker independently verifies again.
    process = multiprocessing.get_context('fork').Process(target=worker, args=(plan_sha256, out))
    return supervise(process, deadline, out, plan_sha256)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--plan-sha256')
    args = parser.parse_args(argv)
    if not args.run:
        print(encoded({'status': 'dry_no_http', 'request_count': 0, 'url': URL,
                       'body': BODY.decode('ascii')}).decode(), end='')
        return 0
    try:
        result = run(args.plan_sha256)
    except Refusal as exc:
        result = {'status': 'refused_no_retry', 'code': str(exc)}
    except FileExistsError:
        result = {'status': 'refused_no_retry', 'code': 'existing_output'}
    except Exception:
        result = {'status': 'failed_no_retry', 'code': 'internal_failure'}
    print(encoded(result).decode(), end='')
    return 0 if result.get('conclusion_eligible') is True else 1


if __name__ == '__main__':
    raise SystemExit(main())
