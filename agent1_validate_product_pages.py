#!/usr/bin/env python3
import re, json, time, requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse

HEADERS = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
INPUT = "product_pages.txt"
OUT = "output/clean_product_pages.json"
AZURE_VISION_ENDPOINT = "https://velta-md43xkh4-eastus2.cognitiveservices.azure.com/"  # keep in env in real run
AZURE_VISION_KEY = None  # load from env if you want pre-checks

def normalize(url):
    s = url.strip()
    s = re.sub(r'[\s,;]+$', '', s)                       # remove trailing punctuation
    s = s.replace('//collections/', '/collections/')     # simple double-slash fix for path portion
    # ensure scheme
    if not s.startswith("http"):
        s = "https://" + s.lstrip("/")
    p = urlparse(s)
    # reconstruct (remove fragment)
    return urlunparse((p.scheme, p.netloc, p.path or "/", "", p.query or "", ""))

def extract_images_from_html(html, base):
    soup = BeautifulSoup(html, "html.parser")
    images = []
    # 1) JSON-LD product image
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or "{}")
        except Exception:
            continue
        def walk(o):
            if isinstance(o, dict):
                if o.get("@type","").lower() == "product" and o.get("image"):
                    imgs = o.get("image")
                    if isinstance(imgs, list):
                        return imgs
                    return [imgs]
                for v in o.values():
                    r = walk(v)
                    if r:
                        return r
            elif isinstance(o, list):
                for it in o:
                    r = walk(it)
                    if r:
                        return r
            return None
        found = walk(data)
        if found:
            for f in found:
                images.append(urljoin(base, f))
    # 2) og:image
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        images.append(urljoin(base, og["content"]))
    # 3) link rel=image_src
    linkimg = soup.find("link", rel="image_src")
    if linkimg and linkimg.get("href"):
        images.append(urljoin(base, linkimg["href"]))
    # 4) first product-gallery <img> or main <img> with class containing 'product' or 'main'
    imgs = soup.find_all("img", src=True)
    for im in imgs[:20]:
        src = im["src"]
        cls = " ".join(im.get("class",[])).lower()
        if "product" in cls or "hero" in cls or "main" in cls or "gallery" in cls:
            images.append(urljoin(base, src))
    # fallback: first large image
    for im in imgs:
        src = im["src"]
        images.append(urljoin(base, src))
    # dedupe preserve order
    seen = set(); out=[]
    for u in images:
        u2 = u.split("?")[0]
        if u2 not in seen:
            seen.add(u2); out.append(u)
    return out

def is_clothing_by_vision(img_url):
    # Lightweight check: call Azure Vision 'analyze' for tags (optional).
    # For speed, you can omit this step and rely on schema/org heuristics.
    if not AZURE_VISION_KEY or not AZURE_VISION_ENDPOINT:
        return True, "no-vision-check"
    try:
        headers = {
            "Ocp-Apim-Subscription-Key": AZURE_VISION_KEY,
            "Content-Type": "application/json"
        }
        api = AZURE_VISION_ENDPOINT.rstrip("/") + "/vision/v3.2/analyze?visualFeatures=Tags"
        r = requests.post(api, headers=headers, json={"url": img_url}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            tags = [t['name'] for t in data.get('tags',[])]
            # typical clothing tags:
            if any(x in tags for x in ("clothing","dress","shirt","trousers","sari","kurta","top","skirt","leheng a","blouse")):
                return True, "vision-tags"
            # if tags include 'logo' or 'text' but not clothing -> reject
            if any(x in tags for x in ("logo","text","screenshot","icon")):
                return False, "vision-non-clothing"
            return True, "vision-ambiguous"
        else:
            return True, "vision-unavailable"
    except Exception as e:
        return True, "vision-error"

def main():
    lines = open(INPUT).read().splitlines()
    normalized = []
    for l in lines:
        if not l.strip(): continue
        normalized.append(normalize(l))
    # dedupe
    seen=set(); normalized2=[]
    for u in normalized:
        if u not in seen:
            seen.add(u); normalized2.append(u)
    results=[]
    for i,u in enumerate(normalized2):
        if i % 100 == 0: print("checked", i)
        try:
            r = requests.get(u, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                results.append({"url":u, "ok":False, "reason":f"http_{r.status_code}"})
                continue
            imgs = extract_images_from_html(r.text, u)
            if not imgs:
                results.append({"url":u, "ok":False, "reason":"no_images_found"})
                continue
            # check first candidate image with Azure (optional)
            ok, reason = is_clothing_by_vision(imgs[0])
            results.append({
                "url":u,
                "ok": ok,
                "reason": reason,
                "image_candidates": imgs[:5]
            })
        except Exception as e:
            results.append({"url":u, "ok":False, "reason":"fetch_error"})
        time.sleep(0.25)
    good = [r for r in results if r["ok"]]
    open(OUT,"w",encoding="utf-8").write(json.dumps({"all":results, "good":good}, ensure_ascii=False, indent=2))
    print("done. total:", len(results), "good:", len(good))

if __name__ == "__main__":
    main()
