#!/usr/bin/env python3
"""Rebuild all derived analysis and figures offline from the archived experiment."""
import pathlib,subprocess,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from analyze_live import analyze_run,summarize,csvwrite

def main():
    for script in ('build_inventory_tables.py','analyze_live.py','analyze_rh_lighter.py','roundtrip_check.py','history_analyze.py','analyze_comparator_live.py'):
        command=[sys.executable,str(ROOT/'scripts'/script)]
        if script=='history_analyze.py':command.extend(['--rh-multipliers',str(ROOT/'data/raw/robinhood_multipliers_20260929T040952Z.json')])
        subprocess.run(command,cwd=ROOT,check=True)
    p=ROOT/'data/raw/supplement_live/paired'
    obs,depth,rejected,quality=analyze_run(p)
    for name,data in [('summary',summarize(obs)),('observations',obs),('depth',depth)]:csvwrite(ROOT/f'data/derived/supplement_{name}.csv',data)
    for script in ('plot_results.py','build_report.py'):
        subprocess.run([sys.executable,str(ROOT/'scripts'/script)],cwd=ROOT,check=True)
if __name__=='__main__':main()
