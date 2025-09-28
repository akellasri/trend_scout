#!/usr/bin/env python3
# vision_prefilter.py
import os, json, time, requests
from urllib.parse import urljoin

AZURE_VISION_ENDPOINT = os.environ.get("AZURE_VISION_ENDPOINT")
AZURE_VISION_KEY = os.environ.get("AZURE_VISION_KEY")
INPUT = "output/clean_product_pages.json"   # your validator output
OUT = "output/to_enrich.json"

def call_vision_tags(image_url, timeout=12):
    api = f"{AZURE_VISION_ENDPOINT.rstrip('/')}/vision/v3.2/analyze"
    params = {"visualFeatures":"Tags"}
    headers = {"Ocp-Apim-Subscription-Key": AZURE_VISION_KEY, "Content-Type":"application/json"}
    try:
        r = requests.post(api, headers=headers, params=params, json={"url": image_url}, timeout=timeout)
        if r.status_code!=200:
            return {"error": f"{r.status_code}"}
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def passes_tags(tags_json):
    # tags_json: result from Vision analyze; return True if clothing/person found
    tags = [t.get("name","").lower() for t in tags_json.get("tags",[])]
    # allow clothing OR person + clothing-related words in tags
    clothing_tokens = {"clothing","dress","shirt","top","saree","kurta","blouse","pant","trousers","skirt","lehenga","outfit"}
    person_tokens = {"person","human","woman","man","female","male","model"}
    if any(t in clothing_tokens for t in tags):
        return True
    if any(t in person_tokens for t in tags) and any(t in ("clothing","dress","top","shirt") for t in tags):
        return True
    return False

data = json.load(open(INPUT, encoding="utf-8"))
all_entries = data.get("all", [])   # or use data["good"]/data["all"] depending on shape
to_enrich = []
for e in all_entries:
    if e.get("ok"): 
        # already good — skip here if you only want to filter false entries
        continue
    # pick first candidate image if exists
    imgs = e.get("image_candidates") or []
    if not imgs:
        continue
    image_url = imgs[0]
    res = call_vision_tags(image_url)
    if "error" in res:
        continue
    if passes_tags(res):
        to_enrich.append({"url": e["url"], "image": image_url, "vision": res})
    time.sleep(0.15)  # polite
open(OUT,"w",encoding="utf-8").write(json.dumps(to_enrich, ensure_ascii=False, indent=2))
print("Candidates to enrich:", len(to_enrich))