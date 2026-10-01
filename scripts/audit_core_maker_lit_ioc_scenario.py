"""Apply frozen fill, cash, inventory and capital audit to the IOC scenario."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
import scripts.audit_core_maker_lit as audit
if __name__=='__main__':
 audit.R=ROOT/'reports/core-maker-lit-ioc-scenario'
 audit.run()
