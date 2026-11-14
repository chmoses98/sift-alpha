import gzip,json,glob,sys,collections,os
root=sys.argv[1]
fs=sorted(glob.glob(root+'/*/*.jsonl.gz'))
st=collections.Counter(); keys=collections.Counter(); ng=0
for f in fs:
    for l in gzip.open(f,'rt'):
        if not l.strip(): continue
        r=json.loads(l); st[r['state']]+=1; keys.update(r.keys()); ng+=1
print(len(fs),ng,st); print(keys)
