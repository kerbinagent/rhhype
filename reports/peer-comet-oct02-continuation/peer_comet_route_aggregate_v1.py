"""Complete fixed-universe conditional bounds; caller hashes are not chain proof."""
BASE='0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48'
WETH='0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'
LEGEND=dict(N='conditional_nonpositive_upper',P='positive_upper_unresolved',
 E='empty_model_domain',Q='quote_unknown',U='pool_unknown',W='unknown_work',J='input_join_unknown')
def need(ok):
 if not ok: raise ValueError('aggregate input')
def decimal(x,hi=(1<<512)-1):
 need(type(x) is str and 1<=len(x)<=155 and x.isascii() and x.isdigit())
 n=int(x); need(str(n)==x and n<=hi); return n
def universe(model,census,queue):
 cr=census['result']['rows']; need(len(cr)==13 and len(queue)==59)
 assets=[r['tuple']['asset'] for r in cr]
 need(len(set(assets))==13 and assets.count(WETH)==1 and BASE not in assets)
 prev={}; ids=set()
 for i,q in enumerate(queue):
  model.integer(q['id'],i,i); model.integer(q['index'],0,12)
  mode=q['mode']; need(mode==('direct' if i<28 else 'weth'))
  need(type(q['fee']) is int and q['fee'] in (100,500,3000,10000) and q['pool'] not in ids)
  ids.add(q['pool']); pair=(q['index'],q['fee'])
  need(mode not in prev or pair>prev[mode]); prev[mode]=pair
  target=BASE if mode=='direct' else WETH
  need(assets[q['index']]!=target and [q['token0'],q['token1']]==sorted((assets[q['index']],target)))
 direct=[q for q in queue if q['mode']=='direct']; inner=queue[28:]
 outer=[q for q in direct if assets[q['index']]==WETH]; need(len(outer)==4)
 routes=[(q['index'],q,None) for q in direct]+[(q['index'],q,o) for q in inner for o in outer]
 need(len(routes)==152); return cr,assets,routes
def aggregate(model,bound,poolcore,census,quote,queue,batches,budget=None):
 cr,assets,routes=universe(model,census,queue)
 parent=census['result']['metadata']['parent']; join=None; params=[None]*13; qfail=[]
 try:
  need(quote['schema']=='peer-comet-quote-parameters-v1' and quote['parent']==parent and len(quote['rows'])==13)
  need(all(quote[k] is False for k in model.FLAGS))
  for i,r in enumerate(quote['rows']):
   need(type(r['index']) is int and r['index']==i and r['asset']==assets[i])
   if r['status']=='unknown': qfail.append([i,'unavailable']); continue
   try:
    need(r['status']=='model_ready' and r['dependency_invariance_proven'] is False and r['requires_principal_debit_ge_q'] is True)
    p,d=decimal(r['p']),decimal(r['d']); stock=decimal(cr[i]['inventory_native'],model.U256)
    caps=model.comet_caps(p,d,stock)
    need(r['empty'] is caps['empty'])
    for k in ('q_min','q_cap','output_cap','minimum_collateral'):
     need(decimal(r[k])==caps[k])
    params[i]=(p,d,stock,caps)
   except (ValueError,KeyError,TypeError): qfail.append([i,'caps'])
 except (ValueError,KeyError,TypeError): join='quote_join'; params=[None]*13
 pools={}; pfail=[]
 if type(batches) is not list or len(batches)!=6: join='batch_layout'
 else:
  for b,doc in enumerate(batches):
   chosen=queue[b*10:min(59,(b+1)*10)]; reason=None
   try:
    if doc is None: reason='unreached'
    else:
     need(type(doc['batch']) is int and doc['batch']==b and doc['parent_hash']==parent['hash'])
     count=5+5*len(chosen); model.integer(doc['planned_calls'],count,count)
     need(len(doc['rows'])==len(chosen))
     need(all(doc[k] is False for k in poolcore.FLAGS))
     need([r['id'] for r in doc['rows']]==[q['id'] for q in chosen])
     need(all(type(r['id']) is int for r in doc['rows']))
     if doc['state_coherent'] is not True or doc['status']!='metadata_complete': reason='failed_batch'
     else: model.integer(doc['attempted_calls'],count,count)
   except (ValueError,KeyError,TypeError): reason='batch_join'
   if reason:
    pfail.extend([q['id'],reason] for q in chosen); continue
   for q,r in zip(chosen,doc['rows']):
    try:
     model.integer(r['identity_checks_passed'],4,4); s=r['slot0']
     need(type(s) is list and len(s)==7 and r['status']=='reported_slot0')
     S=decimal(s[0],(1<<160)-1); model.integer(S,model.MIN_SQRT,model.MAX_SQRT-1)
     tick=model.integer(s[1],model.MIN_TICK,model.MAX_TICK)
     for x in s[2:5]: model.integer(x,0,65535)
     model.integer(s[5],0,255); need(type(s[6]) is bool)
     low=model.sqrt_at_tick(tick); high=model.sqrt_at_tick(tick+1) if tick<model.MAX_TICK else model.MAX_SQRT
     need(low<=S<=high)
     pools[q['id']]=dict(pool_id=q['pool'],token0=q['token0'],token1=q['token1'],fee=q['fee'],sqrt_price=S)
    except (ValueError,KeyError,TypeError): pfail.append([q['id'],'slot_or_identity'])
 if budget is None: budget=bound.Budget()
 need(type(budget) is bound.Budget)
 table=[]
 for i,a,b in routes:
  status='J' if join else 'Q'; upper=arg=None; points=0; covered=False
  if not join and params[i] is not None:
   p,d,stock,caps=params[i]
   if caps['empty']: status='E'; covered=True
   elif a['id'] not in pools or b is not None and b['id'] not in pools: status='U'
   else:
    ps=[pools[a['id']]]+([] if b is None else [pools[b['id']]])
    r=bound.maximum(model,p,d,stock,ps,assets[i],BASE,budget)
    status={v:k for k,v in LEGEND.items()}[r['status']]
    upper=None if r['upper_gain'] is None else str(r['upper_gain'])
    arg=None if r['upper_argmax_q'] is None else str(r['upper_argmax_q'])
    points=r['evaluated_points']; covered=r['domain_covered']
  table.append([i,a['id'],None if b is None else b['id'],status,upper,arg,points,covered])
 return dict(schema='peer-comet-route-upper-v1',parent_hash=parent['hash'],
  columns=['asset_index','qid1','qid2','status','upper_native_usdc','first_upper_argmax_q','enumerated_points','domain_covered'],
  status_legend=LEGEND,table=table,counts={k:sum(r[3]==k for r in table) for k in LEGEND},
  quote_failures=qfail,pool_failures=pfail,input_join_failure=join,
  points_admitted=budget.points,point_limit=budget.limit,time_scope='per-point admission, not hard wall',
  cost_rule='For complete P, nonrefundable native-USDC cost>=upper excludes strict positive cash. No cost floor supplied.',
  requires_source_runtime_binding=True,requires_dependency_invariance=True,
  requires_principal_debit_ge_net_q=True,**model.FLAGS)
