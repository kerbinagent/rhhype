"""Bounded, single-use public RPC evidence capture and exact offline replay."""
import os
import time


class Refusal(Exception):
    pass


class Capture:
    def __init__(self, path, slots, caps, api, started, reason):
        path.mkdir(exist_ok=False)
        self.path, self.slots, self.caps = path, slots, caps
        self.api, self.started, self.reason = api, started, reason
        self.attempts = self.body_bytes = self.raw_bytes = 0

    def save(self, stem, kind, raw, cap):
        if len(raw) > cap or self.raw_bytes+len(raw) > self.caps['raw_bytes']:
            raise Refusal('raw_file_cap')
        with (self.path/(stem+'.'+kind)).open('xb') as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        self.raw_bytes += len(raw)

    def rpc(self, name, method, params, allow_unavailable=False):
        i = self.attempts
        if i >= len(self.slots) or self.slots[i][0] != name:
            raise Refusal('request_slot')
        cap, stem = self.slots[i][1], '%02d' % (i+1)
        request = dict(jsonrpc='2.0', id=i+1, method=method, params=params)
        payload = self.api.encode(dict(name=name, request=request, allow_unavailable=allow_unavailable))
        if (self.body_bytes+cap+1 > self.caps['body_bytes'] or
                self.raw_bytes+len(payload)+cap+1+4096 > self.caps['raw_bytes']):
            raise Refusal('reserve_before_dispatch')
        self.save(stem, 'request.json', payload, self.caps['request_bytes'])
        body, code, dispatched, failure = bytearray(), None, False, None
        with (self.path/(stem+'.body')).open('xb') as f:
            def emit(part):
                if len(body)+len(part) > cap+1 or self.body_bytes+len(part) > self.caps['body_bytes']:
                    raise Refusal('body_cap')
                f.write(part)
                f.flush()
                os.fsync(f.fileno())
                body.extend(part)
                self.body_bytes += len(part)
                self.raw_bytes += len(part)

            def headers(status, data):
                nonlocal code
                code = status
                self.save(stem, 'headers.json', data, 2048)

            def dispatch():
                nonlocal dispatched
                self.attempts += 1
                dispatched = True

            try:
                seconds = min(self.caps['request_seconds'],
                              self.caps['work_seconds']-(time.monotonic()-self.started))
                if seconds <= 0:
                    raise Refusal('work_deadline')
                code, count = self.api.h.fetch(request, cap, seconds, emit, headers, dispatch)
                if code != 200 or count != len(body):
                    raise Refusal('http_status_or_size')
            except Exception as exc:
                failure = self.reason(exc)
        self.save(stem, 'receipt.json', self.api.encode(dict(error=failure, http_status=code,
            dispatch_attempted=dispatched, response_bytes=len(body),
            response_sha256=self.api.sha(body), ended_ns=time.time_ns())), 2048)
        if failure:
            raise Refusal(failure)
        return self.api.rpc_result(bytes(body), i+1, allow_unavailable)


class Reader:
    def __init__(self, path, slots, caps, api):
        self.path, self.slots, self.caps, self.api = path, slots, caps, api
        self.attempts = self.body_bytes = self.raw_bytes = 0
        expected = {('%02d.' % i)+kind for i in range(1, len(slots)+1)
                    for kind in ('request.json', 'headers.json', 'body', 'receipt.json')}
        if {p.name for p in path.iterdir()} != expected:
            raise Refusal('raw_file_manifest')

    def rpc(self, name, method, params, allow_unavailable=False):
        i = self.attempts
        if i >= len(self.slots) or name != self.slots[i][0]:
            raise Refusal('replay_slot')
        cap, stem = self.slots[i][1], '%02d' % (i+1)
        request_raw = self.api.read(self.path/(stem+'.request.json'), self.caps['request_bytes'])
        header_raw = self.api.read(self.path/(stem+'.headers.json'), 2048)
        body = self.api.read(self.path/(stem+'.body'), cap)
        receipt_raw = self.api.read(self.path/(stem+'.receipt.json'), 2048)
        request, headers, receipt = map(self.api.decode, (request_raw, header_raw, receipt_raw))
        self.raw_bytes += sum(map(len, (request_raw, header_raw, body, receipt_raw)))
        self.body_bytes += len(body)
        self.attempts += 1
        if self.raw_bytes > self.caps['raw_bytes'] or self.body_bytes > self.caps['body_bytes']:
            raise Refusal('replay_raw_or_body_cap')
        expected = dict(name=name, request=dict(jsonrpc='2.0', id=i+1, method=method, params=params),
                        allow_unavailable=allow_unavailable)
        if request != expected:
            raise Refusal('request_manifest')
        if (headers.get('status') != 200 or receipt.get('error') is not None or
                receipt.get('http_status') != 200 or receipt.get('dispatch_attempted') is not True or
                receipt.get('response_bytes') != len(body) or receipt.get('response_sha256') != self.api.sha(body)):
            raise Refusal('incomplete_rpc')
        return self.api.rpc_result(body, i+1, allow_unavailable)

    def finish(self):
        if self.attempts != len(self.slots):
            raise Refusal('replay_unused_records')
