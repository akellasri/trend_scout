import json, time, requests
from urllib.parse import urlparse, urlunparse

data = json.load(open("clean_product_pages.json", encoding="utf-8"))
failed = [x for x in data["all"] if not x.get("ok")]
out = []

def normalize_try(url):
    url = url.strip()
    url = url.replace("//collections/", "/collections/")  # simple fix
    if not url.startswith("http"):
        url = "https://" + url.lstrip("/")
    parsed = urlparse(url)
    # try https then http
    candidates = [urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))]
    # swap scheme
    other = "http" if parsed.scheme == "https" else "https"
    candidates.append(urlunparse((other, parsed.netloc, parsed.path, "", "", "")))
    return candidates

for entry in failed:
    url = entry["url"]
    tried=False
    for cand in normalize_try(url):
        try:
            r = requests.get(cand, timeout=20, headers={"User-Agent":"Mozilla/5.0"})
            if r.status_code==200 and "text/html" in r.headers.get("content-type",""):
                out.append({"url":entry["url"], "recovered":cand})
                tried=True
                break
        except Exception:
            pass
        time.sleep(0.5)
    if not tried:
        out.append({"url":entry["url"], "recovered":None})
open("retry_results.json","w",encoding="utf-8").write(json.dumps(out,ensure_ascii=False,indent=2))
