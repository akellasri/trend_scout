# Trend Scout 👗🤖

AI-powered **fashion design pipeline** that scouts, generates, and showcases fashion trends using multi-agent orchestration (Agent 1, Agent 2, Agent 3).  
This project was built to demonstrate **technical excellence, creativity, and real-world commercial potential** in AI-driven fashion innovation.  

---

## 🚀 Overview

The pipeline consists of three core agents:

### 🧠 Agent 1: Trend Insights  
- Scrapes & analyzes fashion websites and social data.  
- Extracts **colors, prints, fabrics, silhouettes, sleeves, neckline, tags, descriptions**.  
- Outputs **trend metrics** (top categories, combos, color distributions).  
- Results visualized later on the frontend with interactive charts.  

### 🎨 Agent 2: Product Design Generator  
- Takes **payload.json** (user/jury input) → generates **design JSONs**.  
- Design JSONs include `title`, `design_id`, `color_palette`, `fabrics`, `prints_patterns`, `garment_type`, `silhouette`, `techpack`, etc.  
- Supports:  
  - Multiple variants (batch mode).  
  - **apply_text_change.py**: Apply natural-language edits (“Change to olive linen, square neck, puff sleeves”).  
  - **design_to_text.py**: Converts JSON into human-readable summaries.  
- Stores outputs in `output/agent2_designs/`.

### 👗 Agent 3: Showcase & Runway Generator  
- Uses **Gemini / Veo** models to render product designs onto AI models.  
- Two modes:  
  - `agent3_virtual_showcase_demo.py` → photorealistic **studio model images**.  
  - `agent3_runway_demo.py` → 6s **AI runway videos** with storyboard + background music.  
- Supports **random selection** of design JSONs.  
- Model attributes configurable: gender, body type, skin tone, pose.  

---

## 🛠️ Pipeline Flow

### 1️⃣ Generate initial designs  
```bash
python test_agent2_payload.py agent2_inputs/payload_combo_0001.json
```
→ Produces output/agent2_designs/*.design.json

or batch mode:

```bash
python batch_agent2_payloads.py
```
→ Processes all payloads in agent2_inputs/.


### 2️⃣ Apply modifications (optional)
If jury requests changes:
```bash
python apply_text_change.py output/agent2_designs/ALD001.design.json \
  "Change to olive linen, square neck, puff sleeves."
```
→ Produces output/agent2_designs/ALD001.modified.design.json


### 3️⃣ Convert design JSON → human-readable text
```bash
python design_to_text.py output/agent2_designs/ALD001.modified.design.json
```
→ Prints a description like
```bash
Ankle-Length Olive Linen Maxi Dress (ALD001)
Colors: olive green
Fabrics: linen, cotton blend lining
Prints: solid color
Garment Type: dress
Silhouette: A-line
Sleeves: short puff sleeves
Neckline: square neck
Length: ankle-length
Style / Fit: relaxed fit through body, gently fitted at waist
Trims & details: concealed side zipper, self-fabric tie, topstitching
```

### 4️⃣ Render flat-lay product images
```bash
python render_utils.py --input output/agent2_designs/ALD001.modified.design.json --variant flatlay
```
→ Produces renders/ALD001__flatlay.png


### 5️⃣ Showcase on model (studio image)
```bash
GEMINI_API_KEY=... python agent3_virtual_showcase_demo.py --design output/agent2_designs/ALD001.modified.design.json
```
→ Produces output/ALD001_showcase.png


### 6️⃣ Runway video generation
```bash
GEMINI_API_KEY=... python agent3_runway_demo.py --input-dir output/agent2_designs --limit 1
```
→ Produces output/ALD001_runway.mp4


## 📂 Repo Structure
```bash
trend_scout/
│
├── agent2_inputs/          # Input payloads
├── output/agent2_designs/  # Generated design JSONs
├── renders/                # Flat-lay render outputs
├── output/                 # Storyboards & runway videos
│
├── test_agent2_payload.py
├── batch_agent2_payloads.py
├── apply_text_change.py
├── design_to_text.py
├── render_utils.py
├── agent3_virtual_showcase_demo.py
├── agent3_runway_demo.py
│
└── README.md
```

## 🎥 Example Outputs

- Design JSON → structured garment metadata.

- Flat-lay render → apparel-only PNG (no model).

- Virtual showcase → studio AI model image wearing design.

- Runway video → 6s AI-generated runway demo.

## 🌐 Future Frontend Integration

We will build a simple dashboard (React / Next.js or Lovable.dev) where the jury can:

- View trend insights from Agent 1 (charts: top colors, fabrics, silhouettes).

- Generate design prompts and view JSON/text outputs.

- Apply live edits with natural-language changes.

- Showcase designs on diverse models and generate runway videos.

- Download Lookbooks & Export runway videos.

## ⚙️ Requirements

- Python 3.10+

- Azure OpenAI (GPT-5-chat for JSON editing)

- Google Generative AI (Gemini / Veo for images & videos)

- Dependencies: requests, google-generativeai, Pillow, dotenv
