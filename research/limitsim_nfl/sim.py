#!/usr/bin/env python3 -I
"""Resting-limit-buy vs closing-ask simulation (research only). stdlib only.
Inputs (extracts made by fetch.py): decisions_private.json, ext/{quotes,books,trades,trades_meta}, names.txt.
Output: results.json (aggregates only). Run: python3 -I sim.py"""
import json,glob,os,math,random,collections,datetime as dt
S=os.path.dirname(os.path.abspath(__file__))+'/'
WEEKS=(4,); HS=[48,24,12,6,1]; RULES=['AT_BID','BID_PLUS_1TICK','INSIDE_MID','AT_ASK']
MAKER,TAKER=0.0175,0.07; NBOOT=2000; GAP_S=180; MAXAGE_S=1800
def T(s):
    if 'Z' in s: s=s.split('Z')[0].lstrip('"')+'+00:00'
    return dt.datetime.fromisoformat(s)
def R(s): return dt.datetime.strptime(s,'%Y%m%dT%H%M%SZ').replace(tzinfo=dt.timezone.utc)
def fee(c,p,rate): return math.ceil(round(rate*c*p*(1-p)*100,6))/100.0
def f(x):
    try: return float(x)
    except: return None
excl=collections.Counter()
dec=[d for d in json.load(open(S+'decisions_private.json')) if d['week'] in WEEKS]
# ---- load extracts
Q={};BK={};qruns=set()
for fn in glob.glob(S+'ext/quotes/*.jsonl'):
    r=os.path.basename(fn)[:16];qruns.add(r)
    for l in open(fn):
        x=json.loads(l);Q[(r,x['ticker'])]=x
for fn in glob.glob(S+'ext/books/*.jsonl'):
    r=os.path.basename(fn)[:16]
    for l in open(fn):
        x=json.loads(l);BK[(r,x['ticker'])]=x
tick={d['ticker'] for d in dec}
TR=collections.defaultdict(dict);nblock=0
for fn in glob.glob(S+'ext/trades/*.v2.jsonl'):
    for l in open(fn):
        x=json.loads(l)
        if x['ticker'] not in tick: continue
        TR[x['ticker']][x['trade_id']]=x
cov=[]
for fn in glob.glob(S+'ext/trades_meta/*.json'):
    m=json.load(open(fn))
    if m['rows']>0: cov.append((T(m['lo']),T(m['hi'])))
cov.sort()
merged=[]
for a,b in cov:
    if merged and (a-merged[-1][1]).total_seconds()<=GAP_S: merged[-1][1]=max(merged[-1][1],b)
    else: merged.append([a,b])
def covered(a,b):
    """True if [a,b] lies inside one merged coverage interval (no gap > GAP_S)."""
    return any(x<=a and b<=y for x,y in merged)
def first_gap_after(a,b):
    # earliest time >=a where coverage lapses before b (None if fully covered)
    for x,y in merged:
        if x<=a<=y: return None if b<=y else y
    return a
tape={}
for tk,d in TR.items():
    yes=[];no=[]
    for x in d.values():
        if x.get('is_block_trade'): continue
        t=T(x['created_time']);sz=f(x['count_fp']);yp=f(x['yes_price_dollars']);npc=f(x['no_price_dollars'])
        if x['taker_side']=='no': yes.append((t,yp,sz))      # taker sells YES-side liquidity into YES bids
        else: no.append((t,npc,sz))                          # taker_side yes hits NO bids (NO buyer's order)
    tape[tk]={'YES':sorted(yes),'NO':sorted(no)}
def sideq(q,side):
    if side=='YES': b,a=f(q['yes_bid_dollars']),f(q['yes_ask_dollars'])
    else: b,a=f(q['no_bid_dollars']),f(q['no_ask_dollars'])
    return b,a
def prior_run(ko,h):
    c=[r for r in qruns if R(r)<=ko-dt.timedelta(hours=h)]
    return max(c,key=R) if c else None
def rule_price(rule,b,a):
    if rule=='AT_ASK': return a
    if rule=='AT_BID': return b
    if rule=='BID_PLUS_1TICK': return round(b+0.01,4) if b+0.01<a-1e-9 else b
    m=math.floor((b+a)/2*100+1e-9)/100
    return m if b<m<a else b
def simulate(tr,side,p,c,t0,t_end,qahead,ko):
    """returns (filled_qty, status) status in FULL/PARTIAL/NONE/UNCERTAIN"""
    rem=c;filled=0.0;qa=qahead;fills_end=None
    for (t,pr,sz) in tr:
        if t<=t0 or t>=t_end: continue
        if pr is None or pr>p+1e-9: continue
        if pr<p-1e-9: g=rem                      # traded strictly through our price
        else:
            if qa>=sz: qa-=sz;continue
            g=min(rem,sz-qa);qa=0
        g=min(g,rem);filled+=g;rem-=g
        if rem<=1e-9: fills_end=t;break
    if rem<=1e-9: return filled,'FULL',fills_end
    # not fully filled: need coverage over [t0,t_end] to call it
    if not covered(t0,t_end): return filled,'UNCERTAIN',None
    return filled,('PARTIAL' if filled>1e-9 else 'NONE'),None
def level(book,side,p):
    lv=book['orderbook_fp']['yes_dollars' if side=='YES' else 'no_dollars']
    for pr,sz in lv:
        if abs(float(pr)-p)<1e-6: return float(sz)
    return 0.0
orders=[];meta=collections.Counter();gamesset=set()
for d in dec:
    ko=T(d['close']['kickoff_utc']);side=d['side'];tk=d['ticker'];c=d['c'];ap=d['pc']/d['c'];cl=d['close']
    if cl['close_status']!='CLOSE_OK' or cl['close_age_seconds'] is None or cl['close_age_seconds']>3600 or R(cl['price_source_run'])>=ko:
        excl['close invalid (status/age>3600s/at-or-after kickoff)']+=1;continue
    if side=='YES': cb,ca=cl['yes_bid'],cl['yes_ask']
    else: cb,ca=cl['no_bid'],cl['no_ask']
    if not cb or not ca: excl['close bid/ask missing']+=1;continue
    cmid=(cb+ca)/2;gamesset.add(cl['gid']);meta['decisions_evaluated']+=1
    # 1h quote for cross variants
    r1=prior_run(ko,1);q1=Q.get((r1,tk)) if r1 else None
    a1=None
    if q1:
        b1,a1=sideq(q1,side)
        if (ko-R(r1)).total_seconds()>3600+MAXAGE_S: a1=None
    tr=tape.get(tk,{'YES':[],'NO':[]})[side]
    has_tape=tk in tape
    for h in HS:
        r=prior_run(ko,h);q=Q.get((r,tk)) if r else None
        if not q or (ko-dt.timedelta(hours=h)-R(r)).total_seconds()>MAXAGE_S:
            excl['no quote at placement instant (H=%d)'%h]+=1;continue
        b,a=sideq(q,side)
        if b is None or a is None or b<=0 or a<=0 or b>=a:
            excl['crossed/empty quote at placement (H=%d)'%h]+=1;continue
        qt=T(q['observed_at']);bk=BK.get((r,tk))
        if bk and abs((T(bk['observed_at'])-qt).total_seconds())>600: bk=None
        meta['placement_instants']+=1
        if bk: meta['with_book']+=1
        for rule in RULES:
            p=rule_price(rule,b,a)
            if rule=='AT_ASK':
                o=dict(pm=(b+a)/2,w=d['week'],g=cl['gid'],rule=rule,h=h,p=p,c=c,cl_ask=ca,cl_mid=cmid,act=ap,a1=a1,
                       lo=('FULL',c,p),up=('FULL',c,p),var=None);orders.append(o);continue
            # tape coverage flag
            res={}
            # UPPER: queue 0 from quote time
            fq,st,_=simulate(tr,side,p,c,qt,ko,0.0,ko) if has_tape or True else (0,'UNCERTAIN',None)
            if not covered(qt,ko) and st in('NONE','PARTIAL'): st='UNCERTAIN'
            up=(st,fq,p)
            # LOWER: queue ahead from book
            if bk:
                bt=max(qt,T(bk['observed_at']))
                bestb=max([float(x[0]) for x in bk['orderbook_fp']['yes_dollars' if side=='YES' else 'no_dollars']] or [0])
                qa=0.0 if p>bestb+1e-9 else level(bk,side,p)
                fl,sl,_=simulate(tr,side,p,c,bt,ko,qa,ko)
                lo=(sl,fl,p)
            else: lo=('UNKNOWN',0.0,p)
            # variant: cancel at ko-1h and cross at the 1h ask (only meaningful for h>1)
            var=None
            if h>1 and a1 is not None:
                t1=T(q1['observed_at'])
                var={}
                for nm,(qa_,t_s,bkok) in (('up',(0.0,qt,True)),('lo',(None,None,bk is not None))):
                    pass
                fu,su,_=simulate(tr,side,p,c,qt,t1,0.0,ko)
                if not covered(qt,t1) and su in('NONE','PARTIAL'): su='UNCERTAIN'
                var['up']=(su,fu)
                if bk:
                    fl2,sl2,_=simulate(tr,side,p,c,bt,t1,qa,ko); var['lo']=(sl2,fl2)
                else: var['lo']=('UNKNOWN',0.0)
            orders.append(dict(pm=(b+a)/2,w=d['week'],g=cl['gid'],rule=rule,h=h,p=p,c=c,cl_ask=ca,cl_mid=cmid,act=ap,a1=a1,lo=lo,up=up,var=var))
meta['games']=len(gamesset)
# ---- per-order values (cents per contract)
def vals(o,bound):
    st,fq,p=o[bound]
    if st in('UNCERTAIN','UNKNOWN'): return None
    c=o['c'];rate=TAKER if o['rule']=='AT_ASK' else MAKER
    if fq<=1e-9: return dict(st=st,frac=0.0)
    fp=fee(fq,p,rate)/fq
    d=dict(st=st,frac=fq/c,p=p,imp_close=(o['cl_ask']-p)*100,imp_act=(o['act']-p)*100,adv=(o['cl_mid']-p)*100,
           fee=fp*100,net=(o['cl_mid']-p-fp)*100)
    return d
def cross_val(o):
    if o['a1'] is None: return None
    fp=fee(o['c'],o['a1'],TAKER)/o['c']
    return (o['cl_mid']-o['a1']-fp)*100
def base_close(o):
    fp=fee(o['c'],o['cl_ask'],TAKER)/o['c'];return (o['cl_mid']-o['cl_ask']-fp)*100
def base_act(o):
    fp=fee(o['c'],o['act'],TAKER)/o['c'];return (o['cl_mid']-o['act']-fp)*100
def varvals(o,bound):
    v=o['var']
    if v is None: return None
    st,fq=v[bound]
    if st in('UNCERTAIN','UNKNOWN'): return None
    c=o['c'];p=o['p'];fm=fee(fq,p,MAKER) if fq>1e-9 else 0
    rem=c-fq;ft=fee(rem,o['a1'],TAKER) if rem>1e-9 else 0
    tot=(fq*(o['cl_mid']-p)+rem*(o['cl_mid']-o['a1'])-fm-ft)/c
    return tot*100
def mean(x): return sum(x)/len(x) if x else None
def stats(os_,bound):
    """aggregate for a list of orders (one rule,window) under one bound"""
    n=len(os_);vs=[vals(o,bound) for o in os_]
    det=[(o,v) for o,v in zip(os_,vs) if v is not None]
    full=[v for o,v in det if v['st']=='FULL'];part=[v for o,v in det if v['st']=='PARTIAL'];non=[(o,v) for o,v in det if v['st']=='NONE']
    unc=n-len(det)
    filled=[(o,v) for o,v in det if v['frac']>0]
    r=dict(n=n,full=len(full),partial=len(part),unfilled=len(non),uncertain_or_unknown=unc)
    r['fill_frac_mean']=mean([v['frac'] for o,v in det])
    r['full_rate_det']=len(full)/len(det) if det else None
    r['any_fill_rate_det']=len(filled)/len(det) if det else None
    for k in('imp_close','imp_act','adv','fee','net'):
        r[k+'_filled_mean']=mean([v[k] for o,v in filled])
    # unfilled-opportunity hypothetical close-ask purchase adverse selection: close_mid - close_ask  (cents)
    r['adv_unfilled_opps_hyp_closeask']=mean([(o['cl_mid']-o['cl_ask'])*100 for o,v in non])
    # opportunity-adjusted per decision: unfilled -> 0 ; variant: unfilled -> cross at ko-1h ask
    A=[];Bv=[]
    for o,v in det:
        fr=v['frac'];nv=v['net'] if fr>0 else 0.0
        A.append(fr*nv)
        cv=cross_val(o)
        Bv.append(fr*nv+(1-fr)*cv if cv is not None else None)
    r['value_per_decision_unfilled_zero']=mean(A)
    bb=[x for x in Bv if x is not None];r['value_per_decision_unfilled_cross1h']=mean(bb);r['n_cross_variant']=len(bb)
    r['drift_filled_mid_to_close']=mean([(o['cl_mid']-o['pm'])*100 for o,v in filled])
    r['drift_unfilled_mid_to_close']=mean([(o['cl_mid']-o['pm'])*100 for o,v in non])
    fb=r['fill_frac_mean'];
    r['breakeven_edge_cents']=((r['value_per_decision_unfilled_zero']-mean([base_close(o) for o,v in det]))/(1-fb)) if det and fb is not None and fb<0.999 else None
    # reprice-at-1h variant
    vv=[varvals(o,bound) for o in os_];vv=[x for x in vv if x is not None]
    r['value_per_decision_reprice1h']=mean(vv) if os_ and os_[0]['var'] is not None or vv else None
    r['n_reprice_variant']=len(vv)
    # baselines on the same determinate decisions
    r['baseline_close_ask_value']=mean([base_close(o) for o,v in det]);r['baseline_owner_actual_value']=mean([base_act(o) for o,v in det])
    return r
# metric keys for bootstrap
KEYS=['drift_filled_mid_to_close','drift_unfilled_mid_to_close','breakeven_edge_cents','full_rate_det','any_fill_rate_det','fill_frac_mean','imp_close_filled_mean','imp_act_filled_mean','adv_filled_mean','net_filled_mean',
      'adv_unfilled_opps_hyp_closeask','value_per_decision_unfilled_zero','value_per_decision_unfilled_cross1h','value_per_decision_reprice1h',
      'baseline_close_ask_value','baseline_owner_actual_value']
random.seed(12345)
def pct(x,q):
    x=sorted(x);
    if not x: return None
    i=q*(len(x)-1);lo=int(math.floor(i));hi=min(lo+1,len(x)-1);return x[lo]+(x[hi]-x[lo])*(i-lo)
out=dict(meta=dict(weeks=list(WEEKS),decisions_note='owner-placed pregame wagers (clv_eligible), NO verified recommendation linkage',
    fee_assumption='maker 1.75%*C*P*(1-P) ceil-to-cent per fill (some series may have no maker fee -> maker costs here are an upper estimate); taker 7%*C*P*(1-P)',
    coverage_gap_tolerance_s=GAP_S,bootstrap_iters=NBOOT,exclusions=dict(excl),**{k:v for k,v in meta.items()}),cells={})
games=sorted({o['g'] for o in orders})
for ws,wf in (('W4',lambda o:o['w']==4),):
    for rule in RULES:
        for h in HS:
            os_=[o for o in orders if o['rule']==rule and o['h']==h and wf(o)]
            if not os_: continue
            cell={}
            for b in ('lo','up'):
                pt=stats(os_,b);cell[b]=dict(point=pt)
                byg=collections.defaultdict(list)
                for o in os_: byg[o['g']].append(o)
                gl=list(byg);bs=collections.defaultdict(list)
                for _ in range(NBOOT):
                    smp=[];
                    for g in random.choices(gl,k=len(gl)): smp+=byg[g]
                    s=stats(smp,b)
                    for k in KEYS:
                        if s.get(k) is not None: bs[k].append(s[k])
                cell[b]['ci95']={k:[pct(bs[k],.025),pct(bs[k],.975)] for k in KEYS if bs[k]}
            out['cells']['%s|%s|%dh'%(ws,rule,h)]=cell
# ---- orientation check using quotes: taker_side=no yes_price vs yes_bid ; taker_side=yes yes_price vs yes_ask
chk=collections.defaultdict(list)
for (r,tk),q in Q.items():
    if tk not in TR: continue
    qt=T(q['observed_at']);yb,ya=f(q['yes_bid_dollars']),f(q['yes_ask_dollars'])
    if not yb or not ya: continue
    for x in TR[tk].values():
        if abs((T(x['created_time'])-qt).total_seconds())<=120:
            yp=f(x['yes_price_dollars'])
            chk[x['taker_side']].append((yp-yb,ya-yp))
def m(x): return sum(x)/len(x) if x else None
out['orientation_check']={k:dict(n=len(v),mean_yesprice_minus_yesbid=m([a for a,b in v]),mean_yesask_minus_yesprice=m([b for a,b in v]),
    share_at_or_below_bid_plus_0p011=m([1.0 if a<=0.011 else 0.0 for a,b in v]),share_at_or_above_ask_minus_0p011=m([1.0 if b<=0.011 else 0.0 for a,b in v])) for k,v in chk.items()}
out['coverage']=dict(merged_trade_intervals=len(merged),
    games=len(gamesset),tickers_with_any_tape=len(tape),tickers=len(tick))
json.dump(out,open(S+'results.json','w'),indent=1)
print(json.dumps(out['meta'],indent=1));print(out['orientation_check']);print(out['coverage'])
