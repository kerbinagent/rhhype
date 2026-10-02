# Offline observations
PINS={
'v2':'f7e0a72a37f4d1d340fa137266be9c1ba4d96c87a0a57ac9ca193d62b301796c',
'helper':'879f58149d222bdfaa627d28b4335c2b01c72aba51a3771655f61764f473a908',
'census':'77ece9feac7ee802ad9ec675b1d058c015b19aa510f3a6a00783abe6a5f171c0',
'interface':'c74e2a73a7554c8f89e5e7fb307afc2569b215d3e44a41c95d74d450541201b9'}
EXTRA={'baseTokenPriceFeed()':'e7dad6bd','storeFrontPriceFactor()':'1f5954bd',
'getPrice(address)':'41976e09'}
def asset_info(h,value):
  raw=h.hex_bytes(value,256)
  w=['0x'+raw[i:i+32].hex() for i in range(0,256,32)]
  return dict(zip(('offset','asset','price_feed','scale','borrow_factor',
    'liquidate_factor','liquidation_factor','supply_cap'),
    (h.uint(w[0],8),h.address(w[1]),h.address(w[2]),h.uint(w[3],64),
     h.uint(w[4],64),h.uint(w[5],64),h.uint(w[6],64),h.uint(w[7],128))))
def collect(v,h,c,rpc):
  parent,m,assets=v.census(h,c); anchor=h.state_selector(parent); prior=c['result']['rows']
  rows=[dict(index=i,asset=a,status='UNKNOWN',price=None,stock=None,
    price_attempted=False) for i,a in enumerate(assets)]
  out=dict(parent=parent,rows=rows,status='UNKNOWN',state_coherent=False,
    checks={},base={},views={},planned_calls=55,prices_native_only=True,
    freshness_proven=False,usd_units_proven=False,discount_formula_used=False,**v.FLAGS)
  checks=out['checks']; current=None
  def equal(key,a,b):
    checks[key]=a==b; v.need(checks[key])
  def view(sig,*args):
    if sig in EXTRA:
      data='0x'+EXTRA[sig]+''.join(format(int(a,16),'064x') for a in args)
      call=dict(h.call_object(h.COMET,'baseToken()'),input=data)
    else: call=h.call_object(h.COMET,sig,*args)
    return rpc('eth_call',[call,anchor])
  def slot():
    return h.address(rpc('eth_getStorageAt',[h.COMET,h.IMPLEMENTATION_SLOT,anchor]))
  try:
    equal('chain',h.quantity(rpc('eth_chainId',[])),1)
    equal('header',h.header(rpc('eth_getBlockByNumber',[parent['number'],False])),parent)
    equal('slot',slot(),m['identity']['implementation_slot'])
    for role in ('proxy','implementation','asset_list'):
      d=m['identity'][role]; code=h.hex_bytes(rpc('eth_getCode',[d['address'],anchor]))
      equal(role,(len(code),h.sha(code)),(d['runtime_bytes'],d['runtime_sha256']))
    base=out['base']
    base['token']=h.address(view('baseToken()')); v.need(base['token']==h.USDC)
    base['scale']=h.uint(view('baseScale()')); v.need(base['scale']==1000000)
    base['feed']=h.address(view('baseTokenPriceFeed()'))
    base['store_front_factor']=h.uint(view('storeFrontPriceFactor()'))
    v.need(base['store_front_factor']<=10**18)
    g=out['views']
    for sig,key,decode in (
      ('isBuyPaused()','buy_paused',h.boolean),
      ('getReserves()','signed_base_reserves',lambda x:str(h.sint(x))),
      ('targetReserves()','target_reserves',lambda x:str(h.uint(x,104)))):
      g[key]=decode(view(sig)); equal(key,g[key],m['global_views'][key])
    for row in rows:
      current=row; i=row['index']
      equal('tuple_'+str(i),asset_info(h,view('getAssetInfoByAddress(address)',assets[i])),
        prior[i]['tuple'])
    for row in rows:
      current=row; i=row['index']
      row['stock']=str(h.uint(view('getCollateralReserves(address)',assets[i])))
      equal('stock_'+str(i),row['stock'],prior[i]['inventory_native'])
    current=None; seen={}
    def price(feed):
      answer=h.uint(view('getPrice(address)',feed))
      v.need(1<=answer<2**255)
      if feed in seen: v.need(seen[feed]==answer)
      seen[feed]=answer; return str(answer)
    base['price']=price(base['feed'])
    for row in rows:
      current=row; row['price_attempted']=True
      row['price']=price(prior[row['index']]['tuple']['price_feed'])
      row['status']='reported_native_answer'
    current=None
    equal('slot_final',slot(),m['identity']['implementation_slot'])
    equal('header_final',h.header(rpc('eth_getBlockByNumber',[parent['number'],False])),parent)
    out['state_coherent']=True; out['status']='metadata_complete'
  except Exception as error:
    if current is not None: current['failed']=True
    out['error']=type(error).__name__+':'+ascii(error)[:120]
    for row in rows: row['status']='UNKNOWN'
  v.need(len(h.encoded(out))<=6000)
  return out
