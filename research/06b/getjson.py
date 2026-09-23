import sys, json, urllib.request, gzip
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
def get(url):
    r=urllib.request.Request(url, headers={"User-Agent":UA,"Accept-Encoding":"gzip"})
    with urllib.request.urlopen(r,timeout=45) as resp:
        d=resp.read()
        if resp.headers.get("Content-Encoding")=="gzip": d=gzip.decompress(d)
        return d.decode("utf-8","replace")
url=sys.argv[1]; path=sys.argv[2] if len(sys.argv)>2 else None
d=json.loads(get(url))
if path:
    for p in path.split("."):
        d = d[int(p)] if isinstance(d,list) else d[p]
print(json.dumps(d, indent=1, ensure_ascii=False)[:6000] if not isinstance(d,str) else d)
