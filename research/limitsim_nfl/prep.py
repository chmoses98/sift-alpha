import json,gzip,glob,collections,sys
B='/tmp/claude-0/-home-user-sift-alpha/8175d499-d824-5369-8293-43901aad664c/scratchpad/'
D=B+'data/'; S=B+'limitsim/'
w=[x for x in json.load(open(D+'out_before/2026/season.actual_wagers.json'))['wagers'] if x['week'] in(4,6) and x['clv_eligible'] and x['transaction_phase']=='PRE_GAME' and x['execution_action']=='BUY']
dec={}
for x in w:
    k=(x['game'],x['market_ticker'],x['side'])
    d=dec.setdefault(k,dict(game=x['game'],ticker=x['market_ticker'],side=x['side'],week=x['week'],c=0,pc=0,t=[]))
    d['c']+=x['contracts'];d['pc']+=x['contracts']*x['execution_price'];d['t'].append(x['executed_at'])
closes={}
for f in glob.glob(D+'nfl_md/data/shadow/v2/closes/2026_04_*/*.gz')+glob.glob(D+'nfl_md2/data/shadow/v2/closes/2026_06_*/*.gz'):
    g=f.split('/')[-2]
    for l in gzip.open(f,'rt'):
        r=json.loads(l)
        c=dict((k,r.get(k)) for k in('yes_bid','yes_ask','no_bid','no_ask','mid','price_source_run','kickoff_utc','close_status','close_age_seconds','close_quality'));c['gid']=g
        closes[r['ticker']]=c
out=[]
for k,d in dec.items():
    d['close']=closes.get(d['ticker'])
    out.append(d)
json.dump(out,open(S+'decisions_private.json','w'))
print(len(out),sum(1 for d in out if d['close']))
ko=collections.defaultdict(set)
for d in out:
    if d['close']:ko[d['close']['gid']].add(d['close']['kickoff_utc'])
for g,v in sorted(ko.items()):print(g,v)
print(collections.Counter(d['close']['close_status'] if d['close'] else None for d in out))
