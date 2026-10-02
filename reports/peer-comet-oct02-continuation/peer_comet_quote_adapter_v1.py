"""Native-unit model; inputs do not prove chain state."""
F=10**18
U=(1<<256)-1
FLAGS=dict(authority_verified=False,source_equivalence_proven=False,
 economic_state_verified=False,cash_closed_execution_proven=False,
 inclusion_proven=False,profitability_proven=False)
def integer(x,lo=0,hi=U):
 if type(x) is not int or not lo<=x<=hi: raise ValueError('integer_domain')
 return x
def decimal(x):
 if type(x) is not str or not x.isascii() or not x.isdigit() or len(x)>78 or str(int(x))!=x:
  raise ValueError('decimal_domain')
 return int(x)
def checked(x):
 if x>U: raise ValueError('checked_product_overflow')
 return x
def derive(B,A,a,b,s,l,stock,k=1):
 try:
  integer(B,1,(1<<255)-1); integer(A,1,(1<<255)-1)
  integer(a,1,(1<<64)-1); integer(b,1000000,1000000); integer(s,0,F)
  integer(l,0,(1<<64)-1); integer(stock); integer(k,1)
  if l>F: raise ValueError('factor_subtraction_underflow')
  discount=checked(s*(F-l))//F
  price=checked(A*(F-discount))//F
  if price==0: raise ValueError('zero_discounted_price')
  p,d=B*a,price*b
  m=min(stock,(1<<128)-1); low=(k*d+p-1)//p
  qa=U//p; qi=((m+1)*d-1)//p; high=min(qa,qi)
  return dict(status='model_ready',p=p,d=d,discount=discount,
   discounted_price=price,q_min=low,q_cap=high,q_arithmetic=qa,
   q_inventory=qi,output_cap=m,minimum_collateral=k,empty=low>high,
   requires_principal_debit_ge_q=True,dependency_invariance_proven=False,**FLAGS)
 except ValueError as e: return dict(status='unknown',reason=str(e),**FLAGS)
def adapt(census,metadata,index,k=1):
 try:
  integer(index,0,12)
  if (metadata['state_coherent'] is not True or metadata['status']!='metadata_complete' or
      metadata['parent']!=census['result']['metadata']['parent']):
   raise ValueError('metadata_unavailable')
  rows=census['result']['rows']; observed=metadata['rows']
  if len(rows)!=13 or len(observed)!=13: raise ValueError('row_domain')
  t=rows[index]['tuple']; r=observed[index]; b=metadata['base']
  integer(r['index'],0,12)
  if (r['index']!=index or r['asset']!=t['asset'] or
      r['stock']!=rows[index]['inventory_native'] or r['status']!='reported_native_answer' or
      b['scale']!=1000000 or b['token']!='0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48'):
   raise ValueError('metadata_join')
  return derive(decimal(b['price']),decimal(r['price']),t['scale'],b['scale'],
   b['store_front_factor'],t['liquidation_factor'],decimal(r['stock']),k)
 except (ValueError,KeyError,TypeError) as e:
  return dict(status='unknown',reason=str(e),**FLAGS)
