#!/usr/bin/env python3
"""Fetch a URL and print its readable text. Usage: python3 fetch.py URL [maxchars]
Appending '.md' trick: many doc sites (developers.openai.com, platform.claude.com)
serve markdown if you append .md to the path. Try it with --md.
"""
import sys, re, html, urllib.request, gzip, io

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=45) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return data.decode("utf-8", "replace")


def clean(t: str) -> str:
    t = re.sub(r"(?is)<script.*?</script>", " ", t)
    t = re.sub(r"(?is)<style.*?</style>", " ", t)
    t = re.sub(r"(?is)<nav.*?</nav>", " ", t)
    t = re.sub(r"(?is)<svg.*?</svg>", " ", t)
    # keep code blocks readable
    t = re.sub(r"(?is)<pre[^>]*>", "\n```\n", t)
    t = re.sub(r"(?is)</pre>", "\n```\n", t)
    t = re.sub(r"(?i)<br\s*/?>", "\n", t)
    t = re.sub(r"(?i)</(p|div|li|h1|h2|h3|h4|tr)>", "\n", t)
    t = re.sub(r"(?i)<li[^>]*>", "- ", t)
    t = re.sub(r"(?i)</t[dh]>", " | ", t)
    t = re.sub(r"(?s)<[^>]+>", "", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t\xa0]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    md = "--md" in sys.argv
    url = args[0]
    limit = int(args[1]) if len(args) > 1 else 12000
    if md and not url.endswith(".md"):
        url = url.split("#")[0].rstrip("/") + ".md"
    try:
        body = get(url)
    except Exception as e:
        print(f"FETCH-FAIL {url}: {e}")
        sys.exit(1)
    text = body if (md or url.endswith(".md")) else clean(body)
    if "--fail-on-error" in sys.argv and not text.strip():
        print(f"FETCH-EMPTY {url}: отримано порожню відповідь", file=sys.stderr)
        sys.exit(2)
    print(f"### SOURCE: {url}\n")
    print(text[:limit])
