#!/usr/bin/env python3
"""
trend_scraper_full_patched_with_fixes.py

Patched from user's original script with the following added fixes requested:
- deterministic dominant color extraction per accepted image (pixel-based) and mapping to nearest named color
- stricter metric fusion: prefer image-confirmed metrics (text+clip) or very-high visual-only matches
- include top-N example images per accepted trend label (with clip scores) in `extracted` for auditing
- add image diagnostics entries for dominant color and color name
- keep other discovery features (BLIP, CLIP, clustering) intact

Usage:
  python trend_scraper_full_patched_with_fixes.py --limit 3 --use-blip --use-phash --cluster

Note: Replace or install optional dependencies as needed (transformers, torch, imagehash, sklearn).
"""

import os
import re
import time
import json
import math
import argparse
import urllib.parse
import requests
from io import BytesIO
from datetime import datetime
from urllib.parse import urlparse
from urllib import robotparser
from collections import Counter

# Rendering + HTML
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# Imaging
from PIL import Image

# Text matching (spaCy PhraseMatcher)
import spacy
from spacy.matcher import PhraseMatcher

# optional image pHash dedupe
try:
    import imagehash
    IMAGEHASH_AVAILABLE = True
except Exception:
    IMAGEHASH_AVAILABLE = False

# optionally CLIP
USE_CLIP = True
try:
    from transformers import CLIPProcessor, CLIPModel
    import torch
    import numpy as np
    CLIP_AVAILABLE = True
except Exception:
    CLIP_AVAILABLE = False
    np = None

# optional BLIP for captions
BLIP_AVAILABLE = False
try:
    from transformers import BlipProcessor, BlipForConditionalGeneration
    BLIP_AVAILABLE = True
except Exception:
    BLIP_AVAILABLE = False

# optional clustering
try:
    from sklearn.cluster import KMeans
    SKLEARN_AVAILABLE = True
except Exception:
    SKLEARN_AVAILABLE = False

# ----------------- CONFIG -----------------
SEEDS = [
    "https://www.lakmefashionweek.co.in/",
    "https://in.kalkifashion.com/blog?source=us&medium=reference",
    "https://www.vogue.in/fashion",
    "https://www.harpersbazaar.in/fashion",
    "https://www.missmalini.com/fashion",
    "https://www.utsavfashion.com/showcase",
    "https://www.azafashions.com/blog",
    "https://taruntahiliani.com/?srsltid=AfmBOooBRdkAHrDz6DpSVSCl_OvyxRCZNzd-9iTc6aUz32MJsNFP2NdL",
    "https://sabyasachi.com/",
    "https://www.shantanunikhil.com/?srsltid=AfmBOoqVWhtu13g_MPtiPYxjVoo0qVA5VtLWs1ymrv1Bn7Pa4HU4KQla",
    "https://www.houseofmasaba.com/",
    "https://anamikakhanna.com/",
    "https://www.masoomminawala.com/",
    "https://www.awigna.com/",
]

HEADERS = {"User-Agent": "TrendScoutBot/1.0 (+contact)"}
SCROLL_PAUSE = 0.6
SCROLL_TIMES = 8
MAX_PAGES_PER_SITE = 40
CRAWL_DELAY = 0.6

# image heuristics (tunable)
MIN_IMAGE_BYTES = 8 * 1024
MIN_WIDTH = 200
MIN_HEIGHT = 150
MAX_IMAGES_PER_PAGE = 12

# CLIP thresholds
CLIP_SIM_THRESHOLD = 0.26
CLIP_SIM_HIGH = 0.38
CLIP_SIM_AGG_THRESHOLD = 0.30
TOP_K = 3
CANDIDATES_PER_CAT = 24

# phrase lists
PRINTS = ["bandhani", "ikat", "kalamkari", "paisley", "floral", "geometric", "abstract",
          "polka", "stripes", "checks", "gingham", "tie-dye", "tie dye", "block print",
          "digital print", "painterly", "batik", "mirror work", "embroidery", "mirrorwork"]
COLORS = ["red","maroon","burgundy","orange","yellow","mellow yellow","mustard","green","olive","mint",
          "emerald","blue","powder blue","navy","teal","pink","dusty pink","blush","pastel","lavender",
          "purple","beige","tan","brown","black","white","ivory","cream","gold","silver","metallic"]
SHAPES = ["co-ord set","co ord set","co-ord","coord","kurta set","lehenga","anarkali","sherwani",
          "wrap dress","sheath","a-line","a line","fit and flare","draped","cape","oversized","boxy",
          "tailored","layered","asymmetric","bodycon","slip dress","maxi","midi","mini","palazzo","culotte",
          "jumpsuit","shrug","blouse","shirt dress"]
FABRICS = ["organza","chiffon","silk","satin","crepe","linen","cotton","khadi","tussar","tussar silk",
           "raw silk","banarasi","banarasi silk","brocade","velvet","denim","chikankari","handloom","woven",
           "lace","net","georgette","viscose","rayon","modal","muslin","twill"]

# spaCy matcher
nlp = spacy.load("en_core_web_sm")   # parser & tagger enabled
try:
    nlp.add_pipe("sentencizer")
except Exception:
    pass
matcher = PhraseMatcher(nlp.vocab, attr="LOWER")

def add_terms(label, terms):
    patterns = [nlp.make_doc(t) for t in sorted(set(terms), key=lambda s: -len(s))]
    matcher.add(label, patterns)

add_terms("PRINT", PRINTS)
add_terms("COLOR", COLORS)
add_terms("SHAPE", SHAPES)
add_terms("FABRIC", FABRICS)

# stronger bad img regex
BAD_IMG_RX = re.compile(
    r"(logo|sprite|icon|placeholder|avatar|pixel|ads?|tracking|badge|close|thumb|spinner|blank|banner|social|og:|share|meta|facebook|twitter|instagram|linkedin|paypal|visa|mastercard|apple-pay|google-pay|qr|watermark|shopify|cdn|/icons/|/assets/|/static/|/logos?/|badge|btn|btn-)",
    re.I
)

from urllib.parse import urlparse, urlunparse


def url_without_query(u):
    try:
        p = urlparse(u)
        return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))
    except Exception:
        return u


def normalize_and_dedupe(img_list, max_keep=MAX_IMAGES_PER_PAGE):
    seen = {}
    order = []
    for u in img_list:
        if not u: continue
        key = url_without_query(u)
        if BAD_IMG_RX.search(u.lower()):
            continue
        if key not in seen or len(u) > len(seen[key]):
            seen[key] = u
        if key not in order:
            order.append(key)
    out = []
    for k in order:
        if k in seen:
            out.append(seen.pop(k))
        if len(out) >= max_keep:
            break
    return out


def extract_from_html(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    canonical = (soup.find("link", rel="canonical") or {}).get("href") or base_url
    article = soup.find("article") or soup.find("main") or soup.body or soup
    # prefer role=main if article too small
    if article is None or len((article.get_text(strip=True) or "")) < 200:
        candidate = soup.find(attrs={"role":"main"}) or soup.find("div", {"class": re.compile(r'(content|article|main|post)', re.I)})
        if candidate:
            article = candidate
    page_text = article.get_text(separator=" ", strip=True)[:120000]
    images = set()
    def add_img(u):
        if not u: return
        try:
            u2 = urllib.parse.urljoin(base_url, u)
        except Exception:
            return
        if BAD_IMG_RX.search(u2):
            return
        images.add(u2)
    og = (soup.find("meta", property="og:image") or {}).get("content")
    add_img(og)
    for img in soup.find_all("img"):
        for attr in ("src","data-src","data-original","data-lazy-src","data-lazy","data-srcset"):
            v = img.get(attr)
            if v:
                if "," in v:
                    v = v.split(",")[0].strip().split(" ")[0]
                add_img(v)
        ss = img.get("srcset")
        if ss:
            for part in ss.split(","):
                add_img(part.strip().split(" ")[0])
        alt = img.get("alt")
        if alt:
            page_text += " " + alt
    for src in soup.find_all("source"):
        ss = src.get("srcset") or src.get("src")
        if ss:
            if "," in ss:
                for part in ss.split(","):
                    add_img(part.strip().split(" ")[0])
            else:
                add_img(ss)
    for el in soup.find_all(style=True):
        style = el.get("style") or ""
        matches = re.findall(r'background(?:-image)?:.*?url\([\'\"]?(.*?)[\'\"]?\)', style, re.I)
        for m in matches:
            add_img(m)
    for js in soup.find_all("script", type="application/ld+json"):
        try:
            obj = json.loads(js.string or "{}")
            def walk(o):
                if isinstance(o, dict):
                    for k,v in o.items():
                        if k.lower() == "image":
                            if isinstance(v, (list,tuple)):
                                for x in v: add_img(x)
                            else: add_img(v)
                        else:
                            walk(v)
                elif isinstance(o, list):
                    for x in o: walk(x)
            walk(obj)
        except Exception:
            pass
    return {"pageUrl": canonical, "text": page_text, "images": sorted(images), "html": html}


def allowed_by_robots(url, user_agent=HEADERS["User-Agent"]):
    try:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        rp = robotparser.RobotFileParser()
        rp.set_url(base + "/robots.txt")
        rp.read()
        return rp.can_fetch(user_agent, url)
    except Exception:
        return True


def render_page_and_extract(url, scroll_times=SCROLL_TIMES, scroll_pause=SCROLL_PAUSE):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width":1280,"height":900})
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            try:
                page.goto(url, wait_until="networkidle", timeout=45000)
            except Exception:
                browser.close()
                return None
        for _ in range(scroll_times):
            try:
                page.evaluate("window.scrollBy(0, window.innerHeight);")
            except Exception:
                pass
            time.sleep(scroll_pause)
        try:
            for btn in page.query_selector_all("a,button"):
                try:
                    txt = (btn.inner_text() or "").lower()
                    if "view gallery" in txt or "view more" in txt or "next" in txt or "gallery" in txt:
                        btn.click(timeout=200)
                        time.sleep(0.2)
                except Exception:
                    pass
        except Exception:
            pass
        html = page.content()
        browser.close()
    return extract_from_html(html, url)


def is_logo_or_small(url, session=None):
    session = session or requests.Session()
    session.headers.update(HEADERS)
    try:
        lowerr = url.lower()
        if BAD_IMG_RX.search(lowerr):
            return True
        if lowerr.endswith(".svg") or lowerr.startswith("data:"):
            return True
        h = session.head(url, allow_redirects=True, timeout=6)
        if h.status_code >= 400:
            return True
        ctype = h.headers.get("Content-Type","")
        if ctype and not ctype.startswith("image"):
            return True
        clen = h.headers.get("Content-Length")
        if clen and int(clen) < MIN_IMAGE_BYTES:
            return True
    except Exception:
        pass
    try:
        r = session.get(url, stream=True, timeout=10)
        if r.status_code != 200:
            return True
        data = r.content[:200000]
        if len(data) < MIN_IMAGE_BYTES:
            return True
        img = Image.open(BytesIO(data)).convert("RGB")
        w,h = img.size
        if w < MIN_WIDTH or h < MIN_HEIGHT:
            return True
        aspect = w / float(h) if h else 0
        if aspect > 6 or aspect < 0.2:
            return True
    except Exception:
        return True
    return False


def extract_metrics_from_text(text):
    doc = nlp(text or "")
    matches = matcher(doc)
    out = {"prints": set(), "colors": set(), "shapes": set(), "fabrics": set()}
    for match_id, start, end in matches:
        label = nlp.vocab.strings[match_id]
        span = doc[start:end].text.lower()
        if label == "PRINT":
            out["prints"].add(span)
        elif label == "COLOR":
            out["colors"].add(span)
        elif label == "SHAPE":
            out["shapes"].add(span)
        elif label == "FABRIC":
            out["fabrics"].add(span)
    return {k: sorted(list(v)) for k,v in out.items()}


def extract_page_date_from_soup_and_headers(soup, headers=None):
    meta_props = [
        ("meta", {"property":"article:published_time"}),
        ("meta", {"name":"date"}),
        ("meta", {"itemprop":"datePublished"}),
        ("meta", {"name":"pubdate"}),
        ("meta", {"property":"article:modified_time"}),
        ("meta", {"name":"last-modified"})
    ]
    for tag, attrs in meta_props:
        el = soup.find(tag, attrs=attrs)
        if el:
            v = el.get("content") or el.get("value") or el.string
            if v:
                try:
                    return datetime.fromisoformat(v.replace("Z","+00:00")).isoformat()+"Z"
                except Exception:
                    try:
                        return datetime.strptime(v, "%Y-%m-%d").isoformat()+"Z"
                    except Exception:
                        pass
    t = soup.find("time")
    if t and t.get("datetime"):
        try:
            return datetime.fromisoformat(t.get("datetime").replace("Z","+00:00")).isoformat()+"Z"
        except Exception:
            pass
    if headers:
        lm = headers.get("Last-Modified")
        if lm:
            try:
                from email.utils import parsedate_to_datetime
                return parsedate_to_datetime(lm).isoformat()+"Z"
            except Exception:
                pass
    return None


class CLIPWrapper:
    def __init__(self, device=None):
        if not CLIP_AVAILABLE:
            raise RuntimeError("CLIP transformer libraries not available")
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32").to(self.device)
        self.processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")

    def similarity_topk(self, pil_image, texts, top_k=TOP_K):
        inputs = self.processor(text=texts, images=pil_image, return_tensors="pt", padding=True).to(self.device)
        with torch.no_grad():
            outputs = self.model(**inputs)
            image_emb = outputs.image_embeds
            text_emb = outputs.text_embeds
            image_emb = image_emb / image_emb.norm(dim=-1, keepdim=True)
            text_emb = text_emb / text_emb.norm(dim=-1, keepdim=True)
            sims = (text_emb @ image_emb.T).squeeze(-1).cpu().numpy().tolist()
        paired = list(zip(texts, sims))
        paired_sorted = sorted(paired, key=lambda x: x[1], reverse=True)
        return paired_sorted[:top_k]

    def get_image_embedding(self, pil_image):
        inputs = self.processor(images=pil_image, return_tensors="pt").to(self.device)
        with torch.no_grad():
            if hasattr(self.model, 'get_image_features'):
                emb = self.model.get_image_features(**inputs)
            else:
                out = self.model(**inputs)
                emb = out.image_embeds
            emb = emb.cpu().numpy()
            emb = emb / np.linalg.norm(emb, axis=1, keepdims=True)
        return emb[0]


def extract_candidate_phrases(text, min_len=3, max_phrases=40):
    try:
        doc = nlp(text or "")
    except Exception:
        words = [w.strip().lower() for w in re.split(r'[.,;:\-\s]+', text or "") if len(w.strip()) > min_len]
        return words[:max_phrases]
    phrases = []
    for nc in doc.noun_chunks:
        s = nc.text.strip().lower()
        if len(s) < min_len:
            continue
        if any(ch.isdigit() for ch in s):
            continue
        phrases.append(s)
    counts = Counter(phrases)
    common = [p for p, _ in counts.most_common(max_phrases)]
    return common


# BLIP caption helpers (lazy load)
BLIP_MODEL = None
BLIP_PROCESSOR = None

def load_blip():
    global BLIP_MODEL, BLIP_PROCESSOR
    if BLIP_MODEL is not None:
        return True
    if not BLIP_AVAILABLE:
        return False
    try:
        BLIP_PROCESSOR = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
        BLIP_MODEL = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base").to("cuda" if torch.cuda.is_available() else "cpu")
        return True
    except Exception:
        return False


def caption_image_bytes(image_bytes):
    if not load_blip():
        return None
    try:
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
        inputs = BLIP_PROCESSOR(images=img, return_tensors="pt").to(BLIP_MODEL.device)
        out = BLIP_MODEL.generate(**inputs, max_length=32)
        caption = BLIP_PROCESSOR.decode(out[0], skip_special_tokens=True)
        return caption
    except Exception:
        return None


# ----------------- New helpers: color extraction & mapping -----------------
# Basic palette for mapping named COLORS -> RGB (approximate)
NAMED_COLOR_PALETTE = {
    'red': (220,20,60), 'maroon': (128,0,0), 'burgundy': (128,0,32), 'orange': (255,165,0),
    'yellow': (255,215,0), 'mustard': (205,173,0), 'green': (34,139,34), 'olive': (128,128,0),
    'mint': (152,255,152), 'emerald': (80,200,120), 'blue': (30,144,255), 'powder blue': (176,224,230),
    'navy': (0,0,128), 'teal': (0,128,128), 'pink': (255,192,203), 'dusty pink': (205,135,145), 'blush': (222,93,131),
    'pastel': (255,179,186), 'lavender': (230,230,250), 'purple': (128,0,128), 'beige': (245,245,220),
    'tan': (210,180,140), 'brown': (165,42,42), 'black': (0,0,0), 'white': (255,255,255), 'ivory': (255,255,240),
    'cream': (255,253,208), 'gold': (212,175,55), 'silver': (192,192,192), 'metallic': (169,169,169)
}


def rgb_distance(c1, c2):
    return math.sqrt(sum((a-b)**2 for a,b in zip(c1,c2)))


def nearest_named_color(hex_rgb):
    # hex_rgb: (r,g,b)
    best = None
    best_d = 1e9
    for name, rgb in NAMED_COLOR_PALETTE.items():
        d = rgb_distance(hex_rgb, rgb)
        if d < best_d:
            best_d = d
            best = name
    return best


def dominant_color_hex_from_bytes(image_bytes, resize=120):
    try:
        img = Image.open(BytesIO(image_bytes)).convert('RGB')
        img = img.resize((resize, resize))
        # use getcolors to find most common color
        colors = img.getcolors(maxcolors=resize*resize+1)
        if not colors:
            arr = list(img.getdata())
            counts = Counter(arr)
            most = counts.most_common(1)[0][0]
        else:
            most = max(colors, key=lambda x: x[0])[1]
        return tuple(int(v) for v in most)
    except Exception:
        return None


# main pipeline for a url

def process_url(url, clip_wrapper=None, limit_images=MAX_IMAGES_PER_PAGE, use_phash=False, use_blip=False, global_image_records=None):
    out_item = {"pageUrl": url, "fetchedAt": datetime.utcnow().isoformat()+"Z", "extracted": None, "metrics": {}, "notes": []}
    if not allowed_by_robots(url):
        out_item["notes"].append("Disallowed by robots.txt")
        return out_item
    rendered = render_page_and_extract(url)
    if not rendered:
        out_item["notes"].append("RenderFailed")
        return out_item
    page_text = rendered.get("text","")
    html = rendered.get("html","")
    candidate_images = rendered.get("images",[])
    candidate_images = normalize_and_dedupe(candidate_images, max_keep=limit_images)

    # diagnostics
    image_diagnostics = {}
    session = requests.Session()
    session.headers.update(HEADERS)
    good_images = []
    image_bytes_map = {}

    for img_url in candidate_images:
        if not img_url: continue
        diag = {"skipped": False, "reason": None}
        low = img_url.lower()
        if BAD_IMG_RX.search(low):
            diag["skipped"] = True
            diag["reason"] = "BAD_IMG_RX matched"
            image_diagnostics[img_url] = diag
            continue
        try:
            h = session.head(img_url, allow_redirects=True, timeout=6)
            if h.status_code >= 400:
                diag["skipped"] = True
                diag["reason"] = f"HEAD status {h.status_code}"
                image_diagnostics[img_url] = diag
                continue
            ctype = h.headers.get("Content-Type","")
            if ctype and not ctype.startswith("image"):
                diag["skipped"] = True
                diag["reason"] = f"non-image content-type {ctype}"
                image_diagnostics[img_url] = diag
                continue
            clen = h.headers.get("Content-Length")
            if clen and int(clen) < MIN_IMAGE_BYTES:
                diag["skipped"] = True
                diag["reason"] = f"content-length too small {clen}"
                image_diagnostics[img_url] = diag
                continue
        except Exception as e:
            diag["head_error"] = str(e)[:200]
        try:
            r = session.get(img_url, timeout=10)
            if r.status_code != 200:
                diag["skipped"] = True
                diag["reason"] = f"GET status {r.status_code}"
                image_diagnostics[img_url] = diag
                continue
            data = r.content[:200000]
            if len(data) < MIN_IMAGE_BYTES:
                diag["skipped"] = True
                diag["reason"] = f"body bytes too small {len(data)}"
                image_diagnostics[img_url] = diag
                continue
            pil = Image.open(BytesIO(data)).convert("RGB")
            w,h = pil.size
            if w < MIN_WIDTH or h < MIN_HEIGHT:
                diag["skipped"] = True
                diag["reason"] = f"dimensions too small {w}x{h}"
                image_diagnostics[img_url] = diag
                continue
            aspect = w/float(h) if h else 0
            if aspect > 6 or aspect < 0.2:
                diag["skipped"] = True
                diag["reason"] = f"extreme aspect {aspect:.2f}"
                image_diagnostics[img_url] = diag
                continue
            # compute deterministic dominant color and map to nearest named color
            dom_rgb = dominant_color_hex_from_bytes(data)
            dom_name = nearest_named_color(dom_rgb) if dom_rgb else None
        except Exception as e:
            diag["skipped"] = True
            diag["reason"] = f"get/parse error: {str(e)[:200]}"
            image_diagnostics[img_url] = diag
            continue
        # accepted
        image_diagnostics[img_url] = {"skipped": False, "reason": "accepted", "width": w, "height": h, "dominant_rgb": dom_rgb, "dominant_color_name": dom_name}
        good_images.append(img_url)
        image_bytes_map[img_url] = data

    # text metrics and candidates
    text_metrics = extract_metrics_from_text(page_text)
    text_candidates = extract_candidate_phrases(page_text)

    visual_labels = {
        "prints": [p for p in PRINTS],
        "fabrics": [f for f in FABRICS],
        "shapes": [s for s in SHAPES],
        "colors": [c for c in COLORS]
    }

    seen_phash = set()
    clip_per_image = {}
    clip_results = {}

    local_image_records = []

    if clip_wrapper:
        for img_url in good_images:
            try:
                if BAD_IMG_RX.search(img_url.lower()):
                    continue
                content = image_bytes_map.get(img_url)
                if content is None:
                    r = session.get(img_url, timeout=12)
                    r.raise_for_status()
                    content = r.content
                if use_phash and IMAGEHASH_AVAILABLE:
                    try:
                        h = str(imagehash.phash(Image.open(BytesIO(content)).convert("RGB")))
                        if h in seen_phash:
                            continue
                        seen_phash.add(h)
                    except Exception:
                        pass
                pil = Image.open(BytesIO(content)).convert("RGB")
            except Exception:
                continue
            try:
                w,h = pil.size
                image_weight = max(0.5, (w * h) / (1000*1000))
            except Exception:
                image_weight = 1.0
            caption = None
            if use_blip:
                try:
                    caption = caption_image_bytes(content)
                except Exception:
                    caption = None
            clip_per_image.setdefault(img_url, {})
            emb = None
            try:
                emb = clip_wrapper.get_image_embedding(pil)
            except Exception:
                emb = None
            if emb is not None and global_image_records is not None:
                local_image_records.append((url, img_url, emb, caption))
            for cat, terms in visual_labels.items():
                candidates = terms[:CANDIDATES_PER_CAT]
                try:
                    topk = clip_wrapper.similarity_topk(pil, candidates, top_k=TOP_K)
                except Exception:
                    topk = []
                filtered_topk = [(t,s) for t,s in topk if s >= CLIP_SIM_THRESHOLD]
                clip_per_image[img_url][cat] = [{"label": t, "score": float(s)} for t,s in filtered_topk]
                if filtered_topk:
                    clip_results.setdefault(cat, []).append({
                        "image": img_url,
                        "topk": [{"label": t, "score": float(s)} for t,s in filtered_topk],
                        "image_weight": image_weight
                    })
            if global_image_records is not None and emb is not None:
                global_image_records.append((url, img_url, emb, caption))

    aggregated_clip = {}
    for cat, items in clip_results.items():
        score_map = {}
        for it in items:
            w = it.get("image_weight", 1.0)
            for lbl in it["topk"]:
                key = lbl["label"].lower()
                score_map.setdefault(key, 0.0)
                score_map[key] += w * float(lbl["score"])
        agg_list = sorted([{"label": k, "agg_score": v} for k,v in score_map.items()], key=lambda x: x["agg_score"], reverse=True)
        aggregated_clip[cat] = agg_list[:6]

    # stricter fusion: prefer image-confirmed metrics or very high visual confidence
    final_metrics = {}
    for cat in ["prints","colors","shapes","fabrics"]:
        text_vals = text_metrics.get(cat, [])
        agg_items = {a["label"].lower(): a["agg_score"] for a in aggregated_clip.get(cat, [])}
        entries = []
        # clip-first high-confidence
        for label, agg_score in agg_items.items():
            if agg_score >= CLIP_SIM_HIGH:
                entries.append({"value": label, "source": "clip", "confidence": "high", "clip_score": agg_score})
        # text-derived items only if supported by clip (>= threshold) or mark as low
        for tv in text_vals:
            tv_low = tv.lower()
            clip_score = agg_items.get(tv_low)
            if clip_score and clip_score >= CLIP_SIM_THRESHOLD:
                conf = "high" if clip_score >= CLIP_SIM_HIGH else "medium"
                entries.append({"value": tv, "source": "text+clip", "confidence": conf, "clip_score": clip_score})
            else:
                # include text-only as low (can be filtered by consumer)
                entries.append({"value": tv, "source": "text", "confidence": "low", "clip_score": clip_score})
        # dedupe by value (prefer highest confidence)
        seen_vals = set()
        final_list = []
        # sort to keep high first
        order_key = lambda x: (0 if x["confidence"]=="high" else (1 if x["confidence"]=="medium" else 2), -(x.get("clip_score") or 0))
        for e in sorted(entries, key=order_key):
            vkey = (e["value"] or "").lower()
            if vkey in seen_vals:
                continue
            seen_vals.add(vkey)
            final_list.append(e)
        final_metrics[cat] = final_list

    # top images per accepted label for auditing
    def top_images_for_label(cat, label, k=3):
        rows = []
        for img, info in clip_per_image.items():
            for entry in info.get(cat, []):
                if entry["label"].lower() == label.lower():
                    rows.append((img, entry["score"]))
        rows = sorted(rows, key=lambda x: x[1], reverse=True)
        return rows[:k]

    top_examples = {}
    for cat, items in final_metrics.items():
        for it in items:
            if it.get("confidence") in ("high","medium"):
                label = it["value"]
                top_examples.setdefault(cat, {})[label] = top_images_for_label(cat, label, k=3)

    # page date
    page_date = None
    try:
        headers = {}
        try:
            head_resp = session.head(url, allow_redirects=True, timeout=6)
            headers = dict(head_resp.headers)
        except Exception:
            headers = {}
        if html:
            soup = BeautifulSoup(html, "html.parser")
            page_date = extract_page_date_from_soup_and_headers(soup, headers=headers)
        if not page_date:
            page_date = extract_page_date_from_soup_and_headers(None, headers=headers)
    except Exception:
        page_date = None

    out_item["extracted"] = {
        "textMetrics": text_metrics,
        "textCandidates": text_candidates,
        "clipPerImage": clip_per_image,
        "clipAggregated": aggregated_clip,
        "images": good_images,
        "imageDiagnostics": image_diagnostics,
        "topExamples": top_examples,
        "pageDate": page_date
    }
    out_item["pageDate"] = page_date
    out_item["metrics"] = final_metrics
    return out_item


def cluster_and_summarize(global_image_records, out_clusters_file="image_clusters_summary.json"):
    if not SKLEARN_AVAILABLE or not global_image_records:
        print("Clustering skipped: sklearn or records unavailable")
        return {}
    X = np.stack([r[2] for r in global_image_records])
    n_clusters = min(40, max(2, len(X)//3))
    km = KMeans(n_clusters=n_clusters, random_state=42).fit(X)
    labels = km.labels_
    clusters = {}
    for i,(page,img,emb,cap) in enumerate(global_image_records):
        lab = int(labels[i])
        clusters.setdefault(lab,[]).append((page,img,cap))
    summary = {}
    for k,v in clusters.items():
        caps = [c for (_,_,c) in v if c]
        sample_images = [im for (_,im,_) in v[:6]]
        summary[k] = {"count": len(v), "top_captions": caps[:6], "sample_images": sample_images}
    with open(out_clusters_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("Wrote image clusters summary to", out_clusters_file)
    return summary


def crawl_site(seed, clip_wrapper, limit_per_site, use_phash, use_blip, global_image_records):
    to_visit = [seed]
    seen_urls = set()
    results = []
    session = requests.Session()
    session.headers.update(HEADERS)

    while to_visit and len(results) < limit_per_site:
        url = to_visit.pop(0)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        try:
            parsed_seed = urlparse(seed)
            parsed_url = urlparse(url)
            if parsed_url.netloc != parsed_seed.netloc:
                continue
        except Exception:
            continue
        try:
            item = process_url(url, clip_wrapper=clip_wrapper, limit_images=MAX_IMAGES_PER_PAGE, use_phash=use_phash, use_blip=use_blip, global_image_records=global_image_records)
            results.append(item)
        except Exception as e:
            print("Error processing", url, e)
        try:
            r = session.get(url, timeout=8)
            if r.status_code == 200 and 'text/html' in (r.headers.get('Content-Type') or ''):
                soup = BeautifulSoup(r.text, 'html.parser')
                for a in soup.find_all('a', href=True):
                    href = a.get('href')
                    if not href: continue
                    try:
                        abs_href = urllib.parse.urljoin(url, href)
                    except Exception:
                        continue
                    parsed_abs = urlparse(abs_href)
                    if parsed_abs.netloc != parsed_seed.netloc:
                        continue
                    if parsed_abs.path == '' or abs_href in seen_urls:
                        continue
                    if re.search(r'\.(jpg|jpeg|png|gif|webp|svg|pdf|zip|mp4|mp3)(\?|$)', parsed_abs.path, re.I):
                        continue
                    if abs_href not in to_visit and abs_href not in seen_urls:
                        to_visit.append(abs_href)
                    if len(to_visit) + len(results) >= limit_per_site * 3:
                        break
        except Exception:
            pass
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-clip", action="store_true", help="Disable CLIP image checks")
    parser.add_argument("--limit", type=int, default=MAX_PAGES_PER_SITE, help="Max pages per seed")
    parser.add_argument("--out", default="trend_output1_patched.json", help="Output JSON filename")
    parser.add_argument("--use-phash", action="store_true", help="Use perceptual-hash dedupe before CLIP (requires imagehash)")
    parser.add_argument("--use-blip", action="store_true", help="Use BLIP image captioning (optional, requires transformers)")
    parser.add_argument("--cluster", action="store_true", help="Cluster collected image embeddings and write summary")
    args = parser.parse_args()

    use_clip = (not args.no_clip) and CLIP_AVAILABLE
    if (not args.no_clip) and (not CLIP_AVAILABLE):
        print("Warning: CLIP libs not available. Run with --no-clip or install transformers/torch.")
        use_clip = False
    if args.use_phash and not IMAGEHASH_AVAILABLE:
        print("Warning: imagehash not available; --use-phash ignored. Install with: pip install imagehash")
    use_blip = args.use_blip and BLIP_AVAILABLE
    if args.use_blip and not BLIP_AVAILABLE:
        print("Warning: BLIP not available; --use-blip ignored. Install transformers and model weights.")

    clip_wrapper = None
    if use_clip:
        print("Loading CLIP model (this may take a while)...")
        clip_wrapper = CLIPWrapper()
        print("CLIP loaded on device", clip_wrapper.device)

    global_image_records = []
    all_results = []

    for seed in SEEDS:
        print(f"Crawling seed site: {seed} (up to {args.limit} pages)")
        try:
            site_results = crawl_site(seed, clip_wrapper, args.limit, args.use_phash, use_blip, global_image_records)
            all_results.extend(site_results)
        except Exception as e:
            print("Error crawling seed", seed, e)
        time.sleep(CRAWL_DELAY)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print("Saved", len(all_results), "items to", args.out)

    if args.cluster and global_image_records:
        cluster_and_summarize(global_image_records)

if __name__ == "__main__":
    main()
