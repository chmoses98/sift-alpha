#!/usr/bin/env python3 -I
"""Stage fetcher: pulls only needed blobs from the partial clone, filters to decision tickers, stores small extracts.
usage: python3 -I fetch.py quotes|trades|count"""
import json,sys,subprocess,os,datetime as dt,collections,concurrent.futures as cf
B='/tmp/claude-0/-home-user-sift-alpha/8175d499-d824-5369-8293-43901aad664c/scratchpad/'
S=B+'limitsim/'; CL=B+'data/nfl_md2'
H=[48,24,12,6,1]
def P(s): return dt.datetime.strptime(s,'%Y%m%dT%H%M%SZ').replace(tzinfo=dt.timezone.utc)
def K(s): return dt.datetime.fromisoformat(s)
dec=json.load(open(S+'decisions_private.json'))
tick={d['ticker'] for d in dec}
games={}
for d in dec: games[d['close']['gid']]=K(d['close']['kickoff_utc'])
runs=collections.defaultdict(dict)  # kind -> run_id -> path
for l in open(S+'names.txt'):
    p=l.strip(); b=os.path.basename(p); parts=b.split('.')
    if len(parts)==3 and parts[1] in('quotes','books','trades') : runs[parts[1]][parts[0]]=p
def nearest_before(kind,t):
    c=[r for r in runs[kind] if P(r)<=t]
    return max(c,key=P) if c else None
def need_quote_runs():
    s=set()
    for g,ko in games.items():
        for h in H:
            r=nearest_before('quotes',ko-dt.timedelta(hours=h))
            if r: s.add(r)
    return sorted(s)
def need_trade_runs():
    s=set()
    for g,ko in games.items():
        for r in runs['trades']:
            if ko-dt.timedelta(hours=48,minutes=20)<=P(r)<=ko+dt.timedelta(minutes=20): s.add(r)
    return sorted(s)
def pull(kind,run,keep):
    out=S+'ext/%s/%s.jsonl'%(kind,run)
    if kind=='trades': out=S+'ext/trades/%s.v2.jsonl'%run
    if os.path.exists(out): return run,0,0
    pr=subprocess.Popen(['git','-C',CL,'-c','gc.auto=0','cat-file','-p','FETCH_HEAD:'+runs[kind][run]],stdout=subprocess.PIPE)
    n=0;rows=[];lo=hi='';nrow=0
    for line in pr.stdout:
        n+=len(line)
        if kind=='trades':
            i=line.find(b'"created_time":"')
            if i>=0:
                c=line[i+16:i+43].decode(); nrow+=1
                if not lo or c<lo: lo=c
                if c>hi: hi=c
        if any(t.encode() in line for t in keep):
            r=json.loads(line)
            if r.get('ticker') in keep: rows.append(line.decode().strip())
    pr.wait()
    if pr.returncode: return run,-1,0
    # also record coverage meta for trades (min/max created) handled in sim via rows; store file-level meta
    if kind=='trades': open(S+'ext/trades_meta/%s.json'%run,'w').write(json.dumps(dict(run=run,rows=nrow,lo=lo,hi=hi,raw=n)))
    open(out+'.tmp','w').write('\n'.join(rows)+('\n' if rows else ''))
    os.rename(out+'.tmp',out); return run,n,len(rows)
if __name__=='__main__':
    m=sys.argv[1]
    os.makedirs(S+'ext/quotes',exist_ok=True);os.makedirs(S+'ext/books',exist_ok=True);os.makedirs(S+'ext/trades',exist_ok=True);os.makedirs(S+'ext/trades_meta',exist_ok=True)
    if m=='count':
        print(len(games),'games',len(need_quote_runs()),'quote runs',len(need_trade_runs()),'trade runs'); sys.exit()
    jobs=[]
    if m=='quotes':
        for r in need_quote_runs():
            jobs.append(('quotes',r))
            if r in runs['books']: jobs.append(('books',r))
    else:
        lo=sys.argv[2] if len(sys.argv)>2 else '0'; hi=sys.argv[3] if len(sys.argv)>3 else 'z'
        jobs=[('trades',r) for r in need_trade_runs() if lo<=r<=hi]
    tot=0;log=open(S+'fetch_log.txt','a')
    def job(j): return (j[0],)+pull(j[0],j[1],tick)
    with cf.ThreadPoolExecutor(6) as ex:
        for kind,run,n,k in ex.map(job,jobs):
            tot+=max(n,0); log.write('%s %s raw=%d rows=%d\n'%(kind,run,n,k)); log.flush()
    print('done raw bytes',tot)
