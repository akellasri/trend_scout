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

1. **Generate designs**  
   ```bash
   python test_agent2_payload.py agent2_inputs/payload_combo_0001.json

   → Produces output/agent2_designs/*.design.json
