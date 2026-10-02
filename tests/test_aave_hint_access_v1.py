import copy
import importlib.util
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('hint',ROOT/'scripts/aave_hint_access_v1.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)


class HintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.setup=a.inputs()

    def fixtures(self):
        info=dict(count=1000,minBlock=a.LOW-10,maxBlock=a.HIGH+10,minTimestamp=100,maxTimestamp=2000000000,maxLimit=500)
        row=dict(block=a.HIGH-1,timestamp=self.setup['block_timestamp']-3,
                 hint=dict(hash=self.setup['double_hash'],txs=[dict(to=self.setup['prefix']['to'],callData=self.setup['prefix']['input'])]))
        return info,row

    def test_hash_and_calldata_match_are_distinct(self):
        info,row=self.fixtures()
        value=a.history_result([row],self.setup)
        self.assertEqual(value['identity_match_rows'],1)
        self.assertEqual(value['content_match_rows'],1)
        self.assertEqual(value['matches'][0]['target_timestamp_minus_hint_seconds'],3)
        row['hint']['hash']='0x'+'ab'*32
        value=a.history_result([row],self.setup)
        self.assertEqual(value['identity_match_rows'],0)
        self.assertEqual(value['content_match_rows'],1)
        row['hint']['txs'][0]={'hash':self.setup['hash']}
        value=a.history_result([row],self.setup)
        self.assertEqual(value['identity_match_rows'],1)
        self.assertEqual(value['content_match_rows'],0)

    def test_missing_content_does_not_disprove_identity_or_mean_full_absence(self):
        info,row=self.fixtures();row['hint']['txs']=None
        self.assertEqual(a.history_result([row],self.setup)['identity_match_rows'],1)
        row['hint']['hash']='0x'+'cd'*32
        value=a.history_result([row]*100,self.setup)
        self.assertEqual(value['matches'],[])
        self.assertTrue(value['limit_reached'])
        self.assertFalse(value['broader_absence_established'])
        self.assertFalse(a.history_result([],self.setup)['broader_absence_established'])

    def test_bad_range_schema_and_false_integer_rejected(self):
        for kind in ('outside','float','boolean','malformed_hash','oversize'):
            info,row=self.fixtures();rows=[row]
            if kind=='outside':row['block']=a.HIGH+1
            if kind=='float':row['timestamp']=1.5
            if kind=='boolean':row['block']=True
            if kind=='malformed_hash':row['hint']['hash']='0x'
            if kind=='oversize':rows=[row]*101
            with self.subTest(kind=kind),self.assertRaises((a.Refusal,a.h.Refusal)):
                a.history_result(rows,self.setup)
        for key,value in (('maxBlock',a.HIGH-1),('minBlock',a.LOW+1),('maxLimit',99)):
            info,row=self.fixtures();info[key]=value
            with self.subTest(key=key),self.assertRaises(a.Refusal):a.info_result(info)

    def execute(self,root,failure=None):
        info,row=self.fixtures()
        payloads=[a.encode(info),a.encode([row])]
        if failure=='sentinel':payloads[0]=b'x'*4097
        if failure=='range':info['minBlock']=a.HIGH;payloads[0]=a.encode(info)
        sent=[];closed=[]
        class Response:
            def __init__(self,index):
                self.status=403 if failure=='http' and index==0 else 200
                self.raw=payloads[index];self.at=0
            def getheaders(self):
                return [('Content-Type','application/json'),('Content-Length',str(len(self.raw)+(1 if failure=='truncated' else 0)))]
            def getheader(self,name,default):return default
            def read1(self,n):
                part=self.raw[self.at:self.at+min(n,73)];self.at+=len(part);return part
        class Connection:
            def __init__(self,host,timeout):
                assert host==a.HOST and 0<timeout<=20
                self.index=len(sent)
            def request(self,method,path,headers):
                assert method=='GET' and path==a.SLOTS[self.index][1]
                assert headers=={'Accept':'application/json','Accept-Encoding':'identity'}
                sent.append((method,path))
            def getresponse(self):return Response(self.index)
            def close(self):closed.append(self.index)
        (root/a.BASE).mkdir(parents=True)
        with mock.patch.object(a,'ROOT',root),mock.patch.object(a,'verify',return_value={'pins':[]}),\
             mock.patch.object(a,'inputs',return_value=self.setup),mock.patch.object(a.resource,'setrlimit'),\
             mock.patch.object(a.http.client,'HTTPSConnection',Connection):
            ok=a.run('a'*64)
            with self.assertRaises(FileExistsError):a.run('a'*64)
        self.assertEqual(len(closed),len(sent))
        return ok,sent

    def test_capture_exact_replay_tamper_and_exclusive_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ok,sent=self.execute(root);self.assertTrue(ok);self.assertEqual(len(sent),2)
            out=root/a.OUT
            value,body,raw=a.replay(out/'raw',self.setup)
            self.assertEqual(value['identity_match_rows'],1)
            term=a.decode((out/'terminal.json').read_bytes())
            self.assertEqual((body,raw),(term['body_bytes'],term['raw_bytes']))
            self.assertEqual(len(list((out/'raw').iterdir())),8)
            path=out/'raw/1.request.json';original=path.read_bytes();changed=a.decode(original)
            changed['host']='example.com';path.write_bytes(a.encode(changed))
            with self.assertRaisesRegex(a.Refusal,'request_identity'):a.replay(out/'raw',self.setup)
            path.write_bytes(original);(out/'raw/1.body').write_bytes(b'{}')
            with self.assertRaisesRegex(a.Refusal,'raw_integrity'):a.replay(out/'raw',self.setup)

    def test_failed_transport_and_coverage_retain_prefix_without_no_match(self):
        for failure in ('http','sentinel','range','truncated'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);ok,sent=self.execute(root,failure);self.assertFalse(ok);self.assertEqual(len(sent),1)
                out=root/a.OUT
                self.assertEqual(a.decode((out/'terminal.json').read_bytes())['status'],'unavailable')
                self.assertFalse((out/'projection.json').exists())
                if failure=='sentinel':self.assertEqual((out/'raw/1.body').stat().st_size,4097)
                if failure=='truncated':
                    self.assertEqual(a.decode((out/'terminal.json').read_bytes())['error'],'incomplete_content_length')
                with self.assertRaisesRegex(a.Refusal,'raw_manifest'):a.replay(out/'raw',self.setup)

    def test_reservation_precedes_connection(self):
        for key in ('raw_bytes','body_bytes'):
            with self.subTest(key=key),tempfile.TemporaryDirectory() as tmp:
                archive=a.Archive(Path(tmp)/'raw',time.monotonic())
                with mock.patch.dict(a.CAPS,{key:100}),mock.patch.object(a.http.client,'HTTPSConnection') as connect,\
                     self.assertRaisesRegex(a.Refusal,'reserve_before_dispatch'):
                    archive.get(*a.SLOTS[0])
                connect.assert_not_called();self.assertEqual(archive.attempts,0)

    def test_content_length_and_chunked_framing(self):
        self.assertEqual(a.body_length([('Content-Length','17')]),17)
        self.assertIsNone(a.body_length([('Transfer-Encoding','chunked')]))
        for headers in ([],[('Content-Length','-1')],[('Content-Length','1.0')],
                        [('Content-Length','1'),('Content-Length','1')],
                        [('Content-Length','1'),('Transfer-Encoding','chunked')],
                        [('Transfer-Encoding','gzip')]):
            with self.subTest(headers=headers),self.assertRaises(a.Refusal):a.body_length(headers)


if __name__=='__main__':unittest.main()
