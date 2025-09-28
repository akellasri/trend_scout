#!/usr/bin/env python3
"""
agent2_input_builder.py (trends-driven)

Reads:
  - output/trends_index.json  (preferred)
  - optionally output/analysis_results_final_updated.json (for catalog examples)

Writes:
  - agent2_inputs/*.json
  - agent2_inputs/index.json

Payload schema is simple and ready to feed to your GPT-5-chat multimodal call:
{
  "id": "...",
  "type": "single_trend"|"combo",
  "system_prompt": "...",
  "user_content": { ... }  <-- the multimodal/user JSON the model should receive
}
"""

import json, uuid, os
from pathlib import Path
from datetime import datetime

# ---------- Config ----------
TRENDS_FILE = Path("output/trends_index.json")
CATALOG_FILE = Path("output/analysis_results_final_updated.json")  # optional
OUT_DIR = Path("agent2_inputs")
TOP_COMBOS_TO_USE = 40        # how many combo payloads to write (if available)
TOP_PER_CATEGORY = 5         # how many items to take from each top_by_category list
EXAMPLES_PER_PAYLOAD = 4     # how many example images to include when available

OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------- Helpful system_prompt (you can edit) ----------
SYSTEM_PROMPT = (
    "You are an expert fashion product designer assistant. "
    "Given the 'user_content' JSON (which contains trending attributes and example images), "
    "produce a single well-structured JSON design object describing a new apparel design. "
    "The assistant MUST respond ONLY with a JSON object (no extra text). "
    "Required keys in the output JSON: "
    "design_id, title, image_prompt, color_palette, fabrics, prints_patterns, garment_type, silhouette, sleeves, neckline, length, style_fit, trims_and_details, techpack (brief), provenance. "
    "If an attribute cannot be identified, return empty list or 'unknown' for single values."
)

# ---------- Utilities ----------
def load_json(p: Path):
    if not p.exists():
        return None
    return json.load(open(p, encoding="utf-8"))

def pick_examples_for_trend(trend_key, trends_obj, catalog_index=None, limit=EXAMPLES_PER_PAYLOAD):
    """
    trend_key: e.g. "color:white" or simply "white" for single lists
    trends_obj: loaded trends_index.json
    catalog_index: optional dict mapping product_url -> product entry
    Returns list of example dicts {product_url, image_url, title}
    """
    ex = []
    # trends.json trend_entries include examples per item — search through them
    for te in trends_obj.get("trend_entries", []):
        if te.get("canonical") == trend_key or te.get("trend_id","").endswith(":" + trend_key):
            ex = te.get("examples", [])[:limit]
            break
    # if no examples found, check top_combos examples
    if not ex and trends_obj.get("top_combos"):
        for c in trends_obj["top_combos"]:
            # c["combo"] may contain pieces like "color:white | print:florals"
            if trend_key in c.get("combo", "") or trend_key == c.get("combo", ""):
                ex = c.get("examples", [])[:limit]
                break
    # fallback: try catalog index to grab any image examples for that canonical if provided
    if not ex and catalog_index:
        # catalog_index maps canonical attributes to list of example dicts
        ex = catalog_index.get(trend_key, [])[:limit]
    return ex

def build_catalog_index(catalog):
    """
    build a simple mapping canonical->examples from catalog items.
    For convenience: keys like "color:white" "fabric:cotton" "garment:dress"
    """
    idx = {}
    for p in catalog:
        url = p.get("product_url") or p.get("group_key")
        imgs = p.get("image_urls") or []
        sample = imgs[0] if imgs else None
        agg = p.get("aggregated", {}) or {}
        for c in agg.get("colors", []) or []:
            key = f"color:{c}"
            idx.setdefault(key, []).append({"product_url": url, "image_url": sample, "title": p.get("example_title")})
        for f in agg.get("fabrics", []) or []:
            key = f"fabric:{f}"
            idx.setdefault(key, []).append({"product_url": url, "image_url": sample, "title": p.get("example_title")})
        for pr in agg.get("prints", []) or []:
            key = f"print:{pr}"
            idx.setdefault(key, []).append({"product_url": url, "image_url": sample, "title": p.get("example_title")})
        gt = agg.get("garment_type")
        if gt:
            key = f"garment:{gt}"
            idx.setdefault(key, []).append({"product_url": url, "image_url": sample, "title": p.get("example_title")})
    return idx

# ---------- Load inputs ----------
trends = load_json(TRENDS_FILE)
if not trends:
    raise SystemExit(f"Trends file not found: {TRENDS_FILE}")

catalog = load_json(CATALOG_FILE) or []
catalog_index = build_catalog_index(catalog) if catalog else None

print("Loaded trends:", TRENDS_FILE, "catalog items:", len(catalog))

# ---------- Prepare single-trend payloads (by category) ----------
payload_files = []
index_list = []

def safe_canon_list(lst):
    return lst if isinstance(lst, list) else []

top_by_cat = trends.get("top_by_category") or trends.get("top_by_category_normalized") or {}
# If top_by_cat is empty, attempt to derive quick lists from trend_entries
if not top_by_cat:
    # build quick mapping
    tb = {}
    entries = trends.get("trend_entries", [])
    for e in entries:
        typ = e.get("type")
        tb.setdefault(typ + "s" if not typ.endswith("s") else typ, []).append(e.get("canonical"))
    top_by_cat = {k: v[:TOP_PER_CATEGORY] for k,v in tb.items()}

# iterate categories and produce single-trend payloads
for cat, items in top_by_cat.items():
    items = items[:TOP_PER_CATEGORY]
    if not items:
        continue
    for i, canon in enumerate(items):
        payload = {
            "id": str(uuid.uuid4()),
            "type": "single_trend",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "system_prompt": SYSTEM_PROMPT,
            "user_content": {
                "mode": "design_from_trend",
                "category": cat,
                "selected_trend": canon,
                "instructions": f"Design a new {cat[:-1] if cat.endswith('s') else cat} inspired by the trend '{canon}'. Keep it commercial and manufacturable. Provide color palette, fabrics, silhouette, sleeves, neckline, trims, and short techpack.",
                "examples": pick_examples_for_trend(canon, trends, catalog_index, EXAMPLES_PER_PAYLOAD)
            }
        }
        fname = OUT_DIR / f"payload_single_{cat}_{i:03d}.json"
        open(fname, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False, indent=2))
        payload_files.append(str(fname))
        index_list.append({"file": str(fname), "type": "single_trend", "trend": canon})

# ---------- Prepare combo payloads ----------
top_combos = trends.get("top_combos") or []
if not top_combos:
    # build combos from top trend_entries pairs (cheap fallback)
    entries = trends.get("trend_entries", [])[:200]
    top_combos = []
    for e in entries:
        # take first few co_occurrences to form combos
        for co in e.get("co_occurrences", [])[:3]:
            combo = {"combo": f"{e['type']}:{e['canonical']} | {co.get('item')}" , "weight": co.get("weight",1)}
            top_combos.append(combo)
# limit
top_combos = top_combos[:TOP_COMBOS_TO_USE]

for idx, combo in enumerate(top_combos):
    combo_key = combo.get("combo") or combo.get("combo_key") or str(combo)
    # try to parse components for examples
    examples = combo.get("examples") or []
    # if examples empty, try to extract canonical parts and pick examples
    if not examples:
        parts = [p.strip() for p in combo_key.split("|")]
        for p in parts[:3]:
            # p eg "color:white" or "fabric:cotton"
            if ":" in p:
                _, val = p.split(":",1)
                examples += pick_examples_for_trend(val.strip(), trends, catalog_index, limit=EXAMPLES_PER_PAYLOAD)
    payload = {
        "id": str(uuid.uuid4()),
        "type": "combo",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "system_prompt": SYSTEM_PROMPT,
        "user_content": {
            "mode": "design_from_combo",
            "combo_key": combo_key,
            "instructions": f"Design a commercial-ready product that combines: {combo_key}. Provide a design JSON with palette, fabrics, prints, silhouette, sleeves, neckline, trims, and short techpack.",
            "examples": examples[:EXAMPLES_PER_PAYLOAD]
        }
    }
    fname = OUT_DIR / f"payload_combo_{idx:04d}.json"
    open(fname, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False, indent=2))
    payload_files.append(str(fname))
    index_list.append({"file": str(fname), "type": "combo", "combo_key": combo_key})

# ---------- Write index.json ----------
index_obj = {
    "generated_at": datetime.utcnow().isoformat() + "Z",
    "payload_count": len(payload_files),
    "files": index_list
}
open(OUT_DIR / "index.json", "w", encoding="utf-8").write(json.dumps(index_obj, ensure_ascii=False, indent=2))

print("Wrote payloads:", len(payload_files), " -> dir:", OUT_DIR)
