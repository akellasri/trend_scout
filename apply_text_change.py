#!/usr/bin/env python3
# apply_text_change.py
"""
Apply a plain-language change to a base design JSON by calling Azure GPT (gpt-5-chat).
Returns a strict JSON object (or falls back to modified base if parsing fails).
Also injects/refreshes a `design_text` field for human-readable display.
"""
import os
import sys
import json
import re
import uuid
import requests
from pathlib import Path

AZ_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZ_KEY = os.getenv("AZURE_OPENAI_KEY")
AZ_DEPLOY = os.getenv("AZURE_OPENAI_DEPLOYMENT")
API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")

if not AZ_ENDPOINT or not AZ_KEY or not AZ_DEPLOY:
    print("Error: Set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY, AZURE_OPENAI_DEPLOYMENT in environment.")
    sys.exit(1)

CHAT_URL = f"{AZ_ENDPOINT.rstrip('/')}/openai/deployments/{AZ_DEPLOY}/chat/completions?api-version={API_VERSION}"
HEADERS = {"Content-Type": "application/json", "api-key": AZ_KEY}

SYSTEM_PROMPT = """
You are a professional fashion product designer assistant.
You will be given a BASE design JSON and a USER CHANGE instruction in plain text.
Return ONLY a single JSON object (no extra commentary) that is the UPDATED design JSON.
The JSON must include the following keys:
- design_id (string), title (string), image_prompt (string),
- color_palette (list of strings), fabrics (list), prints_patterns (list),
- garment_type (string), silhouette (string), sleeves (string), neckline (string),
- length (string), style_fit (list), trims_and_details (list),
- techpack (string), provenance (string)

If a field cannot be determined from the change or base, put "unknown" for strings and [] for lists.
Keep values short and canonical (e.g., "linen", "V-neck", "puff sleeves").
Do not output anything besides the JSON object.
"""

def extract_json_from_text(text):
    if not text or not isinstance(text, str):
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = text[start:end+1]
    try:
        return json.loads(candidate)
    except Exception:
        try:
            import ast
            return ast.literal_eval(candidate)
        except Exception:
            return None

def normalize_choice_content(choice):
    try:
        msg = choice.get("message") or {}
    except Exception:
        msg = {}
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [blk.get("text") for blk in content if isinstance(blk, dict) and blk.get("text")]
        if texts: return "\n".join(texts)
    return json.dumps(choice)

def summarize_design(d: dict) -> str:
    """Generate human-readable summary (design_text)."""
    parts = []
    parts.append(f"{d.get('title','Untitled')} ({d.get('design_id','?')})")
    if d.get("color_palette"): parts.append("Colors: " + ", ".join(d["color_palette"]))
    if d.get("fabrics"): parts.append("Fabrics: " + ", ".join(d["fabrics"]))
    if d.get("prints_patterns"): parts.append("Prints: " + ", ".join(d["prints_patterns"]))
    if d.get("garment_type"): parts.append(f"Garment: {d['garment_type']}")
    if d.get("silhouette"): parts.append(f"Silhouette: {d['silhouette']}")
    if d.get("sleeves"): parts.append(f"Sleeves: {d['sleeves']}")
    if d.get("neckline"): parts.append(f"Neckline: {d['neckline']}")
    if d.get("length"): parts.append(f"Length: {d['length']}")
    if d.get("style_fit"): parts.append("Style/Fit: " + ", ".join(d["style_fit"]))
    if d.get("trims_and_details"): parts.append("Trims: " + ", ".join(d["trims_and_details"]))
    return " ".join(parts)

def apply_change(base_design: dict, user_change: str, temperature=0.0):
    base_text = json.dumps(base_design, ensure_ascii=False, indent=2)
    user_message = (
        "BASE_DESIGN_JSON:\n" + base_text + "\n\n"
        "USER_CHANGE_INSTRUCTION:\n" + user_change + "\n\n"
        "Return the full updated design JSON (one JSON object)."
    )
    body = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ],
        "temperature": temperature,
        "max_tokens": 1200,
        "n": 1
    }

    r = requests.post(CHAT_URL, headers=HEADERS, json=body, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Azure API error {r.status_code}: {r.text}")

    data = r.json()
    content_text = None
    try:
        choice = data["choices"][0]
        content_text = normalize_choice_content(choice)
    except Exception:
        content_text = json.dumps(data)

    parsed = extract_json_from_text(content_text)
    if parsed is None:
        print("WARNING: GPT did not return parseable JSON. Returning modified base with provenance.")
        base_copy = dict(base_design)
        base_copy["provenance"] = f"failed_to_parse_gpt_output; user_change={user_change}"
        base_copy["design_text"] = summarize_design(base_copy)
        return base_copy

    if not parsed.get("design_id"):
        parsed["design_id"] = base_design.get("design_id") or str(uuid.uuid4())[:8]

    # always inject/refresh design_text
    parsed["design_text"] = summarize_design(parsed)
    return parsed

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python apply_text_change.py path/to/base.design.json \"change text...\"")
        sys.exit(1)

    base_path = Path(sys.argv[1])
    change_text = sys.argv[2]

    if not base_path.exists():
        print("Base design file not found:", base_path)
        sys.exit(1)

    base = json.loads(open(base_path, encoding="utf-8").read())
    updated = apply_change(base, change_text)

    # Strip redundant ".design" if present in stem
    stem = base_path.stem
    if stem.endswith(".design"):
        stem = stem[:-7]  # remove ".design"

    out = base_path.with_name(f"{stem}.modified.design.json")
    out.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Wrote:", out)
