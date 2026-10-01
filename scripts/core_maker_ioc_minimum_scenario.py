"""Explicit source-consistent IOC minimum exemption; deployment acceptance unverified."""
from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal
from scripts.replay_core_maker_lit_corrected import OffsetControlBranch
class IocMinimumScenarioBranch(OffsetControlBranch):
 @contextmanager
 def _ioc_rules(self):
  maker,hedge=self.maker,self.hedge
  self.maker=replace(maker,min_qty=maker.qty_step,min_notional=Decimal(0))
  self.hedge=replace(hedge,min_qty=hedge.qty_step,min_notional=Decimal(0))
  try:yield
  finally:self.maker,self.hedge=maker,hedge
 def _fill_hedge(self,intent,book):
  with self._ioc_rules():return super()._fill_hedge(intent,book)
 def _fill_exit(self,venue,book):
  with self._ioc_rules():return super()._fill_exit(venue,book)
 def _episode_executable_exit_mark(self,now_ns):
  with self._ioc_rules():return super()._episode_executable_exit_mark(now_ns)
 def summary(self):
  with self._ioc_rules():result=super().summary()
  result['ioc_minimum_exemption']='published_circuit_scenario_not_verified_deployed_API'
  return result
