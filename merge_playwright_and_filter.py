#!/usr/bin/env python3
"""
merge_playwright_and_filter.py

Merges Playwright image extraction results into clean_product_pages.json,
filters and ranks candidate images, and writes out:

 - clean_product_pages_filtered.json   (full merged dataset)
 - to_enrich.json                      (list of products with at least one filtered image)

Configurable heuristics near the top (KEEP_TOP_N, EXPAND_WIDTH, BAD_KEYWORDS).
"""
import json
import re
from pathlib import Path
from urllib.parse import urlparse, urljoin, urlunparse, parse_qs

# ---------- CONFIG ----------
CLEAN_INPUT = "output/clean_product_pages.json"
PLAYWRIGHT_INPUT = "output/retry_results_playwright_fixed.json"
OUT_CLEAN_FILTERED = "output/clean_product_pages_filtered.json"
OUT_TO_ENRICH = "output/to_enrich.json"

KEEP_TOP_N = 3        # how many top images to keep per product
EXPAND_WIDTH = 1024   # width to use for {width} templates or ?width= parameters

# keywords that indicate site UI assets, logos, payment icons, etc.
BAD_KEYWORDS = [
    "logo", "payment", "icon", "powered_by", "payment_icon", "payment-icon",
    "favicon", "thumbnail", "thumb", "placeholder", "icons-", "contact_size",
    "boost_button", "upi_options", "right_arrow", "spinner", "sprite", "flag",
    "social-icon", "social_icon", "instagram", "facebook", "twitter"
]

IMAGE_EXT_RE = re.compile(r".*\.(jpg|jpeg|png|webp|gif)$", re.I)

# ---------- utilities ----------
def normalize_url(u, base=None):
    if not u:
        return None
    s = str(u).strip()
    # expand {width} token if present
    if "{width}" in s:
        s = s.replace("{width}", str(EXPAND_WIDTH))
    # replace width query param if present
    s = re.sub(r"([?&])width=\d+", r"\1width=%d" % EXPAND_WIDTH, s)
    # promote http -> https
    if s.startswith("http:"):
        s = "https:" + s[5:]
    # remove fragments, keep ?v= if present
    try:
        p = urlparse(s)
        qs = parse_qs(p.query)
        keep_q = ""
        if "v" in qs:
            keep_q = "v=" + qs["v"][0]
        norm = urlunparse((p.scheme or "https", p.netloc, p.path or "/", "", keep_q, ""))
        return norm
    except Exception:
        return s

def is_site_asset(url):
    if not url:
        return True
    low = url.lower()
    # drop svg UI images
    if low.endswith(".svg"):
        return True
    for k in BAD_KEYWORDS:
        if k in low:
            return True
    return False

def guess_resolution_score(u):
    """
    Heuristic score for choosing largest/best images:
    - check patterns like _1200x1200, _3840x2160
    - check ?width= or &width=
    - check numeric tokens at the end like =2048
    Returns integer score (higher = better)
    """
    if not u:
        return 0
    # look for _{w}x{h}
    m = re.search(r"_(\d{2,5})x(\d{2,5})", u)
    if m:
        try:
            return int(m.group(1)) * int(m.group(2))
        except:
            pass
    # look for _{w}x or -{w}x
    m2 = re.search(r"_(\d{3,5})x\b", u)
    if m2:
        try:
            return int(m2.group(1)) * int(m2.group(1))
        except:
            pass
    # query width
    m3 = re.search(r"[?&]width=(\d{2,5})", u)
    if m3:
        try:
            return int(m3.group(1)) * int(m3.group(1))
        except:
            pass
    # numeric trailing =NNNN
    m4 = re.search(r"=(\d{3,5})$", u)
    if m4:
        try:
            return int(m4.group(1)) * int(m4.group(1))
        except:
            pass
    # fallback: small score
    return 0

def filter_and_rank_images(img_urls):
    seen_bases = set()
    cleaned = []
    for raw in (img_urls or []):
        if not raw or not isinstance(raw, str):
            continue
        if is_site_asset(raw):
            continue
        norm = normalize_url(raw)
        # require common image extension OR allow webp/jpg etc inside query
        if not IMAGE_EXT_RE.match(norm):
            if not re.search(r"\.jpg|\.jpeg|\.png|\.webp", norm, re.I):
                # if it still looks like an image via path, keep; otherwise skip
                # (this is conservative)
                continue
        base = norm.split("?")[0]
        if base in seen_bases:
            continue
        seen_bases.add(base)
        score = guess_resolution_score(norm)
        cleaned.append((norm, score))
    # sort by score desc, return top N urls
    cleaned.sort(key=lambda x: x[1], reverse=True)
    return [u for (u, s) in cleaned[:KEEP_TOP_N]]

# ---------- main merge logic ----------
def load_json(path):
    if not Path(path).exists():
        raise SystemExit(f"Missing input file: {path}")
    return json.load(open(path, encoding="utf-8"))

def main():
    clean = load_json(CLEAN_INPUT)
    pw = load_json(PLAYWRIGHT_INPUT)

    # index playwright results by url
    pw_map = {}
    for item in pw:
        url = item.get("url")
        if url:
            # ensure images field exists and is a list
            imgs = item.get("images") or []
            # normalize image strings
            imgs_norm = []
            for i in imgs:
                try:
                    if isinstance(i, dict):
                        # some rare cases might have dicts with 'src'
                        ii = i.get("src") or i.get("url") or ""
                    else:
                        ii = str(i)
                except Exception:
                    ii = ""
                if ii:
                    imgs_norm.append(ii)
            pw_map[url] = {"recovered": item.get("recovered", False), "images": imgs_norm, "error": item.get("error")}

    all_entries = clean.get("all") or []
    recovered_count = 0
    merged_count = 0

    for entry in all_entries:
        u = entry.get("url")
        existing = entry.get("image_candidates") or []
        # only merge if playwright found additional images and we don't have useful candidates
        pw_item = pw_map.get(u)
        if pw_item and pw_item.get("recovered"):
            pw_imgs = pw_item.get("images") or []
            # if entry had no candidates or they were empty, take PW images directly
            if not existing:
                entry["image_candidates"] = pw_imgs.copy()
                recovered_count += 1
            else:
                # merge unique ones (append those not already present)
                added = False
                existing_bases = {x.split("?")[0] for x in existing}
                for pi in pw_imgs:
                    base = pi.split("?")[0]
                    if base not in existing_bases:
                        existing.append(pi)
                        added = True
                if added:
                    entry["image_candidates"] = existing
                    merged_count += 1

    # After merging, run filter+rank for each entry
    for entry in all_entries:
        imgs = entry.get("image_candidates") or []
        filtered = filter_and_rank_images(imgs)
        entry["image_candidates_filtered"] = filtered

    # update good list too: keep those with ok true or with filtered images
    good = []
    for entry in all_entries:
        ok = entry.get("ok", False)
        if ok or entry.get("image_candidates_filtered"):
            # add minimal set
            good.append(entry)
    clean["good"] = good

    # write results
    open(OUT_CLEAN_FILTERED, "w", encoding="utf-8").write(json.dumps(clean, ensure_ascii=False, indent=2))
    # prepare to_enrich.json: minimal list of items to pass to Vision/GPT
    to_enrich = []
    for entry in all_entries:
        filtered = entry.get("image_candidates_filtered") or []
        if filtered:
            to_enrich.append({
                "url": entry.get("url"),
                "image_candidates_filtered": filtered,
                "image_candidates": entry.get("image_candidates") or []
            })
    open(OUT_TO_ENRICH, "w", encoding="utf-8").write(json.dumps(to_enrich, ensure_ascii=False, indent=2))

    # summary print
    total = len(all_entries)
    filtered_count = len(to_enrich)
    print(f"Total entries: {total}")
    print(f"Recovered (playwright filled missing images): {recovered_count}")
    print(f"Merged extra images into existing entries: {merged_count}")
    print(f"Entries with >=1 filtered image (to_enrich): {filtered_count}")
    print(f"Wrote {OUT_CLEAN_FILTERED} and {OUT_TO_ENRICH}")

if __name__ == "__main__":
    main()
