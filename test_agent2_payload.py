#!/usr/bin/env python3
"""
test_agent2_payload.py (updated)

- Forces flat-lay / apparel-only constraints (no model/mannequin).
- Supports user_override_prompt in payload.user_content.
- Supports variants_count in payload.user_content to ask GPT for N variants.
- Adds a "design_text" summary field to each saved design JSON.
- Parses single JSON or JSON array responses and saves each variant separately.

Usage:
  python test_agent2_payload.py path/to/payload.json
"""
import os, sys, json, time, uuid, re
import requests
from pathlib import Path

AZ_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
AZ_KEY = os.environ.get("AZURE_OPENAI_KEY")
AZ_DEPLOY = os.environ.get("AZURE_OPENAI_DEPLOYMENT")  # e.g. "gpt-5-chat"
API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")

if not (AZ_ENDPOINT and AZ_KEY and AZ_DEPLOY):
    print("Missing one of AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY, AZURE_OPENAI_DEPLOYMENT in env.")
    sys.exit(1)

if len(sys.argv) < 2:
    print("Usage: python test_agent2_payload.py path/to/payload.json")
    sys.exit(1)

payload_path = Path(sys.argv[1])
if not payload_path.exists():
    print("Payload file not found:", payload_path)
    sys.exit(1)

payload = json.load(open(payload_path, encoding="utf-8"))

# Destination
out_dir = Path("output/agent2_designs")
out_dir.mkdir(parents=True, exist_ok=True)

# Build chat request for GPT-5-chat (Azure REST)
url = f"{AZ_ENDPOINT.rstrip('/')}/openai/deployments/{AZ_DEPLOY}/chat/completions?api-version={API_VERSION}"
headers = {
    "Content-Type": "application/json",
    "api-key": AZ_KEY
}

# Controls: how many variants to ask for (default 1)
user_content = payload.get("user_content", {}) or {}
variants_count = int(user_content.get("variants", 1) or 1)
# user_override_prompt (friend prompt) — optional
user_override_prompt = user_content.get("user_override_prompt") or user_content.get("image_prompt_override") or ""

# System prompt (default or from payload)
system_prompt = payload.get("system_prompt",
    "You are a fashion product design assistant. Respond ONLY with valid JSON (no extra explanation)."
)

# Strong constraint to force *flat-lay, apparel-only, no model* behavior
flatlay_constraint = (
    "IMPORTANT: The generated image prompts and any render instructions MUST produce an "
    "apparel-only flat-lay / product render. No model, no mannequin, no human, no body parts, "
    "no model poses, and no lifestyle scene. Output should be suitable for product pages: "
    "isolated garment on a plain white or transparent background, high-detail fabric texture, "
    "visible stitching and trims. Respond ONLY with JSON (or JSON array) and nothing else."
)

# Build user blocks (Azure multimodal style)
user_blocks = []
# Compose a clear instruction that requests EXACTLY N variants if variants_count > 1
variant_instruction = (
    f"Please output exactly {variants_count} distinct design variants as a JSON array. "
    "Each variant must be a JSON object with keys: design_id, title, image_prompt, color_palette, "
    "fabrics, prints_patterns, garment_type, silhouette, sleeves, neckline, length, style_fit, "
    "trims_and_details, techpack, provenance.\n\n"
    "If you cannot identify an attribute, use the string 'unknown' or an empty list []."
)

# Merge user_override_prompt but ensure the flatlay constraint appears first
merged_user_text = flatlay_constraint + "\n\n"
if user_override_prompt:
    merged_user_text += "User-specified prompt (merge this into the design, but keep flat-lay constraints):\n" + user_override_prompt.strip() + "\n\n"

# Add the main instruction and the provided payload user_content for context
merged_user_text += variant_instruction + "\n\nUser content (context JSON):\n" + json.dumps(user_content, ensure_ascii=False, indent=2)

user_blocks.append({"type": "text", "text": merged_user_text})

# attach example images if present
examples = user_content.get("examples") or []
for ex in examples:
    img = ex.get("image_url") or ex.get("image")
    if img:
        user_blocks.append({"type":"image_url", "image_url": {"url": img}})

messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": user_blocks}
]

body = {
    "messages": messages,
    "max_tokens": 1600,
    "temperature": 0.15,
    "top_p": 0.95,
    "n": 1
}

print("Sending request to Azure GPT-5-chat...")
resp = requests.post(url, headers=headers, json=body, timeout=180)

payload_id = payload.get("id") or payload_path.stem or str(uuid.uuid4())
raw_resp_file = out_dir / f"{payload_id}.response.json"

if resp.status_code != 200:
    print("Error:", resp.status_code, resp.text[:1000])
    raw_resp_file.write_text(json.dumps({"status": resp.status_code, "text": resp.text}, ensure_ascii=False, indent=2))
    sys.exit(1)

data = resp.json()
raw_resp_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
print("Saved raw response to:", raw_resp_file)

# ------------- helper: convert design JSON -> human text -------------
def design_to_text(d):
    lines = []
    lines.append(f"{d.get('title','Untitled')} ({d.get('design_id')})")
    cp = ", ".join(d.get("color_palette", []) or d.get("colors", [])) or "unknown"
    fabrics = ", ".join(d.get("fabrics", [])) or "unknown"
    prints = ", ".join(d.get("prints_patterns", [])) or "none"
    lines.append(f"Colors: {cp}")
    lines.append(f"Fabrics: {fabrics}")
    lines.append(f"Prints/Patterns: {prints}")
    lines.append(f"Garment Type: {d.get('garment_type','unknown')}")
    lines.append(f"Silhouette: {d.get('silhouette','unknown')}")
    lines.append(f"Sleeves: {d.get('sleeves','unknown')}")
    lines.append(f"Neckline: {d.get('neckline','unknown')}")
    lines.append(f"Length: {d.get('length','unknown')}")
    sf = ", ".join(d.get("style_fit", [])) or ""
    if sf: lines.append(f"Style / Fit: {sf}")
    trims = ", ".join(d.get("trims_and_details", [])) or ""
    if trims: lines.append(f"Trims & details: {trims}")
    if d.get("techpack"):
        lines.append("Techpack: available")
    return "\n".join(lines)

# ------------- extract text from varying Azure response shapes -------------
def extract_text_from_choice(choice):
    msg = choice.get("message") or choice.get("delta") or {}
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        tb = [b.get("text") for b in content if isinstance(b, dict) and b.get("type") == "text" and b.get("text")]
        if tb:
            return "\n\n".join(tb)
        return json.dumps(content, ensure_ascii=False)
    return json.dumps(msg, ensure_ascii=False)

try:
    choice = data.get("choices", [])[0]
    resp_text = extract_text_from_choice(choice)
    print("\n----- MODEL OUTPUT (preview) -----\n")
    print(resp_text[:1200])

    # find first JSON block in the model text (object or array)
    m = re.search(r"(\[?\s*\{[\s\S]*\}\s*\]?)", resp_text)
    parsed = None
    if m:
        text_json = m.group(1)
        try:
            parsed = json.loads(text_json)
        except Exception:
            # tidy trailing commas
            cleaned = re.sub(r",\s*}", "}", text_json)
            cleaned = re.sub(r",\s*]", "]", cleaned)
            try:
                parsed = json.loads(cleaned)
            except Exception:
                parsed = None

    if parsed is None:
        try:
            parsed = json.loads(resp_text.strip())
        except Exception:
            parsed = None

    if parsed is None:
        print("Could not parse JSON automatically. Inspect the raw response file:", raw_resp_file)
    else:
        # ensure list
        if isinstance(parsed, dict):
            parsed = [parsed]

        saved_files = []
        for idx, variant in enumerate(parsed, start=1):
            vid = variant.get("design_id") or f"{payload_id}__v{idx:02d}"
            # ensure canonical keys exist (avoid missing lists)
            for k in ["color_palette","fabrics","prints_patterns","style_fit","trims_and_details"]:
                if k not in variant or variant.get(k) is None:
                    variant[k] = [] if "list" not in k else variant.get(k, [])  # defensive

            # create design_text summary and inject
            try:
                summary = design_to_text(variant)
            except Exception:
                summary = variant.get("title", vid)
            variant["design_text"] = summary

            outfile = out_dir / f"{vid}.design.json"
            outfile.write_text(json.dumps(variant, ensure_ascii=False, indent=2))
            saved_files.append(str(outfile))

        print("Saved design JSON files:", saved_files)

except Exception as e:
    print("Failed to parse or extract model content:", e)
    print("Inspect raw:", raw_resp_file)

print("Done.")
