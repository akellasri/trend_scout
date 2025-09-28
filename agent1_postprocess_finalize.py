#!/usr/bin/env python3
"""
postprocess_finalize.py (updated)

Reads:  output/analysis_results_enriched_updated.json
Writes: output/analysis_results_final_updated.json

What it does:
- Prefer gpt_parsed (enriched GPT outputs) to build canonical aggregated fields.
- Removes "unknown" and empty values
- Maps raw colors/fabrics/prints/necklines/sleeves/silhouettes/lengths/garment types/style_fit
  to a canonical taxonomy (expanded)
- Deduplicates lists and returns a clean product-level JSON suitable for ingestion

Run:
  python postprocess_finalize.py
"""
import json
import os
import re
from pathlib import Path
from collections import Counter, defaultdict

# ---------- Input / output ----------
INPUT = "output/analysis_results_enriched_updated.json"
OUTPUT = "output/analysis_results_final_updated.json"

# ---------- Utilities ----------
def lower_and_strip(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def ensure_list(x):
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]

HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")
def is_hex_token(tok):
    if not tok:
        return False
    t = str(tok).strip()
    if t.startswith("#"):
        t = t[1:]
    return bool(HEX_RE.match(t))

def find_canonical(value, synonyms_map):
    """
    value: string (raw)
    synonyms_map: dict canonical -> [synonyms...]
    returns canonical if matched else None
    """
    if not value:
        return None
    val = lower_and_strip(value)
    # exact synonyms
    for canon, syns in synonyms_map.items():
        for syn in syns:
            if syn == val:
                return canon
    # substring match
    for canon, syns in synonyms_map.items():
        for syn in syns:
            if syn in val:
                return canon
    # if value equals canonical name
    for canon in synonyms_map.keys():
        if lower_and_strip(canon) == val:
            return canon
    return None

# ---------- Expanded canonical taxonomy & synonyms ----------
CANON_COLORS = [
    "lavender", "baby pink", "sage green", "beige", "cream", "white", "grey",
    "olive", "brown", "rust", "black", "navy", "maroon", "red", "pink", "blue",
    "green", "yellow", "orange", "purple", "teal", "burgundy", "mustard", "mint",
    "emerald", "powder blue", "dusty pink", "blush", "pastel", "ivory", "gold",
    "silver", "metallic"
]

COLOR_SYNONYMS = {
    "lavender": ["lavender","lilac"],
    "baby pink": ["baby pink","blush","powder pink","dusty pink"],
    "sage green": ["sage","sage green","salvia"],
    "beige": ["beige","tan","taupe","khaki"],
    "cream": ["cream","off white","ivory"],
    "white": ["white"],
    "grey": ["grey","gray","charcoal","silver"],
    "olive": ["olive","olivedrab"],
    "brown": ["brown","chocolate","tan","bronze"],
    "rust": ["rust","terracotta"],
    "black": ["black"],
    "navy": ["navy","navy blue"],
    "maroon": ["maroon","burgundy","wine","oxblood"],
    "red": ["red"],
    "pink": ["pink"],
    "blue": ["blue","powder blue"],
    "green": ["green","mint","emerald"],
    "yellow": ["yellow","mustard","mellow yellow"],
    "orange": ["orange"],
    "purple": ["purple"],
    "teal": ["teal","cyan","aqua"],
    "gold": ["gold","metallic gold"],
    "silver": ["silver","metallic silver"],
    "ivory": ["ivory"]
}

CANON_FABRICS = [
    "cotton","linen","denim","hemp","bamboo","recycled","knit","crochet",
    "silk","satin","chiffon","velvet","lace","wool","rayon","organza","crepe",
    "khadi","tussar","tussar silk","raw silk","banarasi","banarasi silk","brocade",
    "chikankari","handloom","woven","net","georgette","viscose","modal","muslin","twill","embroidery"
]

FABRIC_SYNONYMS = {
    "cotton":["cotton"],
    "linen":["linen"],
    "denim":["denim","jean","jeans"],
    "hemp":["hemp"],
    "bamboo":["bamboo"],
    "recycled":["recycled"],
    "knit":["knit","knitted"],
    "crochet":["crochet"],
    "silk":["silk","raw silk","tussar silk","banarasi silk"],
    "satin":["satin"],
    "chiffon":["chiffon","georgette"],
    "velvet":["velvet"],
    "lace":["lace"],
    "wool":["wool"],
    "rayon":["rayon","viscose","modal"],
    "organza":["organza"],
    "crepe":["crepe"],
    "khadi":["khadi"],
    "tussar":["tussar"],
    "banarasi":["banarasi","banarasi silk"],
    "brocade":["brocade"],
    "chikankari":["chikankari"],
    "handloom":["handloom","woven"],
    "net":["net"],
    "muslin":["muslin"],
    "twill":["twill"],
    "embroidery": ["embroidery","embroidered","mirror work","mirrorwork"]
}

CANON_PRINTS = [
    "florals","solids / minimalist","logos & slogan","stripes","checks","paisley",
    "geometric","polka dot","leaf motif","bandhani","ikat","kalamkari","gingham",
    "block print","digital print","painterly","batik","mirror work","embroidery","tie-dye","abstract"
]

PRINT_SYNONYMS = {
    "florals":["floral","florals","flower","flowers","botanical"],
    "solids / minimalist":["solid","minimalist","plain"],
    "logos & slogan":["logo","logos","slogan","branding"],
    "stripes":["stripe","stripes"],
    "checks":["check","checks","checked","plaid","gingham"],
    "paisley":["paisley"],
    "geometric":["geometric"],
    "polka dot":["polka","polka dot","dots"],
    "leaf motif":["leaf motif","leaf"],
    "bandhani":["bandhani"],
    "ikat":["ikat"],
    "kalamkari":["kalamkari"],
    "tie-dye":["tie-dye","tie dye"],
    "embroidery":["embroidery","embroidered","mirror work","mirrorwork"]
}

CANON_NECKLINES = [
    "V-neck", "Halter", "Crew neck", "Off-shoulder", "Square neck",
    "Collared", "Cowl neck", "Asymmetrical/One-shoulder", "Sweetheart neck",
    "round neck", "boat neck", "high neck", "mock neck", "keyhole neck"
]

NECK_SYNONYMS = {
    "V-neck": ["v-neck","v neck","vneck"],
    "Halter":["halter","halter neck"],
    "Crew neck":["crew","crew neck","round neck","round-neck"],
    "Off-shoulder":["off-shoulder","off shoulder","offshoulder"],
    "Square neck":["square neck","square-neck","squareneck"],
    "Collared":["collar","collared","button-down","shirt collar"],
    "Cowl neck":["cowl"],
    "Asymmetrical/One-shoulder":["asymmetrical","one-shoulder","one shoulder"],
    "Sweetheart neck":["sweetheart","sweetheart neck"],
    "boat neck": ["boat neck"],
    "high neck": ["high neck","high-neck","mock neck"],
    "keyhole neck": ["keyhole","keyhole neck"]
}

CANON_SLEEVES = [
    "Puff sleeves", "Balloon sleeves", "Oversized sleeves",
    "Sleeveless/Tank", "3/4th sleeves", "Full sleeves", "Cap sleeves",
    "short sleeve", "elbow sleeve", "bishop sleeve", "ruffle sleeve", "kimono sleeve",
    "bell sleeve", "flared sleeve", "dolman sleeve", "petal sleeve", "cold shoulder"
]

SLEEVE_SYNONYMS = {
    "Puff sleeves": ["puff","puff sleeve","puff sleeves"],
    "Balloon sleeves": ["balloon","balloon sleeve"],
    "Oversized sleeves": ["oversized","oversize","oversized sleeve","oversized sleeves"],
    "Sleeveless/Tank": ["sleeveless","tank"],
    "3/4th sleeves": ["3/4","3/4th","three quarter","3/4th sleeves","3/4 sleeves","three-quarter"],
    "Full sleeves": ["full sleeve","full sleeves","long sleeve","long sleeves"],
    "Cap sleeves": ["cap sleeve","cap-sleeve"],
    "short sleeve": ["short sleeve","short-sleeve"],
    "elbow sleeve": ["elbow sleeve","elbow-length sleeve"],
    "bishop sleeve": ["bishop sleeve"],
    "ruffle sleeve": ["ruffle sleeve"],
    "kimono sleeve": ["kimono sleeve"],
    "bell sleeve": ["bell sleeve"],
    "flared sleeve": ["flared sleeve"],
    "dolman sleeve": ["dolman sleeve"],
    "petal sleeve": ["petal sleeve"],
    "cold shoulder": ["cold shoulder","cold-shoulder"]
}

CANON_SILHOUETTES = [
    "Oversized/Baggy", "Bodycon/Fitted", "Draped/Flowing",
    "Cropped Tops", "Baggy pants/Cargo", "Jumpsuits/Coord sets",
    "Tailored", "A-line", "Fit-and-flare", "wrap dress", "sheath", "anarkali", "sherwani", "cape", "slip dress", "layered", "asymmetric"
]

SILHOUETTE_SYNONYMS = {
    "Oversized/Baggy": ["oversized","baggy","boxy","loose fit","loose"],
    "Bodycon/Fitted": ["bodycon","fitted","tight","slim fit"],
    "Draped/Flowing": ["draped","flowing","flowy","flared"],
    "Cropped Tops": ["cropped","crop top","cropped top"],
    "Baggy pants/Cargo": ["baggy pants","cargo","wide leg","baggy"],
    "Jumpsuits/Coord sets": ["jumpsuit","coord","co-ord","coord set"],
    "Tailored": ["tailored"],
    "A-line": ["a-line","a line"],
    "Fit-and-flare": ["fit and flare","fit-and-flare","fit & flare"],
    "wrap dress": ["wrap dress","wrap"],
    "sheath": ["sheath"],
    "anarkali": ["anarkali"],
    "sherwani": ["sherwani"]
}

CANON_LENGTHS = ["Mini", "Midi", "Maxi", "Cropped", "Ankle-length", "Knee-length", "Full-length"]
LENGTH_SYNONYMS = {
    "Mini":["mini"],
    "Midi":["midi"],
    "Maxi":["maxi","floor length","full length"],
    "Cropped":["cropped","crop"],
    "Ankle-length":["ankle","ankle-length"],
    "Knee-length":["knee","knee-length"],
    "Full-length":["full-length","full length"]
}

CANON_GARMENT_TYPES = [
    "dress","kurta","shirt","top","trouser","pants","skirt","jacket","coat","blouse",
    "sari","saree","lehenga","kurta-set","outfit","gown","coord set","jumpsuit","palazzo",
    "robe","tunics","saree-blouse","anarkali","sherwani","shrug","culotte","shirt dress","wrap dress"
]

GARMENT_SYNONYMS = {
    "dress":["dress","gown"],
    "kurta":["kurta"],
    "shirt":["shirt"],
    "top":["top","tee","t-shirt","tank"],
    "trouser":["trouser","trousers"],
    "pants":["pants","pant"],
    "skirt":["skirt"],
    "jacket":["jacket","blazer"],
    "coat":["coat"],
    "blouse":["blouse"],
    "sari":["sari","saree"],
    "lehenga":["lehenga"],
    "kurta-set":["kurta set","kurta-set","set"],
    "outfit":["outfit"],
    "gown":["gown"],
    "coord set":["coord","coord set","co-ord"],
    "jumpsuit":["jumpsuit"],
    "palazzo":["palazzo"],
    "robe":["robe"],
    "tunics":["tunic","tunics"],
    "saree-blouse":["blouse","saree blouse","saree-blouse"],
    "anarkali":["anarkali"],
    "sherwani":["sherwani"],
    "shrug":["shrug"],
    "culotte":["culotte"],
    "shirt dress":["shirt dress"],
    "wrap dress":["wrap dress"]
}

CANON_STYLE_FIT = [
    "Oversized/Baggy", "Bodycon/Fitted", "Draped/Flowing", "Cropped Tops",
    "Baggy pants/Cargo", "Jumpsuits/Coord sets", "Tailored", "A-line", "Fit-and-flare"
]
STYLE_SYNONYMS = SILHOUETTE_SYNONYMS

# ---------- Cleanup rules (garment-type-aware) ----------
CLEANUP_RULES = {
    "sari": {"length": "unknown", "sleeves": "unknown", "neckline": "unknown"},
    "saree": {"length": "unknown", "sleeves": "unknown", "neckline": "unknown"},
    "kurta": {"length": "unknown"},
    "kurta-set": {"length": "unknown"},
    # optionally set lehenga to full-length
    "lehenga": {"length": "Full-length"}
}

# ---------- Mapping helpers ----------
def map_color_list(raw_list):
    mapped = []
    seen = set()
    for raw in ensure_list(raw_list):
        if not raw:
            continue
        # handle dict entries with 'name'
        if isinstance(raw, dict):
            raw_val = raw.get("name") or raw.get("color") or ""
        else:
            raw_val = str(raw)
        r = lower_and_strip(raw_val)
        # skip "unknown"
        if r == "unknown" or r == "":
            continue
        # if token looks like hex, keep hex (but also attempt to map later)
        token = r
        if is_hex_token(token):
            # store hex with leading # for traceability
            token = "#" + token.lstrip("#").upper()
            if token not in seen:
                mapped.append(token)
                seen.add(token)
            continue
        # try synonyms map
        matched = None
        for canon, syns in COLOR_SYNONYMS.items():
            for syn in syns:
                if syn in r:
                    matched = canon
                    break
            if matched:
                break
        # fallback: direct canonical token contained
        if not matched:
            for c in CANON_COLORS:
                if lower_and_strip(c) in r:
                    matched = c
                    break
        if matched and matched not in seen:
            mapped.append(matched)
            seen.add(matched)
    return mapped

def map_generic_list(raw_list, syn_map, allow_list):
    mapped = []
    seen = set()
    for raw in ensure_list(raw_list):
        if not raw:
            continue
        if isinstance(raw, dict):
            raw_val = raw.get("name") or raw.get("value") or ""
        else:
            raw_val = str(raw)
        r = lower_and_strip(raw_val)
        if r == "unknown" or r == "":
            continue
        matched = find_canonical(r, syn_map)
        if not matched:
            # try any canonical token contained in text
            for canon in allow_list:
                if lower_and_strip(canon) in r:
                    matched = canon
                    break
        if matched and matched not in seen:
            mapped.append(matched)
            seen.add(matched)
    return mapped

# ---------- Main processing ----------
def process_products(input_path=INPUT, output_path=OUTPUT):
    p = Path(input_path)
    if not p.exists():
        print("Input file not found:", input_path)
        return
    products = json.loads(p.read_text(encoding="utf-8"))
    final = []
    # stats counters
    color_counter = Counter()
    fabric_counter = Counter()
    garment_counter = Counter()
    used_gpt = 0
    used_agg = 0
    unknown_color_count = 0
    unknown_fabric_count = 0

    for prod in products:
        # Prefer gpt_parsed (enriched) if present, fallback to prod["aggregated"]
        agg = {}
        if prod.get("gpt_parsed"):
            used_gpt += 1
            gp = prod.get("gpt_parsed") or {}
            agg = {
                "colors": gp.get("colors", []),
                "fabrics": gp.get("fabrics", []),
                "prints": gp.get("prints_patterns", []),
                "garment_type": gp.get("garment_type", []),
                "silhouette": gp.get("silhouette"),
                "sleeves": gp.get("sleeves"),
                "neckline": gp.get("neckline"),
                "style_fit": gp.get("style_fit", []),
                "length": gp.get("length"),
                "images_count": (prod.get("vision_summary") or {}).get("images_count") or (prod.get("aggregated") or {}).get("images_count", 1),
                "garment_type_confidence": (gp.get("garment_type_confidence") or (prod.get("aggregated") or {}).get("garment_type_confidence"))
            }
        else:
            used_agg += 1
            agg = prod.get("aggregated", {}) or {}

        # map colors
        raw_colors = agg.get("colors") or agg.get("colors_list") or []
        mapped_colors = map_color_list(raw_colors)
        for c in mapped_colors:
            # only count named canonical colors, not hex tokens
            if c and not c.startswith("#"):
                color_counter[c] += 1
            else:
                # keep hex tokens for traceability but don't increment canonical counter
                pass
        if not mapped_colors:
            unknown_color_count += 1

        # fabrics
        raw_fabs = agg.get("fabrics") or []
        mapped_fabrics = map_generic_list(raw_fabs, FABRIC_SYNONYMS, CANON_FABRICS)
        for f in mapped_fabrics:
            fabric_counter[f] += 1
        if not mapped_fabrics:
            unknown_fabric_count += 1

        # prints
        raw_pr = agg.get("prints") or agg.get("prints_patterns") or []
        mapped_prints = map_generic_list(raw_pr, PRINT_SYNONYMS, CANON_PRINTS)

        # garment type
        raw_gt = agg.get("garment_type") or ""
        if isinstance(raw_gt, list):
            raw_gt = raw_gt[0] if raw_gt else ""
        gt_mapped = map_generic_list([raw_gt], GARMENT_SYNONYMS, CANON_GARMENT_TYPES)
        gt_choice = gt_mapped[0] if gt_mapped else "unknown"
        if gt_choice != "unknown":
            garment_counter[gt_choice] += 1

        # silhouette, sleeves, neckline, style_fit, length
        sil = agg.get("silhouette") or ""
        sil_m = map_generic_list([sil], SILHOUETTE_SYNONYMS, CANON_SILHOUETTES)
        sil_choice = sil_m[0] if sil_m else "unknown"

        sleeves = agg.get("sleeves") or ""
        sleeves_m = map_generic_list([sleeves], SLEEVE_SYNONYMS, CANON_SLEEVES)
        sleeves_choice = sleeves_m[0] if sleeves_m else "unknown"

        neck = agg.get("neckline") or ""
        neck_m = map_generic_list([neck], NECK_SYNONYMS, CANON_NECKLINES)
        neck_choice = neck_m[0] if neck_m else "unknown"

        style = agg.get("style_fit") or []
        style_m = map_generic_list(style, STYLE_SYNONYMS, CANON_STYLE_FIT)

        length = agg.get("length") or ""
        length_m = map_generic_list([length], LENGTH_SYNONYMS, CANON_LENGTHS)
        length_choice = length_m[0] if length_m else "unknown"

        # Garment-type aware cleanup rules
        gtc = (gt_choice or "").lower()
        if gtc in CLEANUP_RULES:
            rules = CLEANUP_RULES[gtc]
            if "length" in rules:
                length_choice = rules["length"]
            if "sleeves" in rules:
                sleeves_choice = rules["sleeves"]
            if "neckline" in rules:
                neck_choice = rules["neckline"]

        # Build final product object
        final_obj = {
            "group_key": prod.get("group_key") or prod.get("product_url"),
            "product_url": prod.get("product_url") or prod.get("page_url"),
            "image_urls": prod.get("vision_summary", {}).get("images", []) or prod.get("image_candidates", []) or prod.get("image_urls", []),
            "example_title": prod.get("product_title") or prod.get("example_title") or (prod.get("_meta_raw") or {}).get("ld_name") or "",
            "aggregated": {
                "colors": mapped_colors,
                "fabrics": mapped_fabrics,
                "prints": mapped_prints,
                "garment_type": gt_choice,
                "garment_type_confidence": agg.get("garment_type_confidence"),
                "silhouette": sil_choice,
                "sleeves": sleeves_choice,
                "neckline": neck_choice,
                "style_fit": style_m,
                "length": length_choice,
                "images_count": agg.get("images_count", 1)
            }
        }
        final.append(final_obj)

    # write out
    outp = Path(output_path)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")

    # print summary
    print("Wrote", output_path)
    print(f"Total products processed: {len(products)}")
    print(f"Used gpt_parsed: {used_gpt}, used aggregated fallback: {used_agg}")
    print("Top colors:", color_counter.most_common(20))
    print("Top fabrics:", fabric_counter.most_common(20))
    print("Top garment types:", garment_counter.most_common(20))
    print(f"Products with no mapped colors: {unknown_color_count}")
    print(f"Products with no mapped fabrics: {unknown_fabric_count}")

if __name__ == "__main__":
    process_products()
