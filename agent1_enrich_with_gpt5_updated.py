#!/usr/bin/env python3
"""
enrich_with_gpt5.py

Reads:  output/analysis_results_updated.json
Writes: output/analysis_results_enriched.json

For each product entry (vision results) it:
 - builds a compact vision_summary
 - calls Azure OpenAI / gpt-5-chat with a strict system prompt
 - parses JSON response (robust)
 - saves both raw text and parsed json

Usage:
  export AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY, AZURE_OPENAI_DEPLOYMENT
  python enrich_with_gpt5.py
"""
import os
import json
import time
import re
import requests
from pathlib import Path
from typing import Any, Dict, List

# ---------- Config ----------
INPUT = Path(os.environ.get("ANALYSIS_INPUT", "output/analysis_results_updated.json"))
OUT = Path(os.environ.get("ANALYSIS_OUTPUT", "output/analysis_results_enriched_updated.json"))
DEPLOY = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5-chat")
OPENAI_BASE = os.environ.get("AZURE_OPENAI_ENDPOINT")
OPENAI_KEY = os.environ.get("AZURE_OPENAI_KEY")
API_VER = "2024-12-01-preview"

# Safety/throughput
BATCH_SIZE = 1188       # how many products to process in one run (tune smaller for pilot)
SLEEP_BETWEEN = 0.25  # seconds between calls (polite)
RETRIES = 2
TIMEOUT = 60

if not OPENAI_BASE or not OPENAI_KEY:
    raise SystemExit("Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY env vars before running.")

API_URL = OPENAI_BASE.rstrip("/") + f"/openai/deployments/{DEPLOY}/chat/completions?api-version={API_VER}"
HEADERS = {"Content-Type": "application/json", "api-key": OPENAI_KEY}

# ---------- System prompt (strict) ----------
SYSTEM_PROMPT = r"""
You are a strict, conservative fashion analysis assistant. Return EXACTLY one JSON object (no surrounding text) following the schema below.

Rules:
- Only return a single JSON object. No prose, no markdown, no commentary.
- If you cannot determine a value, use "unknown" for strings and [] for arrays.
- Use the canonical tokens in the taxonomy (exact spellings).
- Keep values short. `image_description` may be one short sentence.
- Output must be parseable by json.loads().

TAXONOMY (canonical terms, examples):
COLORS: lavender, baby pink, sage green, beige, cream, white, grey, olive, brown, rust, black, navy, maroon, red, pink, blue, green, yellow, orange, purple, teal, burgundy, mustard, mint, emerald, powder blue, dusty pink, blush, pastel, ivory, gold, silver, metallic
FABRICS: cotton, linen, denim, hemp, bamboo, recycled, knit, crochet, silk, satin, chiffon, velvet, lace, wool, rayon, organza, crepe, khadi, tussar, tussar silk, raw silk, banarasi, banarasi silk, brocade, chikankari, handloom, woven, net, georgette, viscose, modal, muslin, twill
PRINTS/PATTERNS: florals, solids / minimalist, logos & slogan, stripes, checks, paisley, geometric, polka dot, leaf motif, tie-dye, abstract, bandhani, ikat, kalamkari, gingham, block print, digital print, painterly, batik, mirror work, embroidery, mirrorwork
NECKLINES: V-neck, Halter, Crew neck, Off-shoulder, Square neck, Collared, Cowl neck, Asymmetrical/One-shoulder, Sweetheart neck, round neck, boat neck, high neck, mock neck, keyhole neck
SLEEVES: Puff sleeves, Balloon sleeves, Oversized sleeves, Sleeveless/Tank, 3/4th sleeves, Full sleeves, Cap sleeves, short sleeve, elbow sleeve, bishop sleeve, ruffle sleeve, kimono sleeve, bell sleeve, flared sleeve, dolman sleeve, petal sleeve, cold shoulder
SILHOUETTES / STYLE_FIT: Oversized/Baggy, Bodycon/Fitted, Draped/Flowing, Cropped Tops, Baggy pants/Cargo, Jumpsuits/Coord sets, Tailored, A-line, Fit-and-flare, wrap dress, sheath, anarkali, sherwani, cape, slip dress, layered, asymmetric
LENGTHS: Mini, Midi, Maxi, Cropped, Ankle-length, Knee-length, Full-length
GARMENT_TYPE: dress, kurta, shirt, top, trouser, pants, skirt, jacket, coat, blouse, sari, saree, lehenga, kurta-set, outfit, gown, coord set, jumpsuit, palazzo, robe, tunics, saree-blouse,
anarkali, sherwani, shrug, culotte, shirt dress, wrap dress

SCHEMA (must return these keys exactly):
{
  "image_description": string,
  "colors": [string],
  "fabrics": [string],
  "prints_patterns": [string],
  "garment_type": [string],
  "silhouette": string,
  "sleeves": string,
  "neckline": string,
  "style_fit": [string],
  "length": string
}
"""

# ---------- Helpers ----------
def compact_vision_summary(vision_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a concise vision summary for GPT from your vision results per product"""
    colors = []
    tags = []
    objects = []
    captions = []
    per_garment = []
    for v in vision_results:
        az = v.get("azure_image_analysis", {})
        # colors: gather dominantColors and accentColor
        c = az.get("color") or {}
        doms = c.get("dominantColors") if isinstance(c.get("dominantColors"), list) else []
        for d in doms:
            if d and d.lower() not in [x.lower() for x in colors]:
                colors.append(d.lower())
        if c.get("accentColor"):
            acc = c.get("accentColor")
            if acc and acc not in colors:
                colors.append(acc)
        # tags: top tag names with confidence
        for t in az.get("tags") or []:
            name = t.get("name")
            conf = t.get("confidence")
            if name:
                tags.append({"name": name, "confidence": conf})
        # description
        desc = az.get("description") or {}
        for cap in desc.get("captions", []) or []:
            if cap.get("text"):
                captions.append({"text": cap.get("text"), "confidence": cap.get("confidence")})
        # objects & per_garment crops
        for o in v.get("per_garment", []) or []:
            per_garment.append({
                "label": o.get("label"),
                "confidence": o.get("confidence"),
                "rectangle": o.get("rectangle"),
                "crop_color": (o.get("crop_analysis") or {}).get("color"),
                "crop_tags": (o.get("crop_analysis") or {}).get("tags")
            })
        for o in az.get("objects") or []:
            objects.append({"object": o.get("object"), "confidence": o.get("confidence"), "rectangle": o.get("rectangle")})
    return {
        "colors_raw": colors,
        "tags": tags,
        "captions": captions,
        "objects": objects,
        "per_garment": per_garment
    }

def make_user_message(product_url: str, vision_summary: Dict[str,Any], title: str="", description: str="") -> str:
    return (
        f"Product URL: {product_url}\n"
        f"Title: {title}\n"
        f"Description: {description}\n\n"
        f"VISION_SUMMARY: {json.dumps(vision_summary, ensure_ascii=False)}\n\n"
        "Return exactly the JSON object described in the system prompt. If unsure, set values to \"unknown\" or []."
    )

def extract_first_json_block(text: str) -> Any:
    """Return python object parsed from first {...} JSON block in text."""
    if not text or "{" not in text:
        raise ValueError("No JSON object found in model output.")
    m = re.search(r"(\{[\s\S]*\})", text)
    if not m:
        raise ValueError("No JSON block match.")
    block = m.group(1)
    # try to fix common trailing commas etc.
    # simple cleanup - remove control chars
    block = re.sub(r"[\x00-\x1f]", " ", block)
    # attempt to parse; if fails we'll raise
    return json.loads(block)

def call_gpt(system: str, user: str) -> Dict[str, Any]:
    payload = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ],
        "temperature": 0.0,
        "max_tokens": 800
    }
    for attempt in range(1, RETRIES + 2):
        try:
            r = requests.post(API_URL, headers=HEADERS, json=payload, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt <= RETRIES:
                wait = 1.5 ** attempt
                time.sleep(wait)
                continue
            else:
                raise

# ---------- Main run ----------
def main():
    data = json.load(open(INPUT, encoding="utf-8"))
    out = []
    total = len(data)
    print(f"Loaded {total} products from {INPUT}")
    # do a pilot: process first BATCH_SIZE products. Adjust as needed.
    to_process = data[:BATCH_SIZE]

    for idx, prod in enumerate(to_process, 1):
        product_url = prod.get("product_url") or prod.get("page_url") or "unknown"
        vision_results = prod.get("vision_results") or []
        title = prod.get("title") or ""
        description = prod.get("description") or ""

        vision_summary = compact_vision_summary(vision_results)
        user_msg = make_user_message(product_url, vision_summary, title, description)

        record = {
            "product_url": product_url,
            "vision_summary": vision_summary,
            "gpt_raw": None,
            "gpt_parsed": None,
            "error": None
        }

        try:
            resp = call_gpt(SYSTEM_PROMPT, user_msg)
            # Azure response structure: choices[0].message.content
            content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
            record["gpt_raw"] = content
            try:
                parsed = extract_first_json_block(content)
                record["gpt_parsed"] = parsed
            except Exception as pe:
                record["error"] = f"parse_error: {str(pe)}"
        except Exception as e:
            record["error"] = f"api_error: {str(e)}"

        out.append(record)
        print(f"[{idx}/{len(to_process)}] {product_url} -> parsed={'yes' if record['gpt_parsed'] else 'no'} error={record['error']}")
        time.sleep(SLEEP_BETWEEN)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("Wrote", OUT)

if __name__ == "__main__":
    main()
