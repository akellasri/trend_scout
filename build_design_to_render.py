#!/usr/bin/env python3
# build_design_to_render.py
import json
from pathlib import Path
import glob

AGENT_DESIGNS_DIR = Path("output/agent2_designs")
RENDERS_DIR = Path("renders")
OUT = Path("output/design_to_render.json")

def find_render_for_design(design_id):
    patterns = [
        f"{design_id}__*.png",
        f"{design_id}__*.jpg",
        f"{design_id}__*.jpeg",
        f"{design_id}__*.webp",
    ]
    for p in patterns:
        matches = list(RENDERS_DIR.glob(p))
        if matches:
            # prefer png if exists
            for m in matches:
                if m.suffix.lower() == ".png":
                    return str(m)
            return str(matches[0])
    return None

def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    mapping = {}
    # read design json files
    for f in sorted(AGENT_DESIGNS_DIR.glob("*.design.json")):
        try:
            j = json.loads(open(f, encoding="utf-8").read())
            design_id = j.get("design_id") or j.get("id") or f.stem.split(".")[0]
            render = find_render_for_design(design_id)
            mapping[design_id] = {
                "design_file": str(f),
                "render": render
            }
        except Exception as e:
            print("skip", f, e)

    # Also pick up any render PNGs that don't have design JSON
    for r in sorted(RENDERS_DIR.glob("*__*.png")):
        key = r.name.split("__")[0]
        if key not in mapping:
            mapping[key] = {"design_file": None, "render": str(r)}

    OUT.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Wrote", OUT, "entries:", len(mapping))

if __name__ == "__main__":
    main()
