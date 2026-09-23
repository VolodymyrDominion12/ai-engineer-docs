import json, urllib.request, sys, time
UA={"User-Agent":"Mozilla/5.0"}
def get(u):
    r=urllib.request.Request(u,headers=UA)
    with urllib.request.urlopen(r,timeout=45) as f: return json.load(f)

authors=sys.argv[1:]
out={}
for a in authors:
    for sort in ["createdAt","downloads"]:
        try:
            d=get(f"https://huggingface.co/api/models?author={a}&sort={sort}&direction=-1&limit=60")
        except Exception as e:
            print("ERR",a,sort,e); continue
        print(f"===== {a} sorted by {sort} =====")
        for m in d:
            print(f"  {m['id']:<58} dl={m.get('downloads',0):<9} likes={m.get('likes',0):<6} created={(m.get('createdAt') or '')[:10]}")
