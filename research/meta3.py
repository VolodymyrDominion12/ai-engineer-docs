import json, urllib.request, sys, concurrent.futures as cf
UA={"User-Agent":"Mozilla/5.0"}
def get(u,js=True):
    r=urllib.request.Request(u,headers=UA)
    with urllib.request.urlopen(r,timeout=60) as f: b=f.read()
    return json.loads(b) if js else b.decode('utf-8','replace')
def probe(q):
    try:
        d=get(f"https://huggingface.co/api/models?search={urllib.parse.quote(q)}&sort=downloads&direction=-1&limit=12")
    except Exception as e: return q,[("ERR",str(e)[:60])]
    return q,[(m["id"], m.get("downloads"), (m.get("createdAt") or "")[:10]) for m in d]
import urllib.parse
for q in sys.argv[1:]:
    name,r=probe(q)
    print(f"### SEARCH: {name}")
    for x in r: print("   ", x)
