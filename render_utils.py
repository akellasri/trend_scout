#!/usr/bin/env python3
# render_utils.py
import os, json, base64, random
from pathlib import Path
import google.generativeai as genai
from PIL import Image

# configure gemini (ensure GEMINI_API_KEY is exported)
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

MODEL_NAME = "gemini-2.5-flash-image-preview"
model = genai.GenerativeModel(MODEL_NAME)

def render_design_via_gemini(design_json, variant="flatlay", out_dir="renders"):
    """
    design_json: dict (expects image_prompt key else will build one)
    variant: "flatlay" or other
    returns path to saved file
    """
    prompt = design_json.get("image_prompt") or design_json.get("title") or "photorealistic flat-lay product image"
    if variant == "flatlay":
        prompt = (
            "Flat-lay apparel-only: isolated garment, NO MODEL, NO MANNEQUIN, NO HUMAN. "
            + prompt
            + ". Photorealistic product-only PNG, high-detail fabric texture. White background."
        )

    resp = model.generate_content(
        prompt,
        generation_config={"temperature": 0.0, "candidate_count": 1}
    )

    img_bytes = None
    mime = "image/png"

    for cand in getattr(resp, "candidates", []) or []:
        if not hasattr(cand, "content"):
            continue
        for part in getattr(cand.content, "parts", []) or []:
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                raw = inline.data
                mime = getattr(inline, "mime_type", mime)
                img_bytes = raw if isinstance(raw, (bytes, bytearray)) else base64.b64decode(raw)
                break
        if img_bytes:
            break

    if not img_bytes:
        raise RuntimeError("No image returned from Gemini for prompt.")

    ext = ".png"
    if "jpeg" in mime or "jpg" in mime:
        ext = ".jpg"

    save_dir = Path(out_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    design_id = design_json.get("design_id", "design")
    out_file = save_dir / f"{design_id}__{variant}{ext}"

    with open(out_file, "wb") as f:
        f.write(img_bytes)

    # normalize with Pillow
    try:
        img = Image.open(out_file)
        fixed_file = save_dir / f"{design_id}__{variant}.png"
        img.save(fixed_file, format="PNG")
        out_file = fixed_file
    except Exception as e:
        print(f"⚠️ Warning: could not re-save with Pillow: {e}")

    return str(out_file)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", help="Path to design.json (optional, if not given will pick random)")
    parser.add_argument("--variant", default="flatlay")
    args = parser.parse_args()

    if args.input:
        d = json.load(open(args.input, encoding="utf-8"))
    else:
        design_dir = Path("output/agent2_designs")
        candidates = list(design_dir.glob("*.design.json"))
        if not candidates:
            raise SystemExit("No design JSONs found in output/agent2_designs/")
        pick = random.choice(candidates)
        print(f"🎲 No input provided. Randomly picked: {pick.name}")
        d = json.load(open(pick, encoding="utf-8"))

    out = render_design_via_gemini(d, args.variant)
    print("✅ Saved:", out)
