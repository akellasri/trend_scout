#!/usr/bin/env python3
"""
merge_social_and_catalog.py

- Input:
    output/analysis_results_final_updated.json   (catalog canonical items)
    input/social_instagram.json                  (social enriched JSON from friend)
      (filename can be changed via constants below)
- Output:
    output/merged_catalog.json
    output/postmerge_report.json
    output/merged_examples_sample.json (small samples)
"""

import json, re, math
from pathlib import Path
from collections import defaultdict
from urllib.parse import urlparse, urlunparse, parse_qs

# --- customize these file names if needed ---
CATALOG_FILE = Path("output/analysis_results_final_updated.json")
SOCIAL_FILE = Path("output/instagram_posts_enriched_azure.json")  # change if different
OUT_MERGED = Path("output/merged_catalog.json")
OUT_REPORT = Path("output/postmerge_report.json")
OUT_SAMPLE = Path("output/merged_examples_sample.json")

# ---------- utils ----------
def norm_image_url(u):
    """Normalize image URL: strip query params that are purely sizing/version tokens,
    and lowercase the path. Keep host + path, remove common CDN params.
    """
    if not u:
        return None
    try:
        parsed = urlparse(u)
        # remove query params except potentially meaningful ones
        # heuristic: keep none — simpler and usually OK for shopify/cdn images
        path = parsed.path.lower()
        netloc = parsed.netloc.lower()
        return f"{parsed.scheme}://{netloc}{path}"
    except Exception:
        return u.lower().split("?")[0]

def jaccard(a,b):
    if not a or not b:
        return None
    sa = set([x.strip().lower() for x in a if x])
    sb = set([x.strip().lower() for x in b if x])
    if not sa and not sb:
        return None
    inter = sa & sb
    uni = sa | sb
    return len(inter) / len(uni) if uni else None

def ensure_list(x):
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]

# ---------- load ----------
catalog = []
social = []

if not CATALOG_FILE.exists():
    print("Catalog file missing:", CATALOG_FILE)
    raise SystemExit(1)

catalog = json.load(open(CATALOG_FILE, encoding="utf-8"))
print("Loaded catalog:", len(catalog))

if not SOCIAL_FILE.exists():
    print("Social file missing:", SOCIAL_FILE, " — proceeding with catalog only.")
else:
    social = json.load(open(SOCIAL_FILE, encoding="utf-8"))
    print("Loaded social:", len(social))

# ---------- index catalog by product_url and normalized image_url ----------
prod_by_url = {}
image_to_prod = defaultdict(list)
catalog_image_count = 0

for item in catalog:
    # canonical product url keys might be 'product_url' or 'group_key'
    purl = item.get("product_url") or item.get("group_key")
    if purl:
        prod_by_url[purl] = item
    # index images
    imgs = item.get("image_urls") or item.get("images") or []
    for im in ensure_list(imgs):
        n = norm_image_url(im)
        if n:
            image_to_prod[n].append(item)
            catalog_image_count += 1

# ---------- process social items ----------
added = 0
merged_by_product_url = 0
merged_by_image = 0
created_new = 0
color_jaccard_values = []
fabric_jaccard_values = []

# helper to merge aggregated fashion attributes
def merge_attributes(base_agg, social_analysis):
    """
    base_agg: existing catalog aggregated dict (may be empty)
    social_analysis: fashion attributes from social post (either 'fashion_analysis' or nested)
    Returns updated agg (mutates base_agg).
    Strategy:
     - Multi-value fields (colors, fabrics, prints, style_fit): union (dedup, preserve canonical)
     - Single-value fields (silhouette, sleeves, neckline, length, garment_type): keep catalog unless missing/unknown
     - Also append social metadata into 'examples_from_social' list under the product for provenance
    """
    if not isinstance(base_agg, dict):
        base_agg = {}
    s = social_analysis or {}
    # multi fields
    for k in ("colors","fabrics","prints","style_fit"):
        cur = ensure_list(base_agg.get(k))
        incoming = ensure_list(s.get(k) or s.get("colors") if k=="colors" else s.get(k))
        # normalize casing
        cur_norm = [str(x).strip() for x in cur if x and str(x).strip().lower()!="unknown"]
        inc_norm = [str(x).strip() for x in incoming if x and str(x).strip().lower()!="unknown"]
        combined = []
        for v in cur_norm + inc_norm:
            if v and v not in combined:
                combined.append(v)
        base_agg[k] = combined

    # single fields
    for k in ("silhouette","sleeves","neckline","length","garment_type"):
        base_val = base_agg.get(k)
        incoming_val = s.get(k) or s.get(k+"_raw") or None
        # if base empty or unknown, take incoming
        if (not base_val or str(base_val).strip().lower()=="unknown") and incoming_val:
            base_agg[k] = incoming_val
        # else keep base

    # images_count
    try:
        base_agg["images_count"] = max(int(base_agg.get("images_count", 0)), 1)
    except Exception:
        base_agg["images_count"] = base_agg.get("images_count", 1)

    # provenance: append social snippet
    prov = base_agg.get("social_examples", [])
    if not isinstance(prov, list):
        prov = []
    snippet = {}
    # pick some useful fields from social analysis if available
    snippet["caption"] = s.get("caption_text") or s.get("caption") or None
    snippet["social_id"] = s.get("post_url") or s.get("page_url") or s.get("id")
    snippet["source"] = "social"
    # include social colors/fabrics if present
    if s.get("colors"):
        snippet["colors"] = s.get("colors")
    if s.get("fabrics"):
        snippet["fabrics"] = s.get("fabrics")
    prov.append(snippet)
    base_agg["social_examples"] = prov

    return base_agg

# iterate social items
for s in social:
    # social object shape may differ — normalize:
    # common fields: image_url, image_urls, page_url, post_url, fashion_analysis, caption_text
    s_image = s.get("image_url") or (s.get("image_urls") and s.get("image_urls")[0]) or None
    s_img_norm = norm_image_url(s_image) if s_image else None
    s_product_url = s.get("post_url") or s.get("page_url") or None
    s_fashion = s.get("fashion_analysis") or s.get("gpt_parsed") or s.get("analysis") or {}

    matched = False

    # 1) try product_url match (exact)
    if s_product_url and s_product_url in prod_by_url:
        target = prod_by_url[s_product_url]
        target_agg = target.get("aggregated", {})
        # compute Jaccard if both have colors/fabrics
        cj = jaccard(target_agg.get("colors"), s_fashion.get("colors"))
        fj = jaccard(target_agg.get("fabrics"), s_fashion.get("fabrics"))
        if cj is not None:
            color_jaccard_values.append(cj)
        if fj is not None:
            fabric_jaccard_values.append(fj)
        merge_attributes(target_agg, s_fashion)
        target["aggregated"] = target_agg
        merged_by_product_url += 1
        matched = True

    # 2) else try normalized image match
    if not matched and s_img_norm and s_img_norm in image_to_prod:
        # choose first matched product (could be enhanced to pick best)
        possible = image_to_prod[s_img_norm]
        target = possible[0]
        target_agg = target.get("aggregated", {})
        cj = jaccard(target_agg.get("colors"), s_fashion.get("colors"))
        fj = jaccard(target_agg.get("fabrics"), s_fashion.get("fabrics"))
        if cj is not None:
            color_jaccard_values.append(cj)
        if fj is not None:
            fabric_jaccard_values.append(fj)
        merge_attributes(target_agg, s_fashion)
        target["aggregated"] = target_agg
        merged_by_image += 1
        matched = True

    # 3) else: create a new product-like entry from social post
    if not matched:
        new_obj = {}
        # minimal product fields: group_key, example_title, image_urls, aggregated
        new_obj["group_key"] = s.get("post_url") or s.get("page_url") or f"social:{len(social)}:{hash(s.get('image_url') or '')}"
        new_obj["product_url"] = s.get("post_url") or None
        new_obj["image_urls"] = [s.get("image_url")] if s.get("image_url") else (s.get("image_urls") or [])
        # aggregated from fashion_analysis if present
        agg = {}
        fa = s_fashion or {}
        agg["colors"] = ensure_list(fa.get("colors"))
        agg["fabrics"] = ensure_list(fa.get("fabrics"))
        agg["prints"] = ensure_list(fa.get("prints_patterns") or fa.get("prints"))
        # single valued
        for k in ("silhouette","sleeves","neckline","length","garment_type","style_fit"):
            val = fa.get(k) or fa.get(k+"_parsed") or None
            if val:
                agg[k] = val
        agg["images_count"] = len(new_obj["image_urls"]) or 1
        agg = merge_attributes(agg, fa)
        new_obj["aggregated"] = agg
        new_obj["example_title"] = s.get("caption_text") or s.get("caption") or None
        # add source marker
        new_obj["_source"] = "social"
        catalog.append(new_obj)
        created_new += 1

# ---------- finish & report ----------
total_after = len(catalog)
report = {
    "catalog_before": len(prod_by_url),
    "social_count": len(social),
    "merged_by_product_url": merged_by_product_url,
    "merged_by_image": merged_by_image,
    "created_new_social_records": created_new,
    "total_after_merge": total_after,
    "catalog_images_indexed": catalog_image_count,
    "color_jaccard_avg": None,
    "fabric_jaccard_avg": None
}

if color_jaccard_values:
    report["color_jaccard_avg"] = sum(color_jaccard_values) / len(color_jaccard_values)
if fabric_jaccard_values:
    report["fabric_jaccard_avg"] = sum(fabric_jaccard_values) / len(fabric_jaccard_values)

# write outputs
OUT_MERGED.parent.mkdir(parents=True, exist_ok=True)
json.dump(catalog, open(OUT_MERGED, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
json.dump(report, open(OUT_REPORT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

# write small sample of merged items for inspection
sample = []
for i, item in enumerate(catalog):
    if i >= 30:
        break
    sample.append({
        "group_key": item.get("group_key"),
        "product_url": item.get("product_url"),
        "image_urls": item.get("image_urls")[:2] if item.get("image_urls") else [],
        "aggregated": item.get("aggregated")
    })
json.dump(sample, open(OUT_SAMPLE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

print("WROTE merged file:", OUT_MERGED)
print("WROTE report:", OUT_REPORT)
print("Summary:", report)
