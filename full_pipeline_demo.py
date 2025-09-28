#!/usr/bin/env python3
"""
pipeline_demo.py

End-to-end demo:
1. Pick a random design JSON (or use the one provided).
2. Apply a text change to the design.
3. Render flatlay PNG.
4. Generate showcase image on model.
5. Generate runway video.
6. Output a clean JSON summary (to stdout and optional file).
"""

import os, sys, json, random, argparse
from pathlib import Path
from apply_text_change import apply_change
from render_utils import render_design_via_gemini
from agent3_virtual_showcase_demo import showcase_on_model
from agent3_runway_demo import design_to_summary, submit_video, poll_and_download

def pick_random_design(input_dir="output/agent2_designs"):
    """Pick a random design.json file from directory"""
    path = Path(input_dir)
    files = [f for f in path.glob("*.design.json") if f.is_file()]
    if not files:
        raise FileNotFoundError(f"No design JSON files found in {input_dir}")
    return random.choice(files)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--design", type=str, help="path to design.json (optional, random if not provided)")
    parser.add_argument("--change", type=str, default="", help="text change to apply (optional)")
    parser.add_argument("--json-out", type=str, help="optional path to save JSON summary")
    args = parser.parse_args()

    # Step 1: Select design (random if not given)
    if args.design:
        base_path = Path(args.design)
    else:
        base_path = pick_random_design()
        print(f"🎲 Picked random design: {base_path}")

    base_design = json.load(open(base_path, encoding="utf-8"))

    # Step 2: Apply text change (if given)
    updated = base_design
    if args.change:
        updated = apply_change(base_design, args.change)

    # Save updated design file
    mod_file = base_path.with_name(base_path.stem.replace(".design", "") + ".modified.json")
    mod_file.write_text(json.dumps(updated, ensure_ascii=False, indent=2))

    # Step 3: Render flatlay
    png_path = render_design_via_gemini(updated, "flatlay")

    # Step 4: Showcase image on model
    showcase_path = showcase_on_model(png_path, f"output/{updated['design_id']}_showcase.png")

    # Step 5: Runway video
    summary = design_to_summary(updated)
    prompt = f"You are a fashion director. Render runway video of this design:\n{summary}"
    op = submit_video(prompt)
    runway_path = poll_and_download(op, Path(f"output/{updated['design_id']}_runway.mp4"))

    # Step 6: JSON summary
    result = {
        "design_id": updated.get("design_id"),
        "design_file": str(mod_file),
        "render_png": str(png_path),
        "showcase_image": str(showcase_path),
        "runway_video": str(runway_path),
        "design_text": updated.get("design_text")
    }

    print(json.dumps(result, indent=2, ensure_ascii=False))

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"📄 Saved JSON summary to {args.json_out}")

if __name__ == "__main__":
    main()
