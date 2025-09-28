#!/usr/bin/env python3
"""
scrape_and_analyze.py (Vision stage)

Input:
  - to_enrich.json (from merge_playwright_and_filter.py)

Output:
  - output/analysis_results_updated.json (Vision results per product)

What it does:
  - Reads filtered product list
  - Runs Azure Vision analysis (color, tags, description, objects)
  - Crops detected objects and re-analyzes
  - Saves results for each product
"""

import os, json, asyncio, aiohttp, aiofiles, hashlib
from pathlib import Path
from PIL import Image
from io import BytesIO
from tqdm.asyncio import tqdm
from dotenv import load_dotenv

# ---------- Setup ----------
load_dotenv()
ENDPOINT = os.environ.get("AZURE_VISION_ENDPOINT")
KEY = os.environ.get("AZURE_VISION_KEY")
OUTPUT_JSON = Path(os.environ.get("OUTPUT_JSON", "output/analysis_results_updated.json"))
TO_ENRICH = Path("output/to_enrich.json")

HEADERS = {"Ocp-Apim-Subscription-Key": KEY}

# ---------- Utilities ----------
def fname_from_url(url: str) -> str:
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()
    ext = Path(url.split("?")[0]).suffix or ".jpg"
    return f"{h}{ext}"

async def analyze_image_url(session: aiohttp.ClientSession, image_url: str):
    api = f"{ENDPOINT}/vision/v3.2/analyze?visualFeatures=Color,Objects,Tags,Description"
    headers = {**HEADERS, "Content-Type": "application/json"}
    payload = {"url": image_url}
    async with session.post(api, headers=headers, json=payload, timeout=60) as r:
        return await r.json()

async def analyze_image_bytes(session: aiohttp.ClientSession, image_bytes: bytes):
    api = f"{ENDPOINT}/vision/v3.2/analyze?visualFeatures=Color,Tags,Description"
    headers = {**HEADERS, "Content-Type": "application/octet-stream"}
    async with session.post(api, headers=headers, data=image_bytes, timeout=60) as r:
        return await r.json()

def crop_image_bytes(image_bytes: bytes, rect):
    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    x, y, w, h = rect["x"], rect["y"], rect["w"], rect["h"]
    x, y, w, h = int(x), int(y), int(w), int(h)
    x2, y2 = x + w, y + h
    x, y = max(0, x), max(0, y)
    x2, y2 = min(img.width, x2), min(img.height, y2)
    crop = img.crop((x, y, x2, y2))
    buf = BytesIO()
    crop.save(buf, format="JPEG")
    return buf.getvalue()

async def process_image(session: aiohttp.ClientSession, image_url: str):
    try:
        res = await analyze_image_url(session, image_url)
    except Exception as e:
        return {"image_url": image_url, "error": str(e)}

    output = {
        "image_url": image_url,
        "azure_image_analysis": {
            "color": res.get("color"),
            "tags": res.get("tags"),
            "description": res.get("description"),
            "objects": res.get("objects", [])
        },
        "per_garment": []
    }

    objects = res.get("objects", [])
    if objects:
        try:
            async with session.get(image_url, timeout=30) as r:
                if r.status != 200:
                    return output
                image_bytes = await r.read()
        except Exception:
            return output

        for obj in objects:
            rect = obj.get("rectangle")
            if not rect:
                continue
            try:
                crop_bytes = crop_image_bytes(image_bytes, rect)
                crop_res = await analyze_image_bytes(session, crop_bytes)
            except Exception:
                crop_res = {}
            output["per_garment"].append({
                "label": obj.get("object"),
                "confidence": obj.get("confidence"),
                "rectangle": rect,
                "crop_analysis": {
                    "color": crop_res.get("color"),
                    "tags": crop_res.get("tags"),
                    "description": crop_res.get("description")
                }
            })
    return output

# ---------- Main ----------
async def main():
    if not TO_ENRICH.exists():
        print("Missing to_enrich.json — run merge_playwright_and_filter.py first")
        return

    to_enrich = json.load(open(TO_ENRICH, encoding="utf-8"))
    results = []

    async with aiohttp.ClientSession() as session:
        sem = asyncio.Semaphore(8)  # adjust concurrency

        async def handle_product(prod):
            async with sem:
                product_url = prod.get("url")
                filtered_imgs = prod.get("image_candidates_filtered", [])[:3]
                product_result = {
                    "product_url": product_url,
                    "image_candidates": filtered_imgs,
                    "vision_results": []
                }
                for img_url in filtered_imgs:
                    try:
                        out = await process_image(session, img_url)
                        product_result["vision_results"].append(out)
                    except Exception as e:
                        product_result["vision_results"].append({"image_url": img_url, "error": str(e)})
                return product_result

        tasks = [handle_product(p) for p in to_enrich]
        for fut in tqdm.as_completed(tasks, total=len(tasks)):
            res = await fut
            if res:
                results.append(res)

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("Wrote", OUTPUT_JSON)

if __name__ == "__main__":
    asyncio.run(main())
