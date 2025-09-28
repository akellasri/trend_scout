#!/usr/bin/env python3
# retry_with_playwright_fixed.py
import json, re, time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

INPUT = "retry_results.json"  # or your retry_results_requests.json / list of urls
OUT = "retry_results_playwright_fixed.json"

def normalize_src(src, base):
    if not src: 
        return None
    src = src.strip()
    # ignore data: and javascript:
    if src.startswith("data:") or src.startswith("javascript:") or src.startswith("about:"):
        return None
    # make absolute
    return urljoin(base, src)

def extract_images_from_html_and_js(page, base_url):
    """
    Robust extraction: looks at DOM <img> attributes, JSON-LD, and common JS globals.
    Returns list of absolute image URLs (deduped).
    """
    imgs = []

    # 1) try meta og:image(s)
    try:
        ogs = page.eval_on_selector_all("meta[property='og:image']", "els => els.map(e => e.content).filter(Boolean)")
        for o in ogs:
            u = normalize_src(o, base_url)
            if u: imgs.append(u)
    except Exception:
        pass

    # 2) grab many attributes from <img> elements (src, srcset, data-src, data-srcset, data-lazy)
    try:
        all_img_attrs = page.eval_on_selector_all("img", """
            els => els.map(e => {
                return {
                    src: e.getAttribute('src'),
                    srcset: e.getAttribute('srcset'),
                    data_src: e.getAttribute('data-src') || e.getAttribute('data-lazy') || e.getAttribute('data-srcset'),
                    alt: e.alt || ''
                }
            })
        """)
        for it in all_img_attrs:
            for key in ("src", "srcset", "data_src"):
                val = it.get(key) if isinstance(it, dict) else None
                if not val:
                    continue
                # if srcset, take highest-res candidate from it
                if key == "srcset" or ("," in val and " " in val):
                    # choose last candidate in srcset
                    parts = [p.strip() for p in val.split(",") if p.strip()]
                    if parts:
                        last = parts[-1].split()[0]
                        u = normalize_src(last, base_url)
                        if u: imgs.append(u)
                else:
                    u = normalize_src(val, base_url)
                    if u: imgs.append(u)
    except Exception:
        pass

    # 3) JSON-LD parsing (robust)
    try:
        jsonld_blocks = page.eval_on_selector_all("script[type='application/ld+json']", "els => els.map(e => e.innerText).filter(Boolean)")
        for block in jsonld_blocks:
            try:
                data = json.loads(block)
            except Exception:
                # try to recover first {...} block
                m = re.search(r"(\{[\s\S]*\})", block)
                if m:
                    try:
                        data = json.loads(m.group(1))
                    except Exception:
                        data = None
                else:
                    data = None
            if not data:
                continue
            # traverse function
            def walk(o):
                found = []
                if isinstance(o, dict):
                    t = o.get("@type") or o.get("type")
                    # product object
                    imgfield = o.get("image") or o.get("images") or o.get("thumbnailUrl") or o.get("thumbnail")
                    if imgfield:
                        if isinstance(imgfield, str):
                            found.append(imgfield)
                        elif isinstance(imgfield, list):
                            for i in imgfield:
                                if isinstance(i, str):
                                    found.append(i)
                                elif isinstance(i, dict) and i.get("url"):
                                    found.append(i.get("url"))
                    # may be nested under '@graph'
                    for v in o.values():
                        found.extend(walk(v))
                elif isinstance(o, list):
                    for it in o:
                        found.extend(walk(it))
                return found
            images_from_jsonld = walk(data)
            for u in images_from_jsonld:
                uu = normalize_src(u, base_url)
                if uu: imgs.append(uu)
    except Exception:
        pass

    # 4) try common JS product objects (Shopify / window.__INITIAL_STATE__ / window.__PRODUCT__)
    try:
        candidates = []
        # attempt several known globals; silent failures if not present
        candidates.append(page.evaluate("() => window.__INITIAL_STATE__ || null"))
        candidates.append(page.evaluate("() => window.__PRODUCT__ || null"))
        candidates.append(page.evaluate("() => window.__STATE__ || null"))
        candidates.append(page.evaluate("() => window.__PRELOADED_STATE__ || null"))
        # also try Shopify theme product JSON: window.Shopify && window.Shopify.designMode? or page variable
        candidates.append(page.evaluate("() => (typeof Shopify !== 'undefined' && Shopify.product) ? Shopify.product : null"))
        for cand in candidates:
            if not cand:
                continue
            # cand may be dict/list or string; search for keys that look like images
            def cand_walk(obj):
                found=[]
                if isinstance(obj, dict):
                    for k,v in obj.items():
                        if k and 'image' in k.lower() and isinstance(v, str):
                            found.append(v)
                        elif k and 'images' in k.lower() and isinstance(v, list):
                            for it in v:
                                if isinstance(it, str):
                                    found.append(it)
                                elif isinstance(it, dict) and it.get('src'):
                                    found.append(it.get('src'))
                        else:
                            found.extend(cand_walk(v))
                elif isinstance(obj, list):
                    for it in obj:
                        found.extend(cand_walk(it))
                return found
            try:
                found = cand_walk(cand)
                for u in found:
                    uu = normalize_src(u, base_url)
                    if uu: imgs.append(uu)
            except Exception:
                continue
    except Exception:
        pass

    # 5) dedupe and return
    out=[]; seen=set()
    for u in imgs:
        if not u: continue
        u_norm = u.split("?")[0]
        if u_norm not in seen:
            seen.add(u_norm); out.append(u)
    return out

def run_playwright(urls):
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36")
        for u in urls:
            page = context.new_page()
            try:
                page.set_default_navigation_timeout(60000)  # 60s
                page.goto(u, timeout=60000)
                # scroll to bottom slowly to trigger lazy load
                for _ in range(3):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(0.6)
                # wait a little for lazy images/xhrs
                page.wait_for_load_state("networkidle", timeout=15000)
                # extract images using robust method
                imgs = extract_images_from_html_and_js(page, u)
                # If still empty, try grabbing any <picture> sources, srcset attributes raw
                if not imgs:
                    try:
                        srcs = page.eval_on_selector_all("picture source, img", "els => els.map(e => e.src || e.getAttribute('src') || e.getAttribute('data-src') || e.getAttribute('data-srcset') || e.getAttribute('data-srcset'))")
                        for s in srcs:
                            if s:
                                s2 = normalize_src(s, u)
                                if s2 and s2 not in imgs:
                                    imgs.append(s2)
                    except Exception:
                        pass
                results.append({"url": u, "recovered": True, "images": imgs})
            except PWTimeout as e:
                results.append({"url": u, "recovered": False, "error": "timeout"})
            except Exception as e:
                results.append({"url": u, "recovered": False, "error": str(e)})
            finally:
                try:
                    page.close()
                except:
                    pass
        context.close()
        browser.close()
    return results

def load_urls_from_input(path):
    data = json.load(open(path, encoding="utf-8"))
    # Accept list of dicts or simple list
    urls = []
    for it in data:
        if isinstance(it, dict) and it.get("url"):
            urls.append(it["url"])
        elif isinstance(it, str):
            urls.append(it)
    return urls

def main():
    if not Path(INPUT).exists():
        print("Missing", INPUT)
        return
    urls = load_urls_from_input(INPUT)
    print("Total urls:", len(urls))
    res = run_playwright(urls)
    open(OUT,"w",encoding="utf-8").write(json.dumps(res, ensure_ascii=False, indent=2))
    print("Wrote", OUT)

if __name__ == "__main__":
    main()
