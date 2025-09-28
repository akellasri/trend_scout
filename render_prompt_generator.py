#!/usr/bin/env python3
"""
render_prompt_generator.py

Reads all design JSON files in output/agent2_designs
Writes render_plan.json with enriched prompts (flat-lay, apparel-only).
"""

import json, os
from pathlib import Path

IN_DIR = Path("output/agent2_designs")
OUT_FILE = Path("output/render_plan.json")

def build_prompt(design):
    base = f"Flat-lay apparel-only product render. NO MODEL, NO MANNEQUIN, NO HUMAN. Photorealistic PNG, isolated on plain white background."
    title = design.get("title") or ""
    desc = design.get("image_prompt") or ""
    prompt = f"{base} {title}. {desc}"

    # Add structured fields
    colors = design.get("color_palette") or []
    fabrics = design.get("fabrics") or []
    prints = design.get("prints_patterns") or []
    gtype = design.get("garment_type") or ""
    silhouette = design.get("silhouette") or ""
    sleeves = design.get("sleeves") or ""
    neckline = design.get("neckline") or ""
    length = design.get("length") or ""
    style = design.get("style_fit") or []
    trims = design.get("trims_and_details") or []
    
    if colors: prompt += f" Colors: {', '.join(colors)}."
    if fabrics: prompt += f" Fabrics: {', '.join(fabrics)}."
    if prints: prompt += f" Prints/patterns: {', '.join(prints)}."
    if gtype: prompt += f" Garment type: {gtype}."
    if silhouette: prompt += f" Silhouette: {silhouette}."
    if sleeves: prompt += f" Sleeves: {sleeves}."
    if neckline: prompt += f" Neckline: {neckline}."
    if length: prompt += f" Length: {length}."
    if style: prompt += f" Style/fit: {', '.join(style)}."
    if trims: prompt += f" Details: {', '.join(trims)}."

    return prompt.strip()

def main():
    render_plan = []
    for f in IN_DIR.glob("*.design.json"):
        design = json.load(open(f, encoding="utf-8"))
        design_id = design.get("design_id") or f.stem
        out_dir = Path(f"renders/{design_id}")
        out_dir.mkdir(parents=True, exist_ok=True)
        item = {
            "design_id": design_id,
            "title": design.get("title"),
            "variant": "flatlay",
            "prompt": build_prompt(design),
            "out_file": str(out_dir / f"{design_id}__flatlay.png"),
            "size": "1024x1024",
            "n": 1
        }
        render_plan.append(item)

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(render_plan, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(render_plan)} render prompts -> {OUT_FILE}")

if __name__ == "__main__":
    main()
