#!/usr/bin/env python3
"""
premerge_analysis.py

Compare catalog and social datasets before merging.

Outputs:
  output/premerge_report.json        - summary + stats
  output/premerge_catalog_unique.json
  output/premerge_social_unique.json
  output/premerge_overlap_samples.json

Edit INPUT_CATALOG / INPUT_SOCIAL constants if your filenames differ.
"""
import json
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from collections import Counter
import math

# ---------- CONFIG ----------
INPUT_CATALOG = Path("output/analysis_results_final_updated.json")
INPUT_SOCIAL  = Path("output/instagram_posts_enriched_azure.json")  # change if needed
OUT_DIR = Path("output")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------- helpers ----------
def load_json(p: Path):
    if not p.exists():
        print(f"[ERROR] File not found: {p}")
        return []
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception as e:
        print("Failed to load", p, e)
        return []

def normalize_image_url(u):
    if not u: 
        return None
    try:
        up = urlparse(u)
        # remove query and fragment - keep scheme/netloc/path
        clean = urlunparse((up.scheme, up.netloc, up.path, "", "", ""))
        return clean.rstrip("/")
    except Exception:
        return u

def first_image_from_record(rec):
    # try common fields where images live
    for k in ("image_urls","image_candidates","images","vision_images"):
        v = rec.get(k)
        if isinstance(v, list) and v:
            return v[0]
        if isinstance(v, str) and v:
            return v
    # social style:
    if rec.get("image_url"):
        return rec.get("image_url")
    # fallback to nested vision_summary
    vs = rec.get("vision_summary") or {}
    if isinstance(vs, dict):
        imgs = vs.get("images") or vs.get("image_urls")
        if isinstance(imgs, list) and imgs:
            return imgs[0]
    return None

def extract_colors_from_catalog(rec):
    # catalog aggregated shape used in your flow
    agg = rec.get("aggregated") or {}
    # some outputs store `colors` or `colors_list` or vision style color hexs
    cols = agg.get("colors") or agg.get("colors_list") or []
    # if dict with name
    out=[]
    for c in cols:
        if isinstance(c, dict):
            n = c.get("name") or c.get("color")
            if n: out.append(str(n).lower())
        else:
            out.append(str(c).lower())
    return set([x.strip() for x in out if x and x.strip()])

def extract_colors_from_social(rec):
    # social style: fashion_analysis.colors or fashion_analysis -> colors
    fa = rec.get("fashion_analysis") or rec.get("gpt_parsed") or {}
    cols = fa.get("colors") or fa.get("colors_list") or []
    out = []
    for c in cols:
        if isinstance(c, dict):
            n = c.get("name")
            if n: out.append(str(n).lower())
        else:
            out.append(str(c).lower())
    return set([x.strip() for x in out if x and x.strip()])

def extract_fabrics_catalog(rec):
    agg = rec.get("aggregated") or {}
    fabs = agg.get("fabrics") or []
    out=[]
    for f in fabs:
        if isinstance(f, dict):
            n = f.get("name") or f.get("fabric")
            if n: out.append(str(n).lower())
        else:
            out.append(str(f).lower())
    return set([x.strip() for x in out if x and x.strip()])

def extract_fabrics_social(rec):
    fa = rec.get("fashion_analysis") or rec.get("gpt_parsed") or {}
    fabs = fa.get("fabrics") or []
    out=[]
    for f in fabs:
        if isinstance(f, dict):
            n = f.get("name")
            if n: out.append(str(n).lower())
        else:
            out.append(str(f).lower())
    return set([x.strip() for x in out if x and x.strip()])

def jaccard(a,b):
    if not a and not b: return None
    A = set(a or [])
    B = set(b or [])
    if not A and not B: return 0.0
    inter = len(A & B)
    union = len(A | B)
    return inter / union if union else 0.0

# ---------- load ----------
catalog = load_json(INPUT_CATALOG)
social = load_json(INPUT_SOCIAL)

# counts
catalog_count = len(catalog)
social_count = len(social)

# index images
catalog_by_img = {}
catalog_by_prod = {}
for rec in catalog:
    img = first_image_from_record(rec)
    nimg = normalize_image_url(img) if img else None
    if nimg:
        catalog_by_img.setdefault(nimg, []).append(rec)
    # product_url normalization
    purl = (rec.get("product_url") or rec.get("group_key") or "").rstrip("/")
    if purl:
        catalog_by_prod.setdefault(purl, []).append(rec)

social_by_img = {}
social_by_post = {}
for rec in social:
    # friend's social format: image_url, post_url
    img = rec.get("image_url") or first_image_from_record(rec)
    nimg = normalize_image_url(img) if img else None
    if nimg:
        social_by_img.setdefault(nimg, []).append(rec)
    post = (rec.get("post_url") or rec.get("page_url") or "").rstrip("/")
    if post:
        social_by_post.setdefault(post, []).append(rec)

# overlap by exact image URL
catalog_imgs_set = set(catalog_by_img.keys())
social_imgs_set = set(social_by_img.keys())
img_intersection = catalog_imgs_set & social_imgs_set
img_only_catalog = catalog_imgs_set - social_imgs_set
img_only_social = social_imgs_set - catalog_imgs_set

# overlap by product / post url
catalog_prods_set = set(catalog_by_prod.keys())
social_posts_set = set(social_by_post.keys())
prod_intersection = catalog_prods_set & social_posts_set

# sample overlap examples (first 50)
overlap_samples = []
for i, img in enumerate(list(img_intersection)[:50]):
    cat_recs = catalog_by_img.get(img, [])[:2]
    soc_recs = social_by_img.get(img, [])[:2]
    overlap_samples.append({
        "image_url": img,
        "catalog_examples_count": len(catalog_by_img.get(img, [])),
        "social_examples_count": len(social_by_img.get(img, [])),
        "catalog_examples": [{"product_url": c.get("product_url") or c.get("group_key"), "title": c.get("example_title")} for c in cat_recs],
        "social_examples": [{"post_url": s.get("post_url") or s.get("page_url"), "caption": (s.get("caption_text") or "")[:200]} for s in soc_recs]
    })

# attribute agreement: sample first 500 pairs where image matches
color_agreements = []
fabric_agreements = []
pair_count = 0
for img in list(img_intersection)[:500]:
    cats = catalog_by_img.get(img, [])
    socs = social_by_img.get(img, [])
    # compare first pair each
    for c in cats[:1]:
        for s in socs[:1]:
            c_colors = extract_colors_from_catalog(c)
            s_colors = extract_colors_from_social(s)
            c_fabs = extract_fabrics_catalog(c)
            s_fabs = extract_fabrics_social(s)
            color_agreements.append({"image_url":img, "catalog_colors":list(c_colors), "social_colors":list(s_colors), "jaccard": jaccard(c_colors, s_colors)})
            fabric_agreements.append({"image_url":img, "catalog_fabrics":list(c_fabs), "social_fabrics":list(s_fabs), "jaccard": jaccard(c_fabs, s_fabs)})
            pair_count += 1

# compute basic stats
report = {
    "catalog_count": catalog_count,
    "social_count": social_count,
    "catalog_unique_image_urls": len(catalog_imgs_set),
    "social_unique_image_urls": len(social_imgs_set),
    "image_url_exact_overlap_count": len(img_intersection),
    "image_url_exact_overlap_pct_of_social": round(100 * len(img_intersection) / social_count if social_count else 0, 2),
    "image_url_exact_overlap_pct_of_catalog": round(100 * len(img_intersection) / catalog_count if catalog_count else 0, 2),
    "product_url_overlap_count": len(prod_intersection),
    "sample_overlap_examples_saved": len(overlap_samples),
    "attribute_pair_samples": pair_count,
    "color_jaccard_avg": None,
    "fabric_jaccard_avg": None
}

# average jaccard
cj = [x["jaccard"] for x in color_agreements if x["jaccard"] is not None]
fj = [x["jaccard"] for x in fabric_agreements if x["jaccard"] is not None]
report["color_jaccard_avg"] = (sum(cj)/len(cj)) if cj else None
report["fabric_jaccard_avg"] = (sum(fj)/len(fj)) if fj else None

# write outputs
OUT_DIR.joinpath("premerge_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
OUT_DIR.joinpath("premerge_overlap_samples.json").write_text(json.dumps(overlap_samples, indent=2, ensure_ascii=False), encoding="utf-8")
# write the lists of unique (image-only) identifiers (just URLs) for manual inspection
OUT_DIR.joinpath("premerge_catalog_unique_images.json").write_text(json.dumps(list(img_only_catalog)[:5000], indent=2), encoding="utf-8")
OUT_DIR.joinpath("premerge_social_unique_images.json").write_text(json.dumps(list(img_only_social)[:5000], indent=2), encoding="utf-8")
# write attribute agreement samples
OUT_DIR.joinpath("premerge_color_agreements.json").write_text(json.dumps(color_agreements[:500], indent=2, ensure_ascii=False), encoding="utf-8")
OUT_DIR.joinpath("premerge_fabric_agreements.json").write_text(json.dumps(fabric_agreements[:500], indent=2, ensure_ascii=False), encoding="utf-8")

print("WROTE report ->", OUT_DIR / "premerge_report.json")
print("Summary:")
print(" Catalog items:", catalog_count)
print(" Social items:", social_count)
print(" Catalog unique images:", report['catalog_unique_image_urls'])
print(" Social unique images:", report['social_unique_image_urls'])
print(" Exact image-url overlaps:", report['image_url_exact_overlap_count'])
print(" Product URL overlaps:", report['product_url_overlap_count'])
print(" Avg color jaccard (sample):", report['color_jaccard_avg'])
print(" Avg fabric jaccard (sample):", report['fabric_jaccard_avg'])
