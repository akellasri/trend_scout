#!/usr/bin/env python3
"""
agent3_virtual_showcase_demo.py

Demo: take apparel design JSON(s) and generate a model showcase image.
Supports model attribute overrides (gender, age_range, body_type, skin_tone, pose).

Usage:
  # single design with default model attributes
  GEMINI_API_KEY="..." python agent3_virtual_showcase_demo.py --design output/agent2_designs/ALD001.design.json

  # random from directory with overrides from JSON
  GEMINI_API_KEY="..." python agent3_virtual_showcase_demo.py --input-dir output/agent2_designs --limit 3 \
      --model-attrs '{"gender":"female","age_range":"25-32","body_type":"curvy","skin_tone":"medium-dark","pose":"standing, hand on hip"}'

  # or use separate flags
  GEMINI_API_KEY="..." python agent3_virtual_showcase_demo.py --design output/agent2_designs/ALD001.design.json \
      --gender female --body_type athletic --pose "standing natural fashion pose"
"""

import os
import json
import argparse
import random
import base64
from pathlib import Path
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

# import gemini wrapper with graceful fallback (works across SDK variants)
try:
    from google import genai
except Exception:
    raise SystemExit("Install/enable google-generativeai (pip install google-generativeai) and set GEMINI_API_KEY")

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise SystemExit("Set GEMINI_API_KEY in environment")

# try to construct client or fallback
try:
    client = genai.Client()
except Exception:
    client = genai
# Some SDK variants require genai.configure
try:
    genai.configure(api_key=API_KEY)
except Exception:
    pass

# Model to use for image generation
MODEL_NAME = "gemini-2.5-flash-image-preview"

# Prompt template for image showcase (we will inject model attributes)
PROMPT_TEMPLATE = """
Generate a photorealistic studio image of a fashion model wearing the garment described below.

Model attributes:
- Gender: {gender}
- Age range: {age_range}
- Body type: {body_type}
- Skin tone: {skin_tone}
- Pose / action: {pose}
- Framing: {framing}

Design summary:
{design_summary}

Requirements:
- Preserve fabric texture, stitching, trims and colors exactly.
- Natural lighting, neutral studio background (white/gray) or transparent background if requested.
- No logos or text overlays.
- Output: high-resolution image (PNG) of the model wearing the garment.
"""

def design_to_summary(d: dict) -> str:
    parts = []
    title = d.get("title") or d.get("design_id") or "Untitled"
    parts.append(f"Title: {title}")
    palette = d.get("color_palette") or d.get("colors") or []
    if palette: parts.append("Colors: " + ", ".join(palette))
    fabrics = d.get("fabrics") or []
    if fabrics: parts.append("Fabrics: " + ", ".join(fabrics))
    garment = d.get("garment_type") or d.get("garment") or ""
    if garment: parts.append("Garment: " + garment)
    silhouette = d.get("silhouette") or d.get("style_fit") or ""
    if silhouette: parts.append("Silhouette: " + (silhouette if isinstance(silhouette, str) else ", ".join(silhouette)))
    if d.get("sleeves"): parts.append("Sleeves: " + d.get("sleeves"))
    if d.get("neckline"): parts.append("Neckline: " + d.get("neckline"))
    if d.get("prints_patterns"): parts.append("Prints: " + ", ".join(d.get("prints_patterns")))
    tech = d.get("techpack") or d.get("image_prompt")
    if tech: parts.append("Notes: " + (str(tech)[:400]))
    return ". ".join(parts)

def build_prompt(summary: str, model_attrs: dict) -> str:
    # framing: default full-body studio shot
    framing = model_attrs.get("framing") or "full-body, studio frame, no close-ups"
    return PROMPT_TEMPLATE.format(
        gender=model_attrs.get("gender", "female"),
        age_range=model_attrs.get("age_range", "25-32"),
        body_type=model_attrs.get("body_type", "slim"),
        skin_tone=model_attrs.get("skin_tone", "medium"),
        pose=model_attrs.get("pose", "standing, natural fashion pose"),
        framing=framing,
        design_summary=summary
    )

def showcase_from_design_file(design_file: Path, model_attrs: dict, out_dir: Path):
    d = json.loads(design_file.read_text(encoding="utf-8"))
    design_id = d.get("design_id") or design_file.stem
    summary = design_to_summary(d)
    prompt = build_prompt(summary, model_attrs)

    # Save storyboard / prompt for traceability
    out_dir.mkdir(parents=True, exist_ok=True)
    storyboard = out_dir / f"{design_id}_storyboard.txt"
    storyboard.write_text(prompt, encoding="utf-8")

    # Call Gemini image generate (generate_content shape)
    print(f"-> Generating showcase for {design_id} with attributes {model_attrs}")
    try:
        resp = client.models.generate_content(model=MODEL_NAME, prompt=prompt, generation_config={"temperature": 0.0, "candidate_count": 1})
    except Exception:
        # fallback: some SDK variants expose generate_content directly on genai
        resp = client.generate_content(prompt)

    # Extract image bytes from response in a few common shapes
    img_bytes = None
    mime = "image/png"
    try:
        for cand in getattr(resp, "candidates", []) or []:
            for part in getattr(cand, "content", {}).get("parts", []) if hasattr(cand, "content") else getattr(cand, "content", []):
                inline = getattr(part, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    raw = inline.data
                    mime = getattr(inline, "mime_type", mime)
                    img_bytes = raw if isinstance(raw, (bytes, bytearray)) else base64.b64decode(raw)
                    break
            if img_bytes:
                break
    except Exception:
        # try different shape: resp.candidates[0].content[0].binary or resp.image or resp.output
        # attempt to find any bytes-like payload
        try:
            # sometimes resp.output is bytes
            if hasattr(resp, "output") and isinstance(resp.output, (bytes, bytearray)):
                img_bytes = resp.output
        except Exception:
            pass

    if not img_bytes:
        raise RuntimeError("No image returned from Gemini for showcase. Inspect response object.")

    # Write file
    out_file = out_dir / f"{design_id}_showcase.png"
    out_file.write_bytes(img_bytes)

    # Normalize via PIL (optional)
    try:
        img = Image.open(out_file)
        img.save(out_file, format="PNG")
    except Exception as e:
        print("⚠️ Pillow normalization skipped:", e)

    print(f"✅ Saved showcase image: {out_file} ({len(img_bytes)} bytes)")
    return str(out_file)

def parse_model_attrs(args):
    # order of precedence: JSON string -> individual flags -> defaults
    attrs = {}
    if args.model_attrs:
        try:
            attrs = json.loads(args.model_attrs)
        except Exception:
            print("Warning: failed to parse --model-attrs JSON, ignoring.")
            attrs = {}
    # individual flags override
    for k in ("gender", "age_range", "body_type", "skin_tone", "pose", "framing"):
        v = getattr(args, k, None)
        if v:
            attrs[k] = v
    # defaults
    defaults = {
        "gender": "female",
        "age_range": "25-32",
        "body_type": "slim",
        "skin_tone": "medium-dark",
        "pose": "standing, natural fashion pose",
        "framing": "full-body, studio frame, no close-ups"
    }
    for k, dv in defaults.items():
        attrs.setdefault(k, dv)
    return attrs

def find_design_files(path: Path):
    if path.is_file():
        return [path]
    files = sorted([p for p in path.iterdir() if p.is_file() and p.suffix == ".json" and "design" in p.name.lower()])
    return files

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--design", type=str, help="single design JSON file")
    parser.add_argument("--input-dir", type=str, default="output/agent2_designs", help="directory of design JSONs")
    parser.add_argument("--limit", type=int, default=1, help="how many random showcases to generate")
    parser.add_argument("--seed", type=int, default=None, help="seed for reproducible randomness")
    parser.add_argument("--model-attrs", type=str, help="JSON string with model attributes")
    # also accept individual overrides
    parser.add_argument("--gender", type=str)
    parser.add_argument("--age_range", type=str)
    parser.add_argument("--body_type", type=str)
    parser.add_argument("--skin_tone", type=str)
    parser.add_argument("--pose", type=str)
    parser.add_argument("--framing", type=str)
    parser.add_argument("--out-dir", type=str, default="output")
    args = parser.parse_args()

    if args.design:
        files = find_design_files(Path(args.design))
    else:
        files = find_design_files(Path(args.input_dir))
        if args.seed is not None:
            random.seed(args.seed)
        random.shuffle(files)
        files = files[: args.limit]

    model_attrs = parse_model_attrs(args)
    out_dir = Path(args.out_dir)
    print(f"Found {len(files)} designs to showcase. Using model_attrs={model_attrs}")

    for f in files:
        try:
            showcase_from_design_file(f, model_attrs, out_dir)
        except Exception as e:
            print(f"Failed for {f.name}: {e}")

if __name__ == "__main__":
    main()
