"""Isolate maker exit decisions from the separately reported stress reserve."""
from scripts.core_passive_lit_branch import CorePassiveBranch
from scripts.core_passive_sell_branch import CorePassiveSellBranch
class CashExitMixin:
 def _episode_executable_exit_mark(self,now):
  mark=super()._episode_executable_exit_mark(now)
  return None if mark is None else mark+self.reserve_cost-self._episode_start_reserve
class CashBuyBranch(CashExitMixin,CorePassiveBranch):pass
class CashSellBranch(CashExitMixin,CorePassiveSellBranch):pass
