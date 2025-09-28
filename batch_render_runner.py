#!/usr/bin/env python3
"""
batch_render_runner.py

Run image renders for items in output/render_plan.json
Supports: Azure DALL·E 3 or Google Gemini (Nano Banana).

Usage examples:
  python batch_render_runner.py --adapter gemini --limit 10 --skip-existing
  python batch_render_runner.py --adapter dalle  --limit 5  --variant flatlay
"""
import os
import json
import argparse
import base64
import time
import random
from pathlib import Path

# optional imports
try:
    import requests
except Exception:
    requests = None

try:
    from PIL import Image
except Exception:
    Image = None

# Gemini SDK (google-generativeai)
try:
    import google.generativeai as genai
except Exception:
    genai = None

# ---- ENV Vars ----
AZ_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZ_KEY = os.getenv("AZURE_OPENAI_KEY")
AZ_DEPLOY = os.getenv("AZURE_OPENAI_DALLE_DEPLOYMENT")  # e.g. "dall-e-3"
AZ_VERSION = "2024-12-01-preview"

GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# Files
IN_FILE = Path("output/render_plan.json")
OUT_DIR = Path("renders")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Default generation config
DEFAULT_SIZE = "1024x1024"
DEFAULT_N = 1
DEFAULT_TEMPERATURE = 0.0
DEFAULT_CANDIDATE_COUNT = 1
COOLDOWN = 0.6  # seconds between calls

# ---------------- Helpers ----------------
def load_plan():
    if not IN_FILE.exists():
        raise FileNotFoundError(f"Render plan not found: {IN_FILE}")
    return json.load(open(IN_FILE, encoding="utf-8"))

def normalize_item_out_file(item):
    did = item.get("design_id") or item.get("title", "unnamed").replace(" ", "_")[:40]
    variant = item.get("variant", "flatlay")
    # always save flat under renders/
    ext = ".png"
    out_path = OUT_DIR / f"{did}__{variant}{ext}"
    item["out_file"] = str(out_path)
    item.setdefault("size", DEFAULT_SIZE)
    item.setdefault("n", DEFAULT_N)
    item.setdefault("temperature", DEFAULT_TEMPERATURE)
    item.setdefault("candidate_count", DEFAULT_CANDIDATE_COUNT)
    return item

# ---------------- Azure DALL·E adapter ----------------
def render_dalle(item):
    if requests is None:
        raise RuntimeError("requests library required for DALL·E adapter")
    if not (AZ_ENDPOINT and AZ_KEY and AZ_DEPLOY):
        raise RuntimeError("AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY, AZURE_OPENAI_DALLE_DEPLOYMENT must be set for DALL·E")
    url = f"{AZ_ENDPOINT.rstrip('/')}/openai/deployments/{AZ_DEPLOY}/images/generations?api-version={AZ_VERSION}"
    headers = {"api-key": AZ_KEY, "Content-Type": "application/json"}
    body = {"prompt": item["prompt"], "size": item.get("size", DEFAULT_SIZE), "n": item.get("n", DEFAULT_N)}
    resp = requests.post(url, headers=headers, json=body, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    out_paths = []
    for i, d in enumerate(data.get("data", []) or []):
        b64 = d.get("b64_json")
        if not b64:
            continue
        img_bytes = base64.b64decode(b64)
        # if multiple images, append index
        if item.get("n", 1) > 1:
            stem, ext = item["out_file"].rsplit(".", 1)
            out_file = f"{stem}_{i}.{ext}"
        else:
            out_file = item["out_file"]
        Path(out_file).parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "wb") as f:
            f.write(img_bytes)
        out_paths.append(out_file)
    # try normalize via Pillow to PNG
    normalized = []
    for p in out_paths:
        normalized.append(_try_normalize_png(p))
    return normalized or out_paths

# ---------------- Gemini adapter ----------------
def init_gemini():
    if genai is None:
        raise RuntimeError("google-generativeai not installed (pip install google-generativeai)")
    if not GEMINI_KEY:
        raise RuntimeError("GEMINI_API_KEY not set in environment")
    genai.configure(api_key=GEMINI_KEY)
    # recommended image model; adjust if required
    return genai.GenerativeModel("gemini-2.5-flash-image-preview")

def _extract_image_from_gemini_resp(resp):
    """
    Resp parsing is defensive — handles several SDK shapes:
    - resp.candidates -> candidate.content.parts[*].inline_data.data (bytes or base64)
    - candidate.content.parts[*].text with data URI
    - candidate.text that starts with data:image...
    """
    images = []
    # try candidates structure
    for cand in getattr(resp, "candidates", []) or []:
        content = getattr(cand, "content", None)
        # if content has 'parts' and each part maybe dict-like or object-like
        parts = None
        if isinstance(content, dict):
            parts = content.get("parts", [])
        elif hasattr(content, "parts"):
            parts = content.parts
        if parts:
            for part in parts:
                # object-like inline_data
                inline_data = getattr(part, "inline_data", None)
                if inline_data and getattr(inline_data, "data", None):
                    data = getattr(inline_data, "data")
                    images.append((data, getattr(inline_data, "mime_type", "image/png")))
                    continue
                # dict-like part
                if isinstance(part, dict):
                    idata = part.get("inline_data") or part.get("image") or {}
                    if isinstance(idata, dict) and idata.get("data"):
                        images.append((idata.get("data"), idata.get("mime_type", "image/png")))
                        continue
                    # sometimes text contains data URI
                    txt = part.get("text") or ""
                    if isinstance(txt, str) and txt.strip().startswith("data:image"):
                        b64 = txt.split(",", 1)[1]
                        images.append((b64, "image/png"))
                        continue
                # object-like part with text attr
                txt = getattr(part, "text", None)
                if isinstance(txt, str) and txt.strip().startswith("data:image"):
                    images.append((txt.split(",",1)[1], "image/png"))
    # fallback: candidate top-level text
    if not images:
        for cand in getattr(resp, "candidates", []) or []:
            text = getattr(cand, "content", None)
            if isinstance(text, str) and text.strip().startswith("data:image"):
                images.append((text.split(",",1)[1], "image/png"))
    return images

def render_gemini(item, model):
    prompt = item["prompt"]
    gen_conf = {"temperature": float(item.get("temperature", DEFAULT_TEMPERATURE)),
                "candidate_count": int(item.get("candidate_count", DEFAULT_CANDIDATE_COUNT))}
    resp = model.generate_content(prompt, generation_config=gen_conf)
    images = _extract_image_from_gemini_resp(resp)
    if not images:
        # sometimes the response contains a 'text' with URL or base64 - try to read
        raise RuntimeError("No image data returned from Gemini.")
    # write first image
    data, mime_type = images[0]
    # data could be bytes or base64 string
    if isinstance(data, (bytes, bytearray)):
        img_bytes = data
    else:
        img_bytes = base64.b64decode(data)
    # extension from mime
    ext = ".png"
    if "jpeg" in mime_type or "jpg" in mime_type:
        ext = ".jpg"
    elif "webp" in mime_type:
        ext = ".webp"
    out_name = str(Path(item["out_file"]).with_suffix(ext))
    Path(out_name).parent.mkdir(parents=True, exist_ok=True)
    with open(out_name, "wb") as f:
        f.write(img_bytes)
    # try normalize to PNG
    normalized = _try_normalize_png(out_name)
    return [normalized or out_name]

def _try_normalize_png(path):
    """Try to open & re-save as PNG with Pillow. Returns normalized path (string) or None."""
    if Image is None:
        return None
    try:
        im = Image.open(path).convert("RGBA")
        normalized_path = str(Path(path).with_suffix(".png"))
        im.save(normalized_path, format="PNG")
        if normalized_path != str(path):
            try:
                Path(path).unlink()
            except Exception:
                pass
        return normalized_path
    except Exception:
        return None

# ---------------- Main ----------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", choices=["dalle", "gemini"], required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--variant", type=str, default=None)
    parser.add_argument("--start", type=int, default=0, help="start index in plan (0-based)")
    parser.add_argument("--cooldown", type=float, default=COOLDOWN)
    args = parser.parse_args()

    if args.adapter == "dalle" and (not AZ_ENDPOINT or not AZ_KEY or not AZ_DEPLOY):
        raise RuntimeError("Azure DALL·E requires AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY and AZURE_OPENAI_DALLE_DEPLOYMENT env vars.")
    if args.adapter == "gemini" and not GEMINI_KEY:
        raise RuntimeError("Gemini adapter requires GEMINI_API_KEY env var.")

    plan = load_plan()
    if args.variant:
        plan = [p for p in plan if p.get("variant") == args.variant]
    total = len(plan)
    if args.seed is not None:
        random.seed(args.seed)

    # optionally shuffle to pick random entries
    random.shuffle(plan)

    # apply start/limit
    plan = plan[args.start: (args.start + args.limit) if args.limit else None]
    print(f"Plan entries to process: {len(plan)} / total {total}")

    # normalize out_file and defaults and optionally skip existing
    selected = []
    for it in plan:
        normalize_item_out_file(it)
        if args.skip_existing and Path(it["out_file"]).exists():
            continue
        selected.append(it)

    if not selected:
        print("No items to process after filters.")
        return

    # init model if needed
    model = None
    if args.adapter == "gemini":
        model = init_gemini()

    for idx, item in enumerate(selected, start=1):
        print(f"[{idx}/{len(selected)}] {item.get('design_id')} -> {args.adapter}")
        try:
            if args.adapter == "dalle":
                paths = render_dalle(item)
            else:
                paths = render_gemini(item, model)
            print("  Saved:", paths)
        except Exception as e:
            print("  ERROR:", e)
        time.sleep(args.cooldown)

if __name__ == "__main__":
    main()
