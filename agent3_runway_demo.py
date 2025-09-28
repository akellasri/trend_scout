#!/usr/bin/env python3
"""
agent3_runway_demo.py

Read design JSON(s) from agent2_designs and generate runway video(s) via Gemini Veo.
Supports model attributes (gender, age_range, body_type, skin_tone, pose) via CLI.

Usage:
  GEMINI_API_KEY="..." python agent3_runway_demo.py --input-dir output/agent2_designs --limit 2 \
      --model-attrs '{"gender":"female","body_type":"curvy","pose":"runway walk, slight turn"}'
"""
import os
import time
import json
import argparse
import random
from pathlib import Path

try:
    from google import genai
except Exception:
    raise SystemExit("Install google-generativeai (pip install google-generativeai) and set GEMINI_API_KEY")

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise SystemExit("Set GEMINI_API_KEY in env")

# client fallback pattern
try:
    client = genai.Client()
except Exception:
    client = genai

# ensure configure if available
try:
    genai.configure(api_key=API_KEY)
except Exception:
    pass

PROMPT_TEMPLATE = """
You are a fashion video director. Use the design summary below to:
1) produce a short 6-second storyboard describing camera framing, timing and moves (3-5 bullets).
2) then render a photorealistic 6-second runway video showing an Indian model wearing the design.

Model attributes:
- Gender: {gender}
- Age range: {age_range}
- Body type: {body_type}
- Skin tone: {skin_tone}
- Pose / action: {pose}

Design summary:
{design_summary}

Requirements for the video:
- Shots: Full-length runway shots only (no close-ups). 3–4 distinct moves (walk, turn, pose).
- Lighting: soft studio key + subtle rim, neutral background, no logos or text.
- Output: photorealistic MP4, duration ~6s.
"""

def design_to_summary(d: dict) -> str:
    parts = []
    title = d.get("title") or d.get("design_id") or "Untitled"
    parts.append(f"Title: {title}.")
    palette = d.get("color_palette") or d.get("colors") or []
    if palette: parts.append("Colors: " + ", ".join(palette) + ".")
    fabrics = d.get("fabrics") or []
    if fabrics: parts.append("Fabrics: " + ", ".join(fabrics) + ".")
    garment = d.get("garment_type") or d.get("garment") or ""
    if garment: parts.append("Garment: " + garment + ".")
    silhouette = d.get("silhouette") or d.get("style_fit") or ""
    if silhouette:
        if isinstance(silhouette, list):
            parts.append("Silhouette: " + ", ".join(silhouette) + ".")
        else:
            parts.append("Silhouette: " + silhouette + ".")
    if d.get("sleeves"): parts.append("Sleeves: " + d.get("sleeves") + ".")
    if d.get("neckline"): parts.append("Neckline: " + d.get("neckline") + ".")
    if d.get("prints_patterns"): parts.append("Prints: " + ", ".join(d.get("prints_patterns")) + ".")
    tech = d.get("techpack") or d.get("image_prompt")
    if tech: parts.append("Notes: " + (str(tech)[:400]))
    return " ".join(parts)

def build_prompt(summary: str, attrs: dict) -> str:
    return PROMPT_TEMPLATE.format(
        gender=attrs.get("gender", "female"),
        age_range=attrs.get("age_range", "25-32"),
        body_type=attrs.get("body_type", "slim"),
        skin_tone=attrs.get("skin_tone", "medium-dark"),
        pose=attrs.get("pose", "runway walk, natural turn"),
        design_summary=summary
    )

def submit_video(prompt: str):
    # Use Veo generation via client.models.generate_videos if available
    try:
        op = client.models.generate_videos(model="veo-3.0-generate-001", prompt=prompt)
    except Exception:
        # fallback shape (older/newer SDKs)
        op = client.generate_videos(model="veo-3.0-generate-001", prompt=prompt)
    return op

def poll_and_download(operation, out_path: Path, timeout=600):
    start = time.time()
    while not getattr(operation, "done", False):
        time.sleep(5)
        try:
            operation = client.operations.get(operation)
        except Exception as e:
            print("Warning: poll refresh failed:", e)
        if time.time() - start > timeout:
            raise TimeoutError("Timed out waiting for Veo operation")

    # extract video bytes
    generated_video = operation.response.generated_videos[0]
    vid_field = getattr(generated_video, "video", None)
    if not vid_field:
        raise RuntimeError("No 'video' field in generated_videos (inspect operation)")

    if isinstance(vid_field, (bytes, bytearray)):
        data = vid_field
    else:
        file_obj = client.files.download(file=vid_field)
        data = getattr(file_obj, "content", None) or getattr(file_obj, "bytes", None) or file_obj

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, (bytes, bytearray)):
        out_path.write_bytes(data)
    else:
        with open(out_path, "wb") as fh:
            fh.write(data.read())
    return str(out_path)

def parse_model_attrs(args):
    attrs = {}
    if args.model_attrs:
        try:
            attrs = json.loads(args.model_attrs)
        except Exception:
            print("Warning: failed to parse --model-attrs JSON, ignoring.")
            attrs = {}
    for k in ("gender","age_range","body_type","skin_tone","pose"):
        v = getattr(args, k, None)
        if v: attrs[k] = v
    defaults = {"gender":"female","age_range":"25-32","body_type":"slim","skin_tone":"medium-dark","pose":"runway walk, natural turn"}
    for k,v in defaults.items(): attrs.setdefault(k,v)
    return attrs

def find_design_files(path: Path):
    if path.is_file():
        return [path]
    files = sorted([p for p in path.iterdir() if p.is_file() and p.suffix == ".json" and "design" in p.name.lower()])
    return files

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--design", type=str, help="single design JSON file")
    parser.add_argument("--input-dir", type=str, default="output/agent2_designs", help="directory with design JSONs")
    parser.add_argument("--limit", type=int, default=1, help="limit number of designs to process")
    parser.add_argument("--seed", type=int, default=None, help="optional RNG seed for reproducible random selection")
    parser.add_argument("--model-attrs", type=str, help="JSON string with model attributes")
    parser.add_argument("--gender", type=str)
    parser.add_argument("--age_range", type=str)
    parser.add_argument("--body_type", type=str)
    parser.add_argument("--skin_tone", type=str)
    parser.add_argument("--pose", type=str)
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
    print(f"Found {len(files)} design files to process. model_attrs={model_attrs}")
    out_dir = Path(args.out_dir)

    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Skipping {f.name}: read error {e}")
            continue
        design_id = d.get("design_id") or f.stem
        summary = design_to_summary(d)
        prompt = build_prompt(summary, model_attrs)

        # save storyboard
        sb_file = out_dir / f"{design_id}_storyboard.txt"
        sb_file.parent.mkdir(parents=True, exist_ok=True)
        sb_file.write_text(prompt, encoding="utf-8")

        print(f"-> [{design_id}] Submitting Veo request...")
        try:
            op = submit_video(prompt)
        except Exception as e:
            print(f"  Submit failed: {e}. Saved storyboard to {sb_file}")
            continue

        print("  Polling for completion...")
        try:
            out_path = out_dir / f"{design_id}_runway.mp4"
            saved = poll_and_download(op, out_path)
            print(f"  Saved video: {saved}")
        except Exception as e:
            print(f"  Failed to get video for {design_id}: {e}. Saved storyboard to {sb_file}")

if __name__ == "__main__":
    main()
