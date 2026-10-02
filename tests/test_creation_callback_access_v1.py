"""Tiny bounded EVM stack/call interpreter, not a gas/client conformance test."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import creation_callback_access_v1 as m


class Reverted(Exception): pass


class EVM:
    def __init__(self,fault=None):
        self.code={}; self.calls=[]; self.created=[]; self.steps=0; self.fault=fault
    def execute(self,code,address=7,caller=1,data=b'',depth=0):
        if depth>8: raise AssertionError('depth bound')
        stack=[]; memory=bytearray(4096); pc=0; ret=b''; destinations=set(); cursor=0
        while cursor<len(code):
            op=code[cursor]
            if op==0x5b: destinations.add(cursor)
            cursor+=1+(op-0x5f if 0x60<=op<=0x7f else 0)
        def pop():
            if not stack: raise AssertionError('stack underflow')
            return stack.pop()
        def region(offset,size):
            if offset<0 or size<0 or offset+size>4096: raise AssertionError('memory bound')
            return slice(offset,offset+size)
        while pc<len(code):
            self.steps+=1
            if self.steps>500 or len(stack)>128: raise AssertionError('work bound')
            op=code[pc]; pc+=1
            if 0x60<=op<=0x7f:
                n=op-0x5f
                if pc+n>len(code): raise AssertionError('truncated push')
                stack.append(int.from_bytes(code[pc:pc+n],'big')); pc+=n
            elif op==0x80: stack.append(stack[-1])
            elif op==0x14: stack.append(int(pop()==pop()))
            elif op==0x15: stack.append(int(pop()==0))
            elif op==0x30: stack.append(address)
            elif op==0x33: stack.append(caller)
            elif op==0x36: stack.append(len(data))
            elif op==0x35:
                off=pop(); stack.append(int.from_bytes(data[off:off+32].ljust(32,b'\0'),'big'))
            elif op==0x39:
                dest,off,size=pop(),pop(),pop(); memory[region(dest,size)]=code[off:off+size].ljust(size,b'\0')
            elif op==0x3b: stack.append(len(self.code.get(pop(),b'')))
            elif op==0x3d: stack.append(len(ret))
            elif op==0x51: stack.append(int.from_bytes(memory[region(pop(),32)],'big'))
            elif op==0x52:
                off,value=pop(),pop(); memory[region(off,32)]=value.to_bytes(32,'big')
            elif op==0x57:
                dest,condition=pop(),pop()
                if condition:
                    if dest not in destinations: raise AssertionError('invalid jumpdest')
                    pc=dest
            elif op==0x5a: stack.append(100000) # Arbitrary available gas; not metered.
            elif op==0x5b: pass
            elif op==0xf0:
                value,off,size=pop(),pop(),pop()
                if value: raise AssertionError('unexpected CREATE value')
                if self.fault=='create_failure': stack.append(0); continue
                child=100+len(self.created)
                runtime=self.execute(bytes(memory[region(off,size)]),child,address,depth=depth+1)
                self.created.append((child,runtime))
                self.code[child]=b'' if self.fault=='missing_runtime' else runtime
                stack.append(child); ret=b''
            elif op==0xf1:
                gas,target,value,off,size,outoff,outsize=[pop() for _ in range(7)]
                if value: raise AssertionError('unexpected CALL value')
                input_=bytes(memory[region(off,size)]); self.calls.append((address,target,input_))
                success=True
                try:
                    if self.fault=='call_failure' and depth==0: raise Reverted()
                    ret=self.execute(self.code.get(target,b''),target,
                        999 if self.fault=='wrong_self_caller' and address==target else address,input_,depth+1)
                    if self.fault=='short_return' and address==target: ret=ret[:-1]
                except Reverted: success=False; ret=b''
                memory[region(outoff,min(outsize,len(ret)))]=ret[:outsize]
                stack.append(int(success))
            elif op in (0xf3,0xfd):
                off,size=pop(),pop()
                if op==0xfd: raise Reverted()
                return bytes(memory[region(off,size)])
            else: raise AssertionError('unsupported opcode '+hex(op))
        return b''


def values():
    block=dict(hash='0x'+'aa'*32,parentHash='0x'+'bb'*32,number='0x10',timestamp='0x20',transactions=[])
    return ['0x1',block,*m.EXPECTED,dict(block)]


class Tests(unittest.TestCase):
    def test_bytecode_exact_offsets_live_child_and_authenticated_self_call(self):
        vm=EVM(); result=vm.execute(bytes.fromhex(m.CONSTANT))
        self.assertEqual('0x'+result.hex(),m.EXPECTED[0])
        vm=EVM(); result=vm.execute(bytes.fromhex(m.CALLBACK))
        self.assertEqual('0x'+result.hex(),m.EXPECTED[1])
        self.assertEqual(vm.created,[(100,bytes.fromhex(m.RUNTIME))])
        self.assertEqual(vm.calls,[(7,100,b''),(100,100,b'abcd')])
        spec=m.bytecode_spec()['offsets']
        outer=bytes.fromhex(m.CALLBACK); runtime=bytes.fromhex(m.RUNTIME)
        self.assertEqual(outer[spec['outer_child_offset']:],bytes.fromhex(m.CHILD))
        self.assertEqual(bytes.fromhex(m.CHILD)[12:],runtime)
        for code,pushes,targets in [(outer,spec['outer_jump_pushes'],[67]*4),
                                  (runtime,spec['runtime_jump_pushes'],[106,147,147,147,147,147])]:
            for pc,target in zip(pushes,targets):
                self.assertEqual(code[pc],0x61)
                self.assertEqual(int.from_bytes(code[pc+1:pc+3],'big'),target)
                self.assertEqual(code[target],0x5b)
        for fault in ('create_failure','missing_runtime','call_failure','wrong_self_caller','short_return'):
            with self.assertRaises(Reverted): EVM(fault).execute(outer)
        with self.assertRaises(Reverted): EVM().execute(runtime,100,999,b'abcd')
        with self.assertRaises(Reverted): EVM().execute(runtime,100,100,b'bad!')
        with self.assertRaises(Reverted): EVM().execute(runtime,100,100,b'abc')

    def test_dry_and_five_fixed_manifest(self):
        with patch.object(m,'run') as run,patch.object(m.h,'fetch') as fetch,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(m.main([]),0); run.assert_not_called(); fetch.assert_not_called()
        calls=m.build_manifest(); self.assertEqual(len(calls),5)
        for call in calls[2:4]:
            obj=call['params'][0]; self.assertNotIn('to',obj)
            self.assertEqual(set(obj),{'from','input','value','gasPrice','gas'})
            self.assertEqual(obj['gas'],hex(500000)); self.assertEqual(obj['gasPrice'],'0x0')
            self.assertEqual(call['params'][1],'$block.number')
        with patch.object(m.h,'fetch') as fetch:
            with self.assertRaises(Exception): m.run(None)
            fetch.assert_not_called()

    def test_pin_refusal_existing_output_and_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); pins=[]
            for path in (m.SOURCE,m.TEST,m.DESIGN,m.DRAFT):
                file=root/path; file.parent.mkdir(parents=True,exist_ok=True); file.write_bytes(b'fixture')
                pins.append(dict(path=path,bytes=7,sha256=m.sha(b'fixture')))
            for fixed in (m.HELPER,m.ALLOCATION):
                file=root/fixed['path']; file.parent.mkdir(parents=True,exist_ok=True)
                # No copies of the27KiB helper: map pin reads back to immutable originals.
                pins.append(fixed)
            plan=dict(schema='creation-callback-access-v1',status='frozen_creation_callback_probe',
                endpoint=m.ENDPOINT,output_dir=m.OUT,chain_id=1,allocation=m.ALLOCATION,helper=m.HELPER,
                resource_limits=m.CAPS,bytecode_spec=m.bytecode_spec(),request_manifest=m.build_manifest(),
                claims=m.CLAIMS,runtime=m.h.runtime(),source_pins=pins)
            file=root/m.PLAN; file.parent.mkdir(parents=True,exist_ok=True); raw=m.encode(plan); file.write_bytes(raw)
            original=m.read; original_root=m.ROOT
            def read(path,cap):
                if path in (root/m.HELPER['path'],root/m.ALLOCATION['path']):
                    return original(original_root/path.relative_to(root),cap)
                return original(path,cap)
            with patch.object(m,'ROOT',root),patch.object(m,'read',side_effect=read),patch.object(m.h,'fetch') as fetch:
                m.verify(m.sha(raw)); (root/m.OUT).mkdir()
                with self.assertRaises(FileExistsError): m.run(m.sha(raw))
                (root/m.SOURCE).write_bytes(b'changed')
                with self.assertRaises(m.Refusal): m.verify(m.sha(raw))
                fetch.assert_not_called()

    def fixture(self,out,results,fail=None):
        calls=[]
        def fetch(request,cap,seconds,emit,headers,dispatch):
            i=len(calls); calls.append(request); dispatch(); headers(200,m.encode(dict(status=200,headers=[])))
            if fail==i:
                emit(b'partial'); raise TimeoutError('synthetic timeout')
            raw=m.encode(dict(jsonrpc='2.0',id=i+1,result=results[i])); emit(raw); return 200,len(raw)
        with patch.object(m,'ROOT',out.parents[2]),patch.object(m,'verify',return_value=dict(source_pins=[])), \
             patch.object(m.h,'fetch',side_effect=fetch),patch.object(m.resource,'setrlimit'):
            ok=m.run('a'*64)
        return ok,calls

    def test_complete_replay_output_and_failure_denominator(self):
        for failure in (None,2):
            with tempfile.TemporaryDirectory() as tmp:
                out=Path(tmp)/m.OUT
                ok,calls=self.fixture(out,values(),failure)
                terminal=m.decode((out/'terminal.json').read_bytes())
                self.assertEqual(terminal['request_denominator'],5)
                if failure is None:
                    self.assertTrue(ok); self.assertEqual(len(calls),5)
                    state,pin=m.replay(out/'responses.frames')
                    self.assertEqual(m.decode((out/'projection.json').read_bytes()),state.projection('a'*64,pin))
                    self.assertTrue(all(c['params'][1]=='0x10' for c in calls[2:4]))
                else:
                    self.assertFalse(ok); self.assertEqual(len(calls),3)
                    self.assertIn(b'partial',(out/'responses.frames').read_bytes())
                    self.assertEqual(terminal['requests_attempted'],3)
                    self.assertFalse((out/'projection.json').exists())
                    with self.assertRaises(Exception): m.replay(out/'responses.frames')

    def test_canonical_output_and_raw_caps(self):
        for index,replacement in [(0,'0x2'),(3,'0x'+'11'*32),(4,dict(values()[4],hash='0x'+'cc'*32))]:
            state=m.State()
            for i,v in enumerate(values()[:index]): state.accept(i,v)
            with self.assertRaises(Exception): state.accept(index,replacement)
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp); frames=m.Frames(out)
            with self.assertRaises(m.Refusal): frames.append(b'D',b'x'*4097)
            frames.used=147456-2053
            with self.assertRaises(m.Refusal): frames.append(b'D',b'x')
            frames.append(b'E',b'{}'); frames.close()
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp); frames=m.Frames(out)
            frames.append(b'B',m.encode(dict(request=m.State().request(0))))
            frames.append(b'D',b'{}')
            frames.append(b'H',m.encode(dict(status=200,headers=[])))
            frames.close()
            with self.assertRaisesRegex(m.Refusal,'body_before_headers'): m.replay(out/'responses.frames')


if __name__=='__main__': unittest.main()
