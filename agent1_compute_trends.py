#!/usr/bin/env python3
"""
compute_trends.py (updated)

Input:  output/merged_catalog.json  (if present) else output/analysis_results_final_updated.json
Output: output/trends_index.json (ranked list) with survey-boosting, grouped categories,
        and top_by_category + top_combos for easier downstream consumption.
"""

import json, math, time
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime, timezone
from dateutil import parser as dateparse  # pip install python-dateutil if missing

# ---------- Files ----------
IN_CANDIDATES = [
    Path("output/merged_catalog.json")
]
OUT = Path("output/trends_index.json")

# ---------- Parameters ----------
TOP_K = 400
TOP_PER_CATEGORY = 10
TOP_COMBOS = 200

# source weights: upweight social items if present
SOURCE_WEIGHTS = {"catalog": 1.0, "social": 1.25}

# time decay half-life in days (set to None to disable)
TIME_DECAY_HALF_LIFE_DAYS = 365  # make recent items matter more; set None to disable time decay

# ---------- Survey priors: boost factors (tune these) ----------
PRIOR_BOOSTS = {
    # colors (boost pastels/neutrals/earth)
    "baby pink": 1.8, "lavender": 1.8, "sage green": 1.8,
    "beige": 1.5, "cream": 1.5, "white": 1.2, "grey": 1.2,
    "olive": 1.6, "brown": 1.3, "rust": 1.6,

    # fabrics
    "cotton": 1.6, "linen": 1.6, "denim": 1.3, "hemp": 1.8, "bamboo": 1.8, "recycled": 1.6, "knit":1.4, "crochet":1.4,
    "silk": 1.4, "satin": 1.3, "chiffon": 1.3, "velvet": 1.2, "lace": 1.2, "organza": 1.2, "georgette": 1.2, "viscose":1.1,

    # prints
    "florals": 1.6, "solids / minimalist": 1.4, "embroidery":1.5, "bandhani":1.5, "ikat":1.4, "tie-dye":1.4, "paisley":1.3,

    # sleeves & silhouettes
    "Puff sleeves": 1.7, "Balloon sleeves": 1.7, "Oversized/Baggy": 1.4, "Bodycon/Fitted":1.2, "Draped/Flowing":1.3,

    # necklines
    "V-neck": 1.5, "Halter": 1.4, "Off-shoulder":1.4, "Square neck":1.4, "Sweetheart neck":1.4
}

# ---------- Group mappings (for aggregated categories like Pastels) ----------
COLOR_GROUPS = {
    "Pastels": ["lavender", "baby pink", "powder pink", "mint", "pale blue", "pale green"],
    "Neutrals": ["beige", "cream", "white", "grey", "ivory"],
    "Earth tones": ["olive", "brown", "rust", "terracotta"]
}

# ---------- Helpers ----------
def load_input():
    for p in IN_CANDIDATES:
        if p.exists():
            print("Using input:", p)
            return json.load(open(p, encoding="utf-8"))
    raise SystemExit("No input catalog found in expected locations.")

def parse_timestamp(s):
    if not s:
        return None
    try:
        return dateparse.parse(s)
    except Exception:
        # sometimes social timestamps are epoch numbers
        try:
            return datetime.fromtimestamp(float(s), tz=timezone.utc)
        except Exception:
            return None

def time_weight_from_timestamp(ts):
    if not ts or TIME_DECAY_HALF_LIFE_DAYS is None:
        return 1.0
    if isinstance(ts, str):
        ts = parse_timestamp(ts)
    if not ts:
        return 1.0
    now = datetime.now(timezone.utc)
    if not ts.tzinfo:
        ts = ts.replace(tzinfo=timezone.utc)
    age_days = (now - ts).total_seconds() / (3600*24)
    # half-life decay: weight = 2^(-age_days / half_life)
    return 2 ** (-age_days / float(TIME_DECAY_HALF_LIFE_DAYS))

def confidence_weight_from_record(rec):
    # use available confidence fields if present (garment_type_confidence etc.)
    c = rec.get("aggregated",{}).get("garment_type_confidence") or rec.get("garment_type_confidence")
    try:
        return float(c) if c else 1.0
    except Exception:
        return 1.0

# ---------- Load data ----------
data = load_input()
N = len(data)
print("Records:", N)

# ---------- Counters (weighted) ----------
color_count = Counter()
fabric_count = Counter()
print_count = Counter()
silhouette_count = Counter()
sleeve_count = Counter()
neck_count = Counter()
garment_count = Counter()
length_count = Counter()
co = defaultdict(Counter)

# helper to inc weighted counters and co-occurrence
def weighted_inc(counter, key, w=1.0):
    if not key:
        return
    try:
        counter[key] += w
    except Exception:
        counter[str(key)] += w

def add_co_weighted(a,b,w=1.0):
    if a and b:
        co[a][b] += w
        co[b][a] += w

# ---------- Iterate items and accumulate weighted counts ----------
for p in data:
    agg = p.get("aggregated", {}) or {}
    # source detection - merged script may put _source or we can detect missing fields
    source = p.get("_source") or p.get("source") or ("social" if p.get("product_url", "").startswith("http") and "instagram" in (p.get("product_url") or "") else "catalog")
    src_weight = SOURCE_WEIGHTS.get(source, 1.0)
    # time weight: prefer newer posts if timestamp present on social items
    timestamp = p.get("post_timestamp") or p.get("created_at") or agg.get("post_timestamp")
    t_weight = time_weight_from_timestamp(timestamp)
    conf_w = confidence_weight_from_record(p)
    product_weight = src_weight * t_weight * conf_w

    colors = agg.get("colors") or []
    fabrics = agg.get("fabrics") or []
    prints = agg.get("prints") or agg.get("prints_patterns") or []
    sil = agg.get("silhouette")
    sleeves = agg.get("sleeves")
    neck = agg.get("neckline")
    gtype = agg.get("garment_type")
    length = agg.get("length")

    # increment counts with product_weight
    for c in colors:
        if c and c != "unknown":
            weighted_inc(color_count, c, product_weight)
    for f in fabrics:
        if f and f != "unknown":
            weighted_inc(fabric_count, f, product_weight)
    for pr in prints:
        if pr and pr != "unknown":
            weighted_inc(print_count, pr, product_weight)
    if sil and sil != "unknown":
        weighted_inc(silhouette_count, sil, product_weight)
    if sleeves and sleeves != "unknown":
        weighted_inc(sleeve_count, sleeves, product_weight)
    if neck and neck != "unknown":
        weighted_inc(neck_count, neck, product_weight)
    if gtype and gtype != "unknown":
        weighted_inc(garment_count, gtype, product_weight)
    if length and length != "unknown":
        weighted_inc(length_count, length, product_weight)

    # build components for co-occurrence (only include non-empty canonical tokens)
    comps = []
    comps += [f"color:{c}" for c in colors if c and c!="unknown"]
    comps += [f"fabric:{f}" for f in fabrics if f and f!="unknown"]
    comps += [f"print:{pr}" for pr in prints if pr and pr!="unknown"]
    if sil and sil!="unknown": comps.append(f"silhouette:{sil}")
    if sleeves and sleeves!="unknown": comps.append(f"sleeve:{sleeves}")
    if neck and neck!="unknown": comps.append(f"neck:{neck}")
    if gtype and gtype!="unknown": comps.append(f"garment:{gtype}")
    if length and length!="unknown": comps.append(f"length:{length}")

    for i in range(len(comps)):
        for j in range(i+1, len(comps)):
            add_co_weighted(comps[i], comps[j], product_weight)

# ---------- group counts (map color canonical to group) ----------
group_count = Counter()
for group, color_list in COLOR_GROUPS.items():
    for col in color_list:
        group_count[group] += color_count.get(col, 0)

# ---------- Build trend entries ----------
trend_entries = []
def append_counter(counter, kind):
    for k,v in counter.most_common():
        # convert weighted counts to integers for display if desired
        trend_entries.append({"trend_id": f"{kind}:{k}", "type": kind, "canonical": k, "count": float(v)})

append_counter(color_count, "color")
append_counter(fabric_count, "fabric")
append_counter(print_count, "print")
append_counter(silhouette_count, "silhouette")
append_counter(sleeve_count, "sleeve")
append_counter(neck_count, "neckline")
append_counter(garment_count, "garment_type")
append_counter(length_count, "length")
# add groups as separate trend items
for grp, cnt in group_count.items():
    trend_entries.append({"trend_id": f"group:color_group:{grp}", "type": "group", "canonical": grp, "count": float(cnt)})

# ---------- compute scores with PRIOR_BOOSTS and co-occurrence ----------
max_count = max((e["count"] for e in trend_entries), default=1.0)
for e in trend_entries:
    c = float(e["count"])
    norm = math.log(1+c)/math.log(1+max_count)
    key = e["canonical"]
    boost = PRIOR_BOOSTS.get(key, 1.0)

    # group items: compute member-boost mean if group is color_group
    if e["type"]=="group" and e["canonical"] in COLOR_GROUPS:
        members = COLOR_GROUPS[e["canonical"]]
        bsum = 0.0
        cntm = 0
        for m in members:
            bsum += PRIOR_BOOSTS.get(m, 1.0)
            cntm += 1
        boost = (bsum/cntm) if cntm else 1.0

    # co-occurrence score (weighted)
    co_scores = co.get(f"{e['type']}:{e['canonical']}", Counter())
    co_score = sum(co_scores.values())/(1+len(co_scores)) if co_scores else 0.0
    co_norm = math.log(1+co_score)/(1+math.log(1+max_count)) if co_score else 0.0

    # combine into final score (tunable)
    score = (0.60 * norm + 0.30 * (math.log(1+c)/math.log(1+max_count)) + 0.10 * co_norm) * boost
    e["score"] = round(float(score), 5)
    # provide top co-occurrences in array form
    # convert Counter-like to list of tuples
    e["co_occurrences"] = [{"item": k, "weight": v} for k,v in co.get(f"{e['type']}:{e['canonical']}", Counter()).most_common(6)]

# ---------- rank and attach examples (cheap sampling) ----------
trend_entries.sort(key=lambda x: x["score"], reverse=True)
for i,e in enumerate(trend_entries, start=1):
    e["rank"] = i

# attach examples (sample up to 6)
example_map = defaultdict(list)
for p in data:
    agg = p.get("aggregated", {})
    url = p.get("product_url") or p.get("group_key")
    imgs = p.get("image_urls") or p.get("image_candidates") or []
    sample_img = imgs[0] if isinstance(imgs, list) and imgs else (p.get("image_url") or None)
    for c in agg.get("colors", []) or []:
        example_map[f"color:{c}"].append({"product_url": url, "image_url": sample_img, "title": p.get("example_title")})
    for f in agg.get("fabrics", []) or []:
        example_map[f"fabric:{f}"].append({"product_url": url, "image_url": sample_img, "title": p.get("example_title")})
    for pr in agg.get("prints", []) or []:
        example_map[f"print:{pr}"].append({"product_url": url, "image_url": sample_img, "title": p.get("example_title")})
    if agg.get("silhouette") and agg.get("silhouette")!="unknown":
        example_map[f"silhouette:{agg.get('silhouette')}"].append({"product_url": url, "image_url": sample_img, "title": p.get("example_title")})
    if agg.get("sleeves") and agg.get("sleeves")!="unknown":
        example_map[f"sleeve:{agg.get('sleeves')}"].append({"product_url": url, "image_url": sample_img, "title": p.get("example_title")})
    if agg.get("neckline") and agg.get("neckline")!="unknown":
        example_map[f"neck:{agg.get('neckline')}"].append({"product_url": url, "image_url": sample_img, "title": p.get("example_title")})
    if agg.get("garment_type") and agg.get("garment_type")!="unknown":
        example_map[f"garment:{agg.get('garment_type')}"].append({"product_url": url, "image_url": sample_img, "title": p.get("example_title")})

for e in trend_entries:
    key = f"{e['type']}:{e['canonical']}"
    if e["type"]=="group" and e["canonical"] in COLOR_GROUPS:
        members = COLOR_GROUPS[e["canonical"]]
        exs = []
        for m in members:
            exs += example_map.get(f"color:{m}", [])[:3]
        e["examples"] = exs[:6]
    else:
        e["examples"] = example_map.get(key, [])[:6]

# ---------- produce top_by_category + top_combos for downstream consumption ----------
top_by_category = {
    "colors": [t["canonical"] for t in trend_entries if t["type"]=="color"][:TOP_PER_CATEGORY],
    "fabrics": [t["canonical"] for t in trend_entries if t["type"]=="fabric"][:TOP_PER_CATEGORY],
    "prints": [t["canonical"] for t in trend_entries if t["type"]=="print"][:TOP_PER_CATEGORY],
    "silhouettes": [t["canonical"] for t in trend_entries if t["type"]=="silhouette"][:TOP_PER_CATEGORY],
    "sleeves": [t["canonical"] for t in trend_entries if t["type"]=="sleeve"][:TOP_PER_CATEGORY],
    "necklines": [t["canonical"] for t in trend_entries if t["type"]=="neckline"][:TOP_PER_CATEGORY],
    "garment_types": [t["canonical"] for t in trend_entries if t["type"]=="garment_type"][:TOP_PER_CATEGORY],
    "lengths": [t["canonical"] for t in trend_entries if t["type"]=="length"][:TOP_PER_CATEGORY],
    "groups": [t["canonical"] for t in trend_entries if t["type"]=="group"][:TOP_PER_CATEGORY]
}

# combos: take top co-occurrence pairs/triples from co dict (already weighted)
combos = []
# create combos list sorted by summed co weights
seen = set()
for k,v in co.items():
    # k is like "color:white"
    for other, w in v.most_common(10):
        combo_key = " | ".join(sorted([k, other]))
        if combo_key in seen: 
            continue
        seen.add(combo_key)
        examples = []
        # find examples by reading example_map entries for components
        comps = [x.split(":",1)[1] for x in combo_key.split("|")]
        # cheap: pick first example that matches any component
        # (downstream script will enrich more carefully)
        combos.append({"combo": combo_key, "weight": float(w), "examples": examples})
# sort combos
combos.sort(key=lambda x: x["weight"], reverse=True)
top_combos = combos[:TOP_COMBOS]

# ---------- write output ----------
OUT.parent.mkdir(parents=True, exist_ok=True)
out_obj = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "records_count": N,
    "top_by_category": top_by_category,
    "top_combos": top_combos,
    "trend_entries": trend_entries[:TOP_K]
}
json.dump(out_obj, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("Wrote", OUT)
print("Top 20 trends (type canonical count score):")
for t in trend_entries[:20]:
    print(f"{t['rank']:>3}. {t['type']:<10} {t['canonical']:<20} count={t['count']:4} score={t['score']}")
