"""Identical economics; preserve full trace with continuous lossless gzip."""
import gzip,json,sys,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts import replay_core_passive_fair_value as replay
from scripts.core_rh_small_shortterm import CapError
class Archive:
 def __init__(self,path,unused_old_cap):
  self.file=path.open('xb');self.encoder=zlib.compressobj(6,zlib.DEFLATED,31);self.cap=131072;self.bytes=0;self.count=0
 def add(self,row):
  encoder=self.encoder.copy();chunk=encoder.compress(replay.encode(row));probe=encoder.copy().flush(zlib.Z_FINISH)
  if self.bytes+len(chunk)+len(probe)>self.cap:raise CapError('lossless_trace_hard_cap')
  self.encoder=encoder;self.file.write(chunk);self.bytes+=len(chunk);self.count+=1
 def close(self):
  tail=self.encoder.flush(zlib.Z_FINISH);assert self.bytes+len(tail)<=self.cap
  self.file.write(tail);self.bytes+=len(tail);self.file.close()
def run():
 replay.RESULT=ROOT/'reports/core-passive-fair-retry'
 replay.PLAN=ROOT/'reports/experiment-storage/core-passive-fair-retry-v1.json'
 replay.Archive=Archive;replay.run()
if __name__=='__main__':run()
