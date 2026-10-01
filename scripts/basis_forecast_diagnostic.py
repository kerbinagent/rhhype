"""Read-only post-outcome basis forecast diagnostic; never execution P&L."""
import bisect,gzip,hashlib,json,math,statistics
from collections import defaultdict,deque
from pathlib import Path
R=Path(__file__).resolve().parents[1];P=R/'reports/experiment-storage/basis-forecast-diagnostic-allocation-v1.json';O=R/'reports/basis-forecast-diagnostic'
def metrics(rows):
 if not rows:return {'n':0}
 median=[x['future']-x['median'] for x in rows];rw=[x['future']-x['current'] for x in rows]
 mm=statistics.mean(x*x for x in median);rm=statistics.mean(x*x for x in rw)
 moves=[(1 if x['current']>x['median'] else -1)*(x['current']-x['future']) for x in rows]
 return {'n':len(rows),'median_forecast_rmse_bps':math.sqrt(mm),'no_change_rmse_bps':math.sqrt(rm),'mse_skill_vs_no_change':1-mm/rm if rm else None,'median_forecast_mae_bps':statistics.mean(map(abs,median)),'no_change_mae_bps':statistics.mean(map(abs,rw)),'mean_favorable_fade_bps':statistics.mean(moves),'median_favorable_fade_bps':statistics.median(moves),'positive_fade_count':sum(v>0 for v in moves),'mean_predicted_excursion_bps':statistics.mean(abs(x['current']-x['median']) for x in rows)}
def main():
 plan=json.loads(P.read_bytes());src=R/plan['source_raw'];assert hashlib.sha256(src.read_bytes()).hexdigest()==plan['source_raw_sha256'];rows=[json.loads(l) for l in gzip.decompress(src.read_bytes()).splitlines()];meta=json.loads((src.parent/'metadata.json').read_bytes());mapping={f"{p[v]['venue']}:{p[v]['market']}":p['asset'] for p in meta['pairs'] for v in ('hl','other')};history=defaultdict(lambda:deque(maxlen=125));valid=defaultdict(list);forecasts=defaultdict(list)
 for r in rows:
  if r['kind']=='invalid':
   b=r['book'];history[mapping[f"{b['venue']}:{b['market']}"]].clear()
  elif r['kind']=='sample' and r['valid']:
   a=r['asset'];t=r['t'];v=r['basis_bps'];valid[a].append((t,v));history[a].append((t,v));prior=[(at,x) for at,x in history[a] if t-122<=at<=t-2]
   if len(prior)>=90 and prior[-1][0]-prior[0][0]>=89:forecasts[a].append({'t':t,'current':v,'median':statistics.median(x for _,x in prior)})
 output=[];all_principal=[];all_exc=[];details=[]
 for a in sorted(valid):
  values=valid[a];ts=[x[0] for x in values];matched=[];principal=[];last=-1e30
  for x in forecasts[a]:
   target=x['t']+60;i=bisect.bisect_left(ts,target);options=[j for j in (i-1,i) if 0<=j<len(ts)];j=min(options,key=lambda j:abs(ts[j]-target))
   if abs(ts[j]-target)>.25:continue
   y=x|{'asset':a,'target_t':ts[j],'future':values[j][1]};matched.append(y)
   if x['t']-last>=60:principal.append(y);last=x['t']
  excursions=[x for x in matched if abs(x['current']-x['median'])>=5]
  output.append({'asset':a,'valid_samples':len(valid[a]),'past_only_forecasts':len(forecasts[a]),'matched_targets':len(matched),'principal_60s_spaced_origins':metrics(principal),'overlapping_5bp_excursions':metrics(excursions)})
  all_principal+=principal;all_exc+=excursions;details+=principal
 result={'source_raw_sha256':plan['source_raw_sha256'],'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'plan_sha256':hashlib.sha256(P.read_bytes()).hexdigest(),'scope':'Post-outcome diagnostic only. Forecast target is basis60seconds later, not executable cash. Principal origins spaced60seconds perasset but crossassetdependence andsharedpasttraining remain; no confidenceclaim. Excursionrows overlap andarenotindependentsamples. Missing futuretargets skippedbytimestampcoverageonly. No activeexperimentchange.','by_asset':output,'principal_all_assets':metrics(all_principal),'overlapping_excursions_all_assets':metrics(all_exc),'principal_rows':details}
 data=gzip.compress((json.dumps(result,separators=(',',':'))+'\n').encode(),mtime=0);assert len(data)<=plan['categories_bytes']['output']-2048;O.mkdir(exist_ok=False);(O/'diagnostic.json.gz').write_bytes(data);print(json.dumps({k:result[k] for k in ('principal_all_assets','overlapping_excursions_all_assets')}));print([(x['asset'],x['principal_60s_spaced_origins']['n']) for x in output])
if __name__=='__main__':main()
